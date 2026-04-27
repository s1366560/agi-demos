"""Unit tests for the workspace health verdict tool."""

from __future__ import annotations

import pytest

from src.domain.events.agent_events import AgentSupervisorVerdictEvent
from src.domain.events.types import AgentEventType
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.workspace_health_verdict import (
    workspace_health_verdict_tool,
)


def _make_ctx(agent_id: str = "workspace-supervisor") -> ToolContext:
    return ToolContext(
        session_id="sess-1",
        message_id="msg-1",
        call_id="call-1",
        agent_name=agent_id,
        conversation_id="conv-1",
        runtime_context={"agent_id": agent_id},
    )


def _drain(ctx: ToolContext) -> list[object]:
    return ctx.consume_pending_events()


class TestWorkspaceHealthVerdictTool:
    @pytest.mark.asyncio
    async def test_emits_agent_judged_workspace_verdict(self) -> None:
        ctx = _make_ctx("oracle")

        result = await workspace_health_verdict_tool.execute(
            ctx,
            workspace_id="ws-1",
            status="stalled",
            rationale="The latest attempt is blocked and no successful tools were recorded.",
            diagnostics_snapshot={
                "blockers": [{"type": "attempt_blocked", "task_id": "task-1"}],
                "evidence_gaps": [{"task_id": "task-1"}],
                "recent_tool_failures": [],
            },
            evidence=["task-1 has no verification evidence"],
            recommended_actions=["reassign task-1 to a fresh worker"],
            trigger="diagnostics",
            next_action="reassign",
            confidence=0.82,
        )

        assert result.is_error is False
        assert result.metadata["status"] == "stalled"
        assert result.metadata["workspace_id"] == "ws-1"
        assert result.metadata["next_action"] == "reassign"
        assert result.metadata["confidence"] == 0.82

        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentSupervisorVerdictEvent)
        assert event.event_type == AgentEventType.AGENT_SUPERVISOR_VERDICT
        assert event.actor_agent_id == "oracle"
        assert event.conversation_id == "conv-1"
        assert event.status == "stalled"
        assert event.trigger == "diagnostics"
        assert event.metadata["workspace_id"] == "ws-1"
        assert event.metadata["source"] == "workspace_execution_diagnostics"
        assert event.metadata["next_action"] == "reassign"
        assert event.metadata["evidence"] == ["task-1 has no verification evidence"]

    @pytest.mark.asyncio
    async def test_rejects_budget_risk_and_invalid_actions(self) -> None:
        ctx = _make_ctx()

        result = await workspace_health_verdict_tool.execute(
            ctx,
            workspace_id="ws-1",
            status="budget_risk",
            rationale="not a workspace execution verdict",
            diagnostics_snapshot={},
        )

        assert result.is_error is True
        assert "status must be one of" in result.output
        assert _drain(ctx) == []

        result = await workspace_health_verdict_tool.execute(
            ctx,
            workspace_id="ws-1",
            status="healthy",
            rationale="looks good",
            diagnostics_snapshot={},
            next_action="guess",
        )

        assert result.is_error is True
        assert "next_action must be one of" in result.output
        assert _drain(ctx) == []

    @pytest.mark.asyncio
    async def test_requires_non_empty_rationale_and_object_snapshot(self) -> None:
        ctx = _make_ctx()

        result = await workspace_health_verdict_tool.execute(
            ctx,
            workspace_id="ws-1",
            status="healthy",
            rationale=" ",
            diagnostics_snapshot={},
        )
        assert result.is_error is True
        assert "rationale" in result.output

        result = await workspace_health_verdict_tool.execute(
            ctx,
            workspace_id="ws-1",
            status="healthy",
            rationale="ok",
            diagnostics_snapshot=[],  # type: ignore[arg-type]
        )
        assert result.is_error is True
        assert "diagnostics_snapshot" in result.output
        assert _drain(ctx) == []
