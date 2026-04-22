"""Unit tests for the multi-agent structured action toolset (Track B).

Verifies:
- Each tool emits exactly one typed domain event carrying the actor
  agent id, conversation id, and prose rationale / reason verbatim.
- Structural validation rejects empty strings, out-of-range enums, and
  bad numeric ranges.
- The decision log (emitted events) is the only side effect — no DB
  coupling, no regex, no hardcoded policy lookup.
"""

from __future__ import annotations

import pytest

from src.domain.events.agent_events import (
    AgentConflictMarkedEvent,
    AgentEscalatedEvent,
    AgentGoalCompletedEvent,
    AgentHumanInputRequestedEvent,
    AgentProgressDeclaredEvent,
    AgentTaskAssignedEvent,
    AgentTaskRefusedEvent,
)
from src.domain.events.types import AgentEventType
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.multi_agent_action_tools import (
    assign_task_tool,
    declare_progress_tool,
    escalate_tool,
    mark_conflict_tool,
    refuse_task_tool,
    request_human_input_tool,
    signal_goal_complete_tool,
)
from src.infrastructure.agent.tools.result import ToolResult


def _make_ctx(agent_id: str = "coordinator-01") -> ToolContext:
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


# ---------------------------------------------------------------------------
# assign_task
# ---------------------------------------------------------------------------


class TestAssignTask:
    @pytest.mark.asyncio
    async def test_emits_event_and_returns_structured_metadata(self) -> None:
        ctx = _make_ctx("coord")
        result = await assign_task_tool.execute(
            ctx,
            target_agent_id="worker-1",
            task_title="Draft the proposal",
            rationale="worker-1 owns the research artifact referenced by the goal.",
        )
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert result.metadata["target_agent_id"] == "worker-1"
        assert result.metadata["task_title"] == "Draft the proposal"
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentTaskAssignedEvent)
        assert event.event_type == AgentEventType.AGENT_TASK_ASSIGNED
        assert event.actor_agent_id == "coord"
        assert event.target_agent_id == "worker-1"
        assert event.rationale.startswith("worker-1 owns")

    @pytest.mark.asyncio
    async def test_rejects_empty_rationale(self) -> None:
        ctx = _make_ctx()
        result = await assign_task_tool.execute(
            ctx,
            target_agent_id="worker-1",
            task_title="Task",
            rationale="   ",
        )
        assert result.is_error is True
        assert _drain(ctx) == []

    @pytest.mark.asyncio
    async def test_rejects_empty_target(self) -> None:
        ctx = _make_ctx()
        result = await assign_task_tool.execute(
            ctx,
            target_agent_id="",
            task_title="Task",
            rationale="Reason",
        )
        assert result.is_error is True
        assert _drain(ctx) == []

    @pytest.mark.asyncio
    async def test_actor_id_falls_back_to_agent_name(self) -> None:
        ctx = ToolContext(
            session_id="s",
            message_id="m",
            call_id="c",
            agent_name="solo-agent",
            conversation_id="conv-1",
            runtime_context={},  # no agent_id
        )
        await assign_task_tool.execute(
            ctx,
            target_agent_id="w",
            task_title="T",
            rationale="R",
        )
        events = _drain(ctx)
        assert len(events) == 1
        assert events[0].actor_agent_id == "solo-agent"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# refuse_task
# ---------------------------------------------------------------------------


class TestRefuseTask:
    @pytest.mark.asyncio
    async def test_emits_event_with_reason(self) -> None:
        ctx = _make_ctx("worker-1")
        result = await refuse_task_tool.execute(
            ctx,
            reason="I don't have access to the target artifact.",
            task_id="task-abc",
            suggested_reassignment="worker-2",
        )
        assert result.is_error is False
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentTaskRefusedEvent)
        assert event.task_id == "task-abc"
        assert event.reason.startswith("I don't have access")
        assert event.suggested_reassignment == "worker-2"

    @pytest.mark.asyncio
    async def test_rejects_empty_reason(self) -> None:
        ctx = _make_ctx()
        result = await refuse_task_tool.execute(ctx, reason="")
        assert result.is_error is True
        assert _drain(ctx) == []


# ---------------------------------------------------------------------------
# request_human_input
# ---------------------------------------------------------------------------


class TestRequestHumanInput:
    @pytest.mark.asyncio
    async def test_emits_event_with_urgency(self) -> None:
        ctx = _make_ctx("agent-x")
        result = await request_human_input_tool.execute(
            ctx,
            question="Should I proceed with the destructive migration?",
            context="The target database has 2TB of data.",
            urgency="blocking",
        )
        assert result.is_error is False
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentHumanInputRequestedEvent)
        assert event.urgency == "blocking"
        assert "destructive migration" in event.question

    @pytest.mark.asyncio
    async def test_rejects_bad_urgency(self) -> None:
        ctx = _make_ctx()
        result = await request_human_input_tool.execute(
            ctx,
            question="Q?",
            urgency="extreme",
        )
        assert result.is_error is True
        assert _drain(ctx) == []


