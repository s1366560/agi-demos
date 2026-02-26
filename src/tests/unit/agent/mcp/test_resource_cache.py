"""Tests for MCPResourceCache and ResourceCacheEntry."""

import asyncio
import time

import pytest

from src.infrastructure.mcp.resource_cache import MCPResourceCache, ResourceCacheEntry


@pytest.mark.unit
class TestResourceCacheEntry:
    """Tests for ResourceCacheEntry dataclass."""

    def test_create(self) -> None:
        entry = ResourceCacheEntry(
            content="<html></html>",
            mime_type="text/html",
            fetched_at=time.monotonic(),
        )
        assert entry.content == "<html></html>"
        assert entry.mime_type == "text/html"
        assert entry.ttl_seconds == 60.0

    def test_not_expired(self) -> None:
        entry = ResourceCacheEntry(
            content="data",
            mime_type="text/plain",
            fetched_at=time.monotonic(),
            ttl_seconds=60.0,
        )
        assert entry.is_expired() is False

    def test_expired(self) -> None:
        entry = ResourceCacheEntry(
            content="data",
            mime_type="text/plain",
            fetched_at=time.monotonic() - 120,
            ttl_seconds=60.0,
        )
        assert entry.is_expired() is True


@pytest.mark.unit
class TestMCPResourceCache:
    """Tests for MCPResourceCache."""

    async def test_get_miss(self) -> None:
        cache = MCPResourceCache()
        result = await cache.get("http://example.com/resource")
        assert result is None

    async def test_put_and_get(self) -> None:
        cache = MCPResourceCache()
        await cache.put("uri1", "<html>Hello</html>", "text/html")

        result = await cache.get("uri1")
        assert result == "<html>Hello</html>"

    async def test_get_expired_returns_none(self) -> None:
        cache = MCPResourceCache(default_ttl=0.01)
        await cache.put("uri1", "content")
        await asyncio.sleep(0.02)

        result = await cache.get("uri1")
        assert result is None

    async def test_custom_ttl(self) -> None:
        cache = MCPResourceCache(default_ttl=60.0)
        await cache.put("uri1", "content", ttl=0.01)
        await asyncio.sleep(0.02)

        result = await cache.get("uri1")
        assert result is None

    async def test_invalidate(self) -> None:
        cache = MCPResourceCache()
        await cache.put("uri1", "content")
        await cache.invalidate("uri1")

        result = await cache.get("uri1")
        assert result is None

    async def test_invalidate_nonexistent(self) -> None:
        cache = MCPResourceCache()
        # Should not raise
        await cache.invalidate("nonexistent")

    async def test_lru_eviction(self) -> None:
        cache = MCPResourceCache(max_size=2)
        await cache.put("uri1", "content1")
        await asyncio.sleep(0.001)
        await cache.put("uri2", "content2")
        await asyncio.sleep(0.001)

        # Adding third should evict oldest (uri1)
        await cache.put("uri3", "content3")

        assert await cache.get("uri1") is None
        assert await cache.get("uri2") == "content2"
        assert await cache.get("uri3") == "content3"

    async def test_stats_tracking(self) -> None:
        cache = MCPResourceCache()
        await cache.put("uri1", "content")

        await cache.get("uri1")  # hit
        await cache.get("uri2")  # miss

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1

    async def test_stats_initial(self) -> None:
        cache = MCPResourceCache()
        stats = cache.get_stats()
        assert stats == {"hits": 0, "misses": 0, "size": 0}

    async def test_prefetch(self) -> None:
        cache = MCPResourceCache()

        async def fetcher(uri: str) -> str:
            return f"fetched:{uri}"

        cache.prefetch("http://example.com", fetcher)
        # Allow background task to complete
        await asyncio.sleep(0.05)

        result = await cache.get("http://example.com")
        assert result == "fetched:http://example.com"

    async def test_prefetch_failure_handled(self) -> None:
        cache = MCPResourceCache()

        async def failing_fetcher(uri: str) -> str:
            raise ConnectionError("network error")

        cache.prefetch("http://example.com", failing_fetcher)
        await asyncio.sleep(0.05)

        # Should not have cached anything
        result = await cache.get("http://example.com")
        assert result is None

    async def test_prefetch_empty_content_not_cached(self) -> None:
        cache = MCPResourceCache()

        async def empty_fetcher(uri: str) -> str:
            return ""

        cache.prefetch("http://example.com", empty_fetcher)
        await asyncio.sleep(0.05)

        result = await cache.get("http://example.com")
        assert result is None

    async def test_cleanup_expired(self) -> None:
        cache = MCPResourceCache(default_ttl=0.01)
        await cache.put("uri1", "c1")
        await cache.put("uri2", "c2")
        await asyncio.sleep(0.02)

        removed = await cache.cleanup_expired()
        assert removed == 2
        assert cache.get_stats()["size"] == 0

    async def test_cleanup_expired_partial(self) -> None:
        cache = MCPResourceCache()
        await cache.put("old", "c1", ttl=0.01)
        await asyncio.sleep(0.02)
        await cache.put("fresh", "c2", ttl=60.0)

        removed = await cache.cleanup_expired()
        assert removed == 1
        assert await cache.get("fresh") == "c2"

    async def test_overwrite_existing_key(self) -> None:
        cache = MCPResourceCache(max_size=2)
        await cache.put("uri1", "v1")
        await cache.put("uri1", "v2")

        result = await cache.get("uri1")
        assert result == "v2"
        assert cache.get_stats()["size"] == 1
