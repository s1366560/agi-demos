"""Shared constants for workspace goal sensing decisions and source types."""

from __future__ import annotations

from typing import Final

ADOPT_EXISTING_GOAL: Final[str] = "adopt_existing_goal"
FORMALIZE_NEW_GOAL: Final[str] = "formalize_new_goal"
DEFER: Final[str] = "defer"
REJECT_AS_NON_GOAL: Final[str] = "reject_as_non_goal"

EXISTING_ROOT_TASK: Final[str] = "existing_root_task"
EXISTING_OBJECTIVE: Final[str] = "existing_objective"
BLACKBOARD_SIGNAL: Final[str] = "blackboard_signal"
MESSAGE_SIGNAL: Final[str] = "message_signal"
CONVERGED_SIGNAL: Final[str] = "converged_signal"
