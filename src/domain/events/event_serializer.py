"""Domain Event Serializer.

This module provides the SINGLE SOURCE OF TRUTH for converting AgentDomainEvent
to transport format (WebSocket/Redis). All event serialization should go through
this class to ensure consistency across the system.

Event Format:
    {
        "type": "event_type_string",  # e.g., "thought", "text_delta"
        "data": { ...event_fields },   # Event-specific data (without type/timestamp)
        "event_time_us": timestamp_us, # Microsecond timestamp for ordering
        "event_counter": counter,      # Counter within the same microsecond
        "timestamp": epoch_time,       # When the event occurred
    }
"""

from typing import Any

from .agent_events import (
    AgentDomainEvent,
    AgentEventType,
)


class EventSerializer:
    """Serializes domain events to transport format for WebSocket/Redis.

    This is the ONLY place where domain events are converted to dictionaries.
    All other code should use this class to ensure consistent event formatting.
    """

    @staticmethod
    def to_dict(
        event: AgentDomainEvent,
        message_id: str | None = None,
        event_time_us: int | None = None,
        event_counter: int | None = None,
    ) -> dict[str, Any]:
        """Convert domain event to dictionary for WebSocket/Redis transport.

        Args:
            event: The domain event to serialize
            message_id: Optional message ID for filtering events by message
            event_time_us: Optional microsecond timestamp for ordering
            event_counter: Optional counter within the same microsecond

        Returns:
            Dictionary with keys: type, data, event_time_us, event_counter, timestamp

        Examples:
            >>> event = AgentThoughtEvent(content="Thinking...", thought_level="task")
            >>> EventSerializer.to_dict(event, message_id="msg-123", event_time_us=1234567890123456, event_counter=0)
            {
                "type": "thought",
                "data": {"content": "Thinking...", "thought_level": "task"},
                "event_time_us": 1234567890123456,
                "event_counter": 0,
                "timestamp": 1234567890.123
            }
        """
        # Get all fields except event_type (which goes to "type") and timestamp
        event_data = event.model_dump(exclude={"event_type", "timestamp"})

        # Build the transport format
        result: dict[str, Any] = {
            "type": event.event_type.value,
            "data": event_data,
            "timestamp": event.timestamp,
        }

        # Add optional fields
        if message_id is not None:
            result["data"]["message_id"] = message_id
        if event_time_us is not None:
            result["event_time_us"] = event_time_us
        if event_counter is not None:
            result["event_counter"] = event_counter

        return result

    @staticmethod
    def to_dict_batch(
        events: list[tuple[AgentDomainEvent, str | None, int, int]],
    ) -> list[dict[str, Any]]:
        """Convert multiple domain events to transport format.

        Args:
            events: List of (event, message_id, event_time_us, event_counter) tuples

        Returns:
            List of serialized event dictionaries
        """
        return [
            EventSerializer.to_dict(
                event,
                message_id=msg_id,
                event_time_us=time_us,
                event_counter=counter,
            )
            for event, msg_id, time_us, counter in events
        ]

    @staticmethod
    def get_event_type_value(event_type: AgentEventType) -> str:
        """Get the string value of an event type.

        This is useful for frontend type generation.

        Args:
            event_type: The AgentEventType enum value

        Returns:
            String value of the event type (e.g., "thought", "text_delta")
        """
        return event_type.value

    @staticmethod
    def get_all_event_types() -> list[str]:
        """Get all event type values for frontend type generation.

        Returns:
            List of all event type strings
        """
        return [et.value for et in AgentEventType]

    @staticmethod
    def get_public_event_types() -> list[str]:
        """Get event types that should be exposed to the frontend.

        Some events are internal-only and should not be sent to clients.

        Returns:
            List of public event type strings
        """
        # Internal events that should not be exposed to frontend
        internal_events = {
            AgentEventType.STATUS,  # Internal status tracking
            AgentEventType.COMPACT_NEEDED,  # Internal compression signal
            AgentEventType.RETRY,  # Internal retry logic
        }

        return [et.value for et in AgentEventType if et not in internal_events]


# Convenience function for quick serialization
def serialize_event(
    event: AgentDomainEvent,
    message_id: str | None = None,
    event_time_us: int | None = None,
    event_counter: int | None = None,
) -> dict[str, Any]:
    """Quick serialization function for domain events.

    This is a convenience wrapper around EventSerializer.to_dict().

    Args:
        event: The domain event to serialize
        message_id: Optional message ID for filtering
        event_time_us: Optional microsecond timestamp
        event_counter: Optional counter within same microsecond

    Returns:
        Serialized event dictionary
    """
    return EventSerializer.to_dict(
        event,
        message_id=message_id,
        event_time_us=event_time_us,
        event_counter=event_counter,
    )
