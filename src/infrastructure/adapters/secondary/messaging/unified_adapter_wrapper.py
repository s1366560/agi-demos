"""Legacy Adapter Wrappers for backward compatibility.

These adapters wrap the UnifiedEventBusPort to provide backward compatibility
with the existing AgentEventBusPort interface. This allows gradual migration
to the unified event bus without breaking existing code.

Migration Strategy:
1. Configure DI to use UnifiedEventBusPort internally
2. Wrap it with these legacy adapters for existing consumers
3. Gradually migrate consumers to UnifiedEventBusPort
4. Deprecate and remove legacy adapters
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from src.domain.events.envelope import EventEnvelope
from src.domain.events.types import AgentEventType, is_terminal_event
from src.domain.ports.services.agent_event_bus_port import (
    AgentEvent,
    AgentEventBusPort,
)
from src.domain.ports.services.unified_event_bus_port import (
    RoutingKey,
    SubscriptionOptions,
    UnifiedEventBusPort,
)

logger = logging.getLogger(__name__)


class UnifiedAgentEventBusAdapter(AgentEventBusPort):
    """Adapter that wraps UnifiedEventBusPort for AgentEventBusPort interface.

    This provides backward compatibility for code using the AgentEventBusPort
    interface while internally using the unified event bus.

    Usage:
        unified_bus = RedisUnifiedEventBusAdapter(redis_client)
        legacy_adapter = UnifiedAgentEventBusAdapter(unified_bus)

        # Use legacy interface
        await legacy_adapter.publish_event(
            conversation_id="conv-123",
            message_id="msg-456",
            event_type=AgentEventType.THOUGHT,
            data={"content": "thinking..."},
            sequence=1,
        )
    """

    def __init__(
        self,
        unified_bus: UnifiedEventBusPort,
        *,
        stream_prefix: str = "agent",
    ) -> None:
        """Initialize the adapter.

        Args:
            unified_bus: Underlying unified event bus
            stream_prefix: Prefix for agent event streams
        """
        self._unified = unified_bus
        self._prefix = stream_prefix

    def _create_routing_key(self, conversation_id: str, message_id: str) -> RoutingKey:
        """Create routing key for agent events."""
        return RoutingKey.agent(conversation_id, message_id)

    def _create_envelope(
        self,
        conversation_id: str,
        message_id: str,
        event_type: AgentEventType,
        data: dict[str, Any],
        event_time_us: int,
        event_counter: int,
    ) -> EventEnvelope:
        """Create event envelope from legacy parameters."""
        payload = {
            **data,
            "event_time_us": event_time_us,
            "event_counter": event_counter,
            "conversation_id": conversation_id,
            "message_id": message_id,
        }

        return EventEnvelope.wrap(
            event_type=event_type,
            payload=payload,
            correlation_id=conversation_id,  # Use conversation as correlation
            metadata={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "event_time_us": event_time_us,
                "event_counter": event_counter,
            },
        )

    def _envelope_to_agent_event(
        self,
        envelope: EventEnvelope,
        event_id: str,
    ) -> AgentEvent:
        """Convert EventEnvelope to AgentEvent."""
        payload = envelope.payload

        # Get event type
        try:
            event_type = AgentEventType(envelope.event_type)
        except ValueError:
            event_type = AgentEventType.STATUS

        return AgentEvent(
            event_id=event_id,
            event_time_us=payload.get("event_time_us", 0),
            event_counter=payload.get("event_counter", 0),
            event_type=event_type,
            data=payload,
            timestamp=datetime.fromisoformat(envelope.timestamp.replace("Z", "+00:00"))
            if isinstance(envelope.timestamp, str)
            else envelope.timestamp,
            conversation_id=payload.get("conversation_id", ""),
            message_id=payload.get("message_id", ""),
        )

    async def publish_event(
        self,
        conversation_id: str,
        message_id: str,
        event_type: AgentEventType,
        data: dict[str, Any],
        event_time_us: int,
        event_counter: int,
    ) -> str:
        """Publish an event to the stream (legacy interface)."""
        envelope = self._create_envelope(
            conversation_id, message_id, event_type, data, event_time_us, event_counter
        )
        routing_key = self._create_routing_key(conversation_id, message_id)

        result = await self._unified.publish(envelope, routing_key)

        logger.debug(
            f"[LegacyAdapter] Published {event_type.value} to {routing_key}: "
            f"event_time_us={event_time_us}, id={result.sequence_id}"
        )

        return result.sequence_id

    async def subscribe_events(
        self,
        conversation_id: str,
        message_id: str,
        from_time_us: int = 0,
        from_counter: int = 0,
        timeout_ms: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Subscribe to events for a message (legacy interface)."""
        routing_key = self._create_routing_key(conversation_id, message_id)
        _routing_key_str = str(routing_key)

        options = SubscriptionOptions(
            from_time_us=from_time_us,
            from_counter=from_counter,
            block_ms=timeout_ms or 5000,
        )

        # Use pattern matching for this specific stream
        pattern = f"{self._prefix}.{conversation_id}.{message_id}"

        async for event_with_meta in self._unified.subscribe(pattern, options):
            agent_event = self._envelope_to_agent_event(
                event_with_meta.envelope,
                event_with_meta.sequence_id,
            )

            # Filter by event time
            if agent_event.event_time_us > from_time_us or (
                agent_event.event_time_us == from_time_us
                and agent_event.event_counter >= from_counter
            ):
                yield agent_event

                # Check for terminal events
                if is_terminal_event(agent_event.event_type):
                    return

    async def get_events(
        self,
        conversation_id: str,
        message_id: str,
        from_time_us: int = 0,
        from_counter: int = 0,
        to_time_us: int | None = None,
        to_counter: int | None = None,
        limit: int = 100,
    ) -> list[AgentEvent]:
        """Get events in a range (legacy interface)."""
        routing_key = self._create_routing_key(conversation_id, message_id)

        events_with_meta = await self._unified.get_events(
            routing_key,
            from_sequence=str(from_time_us) if from_time_us > 0 else "0",
            max_count=limit,
        )

        events = []
        for ewm in events_with_meta:
            agent_event = self._envelope_to_agent_event(
                ewm.envelope,
                ewm.sequence_id,
            )

            # Filter by event time range
            if agent_event.event_time_us > from_time_us or (
                agent_event.event_time_us == from_time_us
                and agent_event.event_counter >= from_counter
            ):
                if to_time_us is None or agent_event.event_time_us < to_time_us or (
                    agent_event.event_time_us == to_time_us
                    and (to_counter is None or agent_event.event_counter <= to_counter)
                ):
                    events.append(agent_event)

        return events

    async def get_latest_event(
        self,
        conversation_id: str,
        message_id: str,
    ) -> AgentEvent | None:
        """Get the most recent event for a message (legacy interface)."""
        routing_key = self._create_routing_key(conversation_id, message_id)

        latest = await self._unified.get_latest_event(routing_key)
        if latest:
            return self._envelope_to_agent_event(
                latest.envelope,
                latest.sequence_id,
            )
        return None

    async def get_last_event_time(
        self,
        conversation_id: str,
        message_id: str,
    ) -> tuple[int, int]:
        """Get the last (event_time_us, event_counter) for a message (legacy interface)."""
        latest = await self.get_latest_event(conversation_id, message_id)
        if latest:
            return (latest.event_time_us, latest.event_counter)
        return (0, 0)

    async def mark_complete(
        self,
        conversation_id: str,
        message_id: str,
        ttl_seconds: int = 300,
    ) -> None:
        """Mark a message stream as complete (legacy interface).

        The unified bus handles TTL differently, but we can trim the stream
        to a minimal size for cleanup purposes.
        """
        routing_key = self._create_routing_key(conversation_id, message_id)

        # Note: The unified bus doesn't have a direct mark_complete concept.
        # We could trim or set a flag, but for now we just log it.
        logger.debug(
            f"[LegacyAdapter] Marked complete: {routing_key} (TTL={ttl_seconds}s)"
        )

    async def cleanup_old_streams(
        self,
        older_than_seconds: int = 3600,
        max_streams: int = 100,
    ) -> int:
        """Clean up old streams (legacy interface).

        Note: This is a no-op in the unified adapter as stream cleanup
        should be handled by the unified bus or a separate cleanup service.
        """
        logger.debug(
            f"[LegacyAdapter] cleanup_old_streams called (older_than={older_than_seconds}s)"
        )
        return 0

    async def stream_exists(
        self,
        conversation_id: str,
        message_id: str,
    ) -> bool:
        """Check if a stream exists (legacy interface)."""
        routing_key = self._create_routing_key(conversation_id, message_id)
        return await self._unified.stream_exists(routing_key)

    async def get_stream_length(
        self,
        conversation_id: str,
        message_id: str,
    ) -> int:
        """Get the number of events in a stream (legacy interface)."""
        routing_key = self._create_routing_key(conversation_id, message_id)
        return await self._unified.get_stream_length(routing_key)
