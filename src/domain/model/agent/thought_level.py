"""ThoughtLevel value object for distinguishing thinking levels."""

from enum import Enum


class ThoughtLevel(str, Enum):
    """Level of agent thinking.

    WORK represents high-level planning (work-level thinking).
    TASK represents detailed reasoning for the current step (task-level thinking).
    """

    WORK = "work"  # High-level planning
    TASK = "task"  # Detailed reasoning for current step
