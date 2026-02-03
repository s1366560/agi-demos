"""AgentExecutionEvent entity for persisting SSE events during agent execution.

This entity stores all Server-Sent Events (SSE) emitted during agent execution,
enabling event replay for reconnection and conversation switching scenarios.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

from src.domain.events.agent_events import (
    AgentDomainEvent,
    AgentEventType,  # Unified event type from domain events
)
from src.domain.shared_kernel import Entity

# Additional event types for persistence layer (timeline-specific)
USER_MESSAGE = "user_message"
ASSISTANT_MESSAGE = "assistant_message"

# Re-export for backward compatibility
__all__ = ["AgentExecutionEvent", "AgentEventType", "USER_MESSAGE", "ASSISTANT_MESSAGE"]


@dataclass(kw_only=True)
class AgentExecutionEvent(Entity):
    """
    A single SSE event during agent execution.

    This entity captures all events emitted during the agent's ReAct loop,
    storing them for replay purposes when a client reconnects or switches
    between conversations.

    Attributes:
        conversation_id: The conversation this event belongs to
        message_id: The message this event is associated with
        event_type: Type of SSE event (thought, act, observe, etc.)
        event_data: JSON payload of the event
        sequence_number: Monotonically increasing number for ordering
        created_at: When this event was created
    """

    conversation_id: str
    message_id: str
    event_type: AgentEventType | str
    event_data: Dict[str, Any] = field(default_factory=dict)
    sequence_number: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "event_type": self.event_type,
            "event_data": self.event_data,
            "sequence_number": self.sequence_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_sse_format(self) -> Dict[str, Any]:
        """Convert to SSE event format for streaming."""
        return {
            "type": self.event_type,
            "data": self.event_data,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_domain_event(
        cls,
        event: AgentDomainEvent,
        conversation_id: str,
        message_id: str,
        sequence_number: int = 0,
    ) -> "AgentExecutionEvent":
        """Create from domain event."""
        return cls(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type=event.event_type.value,
            event_data=event.model_dump(exclude={"event_type", "timestamp"}),
            sequence_number=sequence_number,
            created_at=datetime.fromtimestamp(event.timestamp),
        )
