"""
Agent Event Bus Port - Abstract interface for Agent event streaming.

This port defines the contract for Agent event streaming and recovery,
enabling reliable event delivery and recovery after page refresh.

The abstraction allows switching between different implementations:
- Redis Streams (default, recommended)
- Kafka
- etc.

Key Features:
- Event persistence for recovery
- Sequence-based consumption
- Consumer group support
- Automatic cleanup after completion

Note: AgentEventType is imported from types.py (Single Source of Truth).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

# Import AgentEventType from the unified types module (Single Source of Truth)
from src.domain.events.types import AgentEventType, is_terminal_event


@dataclass
class AgentEvent:
    """
    An event in the Agent event stream.

    Attributes:
        event_id: Unique event ID (assigned by the bus, e.g., Redis Stream ID)
        sequence: Sequence number within the message
        event_type: Type of event
        data: Event payload data
        timestamp: When the event was created
        message_id: The message this event belongs to
        conversation_id: The conversation this event belongs to
    """

    event_id: str
    sequence: int
    event_type: AgentEventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    message_id: Optional[str] = None
    conversation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentEvent":
        """Create from dictionary."""
        return cls(
            event_id=data.get("event_id", ""),
            sequence=data.get("sequence", 0),
            event_type=AgentEventType(data.get("event_type", "thought")),
            data=data.get("data", {}),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data.get("timestamp"), str)
                else data.get("timestamp", datetime.utcnow())
            ),
            message_id=data.get("message_id"),
            conversation_id=data.get("conversation_id"),
        )


class AgentEventBusPort(ABC):
    """
    Abstract port for Agent event streaming.

    This port provides:
    - Event publishing during Agent execution
    - Event recovery after page refresh
    - Automatic cleanup after completion

    Stream Structure:
    - One stream per (conversation_id, message_id) pair
    - Events are ordered by sequence number
    - Stream is cleaned up after completion (with TTL for recovery window)
    """

    @abstractmethod
    async def publish_event(
        self,
        conversation_id: str,
        message_id: str,
        event_type: AgentEventType,
        data: Dict[str, Any],
        sequence: int,
    ) -> str:
        """
        Publish an event to the stream.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID (the assistant response being generated)
            event_type: Type of event
            data: Event payload
            sequence: Sequence number within this message

        Returns:
            Event ID assigned by the bus
        """
        pass

    @abstractmethod
    async def subscribe_events(
        self,
        conversation_id: str,
        message_id: str,
        from_sequence: int = 0,
        timeout_ms: Optional[int] = None,
    ) -> AsyncIterator[AgentEvent]:
        """
        Subscribe to events for a message.

        Used for:
        - Real-time streaming to WebSocket
        - Recovery after page refresh (with from_sequence)

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            from_sequence: Start from this sequence (0 = from beginning)
            timeout_ms: Timeout for blocking reads

        Yields:
            AgentEvent objects as they arrive
        """
        pass

    @abstractmethod
    async def get_events(
        self,
        conversation_id: str,
        message_id: str,
        from_sequence: int = 0,
        to_sequence: Optional[int] = None,
        limit: int = 100,
    ) -> List[AgentEvent]:
        """
        Get events in a range (non-blocking).

        Used for batch recovery.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            from_sequence: Start sequence (inclusive)
            to_sequence: End sequence (inclusive), None = latest
            limit: Maximum events to return

        Returns:
            List of events in the range
        """
        pass

    @abstractmethod
    async def get_last_sequence(
        self,
        conversation_id: str,
        message_id: str,
    ) -> int:
        """
        Get the last sequence number for a message.

        Used to check if there are new events to recover.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID

        Returns:
            Last sequence number, or -1 if no events
        """
        pass

    @abstractmethod
    async def mark_complete(
        self,
        conversation_id: str,
        message_id: str,
        ttl_seconds: int = 300,
    ) -> None:
        """
        Mark a message stream as complete.

        Sets TTL for automatic cleanup after the recovery window.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            ttl_seconds: Time to keep the stream for recovery (default 5 minutes)
        """
        pass

    @abstractmethod
    async def stream_exists(
        self,
        conversation_id: str,
        message_id: str,
    ) -> bool:
        """
        Check if a stream exists for the given message.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID

        Returns:
            True if stream exists
        """
        pass

    @abstractmethod
    async def cleanup_stream(
        self,
        conversation_id: str,
        message_id: str,
    ) -> None:
        """
        Immediately delete a stream.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
        """
        pass

    # =========================================================================
    # Convenience methods with default implementations
    # =========================================================================

    async def publish_thought(
        self,
        conversation_id: str,
        message_id: str,
        thought: str,
        sequence: int,
    ) -> str:
        """Convenience method for publishing thought events."""
        return await self.publish_event(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type=AgentEventType.THOUGHT,
            data={"thought": thought},
            sequence=sequence,
        )

    async def publish_thought_delta(
        self,
        conversation_id: str,
        message_id: str,
        delta: str,
        sequence: int,
    ) -> str:
        """Convenience method for publishing thought delta events."""
        return await self.publish_event(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type=AgentEventType.THOUGHT_DELTA,
            data={"delta": delta},
            sequence=sequence,
        )

    async def publish_text_delta(
        self,
        conversation_id: str,
        message_id: str,
        delta: str,
        sequence: int,
    ) -> str:
        """Convenience method for publishing text delta events."""
        return await self.publish_event(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type=AgentEventType.TEXT_DELTA,
            data={"delta": delta},
            sequence=sequence,
        )

    async def publish_complete(
        self,
        conversation_id: str,
        message_id: str,
        sequence: int,
        final_content: Optional[str] = None,
    ) -> str:
        """Convenience method for publishing complete events."""
        data = {}
        if final_content:
            data["content"] = final_content
        return await self.publish_event(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type=AgentEventType.COMPLETE,
            data=data,
            sequence=sequence,
        )

    async def publish_error(
        self,
        conversation_id: str,
        message_id: str,
        error: str,
        sequence: int,
    ) -> str:
        """Convenience method for publishing error events."""
        return await self.publish_event(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type=AgentEventType.ERROR,
            data={"error": error},
            sequence=sequence,
        )
