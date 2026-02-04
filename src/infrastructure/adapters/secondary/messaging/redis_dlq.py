"""Redis Dead Letter Queue Adapter.

Implements the DeadLetterQueuePort using Redis for storage.

Storage Structure:
- Hash: dlq:messages:{message_id} - Message data
- Sorted Set: dlq:index:pending - Pending messages (score = timestamp)
- Sorted Set: dlq:index:by_error_type:{error_type} - Index by error type
- Sorted Set: dlq:index:by_event_type:{event_type} - Index by event type
- Hash: dlq:stats - Aggregate statistics
"""

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import redis.asyncio as redis

from src.domain.events.envelope import EventEnvelope
from src.domain.ports.services.dead_letter_queue_port import (
    DeadLetterMessage,
    DeadLetterQueuePort,
    DLQError,
    DLQMessageNotFoundError,
    DLQMessageStatus,
    DLQRetryError,
    DLQStats,
)
from src.domain.ports.services.unified_event_bus_port import UnifiedEventBusPort

logger = logging.getLogger(__name__)


class RedisDLQAdapter(DeadLetterQueuePort):
    """Redis implementation of the Dead Letter Queue.

    Uses Redis hashes for message storage and sorted sets for indexing.
    """

    # Key prefixes
    MESSAGE_PREFIX = "dlq:messages:"
    PENDING_INDEX = "dlq:index:pending"
    ERROR_TYPE_INDEX_PREFIX = "dlq:index:by_error_type:"
    EVENT_TYPE_INDEX_PREFIX = "dlq:index:by_event_type:"
    STATS_KEY = "dlq:stats"

    # Retry backoff (exponential)
    RETRY_DELAYS = [60, 300, 900, 3600]  # 1min, 5min, 15min, 1hour

    def __init__(
        self,
        redis_client: redis.Redis,
        event_bus: Optional[UnifiedEventBusPort] = None,
        *,
        max_retries: int = 3,
        default_ttl_hours: int = 168,  # 1 week
    ):
        """Initialize the Redis DLQ adapter.

        Args:
            redis_client: Async Redis client
            event_bus: Optional event bus for retry republishing
            max_retries: Default maximum retry attempts
            default_ttl_hours: Default message TTL in hours
        """
        self._redis = redis_client
        self._event_bus = event_bus
        self._max_retries = max_retries
        self._default_ttl = default_ttl_hours * 3600  # Convert to seconds

    def _message_key(self, message_id: str) -> str:
        """Get the Redis key for a message."""
        return f"{self.MESSAGE_PREFIX}{message_id}"

    def _error_type_index_key(self, error_type: str) -> str:
        """Get the index key for an error type."""
        return f"{self.ERROR_TYPE_INDEX_PREFIX}{error_type}"

    def _event_type_index_key(self, event_type: str) -> str:
        """Get the index key for an event type."""
        return f"{self.EVENT_TYPE_INDEX_PREFIX}{event_type}"

    async def send_to_dlq(
        self,
        event_id: str,
        event_type: str,
        event_data: str,
        routing_key: str,
        error: str,
        error_type: str,
        *,
        error_traceback: Optional[str] = None,
        retry_count: int = 0,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a failed event to the DLQ."""
        now = datetime.now(timezone.utc)

        # Calculate next retry time
        next_retry_delay = self.RETRY_DELAYS[min(retry_count, len(self.RETRY_DELAYS) - 1)]
        next_retry_at = datetime.fromtimestamp(
            now.timestamp() + next_retry_delay, tz=timezone.utc
        )

        message = DeadLetterMessage(
            event_id=event_id,
            event_type=event_type,
            event_data=event_data,
            routing_key=routing_key,
            error=error,
            error_type=error_type,
            error_traceback=error_traceback,
            retry_count=retry_count,
            max_retries=max_retries,
            first_failed_at=now,
            last_failed_at=now,
            next_retry_at=next_retry_at if retry_count < max_retries else None,
            status=DLQMessageStatus.PENDING,
            metadata=metadata or {},
        )

        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                # Store message data
                message_key = self._message_key(message.id)
                pipe.hset(message_key, mapping={
                    "data": json.dumps(message.to_dict()),
                })
                pipe.expire(message_key, self._default_ttl)

                # Add to pending index (score = timestamp)
                pipe.zadd(self.PENDING_INDEX, {message.id: now.timestamp()})

                # Add to error type index
                pipe.zadd(self._error_type_index_key(error_type), {message.id: now.timestamp()})

                # Add to event type index
                pipe.zadd(self._event_type_index_key(event_type), {message.id: now.timestamp()})

                # Update stats
                pipe.hincrby(self.STATS_KEY, "total_messages", 1)
                pipe.hincrby(self.STATS_KEY, "pending_count", 1)
                pipe.hincrby(self.STATS_KEY, f"error:{error_type}", 1)
                pipe.hincrby(self.STATS_KEY, f"event:{event_type}", 1)

                await pipe.execute()

            logger.warning(
                f"[DLQ] Message {message.id} added: event={event_id}, "
                f"type={event_type}, error={error_type}"
            )
            return message.id

        except redis.RedisError as e:
            logger.error(f"[DLQ] Failed to store message: {e}")
            raise DLQError(f"Failed to store DLQ message: {e}") from e

    async def get_message(self, message_id: str) -> Optional[DeadLetterMessage]:
        """Get a specific DLQ message."""
        try:
            message_key = self._message_key(message_id)
            data = await self._redis.hget(message_key, "data")

            if not data:
                return None

            if isinstance(data, bytes):
                data = data.decode("utf-8")

            message_dict = json.loads(data)
            return DeadLetterMessage.from_dict(message_dict)

        except redis.RedisError as e:
            logger.error(f"[DLQ] Failed to get message {message_id}: {e}")
            return None

    async def get_messages(
        self,
        *,
        status: Optional[DLQMessageStatus] = None,
        event_type: Optional[str] = None,
        error_type: Optional[str] = None,
        routing_key_pattern: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DeadLetterMessage]:
        """Get DLQ messages with filtering."""
        try:
            # Determine which index to use
            if error_type:
                index_key = self._error_type_index_key(error_type)
            elif event_type:
                index_key = self._event_type_index_key(event_type)
            else:
                index_key = self.PENDING_INDEX

            # Get message IDs from index
            message_ids = await self._redis.zrevrange(
                index_key,
                offset,
                offset + limit - 1,
            )

            if not message_ids:
                return []

            # Fetch messages
            messages = []
            for msg_id in message_ids:
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")

                message = await self.get_message(msg_id)
                if message:
                    # Apply filters
                    if status and message.status != status:
                        continue
                    if routing_key_pattern:
                        import fnmatch
                        if not fnmatch.fnmatch(message.routing_key, routing_key_pattern):
                            continue
                    messages.append(message)

            return messages

        except redis.RedisError as e:
            logger.error(f"[DLQ] Failed to get messages: {e}")
            return []

    async def retry_message(self, message_id: str) -> bool:
        """Retry a DLQ message."""
        message = await self.get_message(message_id)
        if not message:
            raise DLQMessageNotFoundError(message_id)

        if not message.can_retry:
            raise DLQRetryError(
                message_id,
                f"Cannot retry: status={message.status}, retries={message.retry_count}/{message.max_retries}",
            )

        try:
            # Update status to retrying
            message.status = DLQMessageStatus.RETRYING
            message.retry_count += 1
            message.last_failed_at = datetime.now(timezone.utc)

            await self._update_message(message)

            # Attempt to republish
            if self._event_bus:
                try:
                    # Deserialize event data
                    envelope = EventEnvelope.from_json(message.event_data)
                    await self._event_bus.publish(envelope, message.routing_key)

                    # Success - mark as resolved
                    message.status = DLQMessageStatus.RESOLVED
                    await self._update_message(message)
                    await self._update_stats_on_resolve(message)

                    logger.info(f"[DLQ] Message {message_id} retried successfully")
                    return True

                except Exception as e:
                    # Retry failed - update message with new error
                    message.status = DLQMessageStatus.PENDING
                    message.error = str(e)
                    message.error_traceback = traceback.format_exc()

                    # Calculate next retry time
                    if message.retry_count < message.max_retries:
                        delay = self.RETRY_DELAYS[
                            min(message.retry_count, len(self.RETRY_DELAYS) - 1)
                        ]
                        message.next_retry_at = datetime.fromtimestamp(
                            datetime.now(timezone.utc).timestamp() + delay,
                            tz=timezone.utc,
                        )
                    else:
                        message.next_retry_at = None

                    await self._update_message(message)

                    logger.warning(
                        f"[DLQ] Retry failed for {message_id}: {e}"
                    )
                    return False
            else:
                # No event bus configured
                logger.warning(
                    f"[DLQ] Cannot retry {message_id}: no event bus configured"
                )
                message.status = DLQMessageStatus.PENDING
                await self._update_message(message)
                return False

        except DLQError:
            raise
        except Exception as e:
            logger.error(f"[DLQ] Error retrying {message_id}: {e}")
            raise DLQRetryError(message_id, str(e)) from e

    async def retry_batch(
        self,
        message_ids: List[str],
    ) -> Dict[str, bool]:
        """Retry multiple DLQ messages."""
        results = {}
        for msg_id in message_ids:
            try:
                results[msg_id] = await self.retry_message(msg_id)
            except (DLQMessageNotFoundError, DLQRetryError) as e:
                logger.warning(f"[DLQ] Batch retry failed for {msg_id}: {e}")
                results[msg_id] = False
        return results

    async def discard_message(
        self,
        message_id: str,
        reason: str,
    ) -> bool:
        """Discard a DLQ message."""
        message = await self.get_message(message_id)
        if not message:
            raise DLQMessageNotFoundError(message_id)

        try:
            message.status = DLQMessageStatus.DISCARDED
            message.metadata["discard_reason"] = reason
            message.metadata["discarded_at"] = datetime.now(timezone.utc).isoformat()

            await self._update_message(message)
            await self._update_stats_on_discard(message)

            logger.info(f"[DLQ] Message {message_id} discarded: {reason}")
            return True

        except Exception as e:
            logger.error(f"[DLQ] Error discarding {message_id}: {e}")
            return False

    async def discard_batch(
        self,
        message_ids: List[str],
        reason: str,
    ) -> Dict[str, bool]:
        """Discard multiple DLQ messages."""
        results = {}
        for msg_id in message_ids:
            try:
                results[msg_id] = await self.discard_message(msg_id, reason)
            except DLQMessageNotFoundError:
                results[msg_id] = False
        return results

    async def get_stats(self) -> DLQStats:
        """Get DLQ statistics."""
        try:
            stats_data = await self._redis.hgetall(self.STATS_KEY)

            # Decode and parse stats
            decoded = {}
            for k, v in stats_data.items():
                key = k.decode("utf-8") if isinstance(k, bytes) else k
                val = int(v.decode("utf-8") if isinstance(v, bytes) else v)
                decoded[key] = val

            # Extract error and event type counts
            error_counts = {}
            event_counts = {}
            for key, val in decoded.items():
                if key.startswith("error:"):
                    error_counts[key[6:]] = val
                elif key.startswith("event:"):
                    event_counts[key[6:]] = val

            # Get oldest message age
            oldest_timestamp = await self._redis.zrange(
                self.PENDING_INDEX, 0, 0, withscores=True
            )
            oldest_age = 0.0
            if oldest_timestamp:
                _, score = oldest_timestamp[0]
                oldest_age = datetime.now(timezone.utc).timestamp() - score

            return DLQStats(
                total_messages=decoded.get("total_messages", 0),
                pending_count=decoded.get("pending_count", 0),
                retrying_count=decoded.get("retrying_count", 0),
                discarded_count=decoded.get("discarded_count", 0),
                expired_count=decoded.get("expired_count", 0),
                resolved_count=decoded.get("resolved_count", 0),
                oldest_message_age=oldest_age,
                error_type_counts=error_counts,
                event_type_counts=event_counts,
            )

        except redis.RedisError as e:
            logger.error(f"[DLQ] Failed to get stats: {e}")
            return DLQStats()

    async def cleanup_expired(
        self,
        older_than_hours: int = 168,
    ) -> int:
        """Clean up expired DLQ messages."""
        cutoff = datetime.now(timezone.utc).timestamp() - (older_than_hours * 3600)

        try:
            # Get expired message IDs
            expired_ids = await self._redis.zrangebyscore(
                self.PENDING_INDEX,
                "-inf",
                cutoff,
            )

            if not expired_ids:
                return 0

            count = 0
            for msg_id in expired_ids:
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")

                message = await self.get_message(msg_id)
                if message:
                    message.status = DLQMessageStatus.EXPIRED
                    await self._update_message(message)
                    await self._remove_from_indexes(message)
                    count += 1

            # Update stats
            if count > 0:
                await self._redis.hincrby(self.STATS_KEY, "pending_count", -count)
                await self._redis.hincrby(self.STATS_KEY, "expired_count", count)

            logger.info(f"[DLQ] Cleaned up {count} expired messages")
            return count

        except redis.RedisError as e:
            logger.error(f"[DLQ] Cleanup failed: {e}")
            return 0

    async def cleanup_resolved(
        self,
        older_than_hours: int = 24,
    ) -> int:
        """Clean up resolved DLQ messages."""
        # For resolved messages, we can delete them entirely
        # This is a simplified implementation
        return 0  # TODO: Implement full resolved cleanup

    async def _update_message(self, message: DeadLetterMessage) -> None:
        """Update a message in Redis."""
        message_key = self._message_key(message.id)
        await self._redis.hset(message_key, "data", json.dumps(message.to_dict()))

    async def _remove_from_indexes(self, message: DeadLetterMessage) -> None:
        """Remove a message from all indexes."""
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.zrem(self.PENDING_INDEX, message.id)
            pipe.zrem(self._error_type_index_key(message.error_type), message.id)
            pipe.zrem(self._event_type_index_key(message.event_type), message.id)
            await pipe.execute()

    async def _update_stats_on_resolve(self, message: DeadLetterMessage) -> None:
        """Update stats when a message is resolved."""
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hincrby(self.STATS_KEY, "pending_count", -1)
            pipe.hincrby(self.STATS_KEY, "resolved_count", 1)
            await pipe.execute()
        await self._remove_from_indexes(message)

    async def _update_stats_on_discard(self, message: DeadLetterMessage) -> None:
        """Update stats when a message is discarded."""
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hincrby(self.STATS_KEY, "pending_count", -1)
            pipe.hincrby(self.STATS_KEY, "discarded_count", 1)
            await pipe.execute()
        await self._remove_from_indexes(message)
