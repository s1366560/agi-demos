"""Unit tests for the Supervisor toolset (Track B P2-3 phase-2).

Verifies:
- ``verdict`` tool emits exactly one ``AgentSupervisorVerdictEvent`` with
  rationale and recommended_actions preserved verbatim.
- Structural validation rejects invalid status, invalid trigger, and
  empty rationale.
- No content parsing: the tool does not classify rationale text.
"""

from __future__ import annotations

import pytest

from src.domain.events.agent_events import AgentSupervisorVerdictEvent
from src.domain.events.types import AgentEventType
from src.domain.model.agent.conversation.verdict_status import VerdictStatus
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.supervisor_tools import verdict_tool


def _make_ctx(agent_id: str = "supervisor-01") -> ToolContext:
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


class TestVerdictTool:
    @pytest.mark.asyncio
    async def test_emits_event_with_metadata(self) -> None:
        ctx = _make_ctx("supervisor")
        result = await verdict_tool.execute(
            ctx,
            status="stalled",
            rationale="no progress for 10 minutes; agent-a keeps re-reading file.",
            recommended_actions=["reassign to agent-b", "escalate to human"],
            trigger="tick",
        )
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert result.metadata["status"] == "stalled"
        assert result.metadata["trigger"] == "tick"
        assert result.metadata["recommended_actions"] == [
            "reassign to agent-b",
            "escalate to human",
        ]

        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentSupervisorVerdictEvent)
        assert event.event_type == AgentEventType.AGENT_SUPERVISOR_VERDICT
        assert event.actor_agent_id == "supervisor"
        assert event.conversation_id == "conv-1"
        assert event.status == "stalled"
        assert event.rationale.startswith("no progress")
        assert event.recommended_actions[0] == "reassign to agent-b"
        assert event.trigger == "tick"

    @pytest.mark.asyncio
    async def test_accepts_all_valid_statuses(self) -> None:
        for status in VerdictStatus:
            ctx = _make_ctx()
            result = await verdict_tool.execute(
                ctx,
                status=status.value,
                rationale="structural signal triggered",
            )
            assert result.is_error is False, f"rejected valid status {status!r}"
            events = _drain(ctx)
            assert len(events) == 1

    @pytest.mark.asyncio
    async def test_rejects_invalid_status(self) -> None:
        ctx = _make_ctx()
        result = await verdict_tool.execute(ctx, status="panic", rationale="something")
        assert result.is_error is True
        assert "status must be one of" in result.output
        assert _drain(ctx) == []

    @pytest.mark.asyncio
    async def test_rejects_invalid_trigger(self) -> None:
        ctx = _make_ctx()
        result = await verdict_tool.execute(
            ctx, status="healthy", rationale="fine", trigger="hunch"
        )
        assert result.is_error is True
        assert "trigger must be one of" in result.output
        assert _drain(ctx) == []

    @pytest.mark.asyncio
    async def test_rejects_empty_rationale(self) -> None:
        ctx = _make_ctx()
        result = await verdict_tool.execute(ctx, status="healthy", rationale="   ")
        assert result.is_error is True
        assert "rationale" in result.output
        assert _drain(ctx) == []

    @pytest.mark.asyncio
    async def test_recommended_actions_filtered_and_capped(self) -> None:
        ctx = _make_ctx()
        actions = [f"step-{i}" for i in range(20)] + ["", "  "]
        result = await verdict_tool.execute(
            ctx,
            status="looping",
            rationale="doom loop detected at counter=5",
            recommended_actions=actions,
        )
        assert result.is_error is False
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentSupervisorVerdictEvent)
        assert len(event.recommended_actions) == 10
        assert event.recommended_actions[0] == "step-0"

    @pytest.mark.asyncio
    async def test_actor_falls_back_to_agent_name(self) -> None:
        ctx = ToolContext(
            session_id="s",
            message_id="m",
            call_id="c",
            agent_name="supervisor-fallback",
            conversation_id="conv-x",
            runtime_context={},
        )
        result = await verdict_tool.execute(ctx, status="healthy", rationale="ok")
        assert result.is_error is False
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentSupervisorVerdictEvent)
        assert event.actor_agent_id == "supervisor-fallback"
