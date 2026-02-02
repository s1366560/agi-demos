"""Redis Implementation of Distributed Lock Port.

Provides a Redis-based implementation of the DistributedLockPort interface.
Uses the RedisDistributedLock class for actual locking operations.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from src.domain.ports.services.distributed_lock_port import (
    DistributedLockPort,
    LockAcquisitionError,
    LockHandle,
    LockInfo,
)
from src.infrastructure.adapters.secondary.cache.redis_lock import (
    RedisDistributedLock,
    RedisLockManager,
)


class RedisDistributedLockAdapter(DistributedLockPort):
    """
    Redis-based implementation of DistributedLockPort.

    This adapter wraps the low-level RedisDistributedLock class
    and implements the port interface for use by the application layer.

    Thread Safety:
        Safe for concurrent use. Each acquire() creates a new lock instance.

    Configuration:
        - namespace: Lock key prefix (default: "memstack:lock")
        - default_ttl: Default lock TTL (default: 60 seconds)
        - retry_interval: Time between retry attempts (default: 0.1 seconds)
        - max_retries: Maximum retry attempts (default: 300 = 30 seconds)
    """

    def __init__(
        self,
        redis: Any,
        namespace: str = "memstack:lock",
        default_ttl: int = 60,
        retry_interval: float = 0.1,
        max_retries: int = 300,
    ):
        """
        Initialize the Redis lock adapter.

        Args:
            redis: Async Redis client
            namespace: Key namespace prefix
            default_ttl: Default lock TTL in seconds
            retry_interval: Seconds between acquisition attempts
            max_retries: Maximum acquisition attempts
        """
        self._redis = redis
        self._namespace = namespace
        self._default_ttl = default_ttl
        self._retry_interval = retry_interval
        self._max_retries = max_retries
        self._manager = RedisLockManager(
            redis=redis,
            namespace=namespace,
            default_ttl=default_ttl,
            default_retry_interval=retry_interval,
            default_max_retries=max_retries,
        )
        # Track active locks for cleanup
        self._active_locks: dict[str, RedisDistributedLock] = {}

    async def acquire(
        self,
        key: str,
        ttl: int = 60,
        blocking: bool = True,
        timeout: Optional[float] = None,
    ) -> Optional[LockHandle]:
        """
        Acquire a distributed lock.

        Creates a new RedisDistributedLock and attempts to acquire it.

        Args:
            key: Lock identifier
            ttl: Lock TTL in seconds
            blocking: Whether to block waiting for lock
            timeout: Maximum wait time

        Returns:
            LockHandle if acquired, None otherwise
        """
        lock = self._manager.create_lock(key, ttl=ttl or self._default_ttl)

        try:
            acquired = await lock.acquire(blocking=blocking, timeout=timeout)
            if acquired:
                # Create handle and track the lock
                handle = LockHandle(
                    key=key,
                    owner=lock.owner,
                    acquired_at=time.time(),
                    ttl=ttl,
                )
                # Store lock instance for later release/extend
                self._active_locks[f"{key}:{lock.owner}"] = lock
                return handle
            return None

        except Exception as e:
            raise LockAcquisitionError(f"Failed to acquire lock {key}: {e}") from e

    async def release(self, handle: LockHandle) -> bool:
        """
        Release a distributed lock.

        Args:
            handle: Lock handle from acquire()

        Returns:
            True if released, False otherwise
        """
        lock_key = f"{handle.key}:{handle.owner}"
        lock = self._active_locks.pop(lock_key, None)

        if lock is None:
            # Lock not tracked - try to release anyway using owner token
            # This can happen if the adapter was recreated
            return False

        result = await lock.release()
        return result

    async def extend(self, handle: LockHandle, additional_ttl: Optional[int] = None) -> bool:
        """
        Extend lock TTL.

        Args:
            handle: Lock handle from acquire()
            additional_ttl: New TTL (defaults to original)

        Returns:
            True if extended, False otherwise
        """
        lock_key = f"{handle.key}:{handle.owner}"
        lock = self._active_locks.get(lock_key)

        if lock is None:
            return False

        return await lock.extend(additional_ttl or handle.ttl)

    async def is_locked(self, key: str) -> bool:
        """Check if key is locked."""
        return await self._manager.is_locked(key)

    async def get_lock_info(self, key: str) -> LockInfo:
        """Get information about a lock."""
        full_key = f"{self._namespace}:{key}"
        try:
            owner = await self._redis.get(full_key)
            ttl = await self._redis.ttl(full_key)
            return LockInfo(
                key=key,
                owner=owner,
                ttl_remaining=ttl,
                is_locked=owner is not None,
            )
        except Exception:
            return LockInfo(key=key, is_locked=False)

    async def force_release(self, key: str) -> bool:
        """
        Force release a lock (admin operation).

        WARNING: Use with caution - may cause race conditions.
        """
        return await self._manager.force_release(key)

    async def cleanup(self) -> None:
        """
        Release all locks held by this adapter.

        Should be called during shutdown.
        """
        for lock in list(self._active_locks.values()):
            try:
                await lock.release()
            except Exception:
                pass
        self._active_locks.clear()
