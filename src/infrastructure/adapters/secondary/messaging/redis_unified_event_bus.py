"""Redis Unified Event Bus Adapter.

This adapter implements the UnifiedEventBusPort using Redis Streams.
It provides a unified interface for publishing and subscribing to events
across all domains (Agent, HITL, Sandbox, System).

Stream Key Convention:
    events:{namespace}:{entity_id}:{sub_id}

Examples:
    - events:agent:conv-123:msg-456
    - events:hitl:req-789
    - events:sandbox:sbx-abc
    - events:system:health

Features:
    - Consumer group support for load balancing
    - Pattern-based subscriptions
    - Automatic TTL cleanup
    - Event correlation tracking
"""

import asyncio
import fnmatch
import json
import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, List, Optional, Union

import redis.asyncio as redis

from src.domain.events.envelope import EventEnvelope
from src.domain.events.serialization import EventSerializer
from src.domain.ports.services.unified_event_bus_port import (
    EventPublishError,
    EventSubscribeError,
    EventWithMetadata,
    PublishResult,
    RoutingKey,
    SubscriptionOptions,
    UnifiedEventBusPort,
)

logger = logging.getLogger(__name__)


class RedisUnifiedEventBusAdapter(UnifiedEventBusPort):
    """Redis Streams implementation of UnifiedEventBusPort.

    Uses Redis Streams with auto-generated IDs for event ordering and
    consumer groups for load balancing.
    """

    # Stream key prefix
    STREAM_PREFIX = "events:"

    # Default settings
    DEFAULT_MAX_LEN = 10000  # Max events per stream (approximate)
    DEFAULT_BLOCK_MS = 5000  # Default block timeout for reads
    DEFAULT_TTL_SECONDS = 300  # 5 minutes TTL after completion/cleanup

    def __init__(
        self,
        redis_client: redis.Redis,
        stream_prefix: Optional[str] = None,
        default_max_len: Optional[int] = None,
        default_ttl_seconds: Optional[int] = None,
        serializer: Optional[EventSerializer] = None,
    ):
        """Initialize the Redis Unified Event Bus adapter.

        Args:
            redis_client: Async Redis client
            stream_prefix: Optional custom stream prefix
            default_max_len: Optional default max stream length
            default_ttl_seconds: TTL for completed streams
            serializer: Event serializer (default: auto-migrate enabled)
        """
        self._redis = redis_client
        self._stream_prefix = stream_prefix or self.STREAM_PREFIX
        self._max_len = default_max_len or self.DEFAULT_MAX_LEN
        self._ttl = default_ttl_seconds or self.DEFAULT_TTL_SECONDS
        self._serializer = serializer or EventSerializer(auto_migrate=True)
        self._active_subscriptions: Dict[str, bool] = {}

    def _get_stream_key(self, routing_key: Union[str, RoutingKey]) -> str:
        """Convert routing key to stream key."""
        key_str = str(routing_key) if isinstance(routing_key, RoutingKey) else routing_key
        return f"{self._stream_prefix}{key_str}"

    def _extract_routing_key(self, stream_key: str) -> str:
        """Extract routing key from stream key."""
        if stream_key.startswith(self._stream_prefix):
            return stream_key[len(self._stream_prefix):]
        return stream_key

    async def publish(
        self,
        event: EventEnvelope,
        routing_key: Union[str, RoutingKey],
    ) -> PublishResult:
        """Publish an event to the bus."""
        stream_key = self._get_stream_key(routing_key)
        routing_key_str = str(routing_key) if isinstance(routing_key, RoutingKey) else routing_key

        # Serialize event
        event_json = self._serializer.serialize(event)

        # Build stream data
        stream_data = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "schema_version": event.schema_version,
            "data": event_json,
            "timestamp": event.timestamp,
            "routing_key": routing_key_str,
        }

        # Add correlation if present
        if event.correlation_id:
            stream_data["correlation_id"] = event.correlation_id
        if event.causation_id:
            stream_data["causation_id"] = event.causation_id

        try:
            # Add to stream
            sequence_id = await self._redis.xadd(
                stream_key,
                stream_data,
                maxlen=self._max_len,
                approximate=True,
            )

            # Decode sequence_id if bytes
            if isinstance(sequence_id, bytes):
                sequence_id = sequence_id.decode("utf-8")

            logger.debug(
                f"[UnifiedEventBus] Published {event.event_type} to {stream_key}: "
                f"event_id={event.event_id}, seq={sequence_id}"
            )

            return PublishResult(
                sequence_id=sequence_id,
                stream_key=stream_key,
            )

        except redis.RedisError as e:
            logger.error(
                f"[UnifiedEventBus] Failed to publish to {stream_key}: {e}"
            )
            raise EventPublishError(
                f"Failed to publish event: {e}",
                routing_key=routing_key_str,
                event_type=event.event_type,
            ) from e

    async def publish_batch(
        self,
        events: List[tuple[EventEnvelope, Union[str, RoutingKey]]],
    ) -> List[PublishResult]:
        """Publish multiple events atomically using pipeline."""
        if not events:
            return []

        results = []
        async with self._redis.pipeline(transaction=True) as pipe:
            for event, routing_key in events:
                stream_key = self._get_stream_key(routing_key)
                routing_key_str = str(routing_key) if isinstance(routing_key, RoutingKey) else routing_key

                event_json = self._serializer.serialize(event)
                stream_data = {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "schema_version": event.schema_version,
                    "data": event_json,
                    "timestamp": event.timestamp,
                    "routing_key": routing_key_str,
                }

                if event.correlation_id:
                    stream_data["correlation_id"] = event.correlation_id
                if event.causation_id:
                    stream_data["causation_id"] = event.causation_id

                pipe.xadd(stream_key, stream_data, maxlen=self._max_len, approximate=True)

            try:
                sequence_ids = await pipe.execute()

                for i, seq_id in enumerate(sequence_ids):
                    if isinstance(seq_id, bytes):
                        seq_id = seq_id.decode("utf-8")

                    results.append(PublishResult(
                        sequence_id=seq_id,
                        stream_key=self._get_stream_key(events[i][1]),
                    ))

                return results

            except redis.RedisError as e:
                logger.error(f"[UnifiedEventBus] Batch publish failed: {e}")
                raise EventPublishError(f"Batch publish failed: {e}") from e

    async def subscribe(
        self,
        pattern: str,
        options: Optional[SubscriptionOptions] = None,
    ) -> AsyncIterator[EventWithMetadata]:
        """Subscribe to events matching a pattern."""
        opts = options or SubscriptionOptions()
        subscription_id = f"{pattern}:{id(opts)}"

        # Track active subscription
        self._active_subscriptions[subscription_id] = True

        try:
            if opts.consumer_group:
                async for event in self._subscribe_with_consumer_group(
                    pattern, opts, subscription_id
                ):
                    yield event
            else:
                async for event in self._subscribe_direct(pattern, opts, subscription_id):
                    yield event
        finally:
            self._active_subscriptions.pop(subscription_id, None)

    async def _subscribe_direct(
        self,
        pattern: str,
        opts: SubscriptionOptions,
        subscription_id: str,
    ) -> AsyncIterator[EventWithMetadata]:
        """Direct subscription without consumer group."""
        # Get matching stream keys
        stream_keys = await self._get_matching_streams(pattern)
        if not stream_keys:
            logger.debug(f"[UnifiedEventBus] No streams match pattern: {pattern}")
            return

        # Build stream dict with last_id tracking
        last_ids: Dict[str, str] = {key: "$" for key in stream_keys}

        while self._active_subscriptions.get(subscription_id, False):
            try:
                # Read from all matching streams
                streams = await self._redis.xread(
                    last_ids,
                    count=opts.batch_size,
                    block=opts.block_ms,
                )

                if not streams:
                    # Check for new matching streams periodically
                    new_streams = await self._get_matching_streams(pattern)
                    for key in new_streams:
                        if key not in last_ids:
                            last_ids[key] = "0"
                    continue

                for stream_name, messages in streams:
                    if isinstance(stream_name, bytes):
                        stream_name = stream_name.decode("utf-8")

                    for msg_id, fields in messages:
                        if isinstance(msg_id, bytes):
                            msg_id = msg_id.decode("utf-8")

                        event = self._parse_message(msg_id, fields, stream_name)
                        if event:
                            yield event

                        last_ids[stream_name] = msg_id

            except redis.ConnectionError as e:
                logger.error(f"[UnifiedEventBus] Connection error: {e}")
                await asyncio.sleep(1)  # Brief pause before retry
            except Exception as e:
                logger.error(f"[UnifiedEventBus] Subscribe error: {e}")
                raise EventSubscribeError(str(e), pattern=pattern) from e

    async def _subscribe_with_consumer_group(
        self,
        pattern: str,
        opts: SubscriptionOptions,
        subscription_id: str,
    ) -> AsyncIterator[EventWithMetadata]:
        """Subscription with consumer group for load balancing."""
        consumer_group = opts.consumer_group
        consumer_name = opts.consumer_name or f"consumer-{id(self)}"

        # Get matching streams and ensure consumer groups exist
        stream_keys = await self._get_matching_streams(pattern)
        for key in stream_keys:
            await self._ensure_consumer_group(key, consumer_group)

        stream_dict = {key: ">" for key in stream_keys}  # ">" = undelivered messages

        while self._active_subscriptions.get(subscription_id, False):
            try:
                # Read using consumer group
                streams = await self._redis.xreadgroup(
                    groupname=consumer_group,
                    consumername=consumer_name,
                    streams=stream_dict,
                    count=opts.batch_size,
                    block=opts.block_ms,
                )

                if not streams:
                    continue

                for stream_name, messages in streams:
                    if isinstance(stream_name, bytes):
                        stream_name = stream_name.decode("utf-8")

                    for msg_id, fields in messages:
                        if isinstance(msg_id, bytes):
                            msg_id = msg_id.decode("utf-8")

                        event = self._parse_message(msg_id, fields, stream_name)
                        if event:
                            yield event

                            # Auto-ack if configured
                            if opts.ack_immediately:
                                await self._redis.xack(
                                    stream_name, consumer_group, msg_id
                                )

            except redis.ResponseError as e:
                if "NOGROUP" in str(e):
                    # Group was deleted, recreate
                    for key in stream_keys:
                        await self._ensure_consumer_group(key, consumer_group)
                else:
                    logger.error(f"[UnifiedEventBus] Consumer group error: {e}")
                    raise
            except redis.ConnectionError as e:
                logger.error(f"[UnifiedEventBus] Connection error: {e}")
                await asyncio.sleep(1)

    async def _get_matching_streams(self, pattern: str) -> List[str]:
        """Get stream keys matching a pattern."""
        # Convert routing pattern to Redis SCAN pattern
        redis_pattern = f"{self._stream_prefix}{pattern.replace('.', ':')}"
        redis_pattern = redis_pattern.replace("*", "*").replace("?", "?")

        matching = []
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor,
                match=redis_pattern,
                count=100,
            )
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                matching.append(key)

            if cursor == 0:
                break

        return matching

    async def _ensure_consumer_group(
        self,
        stream_key: str,
        group_name: str,
    ) -> None:
        """Ensure a consumer group exists for a stream."""
        try:
            await self._redis.xgroup_create(
                stream_key,
                group_name,
                id="0",
                mkstream=True,
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def _parse_message(
        self,
        msg_id: str,
        fields: Dict[bytes, bytes],
        stream_key: str,
    ) -> Optional[EventWithMetadata]:
        """Parse a stream message to EventWithMetadata."""
        try:
            # Decode fields
            decoded = {}
            for k, v in fields.items():
                key = k.decode("utf-8") if isinstance(k, bytes) else k
                val = v.decode("utf-8") if isinstance(v, bytes) else v
                decoded[key] = val

            # Get event data
            event_json = decoded.get("data")
            if not event_json:
                logger.warning(f"Message {msg_id} has no data field")
                return None

            # Deserialize event
            result = self._serializer.deserialize(event_json)
            envelope = result.envelope

            # Get routing key
            routing_key = decoded.get("routing_key") or self._extract_routing_key(stream_key)

            return EventWithMetadata(
                envelope=envelope,
                routing_key=routing_key,
                sequence_id=msg_id,
            )

        except Exception as e:
            logger.error(f"Failed to parse message {msg_id}: {e}")
            return None

    async def get_events(
        self,
        routing_key: Union[str, RoutingKey],
        from_sequence: str = "0",
        to_sequence: Optional[str] = None,
        max_count: int = 1000,
    ) -> List[EventWithMetadata]:
        """Get events from a specific stream."""
        stream_key = self._get_stream_key(routing_key)
        events = []

        try:
            result = await self._redis.xrange(
                stream_key,
                min=from_sequence,
                max=to_sequence or "+",
                count=max_count,
            )

            for msg_id, fields in result:
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")

                event = self._parse_message(msg_id, fields, stream_key)
                if event:
                    events.append(event)

            return events

        except redis.RedisError as e:
            logger.error(f"Failed to get events from {stream_key}: {e}")
            return []

    async def get_latest_event(
        self,
        routing_key: Union[str, RoutingKey],
    ) -> Optional[EventWithMetadata]:
        """Get the most recent event from a stream."""
        stream_key = self._get_stream_key(routing_key)

        try:
            result = await self._redis.xrevrange(stream_key, count=1)
            if result:
                msg_id, fields = result[0]
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")
                return self._parse_message(msg_id, fields, stream_key)
            return None

        except redis.RedisError as e:
            logger.error(f"Failed to get latest from {stream_key}: {e}")
            return None

    async def acknowledge(
        self,
        routing_key: Union[str, RoutingKey],
        sequence_ids: List[str],
        consumer_group: str,
    ) -> int:
        """Acknowledge processed events."""
        stream_key = self._get_stream_key(routing_key)

        try:
            return await self._redis.xack(stream_key, consumer_group, *sequence_ids)
        except redis.RedisError as e:
            logger.error(f"Failed to ack events: {e}")
            return 0

    async def stream_exists(self, routing_key: Union[str, RoutingKey]) -> bool:
        """Check if a stream exists."""
        stream_key = self._get_stream_key(routing_key)
        return await self._redis.exists(stream_key) > 0

    async def get_stream_length(self, routing_key: Union[str, RoutingKey]) -> int:
        """Get the number of events in a stream."""
        stream_key = self._get_stream_key(routing_key)

        try:
            return await self._redis.xlen(stream_key)
        except redis.RedisError:
            return 0

    async def trim_stream(
        self,
        routing_key: Union[str, RoutingKey],
        max_length: int,
        approximate: bool = True,
    ) -> int:
        """Trim a stream to a maximum length."""
        stream_key = self._get_stream_key(routing_key)

        try:
            return await self._redis.xtrim(
                stream_key,
                maxlen=max_length,
                approximate=approximate,
            )
        except redis.RedisError as e:
            logger.error(f"Failed to trim stream {stream_key}: {e}")
            return 0

    async def delete_stream(self, routing_key: Union[str, RoutingKey]) -> bool:
        """Delete a stream entirely."""
        stream_key = self._get_stream_key(routing_key)

        try:
            result = await self._redis.delete(stream_key)
            return result > 0
        except redis.RedisError as e:
            logger.error(f"Failed to delete stream {stream_key}: {e}")
            return False

    async def create_consumer_group(
        self,
        routing_key: Union[str, RoutingKey],
        group_name: str,
        start_id: str = "0",
    ) -> bool:
        """Create a consumer group for a stream."""
        stream_key = self._get_stream_key(routing_key)

        try:
            await self._redis.xgroup_create(
                stream_key,
                group_name,
                id=start_id,
                mkstream=True,
            )
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                return True  # Group already exists
            logger.error(f"Failed to create consumer group: {e}")
            return False

    def stop_subscription(self, pattern: str) -> None:
        """Stop a subscription by pattern.

        This signals active subscriptions matching the pattern to stop.
        """
        for sub_id in list(self._active_subscriptions.keys()):
            if sub_id.startswith(pattern):
                self._active_subscriptions[sub_id] = False
