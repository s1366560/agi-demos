"""Unit tests for WTP worker-side reporting tools."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.workspace.wtp_envelope import WTP_VERSION, WtpVerb
from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.agent.orchestration.orchestrator import SendResult
from src.infrastructure.agent.orchestration.send_denied import (
    SendDenied,
    SendDeniedCode,
)
from src.infrastructure.agent.tools import workspace_wtp as wtp_tools
from src.infrastructure.agent.workspace_plan.system_actor import WORKSPACE_PLAN_SYSTEM_ACTOR_ID

pytestmark = pytest.mark.unit


@pytest.fixture
def ctx() -> MagicMock:
    from src.infrastructure.agent.tools.context import ToolContext

    ctx = ToolContext(
        session_id="leader-session-worker-conv",
        message_id="msg-1",
        call_id="call-1",
        agent_name="worker-bot",
        conversation_id="conv-1",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        runtime_context={
            "selected_agent_id": "worker-agent-id",
            "selected_agent_name": "worker-bot",
            "workspace_id": "ws-1",
            "root_goal_task_id": "root-task-1",
            "workspace_agent_binding_id": "binding-1",
            "workspace_session_role": "worker",
        },
    )
    return ctx


@pytest.fixture
def leader_ctx() -> Any:
    from src.infrastructure.agent.tools.context import ToolContext

    return ToolContext(
        session_id="leader-session",
        message_id="msg-1",
        call_id="call-1",
        agent_name="leader-bot",
        conversation_id="conv-leader",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        runtime_context={
            "selected_agent_id": "leader-agent-id",
            "workspace_id": "ws-1",
            "workspace_session_role": "leader",
        },
    )


@pytest.fixture
def mock_orchestrator() -> MagicMock:
    orch = MagicMock()
    orch.send_message = AsyncMock()
    wtp_tools.configure_workspace_wtp(orch)
    yield orch
    wtp_tools._orchestrator = None  # type: ignore[attr-defined]


def _ok_send(verb: str = "task.progress") -> SendResult:
    return SendResult(
        message_id=str(uuid.uuid4()),
        from_agent_id="worker-agent-id",
        to_agent_id="leader-agent-id",
        session_id="leader-session",
    )


class TestRoleGuard:
    async def test_non_worker_role_is_rejected(self, leader_ctx, mock_orchestrator):
        result = await wtp_tools.workspace_report_progress_tool.execute(
            leader_ctx,
            task_id="t1",
            attempt_id="a1",
            leader_agent_id="leader-agent-id",
            summary="hi",
        )
        assert result.is_error is True
        payload = json.loads(result.output)
        assert "worker session" in payload["error"]
        mock_orchestrator.send_message.assert_not_awaited()

    async def test_missing_workspace_id_is_rejected(self, mock_orchestrator):
        from src.infrastructure.agent.tools.context import ToolContext

        ctx = ToolContext(
            session_id="s",
            message_id="m",
            call_id="c",
            agent_name="a",
            conversation_id="cv",
            runtime_context={"workspace_session_role": "worker"},
        )
        result = await wtp_tools.workspace_report_progress_tool.execute(
            ctx,
            task_id="t1",
            attempt_id="a1",
            leader_agent_id="leader-agent-id",
            summary="hi",
        )
        assert result.is_error is True
        assert "workspace_id" in json.loads(result.output)["error"]


class TestProgress:
    async def test_successful_send(self, ctx, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send()
        result = await wtp_tools.workspace_report_progress_tool.execute(
            ctx,
            task_id="task-1",
            attempt_id="attempt-1",
            leader_agent_id="leader-agent-id",
            summary="Halfway done",
            phase="drafting",
            percent=50,
        )
        assert result.is_error is False
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["verb"] == "task.progress"
        assert payload["task_id"] == "task-1"

        # Orchestrator was called with NOTIFICATION + WTP metadata.
        call = mock_orchestrator.send_message.await_args
        assert call.kwargs["message_type"] == AgentMessageType.NOTIFICATION
        metadata = call.kwargs["metadata"]
        assert metadata["wtp_verb"] == "task.progress"
        assert metadata["wtp_version"] == WTP_VERSION
        assert metadata["workspace_id"] == "ws-1"
        assert metadata["task_id"] == "task-1"
        assert metadata["attempt_id"] == "attempt-1"
        assert metadata["root_goal_task_id"] == "root-task-1"
        assert metadata["workspace_agent_binding_id"] == "binding-1"
        content_payload = json.loads(call.kwargs["message"])
        assert content_payload["summary"] == "Halfway done"
        assert content_payload["phase"] == "drafting"
        assert content_payload["percent"] == 50.0

    async def test_percent_is_clamped(self, ctx, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send()
        await wtp_tools.workspace_report_progress_tool.execute(
            ctx,
            task_id="t",
            attempt_id="a",
            leader_agent_id="leader-agent-id",
            summary="ok",
            percent=150,
        )
        call = mock_orchestrator.send_message.await_args
        payload = json.loads(call.kwargs["message"])
        assert payload["percent"] == 100.0

    async def test_blank_summary_is_rejected_at_envelope_layer(self, ctx, mock_orchestrator):
        result = await wtp_tools.workspace_report_progress_tool.execute(
            ctx,
            task_id="t",
            attempt_id="a",
            leader_agent_id="leader-agent-id",
            summary="   ",
        )
        assert result.is_error is True
        assert "invalid progress payload" in json.loads(result.output)["error"]
        mock_orchestrator.send_message.assert_not_awaited()

    async def test_send_denied_surfaces_code(self, ctx, mock_orchestrator):
        mock_orchestrator.send_message.return_value = SendDenied(
            ok=False,
            code=SendDeniedCode.TARGET_A2A_DISABLED,
            message="target disabled",
            from_agent_ref="worker-agent-id",
            to_agent_ref="leader-agent-id",
            resolved_from_agent_id="worker-agent-id",
            resolved_to_agent_id="leader-agent-id",
            sender_session_id="s",
            target_session_id=None,
            project_id="proj-1",
            tenant_id="tenant-1",
            allowlist=None,
        )
        result = await wtp_tools.workspace_report_progress_tool.execute(
            ctx,
            task_id="t",
            attempt_id="a",
            leader_agent_id="leader-agent-id",
            summary="attempt",
        )
        assert result.is_error is True
        payload = json.loads(result.output)
        assert payload["error"] == "send_denied"
        assert payload["code"] == SendDeniedCode.TARGET_A2A_DISABLED.value

    async def test_system_actor_progress_uses_local_fan_in(self, ctx, mock_orchestrator):
        with patch.object(
            wtp_tools, "_publish_envelope_for_supervisor", new=AsyncMock()
        ) as mock_publish:
            result = await wtp_tools.workspace_report_progress_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
                summary="Durable-plan worker progress",
            )

        assert result.is_error is False
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["notification_status"] == "local_fan_in"
        assert payload["message_id"].startswith("local:")
        mock_orchestrator.send_message.assert_not_awaited()

        published = mock_publish.await_args.args[0]
        assert published.extra_metadata["leader_agent_id"] == WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        assert published.extra_metadata["worker_agent_id"] == "worker-agent-id"
        assert published.extra_metadata["workspace_agent_binding_id"] == "binding-1"


class TestComplete:
    async def test_sends_envelope_and_applies_report(self, ctx, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send("task.completed")

        with patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply:
            mock_apply.return_value = {"applied": True, "task_status": "in_review"}
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id="leader-agent-id",
                summary="All done",
                artifacts=["/tmp/report.md", ""],
                verifications=["preflight:read-progress", "", "preflight:git-status"],
                commit_ref="abc123",
                git_diff_summary="2 files changed",
                changed_files=["src/app.ts", ""],
            )

        assert result.is_error is False
        payload = json.loads(result.output)
        assert payload["verb"] == "task.completed"
        assert payload["applied_report"] == {"applied": True, "task_status": "in_review"}

        # Only non-empty artifacts are forwarded, with structured git evidence normalized.
        send_call = mock_orchestrator.send_message.await_args
        content = json.loads(send_call.kwargs["message"])
        assert content["artifacts"] == [
            "/tmp/report.md",
            "commit_ref:abc123",
            "git_diff_summary:2 files changed",
            "changed_file:src/app.ts",
        ]
        assert content["verifications"] == ["preflight:read-progress", "preflight:git-status"]
        assert content["commit_ref"] == "abc123"
        assert content["git_diff_summary"] == "2 files changed"
        assert content["changed_files"] == ["src/app.ts"]
        assert send_call.kwargs["message_type"] == AgentMessageType.ANNOUNCE
        assert send_call.kwargs["metadata"]["wtp_verb"] == "task.completed"
        assert send_call.kwargs["metadata"]["workspace_agent_binding_id"] == "binding-1"

        # apply_terminal_report received the normalized artifact list + correct report_type.
        apply_kwargs = mock_apply.await_args.kwargs
        assert apply_kwargs["report_type"] == "completed"
        assert apply_kwargs["artifacts"] == [
            "/tmp/report.md",
            "commit_ref:abc123",
            "git_diff_summary:2 files changed",
            "changed_file:src/app.ts",
        ]
        assert apply_kwargs["verifications"] == [
            "preflight:read-progress",
            "preflight:git-status",
        ]
        assert apply_kwargs["task_id"] == "task-1"
        assert apply_kwargs["attempt_id"] == "attempt-1"
        assert apply_kwargs["leader_agent_id"] == "leader-agent-id"

    async def test_complete_normalizes_scalar_report_fields_from_lenient_tool_calls(
        self, ctx, mock_orchestrator
    ):
        mock_orchestrator.send_message.return_value = _ok_send("task.completed")

        with patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply:
            mock_apply.return_value = {"applied": True, "task_status": "in_review"}
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id="leader-agent-id",
                summary="All done",
                artifacts="artifact:report.md",
                verifications="test_run:22/22 passed",
                changed_files="run-comprehensive.js",
            )

        assert result.is_error is False
        content = json.loads(mock_orchestrator.send_message.await_args.kwargs["message"])
        assert content["artifacts"] == [
            "artifact:report.md",
            "changed_file:run-comprehensive.js",
        ]
        assert content["verifications"] == ["test_run:22/22 passed"]

        apply_kwargs = mock_apply.await_args.kwargs
        assert apply_kwargs["artifacts"] == [
            "artifact:report.md",
            "changed_file:run-comprehensive.js",
        ]
        assert apply_kwargs["verifications"] == ["test_run:22/22 passed"]

    async def test_send_denied_is_warning_when_terminal_report_is_applied(
        self, ctx, mock_orchestrator
    ):
        mock_orchestrator.send_message.return_value = SendDenied(
            ok=False,
            code=SendDeniedCode.TARGET_A2A_DISABLED,
            message="target disabled",
            from_agent_ref="worker-agent-id",
            to_agent_ref="leader-agent-id",
            resolved_from_agent_id="worker-agent-id",
            resolved_to_agent_id="leader-agent-id",
            sender_session_id="s",
            target_session_id=None,
            project_id="proj-1",
            tenant_id="tenant-1",
            allowlist=["builtin:sisyphus"],
        )

        with patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply:
            mock_apply.return_value = {"applied": True, "task_status": "in_review"}
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id="leader-agent-id",
                summary="All done",
                verifications=["preflight:read-progress", "preflight:git-status"],
            )

        assert result.is_error is False
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["error"] == "send_denied"
        assert payload["notification_status"] == "failed"
        assert payload["applied_report"] == {"applied": True, "task_status": "in_review"}

    async def test_system_actor_completion_applies_report_without_a2a(self, ctx, mock_orchestrator):
        with (
            patch.object(wtp_tools, "_publish_envelope_for_supervisor", new=AsyncMock()),
            patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply,
        ):
            mock_apply.return_value = {"applied": True, "task_status": "in_review"}
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
                summary="All done",
                verifications=["test_run:unit"],
            )

        assert result.is_error is False
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["notification_status"] == "local_fan_in"
        assert payload["applied_report"] == {"applied": True, "task_status": "in_review"}
        mock_orchestrator.send_message.assert_not_awaited()
        assert mock_apply.await_args.kwargs["leader_agent_id"] == WORKSPACE_PLAN_SYSTEM_ACTOR_ID

    async def test_protected_test_node_rejects_failed_completion_evidence(
        self, ctx, mock_orchestrator
    ):
        ctx.runtime_context["workspace_verification_integrity"] = {
            "iteration_phase": "test",
            "protected_script_changes": True,
        }

        with patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply:
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id="leader-agent-id",
                summary="Full suite finished with 85/86 passing",
                verifications=[
                    "preflight:read-progress",
                    "preflight:git-status",
                    "test_run:test-data-persistence.js 13 passed 1 failed",
                ],
            )

        assert result.is_error is True
        payload = json.loads(result.output)
        assert "completion denied" in payload["error"]
        assert payload["failed_evidence"] == [
            "Full suite finished with 85/86 passing",
            "test_run:test-data-persistence.js 13 passed 1 failed",
        ]
        mock_orchestrator.send_message.assert_not_awaited()
        mock_apply.assert_not_awaited()

    async def test_protected_test_node_rejects_hidden_partial_contract_without_disposition(
        self, ctx, mock_orchestrator
    ):
        ctx.runtime_context["workspace_verification_integrity"] = {
            "iteration_phase": "review",
            "protected_script_changes": True,
            "test_contract_hints": [
                "Update PRE-PROD report with comprehensive test summary (202/203)",
            ],
        }

        with patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply:
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id="leader-agent-id",
                summary="Updated PRE-PROD report and committed it.",
                verifications=[
                    "preflight:read-progress",
                    "preflight:git-status",
                    "commit_ref:9e5a5d2f",
                ],
            )

        assert result.is_error is True
        payload = json.loads(result.output)
        assert "completion denied" in payload["error"]
        assert payload["failed_evidence"] == [
            "Update PRE-PROD report with comprehensive test summary (202/203)",
        ]
        mock_orchestrator.send_message.assert_not_awaited()
        mock_apply.assert_not_awaited()

    async def test_protected_test_node_rejects_partial_test_bucket_without_disposition(
        self, ctx, mock_orchestrator
    ):
        ctx.runtime_context["workspace_verification_integrity"] = {
            "iteration_phase": "review",
            "protected_script_changes": True,
        }

        with patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply:
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id="leader-agent-id",
                summary="Generated final acceptance evidence.",
                verifications=[
                    "preflight:read-progress",
                    "preflight:git-status",
                    "commit_ref:47d4c54c",
                    "test_run:comprehensive E2E 26 passed 4 partial",
                ],
            )

        assert result.is_error is True
        payload = json.loads(result.output)
        assert "completion denied" in payload["error"]
        assert payload["failed_evidence"] == ["test_run:comprehensive E2E 26 passed 4 partial"]
        mock_orchestrator.send_message.assert_not_awaited()
        mock_apply.assert_not_awaited()

    async def test_protected_test_node_allows_partial_contract_with_disposition_ref(
        self, ctx, mock_orchestrator
    ):
        ctx.runtime_context["workspace_verification_integrity"] = {
            "iteration_phase": "review",
            "protected_script_changes": True,
            "test_contract_hints": [
                "Update PRE-PROD report with comprehensive test summary (202/203)",
            ],
        }

        with (
            patch.object(wtp_tools, "_publish_envelope_for_supervisor", new=AsyncMock()),
            patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply,
        ):
            mock_apply.return_value = {"applied": True, "task_status": "in_review"}
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
                summary="Updated PRE-PROD report and committed it.",
                verifications=[
                    "preflight:read-progress",
                    "preflight:git-status",
                    "contract_disposition:202/203 accepted by node contract; one check deferred",
                    "commit_ref:9e5a5d2f",
                ],
            )

        assert result.is_error is False
        mock_apply.assert_awaited_once()

    async def test_protected_test_node_allows_zero_failed_completion_evidence(
        self, ctx, mock_orchestrator
    ):
        ctx.runtime_context["workspace_verification_integrity"] = {
            "iteration_phase": "test",
            "protected_script_changes": True,
        }

        with (
            patch.object(wtp_tools, "_publish_envelope_for_supervisor", new=AsyncMock()),
            patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply,
        ):
            mock_apply.return_value = {"applied": True, "task_status": "in_review"}
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
                summary="Full suite finished with 86/86 passing and 0 failed",
                verifications=[
                    "preflight:read-progress",
                    "preflight:git-status",
                    "test_run:all 86 passed 0 failed",
                ],
            )

        assert result.is_error is False
        mock_apply.assert_awaited_once()

    async def test_terminal_apply_failure_marks_tool_error(self, ctx, mock_orchestrator):
        with (
            patch.object(wtp_tools, "_publish_envelope_for_supervisor", new=AsyncMock()),
            patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply,
        ):
            mock_apply.return_value = {
                "applied": False,
                "error": "apply_workspace_worker_report returned no task",
            }
            result = await wtp_tools.workspace_report_complete_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
                summary="All done",
                verifications=["test_run:unit"],
            )

        assert result.is_error is True
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["error"] == "terminal_report_apply_failed"
        assert payload["applied_report"] == {
            "applied": False,
            "error": "apply_workspace_worker_report returned no task",
        }


class TestBlocked:
    async def test_sends_envelope_and_applies_report(self, ctx, mock_orchestrator):
        mock_orchestrator.send_message.return_value = _ok_send("task.blocked")

        with patch.object(wtp_tools, "_apply_terminal_report", new=AsyncMock()) as mock_apply:
            mock_apply.return_value = {"applied": True, "task_status": "blocked"}
            result = await wtp_tools.workspace_report_blocked_tool.execute(
                ctx,
                task_id="task-1",
                attempt_id="attempt-1",
                leader_agent_id="leader-agent-id",
                reason="API returned 403",
                evidence="Stack trace: ...",
            )

        assert result.is_error is False
        payload = json.loads(result.output)
        assert payload["verb"] == "task.blocked"
        assert payload["applied_report"]["applied"] is True

        send_call = mock_orchestrator.send_message.await_args
        content = json.loads(send_call.kwargs["message"])
        assert content["reason"] == "API returned 403"
        assert content["evidence"] == "Stack trace: ..."
        assert send_call.kwargs["message_type"] == AgentMessageType.ANNOUNCE
        assert send_call.kwargs["metadata"]["workspace_agent_binding_id"] == "binding-1"

        apply_kwargs = mock_apply.await_args.kwargs
        assert apply_kwargs["report_type"] == "blocked"
        assert "API returned 403" in apply_kwargs["summary"]
        assert "Stack trace" in apply_kwargs["summary"]

    async def test_blank_reason_rejected(self, ctx, mock_orchestrator):
        result = await wtp_tools.workspace_report_blocked_tool.execute(
            ctx,
            task_id="t",
            attempt_id="a",
            leader_agent_id="l",
            reason="",
        )
        assert result.is_error is True
        mock_orchestrator.send_message.assert_not_awaited()


class TestConfiguration:
    async def test_tool_without_configured_orchestrator_fails_gracefully(self, ctx):
        wtp_tools._orchestrator = None  # type: ignore[attr-defined]
        result = await wtp_tools.workspace_report_progress_tool.execute(
            ctx,
            task_id="t",
            attempt_id="a",
            leader_agent_id="l",
            summary="s",
        )
        assert result.is_error is True
        assert "not configured" in json.loads(result.output)["error"]


class TestVerbDefaultMessageType:
    """Sanity-check that each terminal verb maps to the expected AgentMessageType."""

    @pytest.mark.parametrize(
        "verb,expected",
        [
            (WtpVerb.TASK_PROGRESS, AgentMessageType.NOTIFICATION),
            (WtpVerb.TASK_COMPLETED, AgentMessageType.ANNOUNCE),
            (WtpVerb.TASK_BLOCKED, AgentMessageType.ANNOUNCE),
        ],
    )
    def test_default_message_type(self, verb, expected):
        assert verb.default_message_type() == expected
