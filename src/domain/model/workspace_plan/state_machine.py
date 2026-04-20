"""State machines for :class:`TaskIntent` and :class:`TaskExecution`.

Pure. No I/O. This module is the single chokepoint for status transitions in
the new workspace-plan architecture.

Two independent axes:

* :class:`TaskIntent`    — user-facing lifecycle (4 states)
* :class:`TaskExecution` — orchestration transient (5 states)

They are independent: a node can be ``(IN_PROGRESS, DISPATCHED)`` or
``(IN_PROGRESS, RUNNING)`` or even ``(BLOCKED, IDLE)``. The supervisor
drives execution transitions; the verifier/adjudicator drives intent
transitions.
"""

from __future__ import annotations

from src.domain.model.workspace_plan.plan_node import TaskExecution, TaskIntent

__all__ = [
    "ExecutionTransitionError",
    "IntentTransitionError",
    "allowed_execution_next",
    "allowed_intent_next",
    "can_transition_execution",
    "can_transition_intent",
    "guard_execution_reasons",
    "guard_intent_reasons",
    "transition_execution",
    "transition_intent",
]


# --- TaskIntent -----------------------------------------------------------

_INTENT_TRANSITIONS: dict[TaskIntent, frozenset[TaskIntent]] = {
    TaskIntent.TODO: frozenset({TaskIntent.IN_PROGRESS, TaskIntent.BLOCKED}),
    TaskIntent.IN_PROGRESS: frozenset({TaskIntent.DONE, TaskIntent.BLOCKED, TaskIntent.TODO}),
    TaskIntent.BLOCKED: frozenset({TaskIntent.TODO, TaskIntent.IN_PROGRESS}),
    TaskIntent.DONE: frozenset(),  # terminal
}


class IntentTransitionError(ValueError):
    def __init__(
        self,
        current: TaskIntent,
        target: TaskIntent,
        reasons: list[str],
    ) -> None:
        self.current = current
        self.target = target
        self.reasons = reasons
        detail = "; ".join(reasons) if reasons else "transition not allowed"
        super().__init__(f"IllegalIntent {current.value} -> {target.value}: {detail}")


def allowed_intent_next(current: TaskIntent) -> frozenset[TaskIntent]:
    return _INTENT_TRANSITIONS.get(current, frozenset())


def can_transition_intent(current: TaskIntent, target: TaskIntent) -> bool:
    return target in allowed_intent_next(current)


def guard_intent_reasons(current: TaskIntent, target: TaskIntent) -> list[str]:
    reasons: list[str] = []
    if current == target:
        reasons.append(f"no-op transition: already in {current.value}")
        return reasons
    if current is TaskIntent.DONE:
        reasons.append("current is DONE (terminal)")
    if not can_transition_intent(current, target) and not reasons:
        allowed = sorted(s.value for s in allowed_intent_next(current))
        reasons.append(f"target {target.value} not in allowed set {allowed}")
    return reasons


def transition_intent(current: TaskIntent, target: TaskIntent) -> TaskIntent:
    reasons = guard_intent_reasons(current, target)
    if reasons:
        raise IntentTransitionError(current, target, reasons)
    return target


# --- TaskExecution --------------------------------------------------------
#
# Canonical happy path: IDLE → DISPATCHED → RUNNING → REPORTED → VERIFYING → IDLE
# Side branches:
#   * IDLE is the sink — verifier may bounce REPORTED/VERIFYING back to IDLE
#     so supervisor can redispatch (for replan).
#   * RUNNING → IDLE when worker was cancelled.

_EXECUTION_TRANSITIONS: dict[TaskExecution, frozenset[TaskExecution]] = {
    TaskExecution.IDLE: frozenset({TaskExecution.DISPATCHED}),
    TaskExecution.DISPATCHED: frozenset(
        {TaskExecution.RUNNING, TaskExecution.IDLE, TaskExecution.REPORTED}
    ),
    TaskExecution.RUNNING: frozenset({TaskExecution.REPORTED, TaskExecution.IDLE}),
    TaskExecution.REPORTED: frozenset({TaskExecution.VERIFYING, TaskExecution.IDLE}),
    TaskExecution.VERIFYING: frozenset({TaskExecution.IDLE}),
}


class ExecutionTransitionError(ValueError):
    def __init__(
        self,
        current: TaskExecution,
        target: TaskExecution,
        reasons: list[str],
    ) -> None:
        self.current = current
        self.target = target
        self.reasons = reasons
        detail = "; ".join(reasons) if reasons else "transition not allowed"
        super().__init__(f"IllegalExecution {current.value} -> {target.value}: {detail}")


def allowed_execution_next(current: TaskExecution) -> frozenset[TaskExecution]:
    return _EXECUTION_TRANSITIONS.get(current, frozenset())


def can_transition_execution(current: TaskExecution, target: TaskExecution) -> bool:
    return target in allowed_execution_next(current)


def guard_execution_reasons(current: TaskExecution, target: TaskExecution) -> list[str]:
    reasons: list[str] = []
    if current == target:
        reasons.append(f"no-op transition: already in {current.value}")
        return reasons
    if not can_transition_execution(current, target):
        allowed = sorted(s.value for s in allowed_execution_next(current))
        reasons.append(f"target {target.value} not in allowed set {allowed}")
    return reasons


def transition_execution(current: TaskExecution, target: TaskExecution) -> TaskExecution:
    reasons = guard_execution_reasons(current, target)
    if reasons:
        raise ExecutionTransitionError(current, target, reasons)
    return target
