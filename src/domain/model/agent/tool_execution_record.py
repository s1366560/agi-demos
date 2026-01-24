"""ToolExecutionRecord entity for tracking tool executions."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class ToolExecutionRecord(Entity):
    """
    Record of a single tool execution during agent processing.

    This entity stores the complete history of tool executions for each message,
    enabling proper timeline reconstruction when loading historical conversations.
    """

    conversation_id: str
    message_id: str
    call_id: str
    tool_name: str
    tool_input: Dict[str, Any] = field(default_factory=dict)
    tool_output: str | None = None
    status: str = "running"  # running, success, failed
    error: str | None = None
    step_number: int | None = None
    sequence_number: int = 0  # Order within message
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    duration_ms: int | None = None

    def mark_success(self, output: str) -> None:
        """Mark this execution as successful."""
        self.status = "success"
        self.tool_output = output
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)

    def mark_failed(self, error: str) -> None:
        """Mark this execution as failed."""
        self.status = "failed"
        self.error = error
        self.completed_at = datetime.utcnow()
        if self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
            "status": self.status,
            "error": self.error,
            "step_number": self.step_number,
            "sequence_number": self.sequence_number,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
        }
