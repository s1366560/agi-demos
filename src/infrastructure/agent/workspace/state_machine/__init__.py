"""Task state machine — pure, role-aware transition spec.

See :mod:`.transitions` for the implementation and full rationale.

This package is **not wired into runtime code yet**. Migrations M2+ will replace
scattered ``if status == ...`` branches in ``workspace_goal_runtime`` with calls
into :func:`transition`.
"""

from __future__ import annotations

from .transitions import (
    IllegalTransitionError,
    TaskRole,
    allowed_next,
    can_transition,
    guard_reasons,
    transition,
)

__all__ = [
    "IllegalTransitionError",
    "TaskRole",
    "allowed_next",
    "can_transition",
    "guard_reasons",
    "transition",
]
