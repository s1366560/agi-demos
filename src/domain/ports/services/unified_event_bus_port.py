"""Unified Event Bus Port - Interface for the unified event bus.

This port defines the contract for the unified event bus that merges
Agent Events, HITL, and Sandbox event channels into a single interface.

Routing Key Pattern:
- Agent events: "agent.{conversation_id}.{message_id}"
- HITL events: "hitl.{request_id}"
- Sandbox events: "sandbox.{sandbox_id}"
- System events: "system.{event_name}"

Usage:
    class RedisUnifiedEventBusAdapter(UnifiedEventBusPort):
        async def publish(self, event, routing_key):
            # Publish to Redis Streams
            pass

        async def subscribe(self, pattern, consumer_group=None):
            # Subscribe using pattern matching
            async for event in self._stream_events(pattern):
                yield event
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.events.envelope import EventEnvelope


@dataclass(frozen=True)
class RoutingKey:
    """Structured routing key for event routing.

    Format: "{namespace}.{entity_id}[.{sub_id}]"

    Examples:
        - RoutingKey("agent", "conv-123", "msg-456")
        - RoutingKey("hitl", "req-789")
        - RoutingKey("sandbox", "sbx-abc")
    """

    namespace: str
    entity_id: str
    sub_id: str | None = None

    def __str__(self) -> str:
        """Convert to string representation."""
        if self.sub_id:
            return f"{self.namespace}.{self.entity_id}.{self.sub_id}"
        return f"{self.namespace}.{self.entity_id}"

    @classmethod
    def from_string(cls, key: str) -> "RoutingKey":
        """Parse routing key from string.

        Args:
            key: Routing key string

        Returns:
            RoutingKey instance
        """
        parts = key.split(".")
        if len(parts) == 2:
            return cls(namespace=parts[0], entity_id=parts[1])
        elif len(parts) >= 3:
            return cls(namespace=parts[0], entity_id=parts[1], sub_id=".".join(parts[2:]))
        else:
            raise ValueError(f"Invalid routing key format: {key}")

    @classmethod
    def agent(cls, conversation_id: str, message_id: str) -> "RoutingKey":
        """Create agent event routing key."""
        return cls("agent", conversation_id, message_id)

    @classmethod
    def hitl(cls, request_id: str) -> "RoutingKey":
        """Create HITL event routing key."""
        return cls("hitl", request_id)

    @classmethod
    def sandbox(cls, sandbox_id: str) -> "RoutingKey":
        """Create sandbox event routing key."""
        return cls("sandbox", sandbox_id)

    @classmethod
    def system(cls, event_name: str) -> "RoutingKey":
        """Create system event routing key."""
        return cls("system", event_name)


@dataclass
class SubscriptionOptions:
    """Options for event subscription.

    Attributes:
        consumer_group: Name of the consumer group for load balancing
        consumer_name: Unique name for this consumer within the group
        from_time_us: Start reading from this event_time_us
        from_counter: Start reading from this event_counter
        batch_size: Maximum events to fetch at once
        block_ms: Milliseconds to block waiting for new events (0 = no block)
        ack_immediately: Whether to acknowledge events immediately
    """

    consumer_group: str | None = None
    consumer_name: str | None = None
    from_time_us: int = 0
    from_counter: int = 0
    batch_size: int = 100
    block_ms: int = 5000
    ack_immediately: bool = True


@dataclass
class PublishResult:
    """Result of publishing an event.

    Attributes:
        sequence_id: Sequence ID assigned by the bus
        stream_key: Full stream key where event was published
        timestamp: When the event was published
    """

    sequence_id: str
    stream_key: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class EventWithMetadata:
    """Event with delivery metadata.

    Attributes:
        envelope: The event envelope
        routing_key: Routing key the event was published to
        sequence_id: Sequence ID in the stream
        delivered_at: When the event was delivered to this consumer
    """

    envelope: EventEnvelope
    routing_key: str
    sequence_id: str
    delivered_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class UnifiedEventBusPort(ABC):
    """Unified event bus port interface.

    This interface provides a unified way to publish and subscribe to events
    across all domains (Agent, HITL, Sandbox, System).

    Implementation Requirements:
    - Events must be durable (survive restarts)
    - Events must be ordered within a stream
    - Consumer groups must support load balancing
    - Pattern matching must support wildcards
    """

    @abstractmethod
    async def publish(
        self,
        event: EventEnvelope,
        routing_key: str | RoutingKey,
    ) -> PublishResult:
        """Publish an event to the bus.

        Args:
            event: Event envelope to publish
            routing_key: Routing key for the event

        Returns:
            PublishResult with sequence ID and metadata

        Raises:
            EventPublishError: If publishing fails
        """
        pass

    @abstractmethod
    async def publish_batch(
        self,
        events: list[tuple[EventEnvelope, str | RoutingKey]],
    ) -> list[PublishResult]:
        """Publish multiple events atomically.

        Args:
            events: List of (event, routing_key) tuples

        Returns:
            List of PublishResults

        Raises:
            EventPublishError: If publishing fails
        """
        pass

    @abstractmethod
    async def subscribe(
        self,
        pattern: str,
        options: SubscriptionOptions | None = None,
    ) -> AsyncIterator[EventWithMetadata]:
        """Subscribe to events matching a pattern.

        Pattern supports wildcards:
        - "agent.*" matches all agent events
        - "agent.conv-123.*" matches all events for a conversation
        - "hitl.req-*" matches all HITL requests

        Args:
            pattern: Pattern to match routing keys
            options: Subscription options

        Yields:
            EventWithMetadata for each matching event

        Example:
            async for event in bus.subscribe("agent.*"):
                print(f"Got event: {event.envelope.event_type}")
        """
        pass

    @abstractmethod
    async def get_events(
        self,
        routing_key: str | RoutingKey,
        from_sequence: str = "0",
        to_sequence: str | None = None,
        max_count: int = 1000,
    ) -> list[EventWithMetadata]:
        """Get events from a specific stream.

        Args:
            routing_key: Routing key to read from
            from_sequence: Start sequence ID (exclusive)
            to_sequence: End sequence ID (inclusive, None = latest)
            max_count: Maximum events to return

        Returns:
            List of events with metadata
        """
        pass

    @abstractmethod
    async def get_latest_event(
        self,
        routing_key: str | RoutingKey,
    ) -> EventWithMetadata | None:
        """Get the most recent event from a stream.

        Args:
            routing_key: Routing key to read from

        Returns:
            Latest event or None if stream is empty
        """
        pass

    @abstractmethod
    async def acknowledge(
        self,
        routing_key: str | RoutingKey,
        sequence_ids: list[str],
        consumer_group: str,
    ) -> int:
        """Acknowledge processed events.

        Args:
            routing_key: Routing key the events were from
            sequence_ids: IDs of events to acknowledge
            consumer_group: Consumer group name

        Returns:
            Number of events acknowledged
        """
        pass

    @abstractmethod
    async def stream_exists(self, routing_key: str | RoutingKey) -> bool:
        """Check if a stream exists.

        Args:
            routing_key: Routing key to check

        Returns:
            True if stream exists
        """
        pass

    @abstractmethod
    async def get_stream_length(self, routing_key: str | RoutingKey) -> int:
        """Get the number of events in a stream.

        Args:
            routing_key: Routing key to check

        Returns:
            Number of events in the stream
        """
        pass

    @abstractmethod
    async def trim_stream(
        self,
        routing_key: str | RoutingKey,
        max_length: int,
        approximate: bool = True,
    ) -> int:
        """Trim a stream to a maximum length.

        Args:
            routing_key: Routing key to trim
            max_length: Maximum events to keep
            approximate: Use approximate trimming (faster)

        Returns:
            Number of events removed
        """
        pass

    @abstractmethod
    async def delete_stream(self, routing_key: str | RoutingKey) -> bool:
        """Delete a stream entirely.

        Args:
            routing_key: Routing key to delete

        Returns:
            True if stream was deleted
        """
        pass

    @abstractmethod
    async def create_consumer_group(
        self,
        routing_key: str | RoutingKey,
        group_name: str,
        start_id: str = "0",
    ) -> bool:
        """Create a consumer group for a stream.

        Args:
            routing_key: Routing key to create group for
            group_name: Name of the consumer group
            start_id: Start reading from this ID ("0" = beginning, "$" = new)

        Returns:
            True if group was created
        """
        pass


class EventPublishError(Exception):
    """Error publishing an event."""

    def __init__(
        self,
        message: str,
        routing_key: str | None = None,
        event_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.routing_key = routing_key
        self.event_type = event_type


class EventSubscribeError(Exception):
    """Error subscribing to events."""

    def __init__(self, message: str, pattern: str | None = None) -> None:
        super().__init__(message)
        self.pattern = pattern
