import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

import redis.asyncio as redis

from src.domain.ports.services.event_bus_port import EventBusPort

logger = logging.getLogger(__name__)


class RedisEventBusAdapter(EventBusPort):
    """
    Redis-based implementation of EventBusPort.

    Supports both Pub/Sub (legacy) and Redis Streams (recommended).

    Redis Streams advantages over Pub/Sub:
    - Message persistence (survives disconnects)
    - Consumer groups for load balancing
    - Message acknowledgment
    - Automatic retries for failed consumers
    - Message replay from any point
    """

    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client

    # =========================================================================
    # Pub/Sub methods (legacy, kept for backward compatibility)
    # =========================================================================

    async def publish(self, channel: str, message: Dict[str, Any]) -> int:
        """
        Publish a message to a Redis channel (Pub/Sub).

        Args:
            channel: Channel name
            message: Message data (will be serialized to JSON)

        Returns:
            Number of subscribers that received the message
        """
        try:
            # Ensure message is JSON serializable
            # For complex objects, use default=str or similar strategy if needed
            payload = json.dumps(message, default=str)
            return await self._redis.publish(channel, payload)
        except Exception as e:
            logger.error(f"Failed to publish to Redis channel {channel}: {e}")
            raise

    async def subscribe(self, channel: str) -> AsyncIterator[Dict[str, Any]]:
        """
        Subscribe to a Redis channel (Pub/Sub).

        Args:
            channel: Channel name

        Returns:
            Async iterator yielding messages
        """
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        yield data
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to decode JSON from channel {channel}")
                        # Optionally yield raw data or skip
                        continue
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    # =========================================================================
    # Redis Stream methods (recommended for reliable message delivery)
    # =========================================================================

    async def stream_add(
        self,
        stream_key: str,
        message: Dict[str, Any],
        maxlen: Optional[int] = None,
    ) -> str:
        """
        Add a message to a Redis Stream.

        Args:
            stream_key: Stream key name
            message: Message data (will be serialized to JSON)
            maxlen: Optional max length for stream trimming (approximate)

        Returns:
            Message ID assigned by Redis
        """
        try:
            # Serialize message to JSON and store in 'data' field
            payload = {"data": json.dumps(message, default=str)}

            # XADD with optional maxlen for automatic trimming
            if maxlen:
                message_id = await self._redis.xadd(
                    stream_key, payload, maxlen=maxlen, approximate=True
                )
            else:
                message_id = await self._redis.xadd(stream_key, payload)

            # Redis returns bytes, decode to string
            if isinstance(message_id, bytes):
                message_id = message_id.decode("utf-8")

            return message_id

        except Exception as e:
            logger.error(f"[RedisStream] Failed to add to stream {stream_key}: {e}")
            raise

    async def stream_read(
        self,
        stream_key: str,
        last_id: str = "0",
        count: Optional[int] = None,
        block_ms: Optional[int] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Read messages from a Redis Stream.

        Args:
            stream_key: Stream key name
            last_id: Last message ID to start reading from (exclusive)
            count: Max number of messages to return per call
            block_ms: Block timeout in milliseconds (None = non-blocking)

        Yields:
            Message dictionaries with 'id' and 'data' fields
        """
        current_id = last_id

        while True:
            try:
                # XREAD returns: [(stream_name, [(msg_id, {fields}), ...])]
                streams = await self._redis.xread(
                    {stream_key: current_id},
                    count=count or 100,
                    block=block_ms,
                )

                if not streams:
                    # No new messages (timeout or empty)
                    if block_ms is None:
                        # Non-blocking mode, we're done
                        return
                    continue

                for stream_name, messages in streams:
                    for msg_id, fields in messages:
                        # Decode message ID
                        if isinstance(msg_id, bytes):
                            msg_id = msg_id.decode("utf-8")

                        # Parse JSON data
                        raw_data = fields.get(b"data") or fields.get("data")
                        if isinstance(raw_data, bytes):
                            raw_data = raw_data.decode("utf-8")

                        try:
                            data = json.loads(raw_data) if raw_data else {}
                        except json.JSONDecodeError:
                            data = {}

                        current_id = msg_id
                        yield {"id": msg_id, "data": data}

            except Exception as e:
                logger.error(f"[RedisStream] Error reading from {stream_key}: {e}")
                raise

    async def stream_read_group(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        last_id: str = ">",
        count: Optional[int] = None,
        block_ms: Optional[int] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Read messages from a Redis Stream using consumer groups.

        Consumer groups provide:
        - Message acknowledgment
        - Pending entry list for failed consumers
        - Automatic load balancing across consumers

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            consumer_name: Consumer name within the group
            last_id: ">" for new messages only, "0" for pending messages
            count: Max number of messages to return per call
            block_ms: Block timeout in milliseconds

        Yields:
            Message dictionaries with 'id' and 'data' fields
        """
        while True:
            try:
                # XREADGROUP returns same format as XREAD
                streams = await self._redis.xreadgroup(
                    groupname=group_name,
                    consumername=consumer_name,
                    streams={stream_key: last_id},
                    count=count or 10,
                    block=block_ms,
                )

                if not streams:
                    if block_ms is None:
                        return
                    continue

                for stream_name, messages in streams:
                    for msg_id, fields in messages:
                        # Decode message ID
                        if isinstance(msg_id, bytes):
                            msg_id = msg_id.decode("utf-8")

                        # Parse JSON data
                        raw_data = fields.get(b"data") or fields.get("data")
                        if isinstance(raw_data, bytes):
                            raw_data = raw_data.decode("utf-8")

                        try:
                            data = json.loads(raw_data) if raw_data else {}
                        except json.JSONDecodeError:
                            data = {}

                        yield {"id": msg_id, "data": data}

                # For ">" mode, messages are automatically delivered to this consumer
                # For "0" mode (pending), we need to keep reading
                if last_id == ">":
                    # Continue blocking for new messages
                    continue
                else:
                    # Reading pending, check if there are more
                    if not streams or not streams[0][1]:
                        return

            except Exception as e:
                logger.error(
                    f"[RedisStream] Error reading group {group_name} from {stream_key}: {e}"
                )
                raise

    async def stream_ack(
        self,
        stream_key: str,
        group_name: str,
        message_ids: list[str],
    ) -> int:
        """
        Acknowledge messages in a consumer group.

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            message_ids: List of message IDs to acknowledge

        Returns:
            Number of messages acknowledged
        """
        try:
            return await self._redis.xack(stream_key, group_name, *message_ids)
        except Exception as e:
            logger.error(f"[RedisStream] Failed to ack messages in {stream_key}: {e}")
            raise

    async def stream_create_group(
        self,
        stream_key: str,
        group_name: str,
        start_id: str = "$",
        mkstream: bool = True,
    ) -> bool:
        """
        Create a consumer group for a stream.

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            start_id: Starting message ID ("$" = only new messages, "0" = all messages)
            mkstream: Create the stream if it doesn't exist

        Returns:
            True if created successfully
        """
        try:
            await self._redis.xgroup_create(stream_key, group_name, id=start_id, mkstream=mkstream)
            logger.info(f"[RedisStream] Created group {group_name} for {stream_key}")
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists
                logger.debug(f"[RedisStream] Group {group_name} already exists for {stream_key}")
                return True
            logger.error(f"[RedisStream] Failed to create group {group_name}: {e}")
            raise

    async def stream_pending(
        self,
        stream_key: str,
        group_name: str,
        count: int = 10,
    ) -> list[Dict[str, Any]]:
        """
        Get pending messages for a consumer group (messages not yet acknowledged).

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            count: Max number of pending entries to return

        Returns:
            List of pending message info with message_id, consumer, idle_time, delivery_count
        """
        try:
            # XPENDING with IDLE option for detailed info
            result = await self._redis.xpending_range(stream_key, group_name, "-", "+", count)

            pending = []
            for entry in result:
                msg_id = entry.get("message_id")
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")

                consumer = entry.get("consumer")
                if isinstance(consumer, bytes):
                    consumer = consumer.decode("utf-8")

                pending.append(
                    {
                        "message_id": msg_id,
                        "consumer": consumer,
                        "idle_time": entry.get("time_since_delivered", 0),
                        "delivery_count": entry.get("times_delivered", 1),
                    }
                )

            return pending

        except Exception as e:
            logger.error(f"[RedisStream] Failed to get pending for {stream_key}: {e}")
            return []

    async def stream_claim(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        min_idle_ms: int,
        message_ids: list[str],
    ) -> list[Dict[str, Any]]:
        """
        Claim pending messages from another consumer (for recovery).

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            consumer_name: Consumer to claim messages for
            min_idle_ms: Minimum idle time for messages to be claimable
            message_ids: List of message IDs to claim

        Returns:
            List of claimed messages
        """
        try:
            # XCLAIM returns the claimed messages
            result = await self._redis.xclaim(
                stream_key, group_name, consumer_name, min_idle_ms, message_ids
            )

            claimed = []
            for msg_id, fields in result:
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")

                raw_data = fields.get(b"data") or fields.get("data")
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")

                try:
                    data = json.loads(raw_data) if raw_data else {}
                except json.JSONDecodeError:
                    data = {}

                claimed.append({"id": msg_id, "data": data})

            logger.info(
                f"[RedisStream] Claimed {len(claimed)} messages for {consumer_name} in {stream_key}"
            )
            return claimed

        except Exception as e:
            logger.error(f"[RedisStream] Failed to claim messages: {e}")
            return []

    async def stream_len(self, stream_key: str) -> int:
        """
        Get the length of a stream.

        Args:
            stream_key: Stream key name

        Returns:
            Number of messages in the stream
        """
        try:
            return await self._redis.xlen(stream_key)
        except Exception as e:
            logger.error(f"[RedisStream] Failed to get length of {stream_key}: {e}")
            return 0

    async def stream_trim(
        self,
        stream_key: str,
        maxlen: int,
        approximate: bool = True,
    ) -> int:
        """
        Trim a stream to a maximum length.

        Args:
            stream_key: Stream key name
            maxlen: Maximum number of messages to keep
            approximate: Use approximate trimming (faster)

        Returns:
            Number of messages removed
        """
        try:
            return await self._redis.xtrim(stream_key, maxlen=maxlen, approximate=approximate)
        except Exception as e:
            logger.error(f"[RedisStream] Failed to trim {stream_key}: {e}")
            return 0

    # =========================================================================
    # Convenience methods for agent event streaming
    # =========================================================================

    async def publish_to_stream(
        self,
        conversation_id: str,
        event: Dict[str, Any],
        maxlen: int = 1000,
    ) -> str:
        """
        Publish an agent event to both Stream and Pub/Sub.

        This provides:
        - Stream: Persistence, replay, consumer groups
        - Pub/Sub: Real-time notifications (backward compatible)

        Args:
            conversation_id: Conversation ID
            event: Event data with 'type', 'data', 'seq' fields
            maxlen: Max stream length (auto-trim older events)

        Returns:
            Stream message ID
        """
        stream_key = f"agent:events:{conversation_id}"
        channel = f"agent:stream:{conversation_id}"

        # Add to stream (persistent)
        message_id = await self.stream_add(stream_key, event, maxlen=maxlen)

        # Also publish to Pub/Sub for real-time (backward compatible)
        await self.publish(channel, event)

        return message_id

    async def subscribe_to_stream(
        self,
        conversation_id: str,
        last_seq: int = 0,
        block_ms: int = 5000,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Subscribe to agent events using Redis Stream.

        Provides reliable message delivery with:
        - Replay from last_seq
        - No message loss on reconnect
        - Automatic ordering

        Args:
            conversation_id: Conversation ID
            last_seq: Last sequence number received (0 = from beginning)
            block_ms: Block timeout for new messages

        Yields:
            Event dictionaries
        """
        stream_key = f"agent:events:{conversation_id}"

        # Convert seq to stream ID (seq is stored in event data, not stream ID)
        # Start from beginning and filter by seq
        last_id = "0"

        async for message in self.stream_read(stream_key, last_id=last_id, block_ms=block_ms):
            event = message.get("data", {})
            seq = event.get("seq", 0)

            # Skip events we've already seen
            if seq <= last_seq:
                continue

            event["_stream_id"] = message.get("id")
            yield event

            # Check for completion
            event_type = event.get("type", "")
            if event_type in ("complete", "error"):
                return
