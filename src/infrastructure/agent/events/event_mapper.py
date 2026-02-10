"""Event Mapper for ReActAgent SSE Streaming.

Handles conversion of AgentDomainEvent to SSE format for client streaming.

REFACTORED: This module now uses AgentEventType from src.domain.events.types
as the single source of truth. The legacy EventType is provided as an alias
for backward compatibility.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

# Import unified types - SINGLE SOURCE OF TRUTH
from src.domain.events.types import AgentEventType

# Legacy alias for backward compatibility
# DEPRECATED: Use AgentEventType directly in new code
EventType = AgentEventType


@dataclass
class SSEEvent:
    """Server-Sent Event format for streaming."""

    id: str
    event: AgentEventType  # Now uses unified type
    data: Dict[str, Any]
    retry: Optional[int] = None

    def to_sse_format(self) -> str:
        """Convert to SSE format string.

        Returns:
            SSE formatted string (e.g., "id: 1\nevent: message\ndata: {...}\n\n")
        """
        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event.value}")
        lines.append(f"data: {json.dumps(self.data)}")
        if self.retry:
            lines.append(f"retry: {self.retry}")
        lines.append("")  # Empty line to end event
        return "\n".join(lines) + "\n"


@dataclass
class AgentDomainEvent:
    """Base class for domain events in the agent system.

    Note: This is a lightweight event class used by EventMapper/EventBus.
    For the full domain event classes, see src.domain.events.agent_events.
    """

    event_type: AgentEventType  # Now uses unified type
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    conversation_id: Optional[str] = None
    sandbox_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def to_sse(self, event_id: str) -> SSEEvent:
        """Convert domain event to SSE event.

        Args:
            event_id: Unique ID for the SSE event

        Returns:
            An SSEEvent ready for streaming
        """
        return SSEEvent(
            id=event_id,
            event=self.event_type,
            data={
                **self.data,
                "timestamp": self.timestamp.isoformat(),
                "conversation_id": self.conversation_id,
                "sandbox_id": self.sandbox_id,
            },
        )


class EventMapper:
    """
    Maps domain events to SSE format.

    Provides centralized event transformation logic,
    replacing scattered conversion code throughout the agent system.
    """

    def __init__(
        self,
        include_timestamp: bool = True,
        include_conversation_id: bool = True,
        include_sandbox_id: bool = True,
    ) -> None:
        """Initialize the event mapper.

        Args:
            include_timestamp: Whether to include timestamp in events
            include_conversation_id: Whether to include conversation_id
            include_sandbox_id: Whether to include sandbox_id
        """
        self._include_timestamp = include_timestamp
        self._include_conversation_id = include_conversation_id
        self._include_sandbox_id = include_sandbox_id
        self._event_filters: List[Callable[[AgentDomainEvent], bool]] = []
        self._event_transformers: Dict[AgentEventType, Callable[[AgentDomainEvent], Dict[str, Any]]] = {}

    def register_filter(self, filter_fn: Callable[[AgentDomainEvent], bool]) -> None:
        """Register an event filter.

        Args:
            filter_fn: Function that returns True to include event
        """
        self._event_filters.append(filter_fn)

    def register_transformer(
        self,
        event_type: AgentEventType,
        transformer: Callable[[AgentDomainEvent], Dict[str, Any]],
    ) -> None:
        """Register a custom transformer for an event type.

        Args:
            event_type: The event type to transform
            transformer: Function that transforms event data
        """
        self._event_transformers[event_type] = transformer

    def to_sse(
        self,
        event: AgentDomainEvent,
        event_id: str,
    ) -> Optional[SSEEvent]:
        """Convert a domain event to SSE format.

        Args:
            event: The domain event to convert
            event_id: Unique ID for the SSE event

        Returns:
            SSEEvent if event passes filters, None otherwise
        """
        # Check filters
        for filter_fn in self._event_filters:
            if not filter_fn(event):
                return None

        # Apply custom transformer if registered
        if event.event_type in self._event_transformers:
            custom_data = self._event_transformers[event.event_type](event)
            modified_event = AgentDomainEvent(
                event_type=event.event_type,
                timestamp=event.timestamp,
                conversation_id=event.conversation_id,
                sandbox_id=event.sandbox_id,
                data=custom_data,
            )
            event = modified_event

        # Convert to SSE
        sse_event = event.to_sse(event_id)

        # Remove fields based on configuration
        if not self._include_timestamp:
            sse_event.data.pop("timestamp", None)
        if not self._include_conversation_id:
            sse_event.data.pop("conversation_id", None)
        if not self._include_sandbox_id:
            sse_event.data.pop("sandbox_id", None)

        # Clean up None values
        sse_event.data = {k: v for k, v in sse_event.data.items() if v is not None}

        return sse_event

    def to_sse_batch(
        self,
        events: List[AgentDomainEvent],
        id_prefix: str = "evt",
    ) -> List[SSEEvent]:
        """Convert multiple events to SSE format.

        Args:
            events: List of domain events
            id_prefix: Prefix for event IDs

        Returns:
            List of SSEEvents
        """
        sse_events = []
        for i, event in enumerate(events):
            event_id = f"{id_prefix}_{i}"
            sse_event = self.to_sse(event, event_id)
            if sse_event:
                sse_events.append(sse_event)
        return sse_events

    def create_sse_stream(
        self,
        events: List[AgentDomainEvent],
    ) -> str:
        """Create a complete SSE stream string from events.

        Args:
            events: List of domain events

        Returns:
            Complete SSE stream string
        """
        sse_events = self.to_sse_batch(events)
        return "".join(e.to_sse_format() for e in sse_events)


class EventBus:
    """
    Event bus for agent domain events.

    Provides publish-subscribe functionality for agent events,
    enabling loose coupling between event producers and consumers.
    """

    def __init__(self, mapper: Optional[EventMapper] = None) -> None:
        """Initialize the event bus.

        Args:
            mapper: Optional event mapper for SSE conversion
        """
        self._mapper = mapper or EventMapper()
        self._subscribers: Dict[AgentEventType, List[Callable]] = {}
        self._global_subscribers: List[Callable] = []
        self._event_history: List[AgentDomainEvent] = []
        self._max_history = 1000

    def subscribe(
        self,
        event_type: Optional[AgentEventType] = None,
        callback: Optional[Callable[[AgentDomainEvent], None]] = None,
    ) -> Callable[[], None]:
        """Subscribe to events.

        Args:
            event_type: Specific event type or None for all events
            callback: Function to call when event occurs

        Returns:
            Unsubscribe function
        """
        if callback is None:
            return lambda: None

        if event_type is None:
            self._global_subscribers.append(callback)
            return lambda: self._global_subscribers.remove(callback)

        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

        def unsubscribe() -> None:
            if event_type in self._subscribers and callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)

        return unsubscribe

    def publish(self, event: AgentDomainEvent) -> None:
        """Publish an event to all subscribers.

        Args:
            event: The domain event to publish
        """
        # Add to history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        # Notify global subscribers
        for callback in self._global_subscribers:
            try:
                callback(event)
            except Exception:
                # Log but don't fail publishing
                pass

        # Notify type-specific subscribers
        if event.event_type in self._subscribers:
            for callback in self._subscribers[event.event_type]:
                try:
                    callback(event)
                except Exception:
                    # Log but don't fail publishing
                    pass

    def get_history(
        self,
        event_type: Optional[AgentEventType] = None,
        limit: int = 100,
    ) -> List[AgentDomainEvent]:
        """Get events from history.

        Args:
            event_type: Optional event type filter
            limit: Maximum number of events to return

        Returns:
            List of historical events
        """
        if event_type:
            return [
                e for e in self._event_history
                if e.event_type == event_type
            ][-limit:]

        return self._event_history[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()

    def get_mapper(self) -> EventMapper:
        """Get the event mapper."""
        return self._mapper

    def set_mapper(self, mapper: EventMapper) -> None:
        """Set a new event mapper."""
        self._mapper = mapper


# Global event bus instance
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus.

    Returns:
        The global EventBus instance
    """
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def set_event_bus(event_bus: EventBus) -> None:
    """Set the global event bus.

    Args:
        event_bus: The event bus to use globally
    """
    global _global_event_bus
    _global_event_bus = event_bus
