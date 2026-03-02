"""Global connection limiter for MCP connection pools.

Enforces a process-wide file descriptor limit across all MCPConnectionPool
instances. Under high concurrency with many MCP servers, individual per-pool
semaphores are insufficient to prevent file descriptor exhaustion. This module
provides a singleton limiter that coordinates across all pools.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default limits
_DEFAULT_MAX_CONNECTIONS = 100
_DEFAULT_TTL = 300.0  # 5 minutes


@dataclass
class _ConnectionEntry:
    """Tracks a single connection slot in the global limiter."""

    created_at: float
    last_used: float


class GlobalConnectionLimiter:
    """Process-wide connection limiter for MCP WebSocket pools.

    Enforces a global maximum on the total number of active MCP connections
    across all pool instances. When the limit is reached and a new connection
    is needed, the limiter attempts LRU eviction of idle connections from
    other pools before blocking.

    This class should NOT be instantiated directly. Use ``get_global_limiter()``
    to obtain the singleton instance.

    Attributes:
        _max_connections: Global maximum concurrent connections.
        _semaphore: Asyncio semaphore enforcing the global limit.
        _active_connections: Per-pool tracking of connection entries.
        _ttl: Maximum age (seconds) before a connection is eligible for eviction.
        _lock: Async lock for thread-safe bookkeeping.
        _evict_callbacks: Per-pool callbacks to evict one idle connection.
    """

    def __init__(
        self,
        max_connections: int = _DEFAULT_MAX_CONNECTIONS,
        ttl: float = _DEFAULT_TTL,
    ) -> None:
        """Initialize the global connection limiter.

        Args:
            max_connections: Maximum total concurrent connections across all pools.
            ttl: Maximum age in seconds before a connection is eligible for eviction.
        """
        self._max_connections = max_connections
        self._ttl = ttl
        self._semaphore = asyncio.Semaphore(max_connections)
        self._active_connections: dict[str, list[_ConnectionEntry]] = {}
        self._lock = asyncio.Lock()
        self._evict_callbacks: dict[str, Callable[[], Awaitable[bool]]] = {}

    @property
    def max_connections(self) -> int:
        """Global maximum concurrent connections."""
        return self._max_connections

    @property
    def active_count(self) -> int:
        """Total number of active connections across all pools."""
        return sum(len(entries) for entries in self._active_connections.values())

    def register_pool(
        self,
        pool_url: str,
        evict_callback: Callable[[], Awaitable[bool]],
    ) -> None:
        """Register a pool's eviction callback.

        Args:
            pool_url: Unique identifier for the pool (typically the WebSocket URL).
            evict_callback: Async callable that evicts one idle connection from
                the pool. Returns True if a connection was successfully evicted.
        """
        self._evict_callbacks[pool_url] = evict_callback
        if pool_url not in self._active_connections:
            self._active_connections[pool_url] = []
        logger.debug(f"Registered pool: {pool_url}")

    def unregister_pool(self, pool_url: str) -> None:
        """Unregister a pool and remove its tracking data.

        Args:
            pool_url: Unique identifier for the pool to unregister.
        """
        _ = self._evict_callbacks.pop(pool_url, None)
        _ = self._active_connections.pop(pool_url, None)
        logger.debug(f"Unregistered pool: {pool_url}")

    async def acquire(self, pool_url: str) -> None:
        """Acquire a global connection slot for a pool.

        If the semaphore would block (global limit reached), first attempts
        LRU eviction of idle connections from OTHER pools to free a slot.

        Args:
            pool_url: Identifier of the pool requesting a connection slot.
        """
        # Fast path: try non-blocking acquire
        acquired = self._semaphore._value > 0
        if not acquired:
            # Global limit reached -- try to evict an idle connection
            logger.debug(
                "Global limit reached (%d), attempting LRU eviction for %s",
                self._max_connections,
                pool_url,
            )
            evicted = await self.try_evict_lru(exclude_pool=pool_url)
            if evicted:
                logger.debug("LRU eviction freed a slot")

        _ = await self._semaphore.acquire()

        async with self._lock:
            now = time.monotonic()
            if pool_url not in self._active_connections:
                self._active_connections[pool_url] = []
            self._active_connections[pool_url].append(
                _ConnectionEntry(created_at=now, last_used=now)
            )
        logger.debug(
            "Global slot acquired for %s (active: %d/%d)",
            pool_url,
            self.active_count,
            self._max_connections,
        )

    async def release(self, pool_url: str) -> None:
        """Release a global connection slot for a pool.

        Args:
            pool_url: Identifier of the pool releasing a connection slot.
        """
        async with self._lock:
            entries = self._active_connections.get(pool_url, [])
            if entries:
                _ = entries.pop()
                if not entries:
                    _ = self._active_connections.pop(pool_url, None)

        self._semaphore.release()
        logger.debug(
            "Global slot released for %s (active: %d/%d)",
            pool_url,
            self.active_count,
            self._max_connections,
        )

    async def try_evict_lru(self, exclude_pool: str | None = None) -> bool:
        """Find and evict the least-recently-used idle connection across all pools.

        Iterates all registered pools (excluding ``exclude_pool``) and invokes
        the eviction callback on the pool with the oldest ``last_used`` entry.

        Args:
            exclude_pool: Pool URL to exclude from eviction consideration.

        Returns:
            True if a connection was successfully evicted, False otherwise.
        """
        oldest_time: float | None = None
        oldest_pool: str | None = None

        async with self._lock:
            for pool_url, entries in self._active_connections.items():
                if pool_url == exclude_pool:
                    continue
                if not entries:
                    continue
                # Find the oldest entry in this pool
                min_entry = min(entries, key=lambda e: e.last_used)
                if oldest_time is None or min_entry.last_used < oldest_time:
                    oldest_time = min_entry.last_used
                    oldest_pool = pool_url

        if oldest_pool is None:
            logger.debug("No eligible connections to evict")
            return False

        callback = self._evict_callbacks.get(oldest_pool)
        if callback is None:
            logger.debug(f"No eviction callback for pool {oldest_pool}")
            return False

        try:
            evicted = await callback()
            if evicted:
                logger.debug(f"Evicted idle connection from pool {oldest_pool}")
            return evicted
        except Exception as e:
            logger.warning(f"Error during LRU eviction from {oldest_pool}: {e}")
            return False

    async def evict_idle(self) -> int:
        """Evict connections that exceed TTL across all pools.

        Iterates all pools and invokes their eviction callbacks for each
        connection that has exceeded the configured TTL.

        Returns:
            Total number of connections evicted.
        """
        now = time.monotonic()
        evicted_count = 0

        # Collect pools with expired entries
        pools_to_evict: list[str] = []
        async with self._lock:
            for pool_url, entries in self._active_connections.items():
                for entry in entries:
                    if (now - entry.created_at) > self._ttl:
                        pools_to_evict.append(pool_url)
                        break

        for pool_url in pools_to_evict:
            callback = self._evict_callbacks.get(pool_url)
            if callback is None:
                continue
            try:
                evicted = await callback()
                if evicted:
                    evicted_count += 1
            except Exception as e:
                logger.warning(f"Error evicting idle connection from {pool_url}: {e}")

        if evicted_count > 0:
            logger.info(f"Evicted {evicted_count} idle connections exceeding TTL")
        return evicted_count


# Module-level singleton
_global_limiter: GlobalConnectionLimiter | None = None


def get_global_limiter(
    max_connections: int = _DEFAULT_MAX_CONNECTIONS,
    ttl: float = _DEFAULT_TTL,
) -> GlobalConnectionLimiter:
    """Get or create the global connection limiter singleton.

    On first call, creates the limiter with the provided parameters.
    Subsequent calls return the same instance (parameters are ignored).

    Args:
        max_connections: Maximum total concurrent connections (first call only).
        ttl: Connection TTL in seconds (first call only).

    Returns:
        The singleton GlobalConnectionLimiter instance.
    """
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = GlobalConnectionLimiter(
            max_connections=max_connections,
            ttl=ttl,
        )
        logger.info(f"Initialized global connection limiter: max={max_connections}, ttl={ttl}s")
    return _global_limiter