# ---------------------------------------------------------------------------
# escalate
# ---------------------------------------------------------------------------


class TestEscalate:
    @pytest.mark.asyncio
    async def test_emits_event(self) -> None:
        ctx = _make_ctx("worker-2")
        result = await escalate_tool.execute(
            ctx,
            escalated_to="coordinator",
            reason="Goal scope is unclear; need adjudication.",
            severity="high",
        )
        assert result.is_error is False
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentEscalatedEvent)
        assert event.escalated_to == "coordinator"
        assert event.severity == "high"

    @pytest.mark.asyncio
    async def test_rejects_bad_severity(self) -> None:
        ctx = _make_ctx()
        result = await escalate_tool.execute(
            ctx,
            escalated_to="coordinator",
            reason="R",
            severity="insane",
        )
        assert result.is_error is True
        assert _drain(ctx) == []


# ---------------------------------------------------------------------------
# mark_conflict
# ---------------------------------------------------------------------------


class TestMarkConflict:
    @pytest.mark.asyncio
    async def test_emits_event(self) -> None:
        ctx = _make_ctx("reviewer")
        result = await mark_conflict_tool.execute(
            ctx,
            conflict_with="worker-1",
            summary="Disagree with the proposed API signature.",
            evidence="worker-1 message-id abc-123 suggests POST /foo/{id}.",
        )
        assert result.is_error is False
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentConflictMarkedEvent)
        assert event.conflict_with == "worker-1"
        assert "API signature" in event.summary

    @pytest.mark.asyncio
    async def test_rejects_empty_summary(self) -> None:
        ctx = _make_ctx()
        result = await mark_conflict_tool.execute(
            ctx,
            conflict_with="x",
            summary="",
        )
        assert result.is_error is True
        assert _drain(ctx) == []


# ---------------------------------------------------------------------------
# declare_progress
# ---------------------------------------------------------------------------


class TestDeclareProgress:
    @pytest.mark.asyncio
    async def test_emits_event_with_percent(self) -> None:
        ctx = _make_ctx("worker-3")
        result = await declare_progress_tool.execute(
            ctx,
            summary="Draft complete, running tests.",
            task_id="t-9",
            status="in_progress",
            percent_complete=75,
        )
        assert result.is_error is False
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentProgressDeclaredEvent)
        assert event.percent_complete == 75
        assert event.status == "in_progress"
        assert event.task_id == "t-9"

    @pytest.mark.asyncio
    async def test_rejects_bad_status(self) -> None:
        ctx = _make_ctx()
        result = await declare_progress_tool.execute(
            ctx,
            summary="S",
            status="on_fire",
        )
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_rejects_percent_out_of_range(self) -> None:
        ctx = _make_ctx()
        result = await declare_progress_tool.execute(
            ctx,
            summary="S",
            percent_complete=150,
        )
        assert result.is_error is True
        assert _drain(ctx) == []


# ---------------------------------------------------------------------------
# signal_goal_complete
# ---------------------------------------------------------------------------


class TestSignalGoalComplete:
    @pytest.mark.asyncio
    async def test_emits_event_with_artifacts(self) -> None:
        ctx = _make_ctx("coord")
        result = await signal_goal_complete_tool.execute(
            ctx,
            summary="All acceptance criteria met.",
            artifacts=["art-1", "art-2", " ", "art-3"],
        )
        assert result.is_error is False
        events = _drain(ctx)
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, AgentGoalCompletedEvent)
        # blank artifacts filtered out
        assert event.artifacts == ["art-1", "art-2", "art-3"]

    @pytest.mark.asyncio
    async def test_rejects_empty_summary(self) -> None:
        ctx = _make_ctx()
        result = await signal_goal_complete_tool.execute(ctx, summary="   ")
        assert result.is_error is True
        assert _drain(ctx) == []


# ---------------------------------------------------------------------------
# Cross-tool invariants
# ---------------------------------------------------------------------------


class TestDecisionLogInvariants:
    @pytest.mark.asyncio
    async def test_one_tool_call_emits_exactly_one_event(self) -> None:
        """Every successful subjective decision produces exactly one event."""
        ctx = _make_ctx("coord")
        await assign_task_tool.execute(
            ctx,
            target_agent_id="w",
            task_title="T",
            rationale="R",
        )
        await declare_progress_tool.execute(ctx, summary="S")
        await signal_goal_complete_tool.execute(ctx, summary="Done")
        events = _drain(ctx)
        assert len(events) == 3
        assert {e.__class__.__name__ for e in events} == {
            "AgentTaskAssignedEvent",
            "AgentProgressDeclaredEvent",
            "AgentGoalCompletedEvent",
        }

    @pytest.mark.asyncio
    async def test_validation_failures_emit_nothing(self) -> None:
        """Structural validation must not leak a partial event."""
        ctx = _make_ctx()
        await assign_task_tool.execute(
            ctx,
            target_agent_id="",
            task_title="",
            rationale="",
        )
        await refuse_task_tool.execute(ctx, reason="")
        await declare_progress_tool.execute(ctx, summary="S", percent_complete=-5)
        assert _drain(ctx) == []
