"""
Agent Execution Status - Domain model for tracking agent execution state.

This model tracks the execution status of agent responses, enabling:
- Detection of in-progress executions after page refresh
- Event recovery from the correct position
- Proper state restoration in the frontend
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class AgentExecutionStatus(str, Enum):
    """Status of agent execution."""

    PENDING = "pending"  # Queued but not started
    RUNNING = "running"  # Currently executing
    COMPLETED = "completed"  # Successfully completed
    FAILED = "failed"  # Execution failed
    CANCELLED = "cancelled"  # Cancelled by user


@dataclass
class AgentExecution:
    """
    Tracks the execution status of an agent response.

    Each assistant message has an associated execution record that tracks:
    - Whether the agent is still running
    - The last event sequence for recovery
    - Error information if failed

    Attributes:
        id: Unique execution ID (usually same as message_id)
        conversation_id: The conversation this execution belongs to
        message_id: The assistant message being generated
        status: Current execution status
        last_event_sequence: Last emitted event sequence number
        started_at: When execution started
        completed_at: When execution completed (if finished)
        error_message: Error message if failed
        tenant_id: Tenant ID for multi-tenancy
        project_id: Project ID
    """

    id: str
    conversation_id: str
    message_id: str
    status: AgentExecutionStatus
    last_event_sequence: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    error_message: str | None = None
    tenant_id: str | None = None
    project_id: str | None = None

    @property
    def is_running(self) -> bool:
        """Check if execution is still running."""
        return self.status == AgentExecutionStatus.RUNNING

    @property
    def is_finished(self) -> bool:
        """Check if execution has finished (completed, failed, or cancelled)."""
        return self.status in (
            AgentExecutionStatus.COMPLETED,
            AgentExecutionStatus.FAILED,
            AgentExecutionStatus.CANCELLED,
        )

    def mark_running(self) -> None:
        """Mark execution as running."""
        self.status = AgentExecutionStatus.RUNNING
        self.started_at = datetime.now(UTC)

    def mark_completed(self) -> None:
        """Mark execution as completed."""
        self.status = AgentExecutionStatus.COMPLETED
        self.completed_at = datetime.now(UTC)

    def mark_failed(self, error_message: str) -> None:
        """Mark execution as failed with error message."""
        self.status = AgentExecutionStatus.FAILED
        self.completed_at = datetime.now(UTC)
        self.error_message = error_message

    def mark_cancelled(self) -> None:
        """Mark execution as cancelled."""
        self.status = AgentExecutionStatus.CANCELLED
        self.completed_at = datetime.now(UTC)

    def update_sequence(self, sequence: int) -> None:
        """Update the last event sequence number."""
        if sequence > self.last_event_sequence:
            self.last_event_sequence = sequence

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "status": self.status.value,
            "last_event_sequence": self.last_event_sequence,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "is_running": self.is_running,
            "is_finished": self.is_finished,
        }

    @classmethod
    def create(
        cls,
        conversation_id: str,
        message_id: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> "AgentExecution":
        """Factory method to create a new execution in RUNNING status."""
        return cls(
            id=message_id,  # Use message_id as execution_id
            conversation_id=conversation_id,
            message_id=message_id,
            status=AgentExecutionStatus.RUNNING,
            tenant_id=tenant_id,
            project_id=project_id,
        )
