"""Task state machine — pure, role-aware.

Models the legal transitions of ``WorkspaceTaskStatus`` for the two roles that
actually appear in the autonomy loop:

- ``ROOT``       → goal_root task (the user's high-level objective)
- ``EXECUTION``  → leaf execution task dispatched to a worker

The module is **pure** (no DB, no LLM, no I/O). It is intentionally **not wired
into runtime code yet** — that is the next migration step (M2+). M1 only
establishes the canonical spec + tests so later refactors can replace scattered
``if status == ...`` branches with a single ``transition()`` call.

Public API
----------
- :class:`TaskRole`
- :class:`IllegalTransitionError`
- :func:`allowed_next(role, current)` → ``frozenset[WorkspaceTaskStatus]``
- :func:`can_transition(role, current, target)` → ``bool``
- :func:`guard_reasons(role, current, target)` → ``list[str]`` (empty ⇔ legal)
- :func:`transition(role, current, target)` → returns ``target`` or raises
"""

from __future__ import annotations

from enum import Enum

from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus

__all__ = [
    "IllegalTransitionError",
    "TaskRole",
    "allowed_next",
    "can_transition",
    "guard_reasons",
    "transition",
]


class TaskRole(str, Enum):
    """Role a task plays in the workspace autonomy loop."""

    ROOT = "root"
    EXECUTION = "execution"


class IllegalTransitionError(ValueError):
    """Raised when a requested status transition is not permitted."""

    def __init__(
        self,
        role: TaskRole,
        current: WorkspaceTaskStatus,
        target: WorkspaceTaskStatus,
        reasons: list[str],
    ) -> None:
        self.role = role
        self.current = current
        self.target = target
        self.reasons = reasons
        detail = "; ".join(reasons) if reasons else "transition not allowed"
        super().__init__(
            f"IllegalTransition role={role.value} {current.value} -> {target.value}: {detail}"
        )


_S = WorkspaceTaskStatus

# Terminal statuses that cannot transition further. Re-opening a terminal task
# requires a new row (replan), not a state-machine transition — this is the
# invariant P2c relies on when marking a root DONE.
_TERMINAL: frozenset[WorkspaceTaskStatus] = frozenset({_S.DONE})

# Root task (goal_root) transitions.
#
# The current runtime only ever moves a root through this coarse lifecycle:
#   TODO → IN_PROGRESS → (DONE | BLOCKED)
# BLOCKED is reversible back to IN_PROGRESS when human review resolves it.
# Orchestration-only statuses (DISPATCHED/EXECUTING/REPORTED/ADJUDICATING) are
# **never** legal for a root — they describe worker-side lifecycle only.
_ROOT_TRANSITIONS: dict[WorkspaceTaskStatus, frozenset[WorkspaceTaskStatus]] = {
    _S.TODO: frozenset({_S.IN_PROGRESS, _S.BLOCKED}),
    _S.IN_PROGRESS: frozenset({_S.DONE, _S.BLOCKED}),
    _S.BLOCKED: frozenset({_S.IN_PROGRESS, _S.DONE}),
    _S.DONE: frozenset(),  # terminal
    # Orchestration-only → empty (no legal targets; entering these is illegal too)
    _S.DISPATCHED: frozenset(),
    _S.EXECUTING: frozenset(),
    _S.REPORTED: frozenset(),
    _S.ADJUDICATING: frozenset(),
}

# Statuses that are illegal as the CURRENT state of a root (regardless of target).
_ROOT_ILLEGAL_CURRENT: frozenset[WorkspaceTaskStatus] = frozenset(
    {_S.DISPATCHED, _S.EXECUTING, _S.REPORTED, _S.ADJUDICATING}
)

