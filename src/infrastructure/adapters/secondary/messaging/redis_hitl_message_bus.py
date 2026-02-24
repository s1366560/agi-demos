"""
Redis Streams implementation of HITLMessageBusPort.

This adapter uses Redis Streams for reliable cross-process HITL communication.

Redis Streams advantages:
- Message persistence (survives disconnects and restarts)
- Consumer groups for load balancing and at-least-once delivery
- Message acknowledgment
- Automatic retry for failed consumers
- Message replay from any point
- Efficient cleanup via XTRIM

Stream naming convention:
- hitl:stream:{request_id} - One stream per HITL request

Consumer group naming convention:
- hitl:{request_type}:workers - One group per request type
  e.g., hitl:decision:workers, hitl:clarification:workers, hitl:env_var:workers
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import redis.asyncio as redis

from src.domain.ports.services.hitl_message_bus_port import (
    HITLMessage,
    HITLMessageBusPort,
    HITLMessageType,
)

logger = logging.getLogger(__name__)


class RedisHITLMessageBusAdapter(HITLMessageBusPort):
    """
    Redis Streams implementation of HITLMessageBusPort.

    Uses Redis Streams with consumer groups for reliable message delivery.
    Each HITL request gets its own stream for isolation.
    """

    # Stream key prefix
    STREAM_PREFIX = "hitl:stream:"

    # Default stream settings
    DEFAULT_MAX_LEN = 1000  # Max messages per stream (approximate)
    DEFAULT_BLOCK_MS = 5000  # Default block timeout for reads
    DEFAULT_CONSUMER_GROUP = "hitl-workers"

    def __init__(
        self,
        redis_client: redis.Redis,
        stream_prefix: str | None = None,
        default_max_len: int | None = None,
    ) -> None:
        """
        Initialize the Redis HITL message bus adapter.

        Args:
            redis_client: Async Redis client
            stream_prefix: Optional custom stream prefix (default: "hitl:stream:")
            default_max_len: Optional default max stream length
        """
        self._redis = redis_client
        self._stream_prefix = stream_prefix or self.STREAM_PREFIX
        self._default_max_len = default_max_len or self.DEFAULT_MAX_LEN

    def _get_stream_key(self, request_id: str) -> str:
        """Get the stream key for a request."""
        return f"{self._stream_prefix}{request_id}"

    async def publish_response(
        self,
        request_id: str,
        response_key: str,
        response_value: Any,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Publish a response to an HITL request stream.

        Args:
            request_id: HITL request ID
            response_key: Key for the response (e.g., "decision", "answer", "values")
            response_value: The response value
            metadata: Optional additional metadata

        Returns:
            Message ID assigned by Redis
        """
        stream_key = self._get_stream_key(request_id)

        # Build message payload
        message_data = {
            "request_id": request_id,
            "message_type": HITLMessageType.RESPONSE.value,
            "payload": {response_key: response_value},
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
        }

        try:
            # Serialize to JSON and add to stream
            payload = {"data": json.dumps(message_data, default=str)}

            message_id = await self._redis.xadd(
                stream_key,
                payload,  # type: ignore[arg-type]  # Redis type stubs overly strict
                maxlen=self._default_max_len,
                approximate=True,
            )

            # Decode message ID if bytes
            if isinstance(message_id, bytes):
                message_id = message_id.decode("utf-8")

            logger.info(
                f"[HITLMessageBus] Published response to {stream_key}: "
                f"message_id={message_id}, key={response_key}"
            )

            return cast(str, message_id)

        except Exception as e:
            logger.error(f"[HITLMessageBus] Failed to publish to {stream_key}: {e}")
            raise

    async def subscribe_for_response(
        self,
        request_id: str,
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int | None = None,
    ) -> AsyncIterator[HITLMessage]:
        """
        Subscribe to receive responses for an HITL request.

        Uses XREADGROUP for consumer group support.

        Args:
            request_id: HITL request ID to wait for
            consumer_group: Consumer group name
            consumer_name: Consumer name within the group
            timeout_ms: Block timeout in milliseconds

        Yields:
            HITLMessage objects as they arrive
        """
        stream_key = self._get_stream_key(request_id)
        block_ms = timeout_ms or self.DEFAULT_BLOCK_MS

        # Ensure consumer group exists
        await self.create_consumer_group(
            request_id=request_id,
            consumer_group=consumer_group,
            start_from_latest=False,  # Read all messages, including pending
        )

        # First, check for pending messages
        async for msg in self._read_pending_messages(stream_key, consumer_group, consumer_name):
            yield msg

        # Now wait for new messages
        async for msg in self._poll_new_messages(
            stream_key, consumer_group, consumer_name, block_ms
        ):
            yield msg
            return  # Single response expected, exit after receiving

    async def _read_pending_messages(
        self,
        stream_key: str,
        consumer_group: str,
        consumer_name: str,
    ) -> AsyncIterator[HITLMessage]:
        """Read pending messages that were delivered but not acknowledged."""
        try:
            pending = await self._redis.xreadgroup(
                groupname=consumer_group,
                consumername=consumer_name,
                streams={stream_key: "0"},  # "0" = pending messages
                count=10,
                block=0,  # Non-blocking for pending
            )

            if pending:
                for _stream_name, messages in pending:
                    for msg_id, fields in messages:
                        message = self._parse_stream_message(msg_id, fields)
                        if message:
                            yield message

        except Exception as e:
            logger.warning(f"[HITLMessageBus] Error reading pending from {stream_key}: {e}")

    async def _poll_new_messages(
        self,
        stream_key: str,
        consumer_group: str,
        consumer_name: str,
        block_ms: int,
    ) -> AsyncIterator[HITLMessage]:
        """Poll for new messages using consumer group."""
        while True:
            try:
                streams = await self._redis.xreadgroup(
                    groupname=consumer_group,
                    consumername=consumer_name,
                    streams={stream_key: ">"},  # ">" = only new messages
                    count=1,
                    block=block_ms,
                )

                if not streams:
                    continue

                for _stream_name, messages in streams:
                    for msg_id, fields in messages:
                        message = self._parse_stream_message(msg_id, fields)
                        if message:
                            yield message
                            return

            except redis.ConnectionError as e:
                logger.error(f"[HITLMessageBus] Connection error on {stream_key}: {e}")
                raise
            except Exception as e:
                logger.error(f"[HITLMessageBus] Error reading from {stream_key}: {e}")
                raise

    def _parse_stream_message(self, msg_id: Any, fields: dict[Any, Any]) -> HITLMessage | None:
        """Parse a raw Redis stream message into HITLMessage."""
        try:
            # Decode message ID
            if isinstance(msg_id, bytes):
                msg_id = msg_id.decode("utf-8")

            # Get data field
            raw_data = fields.get(b"data") or fields.get("data")
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")

            if not raw_data:
                return None

            # Parse JSON
            data = json.loads(raw_data)

            return HITLMessage(
                message_id=msg_id,
                request_id=data.get("request_id", ""),
                message_type=HITLMessageType(
                    data.get("message_type", HITLMessageType.RESPONSE.value)
                ),
                payload=data.get("payload", {}),
                timestamp=(
                    datetime.fromisoformat(data["timestamp"])
                    if isinstance(data.get("timestamp"), str)
                    else datetime.now(UTC)
                ),
                metadata=data.get("metadata"),
            )

        except Exception as e:
            logger.warning(f"[HITLMessageBus] Failed to parse message {msg_id}: {e}")
            return None

    async def acknowledge(
        self,
        request_id: str,
        consumer_group: str,
        message_ids: list[str],
    ) -> int:
        """
        Acknowledge receipt of messages.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            message_ids: List of message IDs to acknowledge

        Returns:
            Number of messages acknowledged
        """
        stream_key = self._get_stream_key(request_id)

        try:
            acked = await self._redis.xack(stream_key, consumer_group, *message_ids)
            logger.info(f"[HITLMessageBus] Acknowledged {acked} messages in {stream_key}")
            return cast(int, acked)
        except Exception as e:
            logger.error(f"[HITLMessageBus] Failed to ack messages in {stream_key}: {e}")
            raise

    async def create_consumer_group(
        self,
        request_id: str,
        consumer_group: str,
        start_from_latest: bool = True,
    ) -> bool:
        """
        Create a consumer group for an HITL request stream.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            start_from_latest: If True, only read new messages; if False, read from beginning

        Returns:
            True if created successfully (or already exists)
        """
        stream_key = self._get_stream_key(request_id)
        start_id = "$" if start_from_latest else "0"

        try:
            await self._redis.xgroup_create(
                stream_key,
                consumer_group,
                id=start_id,
                mkstream=True,  # Create stream if it doesn't exist
            )
            logger.info(
                f"[HITLMessageBus] Created consumer group {consumer_group} for {stream_key}"
            )
            return True

        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists - this is fine
                logger.debug(
                    f"[HITLMessageBus] Consumer group {consumer_group} already exists for {stream_key}"
                )
                return True
            logger.error(f"[HITLMessageBus] Failed to create group: {e}")
            raise

    async def get_pending_messages(
        self,
        request_id: str,
        consumer_group: str,
        count: int = 10,
    ) -> list[HITLMessage]:
        """
        Get pending messages that haven't been acknowledged.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            count: Maximum number of pending messages to return

        Returns:
            List of pending messages
        """
        stream_key = self._get_stream_key(request_id)
        messages: list[HITLMessage] = []

        try:
            # XPENDING returns summary info, use XPENDING with range for details
            pending_info = await self._redis.xpending_range(
                stream_key,
                consumer_group,
                min="-",
                max="+",
                count=count,
            )

            if not pending_info:
                return messages

            # Get the actual message content for each pending message
            for entry in pending_info:
                msg_id = entry.get("message_id")
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")

                # Read the message content
                result = await self._redis.xrange(stream_key, min=msg_id, max=msg_id, count=1)

                if result:
                    for mid, fields in result:
                        message = self._parse_stream_message(mid, fields)
                        if message:
                            messages.append(message)

            return messages

        except Exception as e:
            logger.error(f"[HITLMessageBus] Failed to get pending messages from {stream_key}: {e}")
            return messages

    async def claim_pending_messages(
        self,
        request_id: str,
        consumer_group: str,
        consumer_name: str,
        min_idle_ms: int,
        message_ids: list[str],
    ) -> list[HITLMessage]:
        """
        Claim pending messages from another consumer.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            consumer_name: Consumer to claim messages for
            min_idle_ms: Minimum idle time for messages to be claimable
            message_ids: List of message IDs to claim

        Returns:
            List of claimed messages
        """
        stream_key = self._get_stream_key(request_id)
        messages = []

        try:
            # XCLAIM returns the claimed messages
            claimed = await self._redis.xclaim(
                stream_key,
                consumer_group,
                consumer_name,
                min_idle_time=min_idle_ms,
                message_ids=message_ids,  # type: ignore[arg-type]  # Redis type stubs overly strict
            )

            for msg_id, fields in claimed:
                message = self._parse_stream_message(msg_id, fields)
                if message:
                    messages.append(message)

            logger.info(f"[HITLMessageBus] Claimed {len(messages)} messages in {stream_key}")
            return messages

        except Exception as e:
            logger.error(f"[HITLMessageBus] Failed to claim messages: {e}")
            return messages

    async def cleanup_stream(
        self,
        request_id: str,
        max_len: int | None = None,
    ) -> int:
        """
        Clean up a stream (trim old messages or delete entirely).

        Args:
            request_id: HITL request ID
            max_len: If provided, trim to this length; if None, delete the stream

        Returns:
            Number of messages removed (or 0 if deleted)
        """
        stream_key = self._get_stream_key(request_id)

        try:
            if max_len is None:
                # Delete the entire stream
                await self._redis.delete(stream_key)
                logger.info(f"[HITLMessageBus] Deleted stream {stream_key}")
                return 0
            else:
                # Trim to max length
                removed = await self._redis.xtrim(stream_key, maxlen=max_len, approximate=True)
                logger.info(f"[HITLMessageBus] Trimmed {removed} messages from {stream_key}")
                return cast(int, removed)

        except Exception as e:
            logger.error(f"[HITLMessageBus] Failed to cleanup {stream_key}: {e}")
            raise

    async def stream_exists(self, request_id: str) -> bool:
        """
        Check if a stream exists for the given request.

        Args:
            request_id: HITL request ID

        Returns:
            True if stream exists
        """
        stream_key = self._get_stream_key(request_id)

        try:
            return cast(bool, await self._redis.exists(stream_key) > 0)
        except Exception as e:
            logger.error(f"[HITLMessageBus] Failed to check stream existence: {e}")
            return False

    # =========================================================================
    # Additional utility methods
    # =========================================================================

    async def get_stream_info(self, request_id: str) -> dict[str, Any] | None:
        """
        Get stream information (length, groups, etc.).

        Args:
            request_id: HITL request ID

        Returns:
            Stream info dictionary or None if stream doesn't exist
        """
        stream_key = self._get_stream_key(request_id)

        try:
            info = await self._redis.xinfo_stream(stream_key)
            return dict(info) if info else None
        except redis.ResponseError as e:
            if "ERR no such key" in str(e):
                return None
            raise

    async def wait_for_single_response(
        self,
        request_id: str,
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int,
        auto_ack: bool = True,
    ) -> HITLMessage | None:
        """
        Convenience method to wait for a single response with timeout.

        This is the most common use case for HITL tools.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            consumer_name: Consumer name
            timeout_ms: Timeout in milliseconds
            auto_ack: If True, automatically acknowledge the message

        Returns:
            HITLMessage if received, None if timeout
        """
        import asyncio

        start_time = asyncio.get_event_loop().time()
        remaining_ms = timeout_ms

        async for message in self.subscribe_for_response(
            request_id=request_id,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            timeout_ms=min(remaining_ms, 5000),  # Check every 5 seconds max
        ):
            if auto_ack:
                await self.acknowledge(
                    request_id=request_id,
                    consumer_group=consumer_group,
                    message_ids=[message.message_id],
                )
            return message

            # Update remaining time  # type: ignore[unreachable]
            elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)  # type: ignore[unreachable]
            remaining_ms = timeout_ms - elapsed_ms
            if remaining_ms <= 0:
                break

        return None


# Factory function for creating the adapter
def create_redis_hitl_message_bus(
    redis_client: redis.Redis,
    stream_prefix: str | None = None,
) -> RedisHITLMessageBusAdapter:
    """
    Create a RedisHITLMessageBusAdapter instance.

    Args:
        redis_client: Async Redis client
        stream_prefix: Optional custom stream prefix

    Returns:
        Configured RedisHITLMessageBusAdapter
    """
    return RedisHITLMessageBusAdapter(
        redis_client=redis_client,
        stream_prefix=stream_prefix,
    )
