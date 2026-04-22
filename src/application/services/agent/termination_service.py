"""Termination service (Track B · Agent First · P2-3 phase-2).

Composes the three structural gates defined in
``src.domain.model.agent.conversation.termination`` and, on fire:

1. Constructs a :class:`TerminationDecision`.
2. Emits :class:`AgentConversationFinishedEvent` via the provided event sink.
3. Invokes the configured :class:`ReceiptNotifier` (best-effort; failures are
   swallowed so they cannot block termination).

The service is **Agent First** by construction: every subjective judgment
(is this looping? is this a loop?) is still made by the Supervisor agent via
``verdict`` tool-calls.  The service only performs arithmetic + enum
set-membership + a fanout.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.domain.events.agent_events import AgentConversationFinishedEvent
from src.domain.model.agent.conversation.termination import (
    BudgetCounters,
    TerminationDecision,
    TerminationReason,
    evaluate_budget,
    evaluate_safety,
)
from src.domain.model.agent.conversation.verdict_status import VerdictStatus
from src.domain.ports.agent.receipt_notifier import ReceiptNotifier

logger = logging.getLogger(__name__)


class _EventSink(Protocol):
    """Minimal contract for an async event publisher."""

    async def publish(self, event: AgentConversationFinishedEvent) -> None: ...


@dataclass
class TerminationContext:
    """Snapshot of all inputs the three gates need.

    Budget caps (``max_turns`` / ``max_usd`` / ``max_wall_seconds``) are
    supplied by the application layer from the owning Workspace /
    WorkspaceTask context. ``None`` means unbounded on that axis.

    ``goal_completed_event_id`` is non-empty iff a coordinator already emitted
    ``AgentGoalCompletedEvent`` this turn; the service treats that as the
    goal gate firing.  The service NEVER inspects message content to decide
    whether a goal is complete.
    """

    conversation_id: str
    user_id: str
    max_turns: int | None = None
    max_usd: float | None = None
    max_wall_seconds: int | None = None
    counters: BudgetCounters = field(default_factory=BudgetCounters)
    latest_verdict: VerdictStatus | str | None = None
    latest_verdict_rationale: str = ""
    supervisor_actor: str = "supervisor"
    doom_loop_triggered: bool = False
    goal_completed_event_id: str = ""
    goal_completed_summary: str = ""
    goal_completed_artifacts: list[str] = field(default_factory=list)
    goal_completed_actor: str = "coordinator"


class TerminationService:
    """Evaluate + fire the three termination gates."""

    def __init__(
        self,
        *,
        event_sink: _EventSink,
        receipt_notifier: ReceiptNotifier,
    ) -> None:
        self._events = event_sink
        self._notifier = receipt_notifier

    def evaluate(self, ctx: TerminationContext) -> TerminationDecision | None:
        """Return the first gate that fires, in order: goal → budget → safety.

        This ordering matters: a coordinator-declared goal completion wins
        over a budget breach that happened in the same turn (user intent).
        """
        if ctx.goal_completed_event_id:
            return TerminationDecision(
                reason=TerminationReason.GOAL_COMPLETED,
                actor=ctx.goal_completed_actor or "coordinator",
                rationale=ctx.goal_completed_summary.strip()[:500],
                triggered_by_event=ctx.goal_completed_event_id,
                metadata={"artifacts": ",".join(ctx.goal_completed_artifacts)},
            )

        budget_decision = evaluate_budget(
            max_turns=ctx.max_turns,
            max_usd=ctx.max_usd,
            max_wall_seconds=ctx.max_wall_seconds,
            counters=ctx.counters,
        )
        if budget_decision is not None:
            return budget_decision

        safety_decision = evaluate_safety(
            verdict_status=ctx.latest_verdict,
            doom_loop_triggered=ctx.doom_loop_triggered,
            verdict_rationale=ctx.latest_verdict_rationale,
            supervisor_actor=ctx.supervisor_actor,
        )
        return safety_decision

    async def finalize(
        self,
        ctx: TerminationContext,
        decision: TerminationDecision,
        *,
        resumable_state: dict[str, Any] | None = None,
        terminal_state_extra: dict[str, Any] | None = None,
    ) -> AgentConversationFinishedEvent:
        """Emit the finished event and deliver the receipt. Idempotent-safe
        at the callsite — the service itself does not track prior emissions;
        the application layer MUST guard against double-finalize.
        """
        terminal_state: dict[str, Any] = {
            "reason": decision.reason.value,
            "gate": decision.gate,
            "actor": decision.actor,
            "rationale": decision.rationale,
            "counters": {
                "turns": ctx.counters.turns,
                "usd": ctx.counters.usd,
                "wall_seconds": ctx.counters.wall_seconds,
            },
            "budget_caps": {
                "max_turns": ctx.max_turns,
                "max_usd": ctx.max_usd,
                "max_wall_seconds": ctx.max_wall_seconds,
            },
        }
        if ctx.latest_verdict is not None:
            latest = (
                ctx.latest_verdict.value
                if isinstance(ctx.latest_verdict, VerdictStatus)
                else str(ctx.latest_verdict)
            )
            terminal_state["latest_verdict"] = latest
            if ctx.latest_verdict_rationale:
                terminal_state["latest_verdict_rationale"] = ctx.latest_verdict_rationale
        if terminal_state_extra:
            terminal_state.update(terminal_state_extra)

        event = AgentConversationFinishedEvent(
            conversation_id=ctx.conversation_id,
            reason=decision.reason.value,
            actor=decision.actor,
            rationale=decision.rationale,
            terminal_state=terminal_state,
            resumable_state=dict(resumable_state or {}),
            metadata={
                "triggered_by_event": decision.triggered_by_event,
                **decision.metadata,
            },
        )
        await self._events.publish(event)

        try:
            await self._notifier.deliver(
                conversation_id=ctx.conversation_id,
                user_id=ctx.user_id,
                reason=decision.reason.value,
                rationale=decision.rationale,
                terminal_state=terminal_state,
                payload={
                    "artifacts": ctx.goal_completed_artifacts
                    if decision.reason is TerminationReason.GOAL_COMPLETED
                    else [],
                },
            )
        except Exception:
            logger.exception(
                "receipt_notifier.deliver failed for conversation=%s reason=%s",
                ctx.conversation_id,
                decision.reason.value,
            )

        return event


__all__ = [
    "TerminationContext",
    "TerminationService",
]
