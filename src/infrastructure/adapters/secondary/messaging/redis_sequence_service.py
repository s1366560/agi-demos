"""
Redis-based atomic sequence number generator.

This service provides atomic sequence number generation using Redis INCR,
eliminating race conditions that occur with read-then-write patterns.

Usage:
    sequence_service = RedisSequenceService(redis_client)
    next_seq = await sequence_service.get_next_sequence(conversation_id)
"""

import logging
from typing import cast

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisSequenceService:
    """
    Redis-based atomic sequence number generator.

    Uses Redis INCR for lock-free atomic sequence generation.
    Each conversation has its own sequence counter.
    """

    SEQUENCE_KEY_PREFIX = "event_seq:"
    SEQUENCE_TTL = 86400 * 7  # 7 days

    def __init__(self, redis_client: redis.Redis) -> None:
        """
        Initialize the Redis sequence service.

        Args:
            redis_client: Async Redis client
        """
        self._redis = redis_client

    def _get_sequence_key(self, conversation_id: str) -> str:
        """Get the Redis key for a conversation's sequence counter."""
        return f"{self.SEQUENCE_KEY_PREFIX}{conversation_id}"

    async def get_next_sequence(self, conversation_id: str) -> int:
        """
        Get the next sequence number atomically using Redis INCR.

        This is thread-safe and handles concurrent requests correctly.

        Args:
            conversation_id: The conversation ID

        Returns:
            The next sequence number (starting from 1)
        """
        key = self._get_sequence_key(conversation_id)

        try:
            # INCR is atomic - no race conditions
            seq = await self._redis.incr(key)

            # Set TTL on first use (INCR creates key if not exists)
            if seq == 1:
                await self._redis.expire(key, self.SEQUENCE_TTL)

            return cast(int, seq)

        except Exception as e:
            logger.error(f"Failed to get next sequence for {conversation_id}: {e}")
            raise

    async def get_current_sequence(self, conversation_id: str) -> int:
        """
        Get the current sequence number without incrementing.

        Args:
            conversation_id: The conversation ID

        Returns:
            The current sequence number (0 if no events yet)
        """
        key = self._get_sequence_key(conversation_id)

        try:
            value = await self._redis.get(key)
            return int(value) if value else 0
        except Exception as e:
            logger.error(f"Failed to get current sequence for {conversation_id}: {e}")
            return 0

    async def sync_from_db(self, conversation_id: str, db_last_seq: int) -> bool:
        """
        Sync Redis sequence from database (for recovery).

        This ensures Redis sequence is at least as high as the DB sequence.
        Uses SET NX to avoid overwriting a higher value.

        Args:
            conversation_id: The conversation ID
            db_last_seq: The last sequence number from database

        Returns:
            True if sync was performed, False if Redis already had higher value
        """
        key = self._get_sequence_key(conversation_id)

        try:
            current = await self.get_current_sequence(conversation_id)

            if db_last_seq > current:
                # Use SETNX pattern: only set if key doesn't exist or use compare-and-swap
                # For simplicity, we use WATCH/MULTI/EXEC for atomicity
                async with self._redis.pipeline(transaction=True) as pipe:
                    try:
                        await pipe.watch(key)
                        current_val = await pipe.get(key)
                        current_int = int(current_val) if current_val else 0

                        if db_last_seq > current_int:
                            pipe.multi()
                            pipe.set(key, db_last_seq)
                            pipe.expire(key, self.SEQUENCE_TTL)
                            await pipe.execute()
                            logger.info(
                                f"Synced sequence for {conversation_id}: {current_int} -> {db_last_seq}"
                            )
                            return True
                    except redis.WatchError:
                        # Another process modified the key, that's fine
                        logger.debug(f"Sequence sync race for {conversation_id}, skipping")

            return False

        except Exception as e:
            logger.error(f"Failed to sync sequence for {conversation_id}: {e}")
            return False

    async def reset_sequence(self, conversation_id: str) -> None:
        """
        Reset the sequence counter for a conversation.

        Warning: This should only be used for testing or cleanup.

        Args:
            conversation_id: The conversation ID
        """
        key = self._get_sequence_key(conversation_id)
        await self._redis.delete(key)
        logger.info(f"Reset sequence for {conversation_id}")

    async def get_batch_sequences(self, conversation_id: str, count: int) -> list[int]:
        """
        Reserve a batch of sequence numbers atomically.

        Useful for bulk event insertion.

        Args:
            conversation_id: The conversation ID
            count: Number of sequences to reserve

        Returns:
            List of reserved sequence numbers
        """
        if count <= 0:
            return []

        key = self._get_sequence_key(conversation_id)

        try:
            # INCRBY is atomic
            end_seq = await self._redis.incrby(key, count)

            # Set TTL if this is the first batch
            if end_seq == count:
                await self._redis.expire(key, self.SEQUENCE_TTL)

            # Calculate the range
            start_seq = end_seq - count + 1
            return list(range(start_seq, end_seq + 1))

        except Exception as e:
            logger.error(f"Failed to get batch sequences for {conversation_id}: {e}")
            raise
