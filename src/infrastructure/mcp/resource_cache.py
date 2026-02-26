"""Dedicated MCP resource caching service.

Extracted from SandboxMCPServerToolAdapter to follow Single Responsibility
Principle. This service handles caching and prefetching of MCP resource
content (typically HTML for UI previews), independent of tool execution.

Can be used by any component that needs to cache previewable MCP resources.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResourceCacheEntry:
    """Single cached resource with metadata.

    Attributes:
        content: The cached content (typically HTML).
        mime_type: MIME type of the content.
        fetched_at: Monotonic timestamp when content was fetched.
        ttl_seconds: Time-to-live in seconds.
    """

    content: str
    mime_type: str
    fetched_at: float
    ttl_seconds: float = 60.0

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return time.monotonic() > self.fetched_at + self.ttl_seconds


class MCPResourceCache:
    """Dedicated service for MCP resource caching and preview generation.

    Separated from tool execution concerns. Provides TTL-based caching
    with LRU eviction, background prefetch, and hit/miss statistics.

    Args:
        max_size: Maximum number of cached entries.
        default_ttl: Default TTL in seconds for new entries.
    """

    def __init__(self, max_size: int = 100, default_ttl: float = 60.0) -> None:
        self._cache: dict[str, ResourceCacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
        self._stats: dict[str, int] = {"hits": 0, "misses": 0}
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def get(self, resource_uri: str) -> str | None:
        """Get cached resource content if available and not expired.

        Args:
            resource_uri: URI of the resource.

        Returns:
            Cached content string, or None if not cached or expired.
        """
        async with self._lock:
            entry = self._cache.get(resource_uri)
            if entry is not None and not entry.is_expired():
                self._stats["hits"] += 1
                return entry.content
            if entry is not None and entry.is_expired():
                del self._cache[resource_uri]
            self._stats["misses"] += 1
            return None

    async def put(
        self,
        resource_uri: str,
        content: str,
        mime_type: str = "text/html",
        ttl: float | None = None,
    ) -> None:
        """Cache a resource with LRU eviction.

        Args:
            resource_uri: URI of the resource.
            content: Content to cache.
            mime_type: MIME type of the content.
            ttl: Optional TTL override (uses default_ttl if None).
        """
        async with self._lock:
            # LRU eviction if at capacity
            if len(self._cache) >= self._max_size and resource_uri not in self._cache:
                oldest_key = min(self._cache, key=lambda k: self._cache[k].fetched_at)
                del self._cache[oldest_key]

            self._cache[resource_uri] = ResourceCacheEntry(
                content=content,
                mime_type=mime_type,
                fetched_at=time.monotonic(),
                ttl_seconds=ttl if ttl is not None else self._default_ttl,
            )

    async def invalidate(self, resource_uri: str) -> None:
        """Remove a specific resource from the cache.

        Args:
            resource_uri: URI to invalidate.
        """
        async with self._lock:
            self._cache.pop(resource_uri, None)

    def prefetch(
        self,
        resource_uri: str,
        fetcher: Callable[[str], Awaitable[str]],
    ) -> None:
        """Start a background prefetch for a resource.

        Non-blocking -- creates a fire-and-forget task.

        Args:
            resource_uri: URI to prefetch.
            fetcher: Async callable that fetches the resource content.
        """

        async def _do_prefetch() -> None:
            try:
                content = await fetcher(resource_uri)
                if content:
                    await self.put(resource_uri, content)
                    logger.debug("Prefetched resource: %s (%d bytes)", resource_uri, len(content))
            except Exception as exc:
                logger.warning("Prefetch failed for %s: %s", resource_uri, exc)

        try:
            task = asyncio.create_task(_do_prefetch())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except RuntimeError:
            pass  # No event loop running

    def get_stats(self) -> dict[str, int]:
        """Return cache statistics.

        Returns:
            Dict with hits, misses, and current size.
        """
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "size": len(self._cache),
        }

    async def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed.
        """
        async with self._lock:
            expired_keys = [k for k, e in self._cache.items() if e.is_expired()]
            for k in expired_keys:
                del self._cache[k]
            return len(expired_keys)
