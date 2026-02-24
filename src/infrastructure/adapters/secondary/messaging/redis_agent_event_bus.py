"""
Redis Streams implementation of AgentEventBusPort.

This adapter uses Redis Streams for Agent event streaming and recovery.

Stream naming convention:
- agent:events:{conversation_id}:{message_id}

Features:
- Automatic sequence tracking
- TTL-based cleanup after completion
- Efficient range queries for recovery
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from src.domain.ports.services.agent_event_bus_port import (
    AgentEvent,
    AgentEventBusPort,
    AgentEventType,
)

logger = logging.getLogger(__name__)


class RedisAgentEventBusAdapter(AgentEventBusPort):
    """
    Redis Streams implementation of AgentEventBusPort.

    Uses Redis Streams with automatic ID generation for event ordering.
    Each message gets its own stream that is cleaned up after completion.
    """

    # Stream key prefix
    STREAM_PREFIX = "agent:events:"

    # Metadata key prefix (for tracking completion status)
    META_PREFIX = "agent:meta:"

    # Default settings
    DEFAULT_MAX_LEN = 500  # Max events per stream (approximate)
    DEFAULT_BLOCK_MS = 5000  # Default block timeout for reads
    DEFAULT_TTL_SECONDS = 300  # 5 minutes TTL after completion

    def __init__(
        self,
        redis_client: redis.Redis,
        stream_prefix: str | None = None,
        default_max_len: int | None = None,
    ) -> None:
        """
        Initialize the Redis Agent Event Bus adapter.

        Args:
            redis_client: Async Redis client
            stream_prefix: Optional custom stream prefix
            default_max_len: Optional default max stream length
        """
        self._redis = redis_client
        self._stream_prefix = stream_prefix or self.STREAM_PREFIX
        self._default_max_len = default_max_len or self.DEFAULT_MAX_LEN

    def _get_stream_key(self, conversation_id: str, message_id: str) -> str:
        """Get the stream key for a message."""
        return f"{self._stream_prefix}{conversation_id}:{message_id}"

    def _get_meta_key(self, conversation_id: str, message_id: str) -> str:
        """Get the metadata key for a message."""
        return f"{self.META_PREFIX}{conversation_id}:{message_id}"

    async def publish_event(
        self,
        conversation_id: str,
        message_id: str,
        event_type: AgentEventType,
        data: dict[str, Any],
        event_time_us: int,
        event_counter: int,
    ) -> str:
        """Publish an event to the stream."""
        stream_key = self._get_stream_key(conversation_id, message_id)

        # Build event data
        event_data = {
            "event_time_us": event_time_us,
            "event_counter": event_counter,
            "event_type": event_type.value,
            "data": json.dumps(data, default=str),
            "timestamp": datetime.now(UTC).isoformat(),
            "conversation_id": conversation_id,
            "message_id": message_id,
        }

        try:
            # Add to stream with auto-generated ID
            event_id = await self._redis.xadd(
                stream_key,
                event_data,
                maxlen=self._default_max_len,
                approximate=True,
            )

            # Decode event ID if bytes
            if isinstance(event_id, bytes):
                event_id = event_id.decode("utf-8")

            logger.debug(
                f"[AgentEventBus] Published event to {stream_key}: "
                f"event_time_us={event_time_us}, type={event_type.value}, id={event_id}"
            )

            return event_id

        except Exception as e:
            logger.error(f"[AgentEventBus] Failed to publish to {stream_key}: {e}")
            raise

    _TERMINAL_EVENTS = frozenset(
        {
            AgentEventType.COMPLETE,
            AgentEventType.ERROR,
            AgentEventType.CANCELLED,
        }
    )

    def _filter_stream_messages(
        self,
        streams: list,
        from_time_us: int,
        from_counter: int,
    ) -> tuple[list[AgentEvent], str | None, bool]:
        """Filter and parse stream messages.

        Returns (events, last_id, is_terminal).
        """
        events: list[AgentEvent] = []
        last_id: str | None = None
        for _stream_name, messages in streams:
            for msg_id, fields in messages:
                last_id = self._decode_bytes(msg_id)
                event = self._parse_stream_message(msg_id, fields)
                if not event:
                    continue
                if event.event_time_us > from_time_us or (
                    event.event_time_us == from_time_us and event.event_counter >= from_counter
                ):
                    events.append(event)
                    if event.event_type in self._TERMINAL_EVENTS:
                        return events, last_id, True
        return events, last_id, False

    async def subscribe_events(
        self,
        conversation_id: str,
        message_id: str,
        from_time_us: int = 0,
        from_counter: int = 0,
        timeout_ms: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Subscribe to events for a message."""
        stream_key = self._get_stream_key(conversation_id, message_id)
        block_ms = timeout_ms or self.DEFAULT_BLOCK_MS

        # First, read existing events from the time
        if from_time_us > 0:
            existing = await self.get_events(
                conversation_id=conversation_id,
                message_id=message_id,
                from_time_us=from_time_us,
                from_counter=from_counter,
            )
            for event in existing:
                yield event

        # Then wait for new events
        last_id = "$"  # Start from newest
        while True:
            try:
                streams = await self._redis.xread(
                    {stream_key: last_id},
                    count=10,
                    block=block_ms,
                )

                if not streams:
                    if await self._is_stream_complete(conversation_id, message_id):
                        return
                    continue

                events, new_last_id, is_terminal = self._filter_stream_messages(
                    streams, from_time_us, from_counter
                )
                if new_last_id is not None:
                    last_id = new_last_id
                for event in events:
                    yield event
                if is_terminal:
                    return

            except redis.ConnectionError as e:
                logger.error(f"[AgentEventBus] Connection error on {stream_key}: {e}")
                raise
            except Exception as e:
                logger.error(f"[AgentEventBus] Error reading from {stream_key}: {e}")
                raise

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
        """Get events in a range (non-blocking)."""
        stream_key = self._get_stream_key(conversation_id, message_id)
        events = []

        try:
            # Read all messages from stream
            result = await self._redis.xrange(
                stream_key,
                min="-",
                max="+",
                count=limit * 2,  # Get more to filter
            )

            for msg_id, fields in result:
                event = self._parse_stream_message(msg_id, fields)
                if event:
                    # Filter by event time range
                    if event.event_time_us > from_time_us or (
                        event.event_time_us == from_time_us and event.event_counter >= from_counter
                    ):
                        if (
                            to_time_us is None
                            or event.event_time_us < to_time_us
                            or (
                                event.event_time_us == to_time_us
                                and (to_counter is None or event.event_counter <= to_counter)
                            )
                        ):
                            events.append(event)
                            if len(events) >= limit:
                                break

            return events

        except Exception as e:
            logger.error(f"[AgentEventBus] Failed to get events from {stream_key}: {e}")
            return events

    async def get_last_event_time(
        self,
        conversation_id: str,
        message_id: str,
    ) -> tuple[int, int]:
        """Get the last (event_time_us, event_counter) for a message."""
        stream_key = self._get_stream_key(conversation_id, message_id)

        try:
            # Get the last entry
            result = await self._redis.xrevrange(stream_key, count=1)

            if not result:
                return (0, 0)

            _msg_id, fields = result[0]
            time_us = fields.get(b"event_time_us") or fields.get("event_time_us")
            counter = fields.get(b"event_counter") or fields.get("event_counter")
            return (int(time_us) if time_us else 0, int(counter) if counter else 0)

        except Exception as e:
            logger.warning(f"[AgentEventBus] Failed to get last event time: {e}")
            return (0, 0)

    async def mark_complete(
        self,
        conversation_id: str,
        message_id: str,
        ttl_seconds: int = 300,
    ) -> None:
        """Mark a message stream as complete and set TTL."""
        stream_key = self._get_stream_key(conversation_id, message_id)
        meta_key = self._get_meta_key(conversation_id, message_id)

        try:
            # Set metadata to indicate completion
            await self._redis.setex(
                meta_key,
                ttl_seconds,
                json.dumps(
                    {
                        "status": "complete",
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                ),
            )

            # Set TTL on the stream
            await self._redis.expire(stream_key, ttl_seconds)

            logger.info(f"[AgentEventBus] Marked {stream_key} complete with TTL={ttl_seconds}s")

        except Exception as e:
            logger.warning(f"[AgentEventBus] Failed to mark complete: {e}")

    async def stream_exists(
        self,
        conversation_id: str,
        message_id: str,
    ) -> bool:
        """Check if a stream exists for the given message."""
        stream_key = self._get_stream_key(conversation_id, message_id)

        try:
            return await self._redis.exists(stream_key) > 0
        except Exception as e:
            logger.warning(f"[AgentEventBus] Failed to check stream existence: {e}")
            return False

    async def cleanup_stream(
        self,
        conversation_id: str,
        message_id: str,
    ) -> None:
        """Immediately delete a stream."""
        stream_key = self._get_stream_key(conversation_id, message_id)
        meta_key = self._get_meta_key(conversation_id, message_id)

        try:
            await self._redis.delete(stream_key, meta_key)
            logger.info(f"[AgentEventBus] Deleted stream {stream_key}")
        except Exception as e:
            logger.warning(f"[AgentEventBus] Failed to cleanup stream: {e}")

    # =========================================================================
    # Private helper methods
    # =========================================================================

    @staticmethod
    def _decode_bytes(value: Any) -> Any:
        """Decode a value from bytes if needed."""
        return value.decode("utf-8") if isinstance(value, bytes) else value

    @staticmethod
    def _decode_int_field(value: Any, default: int = 0) -> int:
        """Decode a bytes/str value to int with a default."""
        if isinstance(value, bytes):
            return int(value.decode())
        return int(value) if value else default

    @staticmethod
    def _parse_data_field(data: Any) -> dict:
        """Parse the data field from raw string/bytes to dict."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {"raw": data}
        return {}

    def _parse_stream_message(self, msg_id: Any, fields: dict[Any, Any]) -> AgentEvent | None:
        """Parse a raw Redis stream message into AgentEvent."""
        try:
            msg_id = self._decode_bytes(msg_id)

            # Helper to get field value
            def get_field(key: str) -> Any:
                return fields.get(key.encode()) if key.encode() in fields else fields.get(key)

            sequence = self._decode_int_field(get_field("event_time_us"))
            counter = self._decode_int_field(get_field("event_counter"))
            event_type = self._decode_bytes(get_field("event_type"))
            data = self._parse_data_field(get_field("data"))
            timestamp = self._decode_bytes(get_field("timestamp"))
            conversation_id = self._decode_bytes(get_field("conversation_id"))
            message_id = self._decode_bytes(get_field("message_id"))

            return AgentEvent(
                event_id=msg_id,
                event_time_us=sequence,
                event_counter=counter,
                event_type=AgentEventType(event_type) if event_type else AgentEventType.THOUGHT,
                data=data,
                timestamp=(datetime.fromisoformat(timestamp) if timestamp else datetime.now(UTC)),
                message_id=message_id,
                conversation_id=conversation_id,
            )

        except Exception as e:
            logger.warning(f"[AgentEventBus] Failed to parse message {msg_id}: {e}")
            return None

    async def _is_stream_complete(self, conversation_id: str, message_id: str) -> bool:
        """Check if a stream is marked as complete."""
        meta_key = self._get_meta_key(conversation_id, message_id)

        try:
            data = await self._redis.get(meta_key)
            if data:
                if isinstance(data, bytes):
                    data = data.decode()
                meta = json.loads(data)
                return meta.get("status") == "complete"
            return False
        except Exception:
            return False

    # =========================================================================
    # Stream info and debugging
    # =========================================================================

    async def get_stream_info(self, conversation_id: str, message_id: str) -> dict[str, Any] | None:
        """Get stream information for debugging."""
        stream_key = self._get_stream_key(conversation_id, message_id)

        try:
            info = await self._redis.xinfo_stream(stream_key)
            return dict(info) if info else None
        except redis.ResponseError as e:
            if "ERR no such key" in str(e):
                return None
            raise


# Factory function
def create_redis_agent_event_bus(
    redis_client: redis.Redis,
    stream_prefix: str | None = None,
) -> RedisAgentEventBusAdapter:
    """
    Create a RedisAgentEventBusAdapter instance.

    Args:
        redis_client: Async Redis client
        stream_prefix: Optional custom stream prefix

    Returns:
        Configured RedisAgentEventBusAdapter
    """
    return RedisAgentEventBusAdapter(
        redis_client=redis_client,
        stream_prefix=stream_prefix,
    )
