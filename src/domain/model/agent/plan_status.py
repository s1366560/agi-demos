"""PlanStatus enum for work plan status tracking."""

from enum import Enum


class PlanStatus(str, Enum):
    """Status of a work plan.

    PLANNING: The plan is being generated
    IN_PROGRESS: The plan is being executed
    COMPLETED: All steps in the plan have been executed successfully
    FAILED: The plan execution failed
    """

    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
