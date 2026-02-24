"""Redis Distributed Lock Implementation.

Provides a distributed lock mechanism using Redis for cross-process synchronization.
This replaces PostgreSQL advisory locks for better performance and reduced database load.

Features:
- Atomic lock acquisition using SET NX EX
- Automatic expiration to prevent deadlocks
- Lock extension for long-running operations
- Async context manager support
- Safe release with owner verification

Usage:
    async with RedisDistributedLock(redis, "sandbox:project-123", ttl=60) as lock:
        if lock.acquired:
            # Critical section - only one process can be here
            await create_sandbox()
        else:
            # Lock not acquired (timeout)
            raise LockNotAcquiredError()

Or manually:
    lock = RedisDistributedLock(redis, "sandbox:project-123")
    if await lock.acquire():
        try:
            await create_sandbox()
        finally:
            await lock.release()
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from redis.asyncio import Redis


@dataclass
class LockStats:
    """Statistics for lock operations."""

    acquisitions: int = 0
    releases: int = 0
    extensions: int = 0
    failures: int = 0
    timeouts: int = 0


class RedisDistributedLock:
    """
    Distributed lock implementation using Redis.

    Uses the SET NX EX pattern for atomic lock acquisition with automatic expiration.
    Each lock has a unique owner token to ensure only the lock holder can release it.

    Thread Safety:
        This class is safe for concurrent use within a single process.
        The lock provides cross-process safety via Redis.

    Lock Semantics:
        - Non-reentrant: Same process cannot acquire the same lock twice
        - Auto-expire: Lock automatically releases after TTL to prevent deadlocks
        - Owner verification: Only the lock holder can release or extend

    Attributes:
        redis: Redis client instance
        key: Lock key in Redis
        ttl: Time-to-live in seconds
        owner: Unique token identifying this lock holder
        acquired: Whether lock is currently held
    """

    # Global stats for monitoring
    _stats = LockStats()

    def __init__(
        self,
        redis: Redis,
        key: str,
        ttl: int = 60,
        retry_interval: float = 0.1,
        max_retries: int = 300,
        namespace: str = "memstack:lock",
    ) -> None:
        """
        Initialize a distributed lock.

        Args:
            redis: Redis client (async redis-py)
            key: Lock identifier (will be prefixed with namespace)
            ttl: Lock TTL in seconds (auto-release if not released)
            retry_interval: Seconds between acquisition attempts
            max_retries: Maximum number of acquisition attempts (0 for single try)
            namespace: Key namespace prefix
        """
        self._redis = redis
        self._key = f"{namespace}:{key}"
        self._ttl = ttl
        self._retry_interval = retry_interval
        self._max_retries = max_retries
        self._owner = secrets.token_hex(16)  # Unique owner token
        self._acquired = False
        self._acquired_at: float | None = None

    @property
    def key(self) -> str:
        """Get the full Redis key for this lock."""
        return self._key

    @property
    def acquired(self) -> bool:
        """Check if lock is currently held by this instance."""
        return self._acquired

    @property
    def owner(self) -> str:
        """Get the owner token for this lock."""
        return self._owner

    async def acquire(self, blocking: bool = True, timeout: float | None = None) -> bool:
        """
        Acquire the lock.

        Args:
            blocking: If True, retry until acquired or timeout
            timeout: Maximum time to wait (None = use max_retries * retry_interval)

        Returns:
            True if lock acquired, False otherwise
        """
        if self._acquired:
            logger.warning(f"Lock {self._key} already held by this instance")
            return True

        start_time = time.time()
        max_wait = timeout if timeout is not None else (self._max_retries * self._retry_interval)
        attempts = 0

        while True:
            try:
                # SET key owner NX EX ttl
                # NX: Only set if not exists
                # EX: Set expiration in seconds
                result = await self._redis.set(
                    self._key,
                    self._owner,
                    nx=True,
                    ex=self._ttl,
                )

                if result:
                    self._acquired = True
                    self._acquired_at = time.time()
                    RedisDistributedLock._stats.acquisitions += 1
                    logger.debug(
                        f"Lock acquired: {self._key} (owner={self._owner[:8]}..., ttl={self._ttl}s)"
                    )
                    return True

                # Lock held by another process
                if not blocking:
                    RedisDistributedLock._stats.failures += 1
                    return False

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed >= max_wait:
                    RedisDistributedLock._stats.timeouts += 1
                    logger.warning(f"Lock acquisition timeout: {self._key} after {elapsed:.1f}s")
                    return False

                attempts += 1
                if attempts >= self._max_retries > 0:
                    RedisDistributedLock._stats.timeouts += 1
                    logger.warning(
                        f"Lock acquisition max retries: {self._key} after {attempts} attempts"
                    )
                    return False

                # Wait before retry
                await asyncio.sleep(self._retry_interval)

            except Exception as e:
                logger.error(f"Error acquiring lock {self._key}: {e}")
                RedisDistributedLock._stats.failures += 1
                return False

    async def release(self) -> bool:
        """
        Release the lock.

        Uses a Lua script to atomically verify ownership and delete.
        Only the lock holder can release the lock.

        Returns:
            True if released, False if not held or error
        """
        if not self._acquired:
            logger.warning(f"Attempting to release non-acquired lock: {self._key}")
            return False

        # Lua script for atomic check-and-delete
        # Only delete if the value matches our owner token
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
        """

        try:
            result = await self._redis.eval(lua_script, 1, self._key, self._owner)
            if result:
                self._acquired = False
                self._acquired_at = None
                RedisDistributedLock._stats.releases += 1
                logger.debug(f"Lock released: {self._key}")
                return True
            else:
                # Lock was taken by another process (expired and re-acquired)
                logger.warning(
                    f"Lock release failed - not owner: {self._key} (our owner={self._owner[:8]}...)"
                )
                self._acquired = False
                self._acquired_at = None
                return False

        except Exception as e:
            logger.error(f"Error releasing lock {self._key}: {e}")
            self._acquired = False
            self._acquired_at = None
            return False

    async def extend(self, additional_ttl: int | None = None) -> bool:
        """
        Extend the lock TTL.

        Useful for long-running operations to prevent lock expiration.
        Only the lock holder can extend.

        Args:
            additional_ttl: New TTL in seconds (defaults to original TTL)

        Returns:
            True if extended, False if not held or error
        """
        if not self._acquired:
            logger.warning(f"Attempting to extend non-acquired lock: {self._key}")
            return False

        ttl = additional_ttl or self._ttl

        # Lua script for atomic check-and-extend
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("EXPIRE", KEYS[1], ARGV[2])
        else
            return 0
        end
        """

        try:
            result = await self._redis.eval(lua_script, 1, self._key, self._owner, ttl)
            if result:
                RedisDistributedLock._stats.extensions += 1
                logger.debug(f"Lock extended: {self._key} (new ttl={ttl}s)")
                return True
            else:
                logger.warning(f"Lock extend failed - not owner: {self._key}")
                self._acquired = False
                return False

        except Exception as e:
            logger.error(f"Error extending lock {self._key}: {e}")
            return False

    async def is_locked(self) -> bool:
        """
        Check if the lock is currently held by any process.

        Returns:
            True if locked, False if available
        """
        try:
            value = await self._redis.get(self._key)
            return value is not None
        except Exception as e:
            logger.error(f"Error checking lock status {self._key}: {e}")
            return False

    async def get_owner(self) -> str | None:
        """
        Get the current lock owner.

        Returns:
            Owner token if locked, None if not
        """
        try:
            return await self._redis.get(self._key)
        except Exception as e:
            logger.error(f"Error getting lock owner {self._key}: {e}")
            return None

    async def time_remaining(self) -> int:
        """
        Get remaining TTL in seconds.

        Returns:
            TTL in seconds, -1 if no expiry, -2 if not exists
        """
        try:
            return await self._redis.ttl(self._key)
        except Exception as e:
            logger.error(f"Error getting lock TTL {self._key}: {e}")
            return -2

    async def __aenter__(self) -> RedisDistributedLock:
        """Async context manager entry - acquire lock."""
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit - release lock."""
        if self._acquired:
            await self.release()

    @classmethod
    def get_stats(cls) -> LockStats:
        """Get global lock statistics."""
        return cls._stats

    @classmethod
    def reset_stats(cls) -> None:
        """Reset global lock statistics."""
        cls._stats = LockStats()


