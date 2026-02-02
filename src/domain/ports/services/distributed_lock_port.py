"""Distributed Lock Port Interface.

Defines the abstract interface for distributed locking mechanisms.
This follows the Hexagonal Architecture pattern - the domain/application layer
depends on this port, while infrastructure provides concrete implementations.

Implementations:
- RedisDistributedLock: Uses Redis SET NX EX for distributed locking
- (Future) PostgresAdvisoryLock: Fallback using PostgreSQL advisory locks
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator, Optional


@dataclass(frozen=True)
class LockInfo:
    """Information about a lock."""

    key: str
    owner: Optional[str] = None
    ttl_remaining: int = -2  # -2 = not exists, -1 = no expiry, >= 0 = seconds
    is_locked: bool = False


class DistributedLockPort(ABC):
    """
    Abstract interface for distributed locking.

    This port defines the contract for distributed lock implementations.
    The application layer uses this interface without knowing the underlying
    implementation (Redis, PostgreSQL, etc.).

    Lock Semantics:
        - Locks are identified by a string key
        - Locks have automatic expiration (TTL) to prevent deadlocks
        - Only the lock holder can release or extend the lock
        - Locks are non-reentrant by default

    Usage:
        # Via context manager (recommended)
        async with lock_port.acquire_lock("resource-id") as lock:
            if lock.acquired:
                # Critical section
                await do_work()

        # Manual acquire/release
        lock = await lock_port.try_acquire("resource-id")
        if lock:
            try:
                await do_work()
            finally:
                await lock_port.release(lock)
    """

    @abstractmethod
    async def acquire(
        self,
        key: str,
        ttl: int = 60,
        blocking: bool = True,
        timeout: Optional[float] = None,
    ) -> Optional[LockHandle]:
        """
        Acquire a distributed lock.

        Args:
            key: Lock identifier (unique within the lock namespace)
            ttl: Lock TTL in seconds (auto-release if not released)
            blocking: If True, wait until lock acquired or timeout
            timeout: Maximum wait time in seconds (None = default based on config)

        Returns:
            LockHandle if acquired, None if not acquired (timeout or non-blocking)

        Raises:
            LockError: If there's an infrastructure error
        """
        pass

    @abstractmethod
    async def release(self, handle: LockHandle) -> bool:
        """
        Release a distributed lock.

        Only the lock holder (matching handle) can release the lock.

        Args:
            handle: Lock handle returned from acquire()

        Returns:
            True if released, False if not held or already released
        """
        pass

    @abstractmethod
    async def extend(self, handle: LockHandle, additional_ttl: Optional[int] = None) -> bool:
        """
        Extend the lock TTL.

        Useful for long-running operations to prevent lock expiration.

        Args:
            handle: Lock handle returned from acquire()
            additional_ttl: New TTL in seconds (None = use original TTL)

        Returns:
            True if extended, False if not held
        """
        pass

    @abstractmethod
    async def is_locked(self, key: str) -> bool:
        """
        Check if a key is currently locked by any process.

        Args:
            key: Lock identifier

        Returns:
            True if locked, False if available
        """
        pass

    @abstractmethod
    async def get_lock_info(self, key: str) -> LockInfo:
        """
        Get information about a lock.

        Args:
            key: Lock identifier

        Returns:
            LockInfo with current lock state
        """
        pass

    @asynccontextmanager
    async def acquire_lock(
        self,
        key: str,
        ttl: int = 60,
        blocking: bool = True,
        timeout: Optional[float] = None,
    ) -> AsyncGenerator["AcquiredLock", None]:
        """
        Context manager for acquiring a lock.

        This is the recommended way to use locks as it ensures
        proper cleanup on exit.

        Args:
            key: Lock identifier
            ttl: Lock TTL in seconds
            blocking: Whether to block waiting for lock
            timeout: Maximum wait time

        Yields:
            AcquiredLock with acquired status and handle

        Example:
            async with lock_port.acquire_lock("my-resource") as lock:
                if lock.acquired:
                    # Safe to proceed
                    pass
                else:
                    # Handle lock not acquired
                    raise TimeoutError("Could not acquire lock")
        """
        handle = await self.acquire(key, ttl=ttl, blocking=blocking, timeout=timeout)
        acquired_lock = AcquiredLock(
            acquired=handle is not None,
            handle=handle,
            key=key,
        )
        try:
            yield acquired_lock
        finally:
            if handle:
                await self.release(handle)


@dataclass
class LockHandle:
    """
    Handle representing an acquired lock.

    This is returned from acquire() and must be passed to release()/extend().
    The handle contains the owner token needed to verify lock ownership.
    """

    key: str
    owner: str
    acquired_at: float
    ttl: int

    def __str__(self) -> str:
        return f"LockHandle(key={self.key}, owner={self.owner[:8]}...)"


@dataclass
class AcquiredLock:
    """
    Result of a lock acquisition attempt via context manager.

    Attributes:
        acquired: Whether the lock was successfully acquired
        handle: Lock handle if acquired, None otherwise
        key: The lock key that was requested
    """

    acquired: bool
    handle: Optional[LockHandle]
    key: str

    def __bool__(self) -> bool:
        """Allow using AcquiredLock in boolean context."""
        return self.acquired


class LockError(Exception):
    """Base exception for lock-related errors."""

    pass


class LockAcquisitionError(LockError):
    """Raised when lock acquisition fails due to an error (not timeout)."""

    pass


class LockReleaseError(LockError):
    """Raised when lock release fails."""

    pass