# Execution task (leaf) transitions.
#
# Canonical happy path:
#   TODO → DISPATCHED → EXECUTING → REPORTED → ADJUDICATING → DONE
# Side branches:
#   * any running state → BLOCKED (needs human / error escalation)
#   * BLOCKED → TODO (replan)
#   * REPORTED/ADJUDICATING → TODO (adjudicator rejects → replan)
#   * DISPATCHED → TODO (worker bounced, redispatch)
#   * ADJUDICATING → BLOCKED (final verdict needs_human)
_EXECUTION_TRANSITIONS: dict[WorkspaceTaskStatus, frozenset[WorkspaceTaskStatus]] = {
    _S.TODO: frozenset({_S.DISPATCHED, _S.BLOCKED}),
    _S.DISPATCHED: frozenset({_S.EXECUTING, _S.TODO, _S.BLOCKED}),
    _S.EXECUTING: frozenset({_S.REPORTED, _S.BLOCKED}),
    _S.REPORTED: frozenset({_S.ADJUDICATING, _S.TODO, _S.BLOCKED}),
    _S.ADJUDICATING: frozenset({_S.DONE, _S.TODO, _S.BLOCKED}),
    _S.BLOCKED: frozenset({_S.TODO}),
    _S.DONE: frozenset(),  # terminal
    # Coarse status not used by execution tasks directly.
    _S.IN_PROGRESS: frozenset(),
}

# Statuses that are illegal as the CURRENT state of an execution task.
_EXECUTION_ILLEGAL_CURRENT: frozenset[WorkspaceTaskStatus] = frozenset({_S.IN_PROGRESS})


def _table(role: TaskRole) -> dict[WorkspaceTaskStatus, frozenset[WorkspaceTaskStatus]]:
    return _ROOT_TRANSITIONS if role is TaskRole.ROOT else _EXECUTION_TRANSITIONS


def _illegal_current(role: TaskRole) -> frozenset[WorkspaceTaskStatus]:
    return _ROOT_ILLEGAL_CURRENT if role is TaskRole.ROOT else _EXECUTION_ILLEGAL_CURRENT


def allowed_next(role: TaskRole, current: WorkspaceTaskStatus) -> frozenset[WorkspaceTaskStatus]:
    """Return the set of legal target statuses from ``current`` for the given role.

    Returns an empty frozenset if the current status is terminal or illegal for
    the role.
    """
    if current in _illegal_current(role):
        return frozenset()
    return _table(role).get(current, frozenset())


def can_transition(
    role: TaskRole,
    current: WorkspaceTaskStatus,
    target: WorkspaceTaskStatus,
) -> bool:
    """Return True iff moving from ``current`` to ``target`` is permitted."""
    return target in allowed_next(role, current)


def guard_reasons(
    role: TaskRole,
    current: WorkspaceTaskStatus,
    target: WorkspaceTaskStatus,
) -> list[str]:
    """Explain why a transition is not permitted.

    Returns an empty list when the transition is legal, so callers can write::

        if reasons := guard_reasons(role, cur, nxt):
            log.warning("refused", reasons=reasons)
    """
    reasons: list[str] = []
    if current == target:
        reasons.append(f"no-op transition: already in {current.value}")
        return reasons
    if current in _illegal_current(role):
        reasons.append(f"current status {current.value} is not valid for role {role.value}")
    if current in _TERMINAL:
        reasons.append(f"current status {current.value} is terminal; cannot transition")
    allowed = allowed_next(role, current)
    if target not in allowed and not reasons:
        allowed_display = sorted(s.value for s in allowed)
        reasons.append(
            f"target {target.value} not in allowed set {allowed_display} for role {role.value}"
        )
    return reasons


def transition(
    role: TaskRole,
    current: WorkspaceTaskStatus,
    target: WorkspaceTaskStatus,
) -> WorkspaceTaskStatus:
    """Assert the transition is legal and return ``target``.

    Raises :class:`IllegalTransitionError` with structured reasons otherwise.
    This is the single chokepoint callers should funnel through once M2+
    refactors are wired in.
    """
    reasons = guard_reasons(role, current, target)
    if reasons:
        raise IllegalTransitionError(role, current, target, reasons)
    return target
