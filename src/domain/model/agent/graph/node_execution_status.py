"""Node execution status enumeration."""

from enum import Enum
from typing import override


class NodeExecutionStatus(str, Enum):
    """Lifecycle status of an individual node execution within a graph run.

    State transitions:
        PENDING -> RUNNING -> COMPLETED
        PENDING -> RUNNING -> FAILED
        PENDING -> SKIPPED (conditional edge not satisfied)
        RUNNING -> CANCELLED (graph cancelled or timeout)
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @override
    def __str__(self) -> str:
        return self.value

    @property
    def is_terminal(self) -> bool:
        """Check if this status represents a terminal state."""
        return self in {
            NodeExecutionStatus.COMPLETED,
            NodeExecutionStatus.FAILED,
            NodeExecutionStatus.SKIPPED,
            NodeExecutionStatus.CANCELLED,
        }
