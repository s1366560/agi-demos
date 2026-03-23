"""Graph run status enumeration."""

from enum import Enum
from typing import override


class GraphRunStatus(str, Enum):
    """Lifecycle status of a graph run instance.

    State transitions:
        PENDING -> RUNNING -> COMPLETED
        PENDING -> RUNNING -> FAILED
        PENDING -> RUNNING -> CANCELLED
        PENDING -> CANCELLED
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @override
    def __str__(self) -> str:
        return self.value

    @property
    def is_terminal(self) -> bool:
        """Check if this status represents a terminal state."""
        return self in {
            GraphRunStatus.COMPLETED,
            GraphRunStatus.FAILED,
            GraphRunStatus.CANCELLED,
        }