class RedisLockManager:
    """
    Manager for creating and managing Redis distributed locks.

    Provides a factory method for creating locks with consistent configuration.
    Can be used as a dependency injection point.

    Usage:
        manager = RedisLockManager(redis_client, namespace="sandbox")
        async with manager.lock("project-123") as lock:
            if lock.acquired:
                # Critical section
                pass
    """

    def __init__(
        self,
        redis: Redis,
        namespace: str = "memstack:lock",
        default_ttl: int = 60,
        default_retry_interval: float = 0.1,
        default_max_retries: int = 300,
    ) -> None:
        """
        Initialize the lock manager.

        Args:
            redis: Redis client
            namespace: Default namespace for lock keys
            default_ttl: Default TTL for locks
            default_retry_interval: Default retry interval
            default_max_retries: Default max retries
        """
        self._redis = redis
        self._namespace = namespace
        self._default_ttl = default_ttl
        self._default_retry_interval = default_retry_interval
        self._default_max_retries = default_max_retries

    def create_lock(
        self,
        key: str,
        ttl: int | None = None,
        retry_interval: float | None = None,
        max_retries: int | None = None,
    ) -> RedisDistributedLock:
        """
        Create a new distributed lock.

        Args:
            key: Lock identifier
            ttl: Optional TTL override
            retry_interval: Optional retry interval override
            max_retries: Optional max retries override

        Returns:
            RedisDistributedLock instance
        """
        return RedisDistributedLock(
            redis=self._redis,
            key=key,
            ttl=ttl or self._default_ttl,
            retry_interval=retry_interval or self._default_retry_interval,
            max_retries=max_retries or self._default_max_retries,
            namespace=self._namespace,
        )

    @asynccontextmanager
    async def lock(
        self,
        key: str,
        ttl: int | None = None,
        blocking: bool = True,
        timeout: float | None = None,
    ) -> AsyncGenerator[RedisDistributedLock, None]:
        """
        Context manager for acquiring a lock.

        Args:
            key: Lock identifier
            ttl: Optional TTL override
            blocking: Whether to block waiting for lock
            timeout: Maximum wait time

        Yields:
            RedisDistributedLock (check .acquired to verify)
        """
        lock = self.create_lock(key, ttl=ttl)
        try:
            await lock.acquire(blocking=blocking, timeout=timeout)
            yield lock
        finally:
            if lock.acquired:
                await lock.release()

    async def is_locked(self, key: str) -> bool:
        """Check if a key is currently locked."""
        full_key = f"{self._namespace}:{key}"
        try:
            value = await self._redis.get(full_key)
            return value is not None
        except Exception:
            return False

    async def force_release(self, key: str) -> bool:
        """
        Force release a lock (admin operation).

        WARNING: This should only be used for recovery from stuck locks.
        It may cause race conditions if the original holder is still active.

        Args:
            key: Lock identifier

        Returns:
            True if deleted, False if not exists or error
        """
        full_key = f"{self._namespace}:{key}"
        try:
            result = await self._redis.delete(full_key)
            if result:
                logger.warning(f"Force released lock: {full_key}")
            return bool(result)
        except Exception as e:
            logger.error(f"Error force releasing lock {full_key}: {e}")
            return False
