"""Unit tests for WTP Phase 3 leader-side tools."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.orchestration.orchestrator import SendResult
from src.infrastructure.agent.orchestration.send_denied import (
    SendDenied,
    SendDeniedCode,
)
from src.infrastructure.agent.tools import workspace_leader_wtp as lwtp

pytestmark = pytest.mark.unit


def _leader_ctx(**overrides: Any) -> Any:
    from src.infrastructure.agent.tools.context import ToolContext

    rc = {
        "selected_agent_id": "leader-agent-id",
        "selected_agent_name": "leader-bot",
        "workspace_id": "ws-1",
        "root_goal_task_id": "root-1",
        "workspace_agent_binding_id": "binding-leader-1",
        "workspace_session_role": "leader",
    }
    rc.update(overrides.get("runtime_context", {}) or {})
    return ToolContext(
        session_id="leader-session",
        message_id="m1",
        call_id="c1",
        agent_name="leader-bot",
        conversation_id="conv-1",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        runtime_context=rc,
    )


def _worker_ctx() -> Any:
    from src.infrastructure.agent.tools.context import ToolContext

    return ToolContext(
        session_id="worker-session",
        message_id="m1",
        call_id="c1",
        agent_name="worker-bot",
        conversation_id="conv-2",
        runtime_context={
            "selected_agent_id": "worker-agent-id",
            "workspace_id": "ws-1",
            "workspace_session_role": "worker",
        },
    )


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.send_message = AsyncMock()
    lwtp.configure_workspace_leader_wtp(orch)
    yield orch
    lwtp._orchestrator = None  # type: ignore[attr-defined]


def _ok_send() -> SendResult:
    return SendResult(
        message_id=str(uuid.uuid4()),
        from_agent_id="leader-agent-id",
        to_agent_id="worker-agent-id",
        session_id="leader-session",
    )


def _denied() -> SendDenied:
    return SendDenied(
        ok=False,
        code=SendDeniedCode.TARGET_NOT_FOUND,
        message="nope",
        from_agent_ref="leader-agent-id",
        to_agent_ref="worker-agent-id",
        resolved_from_agent_id=None,
        resolved_to_agent_id=None,
        sender_session_id="leader-session",
        target_session_id=None,
        project_id="proj-1",
        tenant_id="tenant-1",
        allowlist=None,
    )


class TestAssignTask:
    async def test_non_leader_is_rejected(self, mock_orchestrator):
        result = await lwtp.workspace_assign_task_tool.execute(
            _worker_ctx(),
            task_id="t1",
            worker_agent_id="worker-agent-id",
            title="T",
            description="D",
        )
        assert result.is_error is True
        assert "leader session" in json.loads(result.output)["error"]
        mock_orchestrator.send_message.assert_not_awaited()

    async def test_leader_as_worker_rejected(self, mock_orchestrator):
        result = await lwtp.workspace_assign_task_tool.execute(
            _leader_ctx(),
            task_id="t1",
            worker_agent_id="leader-agent-id",  # self-assign
            title="T",
            description="D",
        )
        assert result.is_error is True
        assert "leader-as-worker" in json.loads(result.output)["error"]
        mock_orchestrator.send_message.assert_not_awaited()

    async def test_missing_orchestrator_denies(self):
        lwtp._orchestrator = None  # type: ignore[attr-defined]
        result = await lwtp.workspace_assign_task_tool.execute(
            _leader_ctx(),
            task_id="t1",
            worker_agent_id="worker-agent-id",
            title="T",
            description="D",
        )
        assert result.is_error is True

    async def test_successful_assign_publishes_envelope(self, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send()
        # Patch schedule_worker_session to avoid actually scheduling.
        with patch(
            "src.infrastructure.agent.tools.workspace_leader_wtp.__init__",
            create=True,
        ):
            pass

        # Stub downstream launcher + service lookup.
        with patch(
            "src.application.services.workspace_task_service."
            "WorkspaceTaskService.get_task",
            new=AsyncMock(return_value=None),  # returns None → launch skipped
        ):
            result = await lwtp.workspace_assign_task_tool.execute(
                _leader_ctx(),
                task_id="t1",
                worker_agent_id="worker-agent-id",
                title="Do the thing",
                description="Full brief here.",
                success_criteria="It is done",
            )

        assert result.is_error is False
        data = json.loads(result.output)
        assert data["verb"] == "task.assign"
        assert data["task_id"] == "t1"
        assert "correlation_id" in data
        assert data["launch"]["scheduled"] is False

        # Verify the orchestrator was called with the right metadata.
        call = mock_orchestrator.send_message.await_args
        meta = call.kwargs["metadata"]
        assert meta["wtp_verb"] == "task.assign"
        assert call.kwargs["to_agent_id"] == "worker-agent-id"
        assert meta["workspace_agent_binding_id"] == "binding-leader-1"

    async def test_send_denied_propagates(self, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _denied()
        result = await lwtp.workspace_assign_task_tool.execute(
            _leader_ctx(),
            task_id="t1",
            worker_agent_id="worker-agent-id",
            title="T",
            description="D",
        )
        assert result.is_error is True
        payload = json.loads(result.output)
        assert payload["error"] == "send_denied"


class TestCancelTask:
    async def test_non_leader_rejected(self, mock_orchestrator):
        result = await lwtp.workspace_cancel_task_tool.execute(
            _worker_ctx(),
            task_id="t1",
            worker_agent_id="worker-agent-id",
            reason="user cancelled",
        )
        assert result.is_error is True
        mock_orchestrator.send_message.assert_not_awaited()

    async def test_successful_cancel_emits_fresh_correlation(self, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send()
        result = await lwtp.workspace_cancel_task_tool.execute(
            _leader_ctx(),
            task_id="t1",
            worker_agent_id="worker-agent-id",
            reason="priorities changed",
        )
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["verb"] == "task.cancel"
        # Fresh correlation id — just ensure it's present and looks like uuid.
        assert len(data["correlation_id"]) >= 8

        call = mock_orchestrator.send_message.await_args
        meta = call.kwargs["metadata"]
        assert meta["wtp_verb"] == "task.cancel"
        assert meta["workspace_agent_binding_id"] == "binding-leader-1"
