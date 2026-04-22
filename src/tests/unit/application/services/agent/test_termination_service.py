"""Unit tests for TerminationService."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import override

from src.application.services.agent.termination_service import (
    TerminationContext,
    TerminationService,
)
from src.domain.events.agent_events import AgentConversationFinishedEvent
from src.domain.model.agent.conversation.goal_contract import GoalBudget, GoalContract
from src.domain.model.agent.conversation.termination import (
    BudgetCounters,
    TerminationReason,
)
from src.domain.model.agent.conversation.verdict_status import VerdictStatus
from src.infrastructure.adapters.secondary.notifications.in_memory_receipt_notifier import (
    InMemoryReceiptNotifier,
)


@dataclass
class _SpySink:
    events: list[AgentConversationFinishedEvent] = field(default_factory=list)

    async def publish(self, event: AgentConversationFinishedEvent) -> None:
        self.events.append(event)


class _FailingNotifier(InMemoryReceiptNotifier):
    @override
    async def deliver(self, **_kwargs: object) -> bool:  # type: ignore[override]
        raise RuntimeError("boom")


def _goal_contract() -> GoalContract:
    return GoalContract(
        primary_goal="ship it",
        budget=GoalBudget(max_turns=3, max_usd=1.0, max_wall_seconds=30),
    )


class TestEvaluate:
    async def test_goal_completed_wins(self) -> None:
        svc = TerminationService(event_sink=_SpySink(), receipt_notifier=InMemoryReceiptNotifier())
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            goal_contract=_goal_contract(),
            counters=BudgetCounters(turns=999),
            goal_completed_event_id="evt-123",
            goal_completed_summary="All green.",
            goal_completed_artifacts=["a1", "a2"],
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        assert decision.reason is TerminationReason.GOAL_COMPLETED
        assert decision.triggered_by_event == "evt-123"

    async def test_budget_fires_when_no_goal(self) -> None:
        svc = TerminationService(event_sink=_SpySink(), receipt_notifier=InMemoryReceiptNotifier())
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            goal_contract=_goal_contract(),
            counters=BudgetCounters(turns=3),
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        assert decision.reason is TerminationReason.BUDGET_TURNS

    async def test_safety_fires_when_no_goal_or_budget(self) -> None:
        svc = TerminationService(event_sink=_SpySink(), receipt_notifier=InMemoryReceiptNotifier())
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            goal_contract=_goal_contract(),
            latest_verdict=VerdictStatus.LOOPING,
            latest_verdict_rationale="same tool called 5x",
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        assert decision.reason is TerminationReason.SAFETY_LOOPING

    async def test_returns_none_when_all_healthy(self) -> None:
        svc = TerminationService(event_sink=_SpySink(), receipt_notifier=InMemoryReceiptNotifier())
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            goal_contract=_goal_contract(),
            counters=BudgetCounters(turns=1),
            latest_verdict=VerdictStatus.HEALTHY,
        )
        assert svc.evaluate(ctx) is None


class TestFinalize:
    async def test_emits_event_and_delivers_receipt(self) -> None:
        sink = _SpySink()
        notifier = InMemoryReceiptNotifier()
        svc = TerminationService(event_sink=sink, receipt_notifier=notifier)
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            goal_contract=_goal_contract(),
            counters=BudgetCounters(turns=2, usd=0.5, wall_seconds=10),
            goal_completed_event_id="evt-1",
            goal_completed_summary="done",
            goal_completed_artifacts=["artifact-1"],
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        event = await svc.finalize(ctx, decision, resumable_state={"cursor": "step-5"})
        assert len(sink.events) == 1
        emitted = sink.events[0]
        assert emitted is event
        assert emitted.reason == "goal_completed"
        assert emitted.conversation_id == "c1"
        assert emitted.resumable_state == {"cursor": "step-5"}
        assert emitted.terminal_state["counters"]["turns"] == 2
        assert emitted.terminal_state["gate"] == "goal"
        assert emitted.terminal_state["goal_contract"]["primary_goal"] == "ship it"
        assert len(notifier.delivered) == 1
        assert notifier.delivered[0].reason == "goal_completed"
        assert notifier.delivered[0].payload["artifacts"] == ["artifact-1"]

    async def test_terminal_state_includes_verdict_for_safety(self) -> None:
        sink = _SpySink()
        svc = TerminationService(event_sink=sink, receipt_notifier=InMemoryReceiptNotifier())
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            goal_contract=_goal_contract(),
            latest_verdict=VerdictStatus.LOOPING,
            latest_verdict_rationale="agent repeats",
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        await svc.finalize(ctx, decision)
        assert sink.events[0].terminal_state["latest_verdict"] == "looping"
        assert sink.events[0].terminal_state["latest_verdict_rationale"] == "agent repeats"

    async def test_notifier_failure_does_not_block_event(self) -> None:
        sink = _SpySink()
        svc = TerminationService(event_sink=sink, receipt_notifier=_FailingNotifier())
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            goal_contract=_goal_contract(),
            counters=BudgetCounters(turns=3),
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        event = await svc.finalize(ctx, decision)
        assert event.reason == "budget_turns"
        assert len(sink.events) == 1

    async def test_user_cancel_finalizes(self) -> None:
        from src.domain.model.agent.conversation.termination import TerminationDecision

        sink = _SpySink()
        notifier = InMemoryReceiptNotifier()
        svc = TerminationService(event_sink=sink, receipt_notifier=notifier)
        ctx = TerminationContext(conversation_id="c1", user_id="u1")
        decision = TerminationDecision.user_cancel(rationale="user DELETE")
        event = await svc.finalize(ctx, decision)
        assert event.reason == "user_cancel"
        assert event.actor == "user"
        assert notifier.delivered[0].reason == "user_cancel"
