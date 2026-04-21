"""Unit tests for WTP Phase 6 clarification tools."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.wtp_envelope import WtpEnvelope, WtpVerb
from src.infrastructure.agent.orchestration.orchestrator import SendResult
from src.infrastructure.agent.orchestration.send_denied import (
    SendDenied,
    SendDeniedCode,
)
from src.infrastructure.agent.tools import workspace_clarification as clar

pytestmark = pytest.mark.unit


def _make_ctx(role: str = "worker") -> Any:
    from src.infrastructure.agent.tools.context import ToolContext

    return ToolContext(
        session_id="s-1",
        message_id="m-1",
        call_id="c-1",
        agent_name=f"{role}-bot",
        conversation_id="conv-1",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        runtime_context={
            "selected_agent_id": f"{role}-agent-id",
            "selected_agent_name": f"{role}-bot",
            "workspace_id": "ws-1",
            "root_goal_task_id": "root-1",
            "workspace_session_role": role,
        },
    )


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.send_message = AsyncMock()
    clar.configure_workspace_clarification(orch)
    yield orch
    clar._orchestrator = None  # type: ignore[attr-defined]
    clar._pending_clarifications.clear()


def _ok_send() -> SendResult:
    return SendResult(
        message_id=str(uuid.uuid4()),
        from_agent_id="worker-agent-id",
        to_agent_id="leader-agent-id",
        session_id="s-1",
    )


def _denied() -> SendDenied:
    return SendDenied(
        ok=False,
        code=SendDeniedCode.TARGET_NOT_FOUND,
        message="no such leader",
        from_agent_ref="worker-agent-id",
        to_agent_ref="leader-agent-id",
        resolved_from_agent_id=None,
        resolved_to_agent_id=None,
        sender_session_id="s-1",
        target_session_id=None,
        project_id="proj-1",
        tenant_id="tenant-1",
        allowlist=None,
    )


class TestRoleGuards:
    async def test_request_rejects_non_worker(self, mock_orchestrator):
        ctx = _make_ctx(role="leader")
        result = await clar.workspace_request_clarification_tool.execute(
            ctx,
            task_id="t1",
            attempt_id="a1",
            leader_agent_id="leader-agent-id",
            question="what now?",
        )
        assert result.is_error is True
        assert "worker session" in json.loads(result.output)["error"]
        mock_orchestrator.send_message.assert_not_awaited()

    async def test_respond_rejects_non_leader(self, mock_orchestrator):
        ctx = _make_ctx(role="worker")
        result = await clar.workspace_respond_clarification_tool.execute(
            ctx,
            worker_agent_id="worker-agent-id",
            task_id="t1",
            attempt_id="a1",
            correlation_id="corr-1",
            answer="use env var FOO",
        )
        assert result.is_error is True
        assert "leader session" in json.loads(result.output)["error"]
        mock_orchestrator.send_message.assert_not_awaited()


class TestRequestClarification:
    async def test_happy_path_resolves_on_response(self, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send()
        ctx = _make_ctx(role="worker")

        task = asyncio.create_task(
            clar.workspace_request_clarification_tool.execute(
                ctx,
                task_id="t1",
                attempt_id="a1",
                leader_agent_id="leader-agent-id",
                question="which API key?",
                timeout_seconds=5.0,
            )
        )

        # Let the send + future registration happen.
        for _ in range(20):
            await asyncio.sleep(0.01)
            if clar._pending_clarifications:
                break

        assert len(clar._pending_clarifications) == 1
        correlation_id = next(iter(clar._pending_clarifications.keys()))

        response_env = WtpEnvelope(
            verb=WtpVerb.TASK_CLARIFY_RESPONSE,
            workspace_id="ws-1",
            task_id="t1",
            attempt_id="a1",
            correlation_id=correlation_id,
            payload={"answer": "use PROD_KEY"},
        )
        assert clar.deliver_clarification_response(response_env) is True

        result = await asyncio.wait_for(task, timeout=2.0)
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["answer"] == "use PROD_KEY"
        assert data["correlation_id"] == correlation_id

    async def test_timeout_returns_error(self, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send()
        ctx = _make_ctx(role="worker")

        result = await clar.workspace_request_clarification_tool.execute(
            ctx,
            task_id="t1",
            attempt_id="a1",
            leader_agent_id="leader-agent-id",
            question="?",
            timeout_seconds=0.1,
        )
        assert result.is_error is True
        payload = json.loads(result.output)
        assert payload["error"] == "clarification_timeout"
        # Registry cleaned up.
        assert not clar._pending_clarifications

    async def test_send_denied_surfaces_and_clears_registry(self, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _denied()
        ctx = _make_ctx(role="worker")

        result = await clar.workspace_request_clarification_tool.execute(
            ctx,
            task_id="t1",
            attempt_id="a1",
            leader_agent_id="leader-agent-id",
            question="?",
        )
        assert result.is_error is True
        payload = json.loads(result.output)
        assert payload["error"] == "send_denied"
        assert not clar._pending_clarifications


class TestRespondClarification:
    async def test_success(self, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send()
        ctx = _make_ctx(role="leader")
        result = await clar.workspace_respond_clarification_tool.execute(
            ctx,
            worker_agent_id="worker-agent-id",
            task_id="t1",
            attempt_id="a1",
            correlation_id="corr-1",
            answer="use env var FOO",
        )
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["wtp_verb"] == "task.clarify_response"
        assert data["correlation_id"] == "corr-1"


class TestDeliveryHook:
    async def test_wrong_verb_returns_false(self):
        env = WtpEnvelope(
            verb=WtpVerb.TASK_PROGRESS,
            workspace_id="ws",
            task_id="t",
            attempt_id="a",
            payload={"summary": "x"},
        )
        assert clar.deliver_clarification_response(env) is False

    async def test_unknown_correlation_returns_false(self):
        env = WtpEnvelope(
            verb=WtpVerb.TASK_CLARIFY_RESPONSE,
            workspace_id="ws",
            task_id="t",
            attempt_id="a",
            correlation_id="does-not-exist",
            payload={"answer": "noop"},
        )
        assert clar.deliver_clarification_response(env) is False
