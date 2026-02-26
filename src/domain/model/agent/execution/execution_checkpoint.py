"""ExecutionCheckpoint entity for agent execution resumption.

This entity stores execution checkpoints at key points during agent execution,
enabling recovery from failures and disconnections.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class CheckpointType(str, Enum):
    """Types of execution checkpoints."""

    LLM_COMPLETE = "llm_complete"  # After LLM generates thought/action
    TOOL_START = "tool_start"  # Before tool execution
    TOOL_COMPLETE = "tool_complete"  # After tool execution
    STEP_COMPLETE = "step_complete"  # After a ReAct step completes
    WORK_PLAN_CREATED = "work_plan_created"  # After work plan is generated


@dataclass(kw_only=True)
class ExecutionCheckpoint(Entity):
    """
    A checkpoint during agent execution for recovery purposes.

    Checkpoints capture the execution state at key moments, allowing
    the agent to resume from that point if execution is interrupted.

    Attributes:
        conversation_id: The conversation this checkpoint belongs to
        message_id: The message being processed
        checkpoint_type: Type of checkpoint
        execution_state: Complete execution state snapshot
        step_number: Current ReAct step number
        created_at: When this checkpoint was created
    """

    conversation_id: str
    message_id: str | None = None
    checkpoint_type: CheckpointType | str
    execution_state: dict[str, Any] = field(default_factory=dict)
    step_number: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "checkpoint_type": str(self.checkpoint_type),
            "execution_state": self.execution_state,
            "step_number": self.step_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
