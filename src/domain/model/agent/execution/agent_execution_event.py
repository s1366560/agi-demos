"""AgentExecutionEvent entity for persisting SSE events during agent execution.

This entity stores all Server-Sent Events (SSE) emitted during agent execution,
enabling event replay for reconnection and conversation switching scenarios.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.events.agent_events import (
    AgentDomainEvent,
    AgentEventType,  # Unified event type from domain events
)
from src.domain.shared_kernel import Entity

# Additional event types for persistence layer (timeline-specific)
USER_MESSAGE = "user_message"
ASSISTANT_MESSAGE = "assistant_message"

# Re-export for backward compatibility
__all__ = ["ASSISTANT_MESSAGE", "USER_MESSAGE", "AgentEventType", "AgentExecutionEvent"]


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
        event_time_us: Microsecond-precision UTC timestamp for ordering
        event_counter: Monotonic counter within the same microsecond
        created_at: When this event was created
    """

    conversation_id: str
    message_id: str
    event_type: AgentEventType | str
    event_data: dict[str, Any] = field(default_factory=dict)
    event_time_us: int = 0
    event_counter: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "event_type": self.event_type,
            "event_data": self.event_data,
            "event_time_us": self.event_time_us,
            "event_counter": self.event_counter,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_sse_format(self) -> dict[str, Any]:
        """Convert to SSE event format for streaming."""
        return {
            "type": self.event_type,
            "data": self.event_data,
            "event_time_us": self.event_time_us,
            "event_counter": self.event_counter,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_domain_event(
        cls,
        event: AgentDomainEvent,
        conversation_id: str,
        message_id: str,
        event_time_us: int = 0,
        event_counter: int = 0,
    ) -> "AgentExecutionEvent":
        """Create from domain event."""
        return cls(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type=event.event_type.value,
            event_data=event.model_dump(exclude={"event_type", "timestamp"}),
            event_time_us=event_time_us,
            event_counter=event_counter,
            created_at=datetime.fromtimestamp(event.timestamp),
        )

    @property
    def is_message_event(self) -> bool:
        """Check if this event represents a user or assistant message."""
        event_type_str = (
            self.event_type.value
            if hasattr(self.event_type, "value")
            else str(self.event_type)
        )
        return event_type_str in (USER_MESSAGE, ASSISTANT_MESSAGE)

    @property
    def is_delta_event(self) -> bool:
        """Check if this is a streaming delta event (not persisted for replay)."""
        event_type_str = (
            self.event_type.value
            if hasattr(self.event_type, "value")
            else str(self.event_type)
        )
        return event_type_str in ("text_delta", "thought_delta")

    @staticmethod
    def filter_for_replay(
        events: list["AgentExecutionEvent"],
    ) -> list["AgentExecutionEvent"]:
        """Filter events for replay, excluding delta events.

        Delta events (text_delta, thought_delta) are transient streaming events
        that should not be replayed. Their final content is captured in
        text_end and thought events respectively.

        Args:
            events: Full list of events from storage

        Returns:
            Filtered list suitable for client replay
        """
        return [e for e in events if not e.is_delta_event]
