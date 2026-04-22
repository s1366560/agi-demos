"""Conversation termination domain (Track B · Agent First · P2-3 phase-2).

The three-gate termination model from ``p2-decisions.md``:

1. **Goal gate** — coordinator calls ``signal_goal_complete`` → emits
   ``AgentGoalCompletedEvent``; this gate is a pure subscription, not a
   judgment.
2. **Budget gate** — arithmetic comparison of counters against
   ``GoalContract.budget``.  Pure integer/float math, Agent First compliant.
3. **Safety gate** — supervisor ``verdict`` ∈ {``LOOPING``} **OR** structural
   doom-loop signal ratified by a supervisor verdict.  The *judgment* (is this
   truly a loop?) stays with the Supervisor Agent; the gate here only tests
   set-membership on the resulting verdict string.

Any gate firing produces a :class:`TerminationDecision` (a value object).  The
service layer is responsible for emitting ``AgentConversationFinishedEvent``
and invoking the ``ReceiptNotifier`` port; this module stays IO-free.

``user_cancel`` is an explicit user-driven gate (via HTTP ``DELETE`` on the
conversation) — it bypasses the internal evaluator and is modeled by
:meth:`TerminationDecision.user_cancel`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.domain.model.agent.conversation.goal_contract import GoalBudget
from src.domain.model.agent.conversation.verdict_status import VerdictStatus


class TerminationReason(str, Enum):
    """Structural reasons a conversation may terminate."""

    GOAL_COMPLETED = "goal_completed"
    BUDGET_TURNS = "budget_turns"
    BUDGET_USD = "budget_usd"
    BUDGET_WALL_SECONDS = "budget_wall_seconds"
    SAFETY_LOOPING = "safety_looping"
    SAFETY_DOOM_LOOP = "safety_doom_loop"
    USER_CANCEL = "user_cancel"

    @property
    def gate(self) -> str:
        """Which of the three gates this reason belongs to."""
        if self is TerminationReason.GOAL_COMPLETED:
            return "goal"
        if self in _BUDGET_REASONS:
            return "budget"
        if self in _SAFETY_REASONS:
            return "safety"
        return "user"


_BUDGET_REASONS: frozenset[TerminationReason] = frozenset(
    {
        TerminationReason.BUDGET_TURNS,
        TerminationReason.BUDGET_USD,
        TerminationReason.BUDGET_WALL_SECONDS,
    }
)
_SAFETY_REASONS: frozenset[TerminationReason] = frozenset(
    {
        TerminationReason.SAFETY_LOOPING,
        TerminationReason.SAFETY_DOOM_LOOP,
    }
)


@dataclass(frozen=True)
class BudgetCounters:
    """Current measured counters for the budget gate.

    ``usd`` is a non-negative float; ``turns`` / ``wall_seconds`` are
    non-negative ints.  All three are arithmetic; no judgment.
    """

    turns: int = 0
    usd: float = 0.0
    wall_seconds: int = 0

    def __post_init__(self) -> None:
        if self.turns < 0:
            raise ValueError(f"BudgetCounters.turns must be >= 0, got {self.turns}")
        if self.usd < 0:
            raise ValueError(f"BudgetCounters.usd must be >= 0, got {self.usd}")
        if self.wall_seconds < 0:
            raise ValueError(f"BudgetCounters.wall_seconds must be >= 0, got {self.wall_seconds}")


@dataclass(frozen=True)
class TerminationDecision:
    """Value object: the outcome of the termination evaluator.

    ``rationale`` is a short, deterministic string describing the arithmetic
    / membership fact that fired the gate (e.g. ``"turns=42 > max_turns=40"``).
    It is **not** an agent-authored explanation — the agent-authored piece is
    ``verdict.rationale`` and is carried separately when relevant.
    """

    reason: TerminationReason
    actor: str = "system"  # "system" | "coordinator" | "supervisor" | "user"
    rationale: str = ""
    triggered_by_event: str = ""  # opaque event id / correlation handle
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def gate(self) -> str:
        return self.reason.gate

    @classmethod
    def user_cancel(cls, *, actor: str = "user", rationale: str = "") -> TerminationDecision:
        return cls(reason=TerminationReason.USER_CANCEL, actor=actor, rationale=rationale)


def evaluate_budget(
    budget: GoalBudget | None,
    counters: BudgetCounters,
) -> TerminationDecision | None:
    """Pure arithmetic: return a budget decision if any cap is exceeded.

    Evaluated in a fixed order so the rationale is deterministic:
    ``turns`` → ``usd`` → ``wall_seconds``.  ``None`` caps are unbounded and
    skipped.  Returns ``None`` when no cap fires.
    """
    if budget is None:
        return None

    if budget.max_turns is not None and counters.turns >= budget.max_turns:
        return TerminationDecision(
            reason=TerminationReason.BUDGET_TURNS,
            actor="system",
            rationale=f"turns={counters.turns} >= max_turns={budget.max_turns}",
        )
    if budget.max_usd is not None and counters.usd >= budget.max_usd:
        return TerminationDecision(
            reason=TerminationReason.BUDGET_USD,
            actor="system",
            rationale=f"usd={counters.usd:.4f} >= max_usd={budget.max_usd:.4f}",
        )
    if budget.max_wall_seconds is not None and counters.wall_seconds >= budget.max_wall_seconds:
        return TerminationDecision(
            reason=TerminationReason.BUDGET_WALL_SECONDS,
            actor="system",
            rationale=(
                f"wall_seconds={counters.wall_seconds} "
                f">= max_wall_seconds={budget.max_wall_seconds}"
            ),
        )
    return None


def evaluate_safety(
    *,
    verdict_status: VerdictStatus | str | None,
    doom_loop_triggered: bool = False,
    verdict_rationale: str = "",
    supervisor_actor: str = "supervisor",
) -> TerminationDecision | None:
    """Safety gate: verdict-only set-membership.

    Two paths can fire this gate:

    - ``verdict_status == LOOPING`` → :attr:`TerminationReason.SAFETY_LOOPING`.
    - ``doom_loop_triggered`` is ``True`` **AND** the verdict is also
      ``LOOPING`` (supervisor ratified the signal) →
      :attr:`TerminationReason.SAFETY_DOOM_LOOP`.

    A structural doom-loop signal without supervisor ratification is
    intentionally NOT a termination — the gate requires agent confirmation
    (Agent First).  ``goal_drift`` / ``budget_risk`` / ``stalled`` are
    actionable verdicts but do not terminate on their own — they are for the
    coordinator to react to.
    """
    if verdict_status is None:
        return None

    if isinstance(verdict_status, str):
        try:
            verdict_status = VerdictStatus(verdict_status)
        except ValueError:
            return None

    if verdict_status is not VerdictStatus.LOOPING:
        return None

    reason = (
        TerminationReason.SAFETY_DOOM_LOOP
        if doom_loop_triggered
        else TerminationReason.SAFETY_LOOPING
    )
    rationale = verdict_rationale.strip() or (
        "doom_loop + supervisor looping" if doom_loop_triggered else "supervisor verdict=looping"
    )
    return TerminationDecision(
        reason=reason,
        actor=supervisor_actor,
        rationale=rationale,
    )


__all__ = [
    "BudgetCounters",
    "TerminationDecision",
    "TerminationReason",
    "evaluate_budget",
    "evaluate_safety",
]
