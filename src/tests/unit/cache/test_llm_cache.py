"""Unit tests for the multi-level LLM response cache."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.cache import llm_cache as cache_module
from src.infrastructure.cache.llm_cache import LLMCache


@pytest.fixture(autouse=True)
def reset_global_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the process-wide cache singleton isolated between tests."""
    monkeypatch.setattr(cache_module, "_llm_cache", None)


@pytest.fixture
def redis_client() -> AsyncMock:
    """Return an isolated async Redis client double."""
    return AsyncMock()


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch, redis_client: AsyncMock) -> LLMCache:
    """Create a cache without opening a real Redis connection."""
    import redis.asyncio as redis

    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: redis_client)
    monkeypatch.setattr(
        cache_module,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://cache.test:6379/0"),
    )
    return LLMCache(l1_size=10, l1_ttl=60, l2_ttl=120)


def test_init_configures_redis_client(
    monkeypatch: pytest.MonkeyPatch,
    redis_client: AsyncMock,
) -> None:
    """The Redis client should use the configured URL and decoded strings."""
    import redis.asyncio as redis

    from_url = Mock(return_value=redis_client)
    monkeypatch.setattr(redis, "from_url", from_url)
    monkeypatch.setattr(
        cache_module,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://configured.test:6380/2"),
    )

    result = LLMCache()

    assert result._redis_client is redis_client
    from_url.assert_called_once_with(
        "redis://configured.test:6380/2",
        encoding="utf-8",
        decode_responses=True,
    )


def test_init_disables_l2_when_redis_import_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing optional Redis support should leave the in-memory cache usable."""
    real_import = builtins.__import__

    def import_without_redis(name: str, *args: object, **kwargs: object) -> object:
        if name == "redis.asyncio":
            raise ImportError("redis unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_redis)

    result = LLMCache()

    assert result._redis_client is None


def test_init_disables_l2_when_client_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis configuration failure should not prevent L1 construction."""
    import redis.asyncio as redis

    monkeypatch.setattr(
        redis, "from_url", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bad URL"))
    )
    monkeypatch.setattr(
        cache_module,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://bad"),
    )

    result = LLMCache()

    assert result._redis_client is None


def test_generate_cache_key_is_stable_for_mapping_order(cache: LLMCache) -> None:
    """Equivalent message and option mappings should produce one cache key."""
    first = cache._generate_cache_key(
        "model-a",
        [{"role": "user", "content": "hello"}],
        temperature=0.2,
        response_format={"type": "json", "strict": True},
    )
    second = cache._generate_cache_key(
        "model-a",
        [{"content": "hello", "role": "user"}],
        response_format={"strict": True, "type": "json"},
        temperature=0.2,
    )

    assert first == second
    assert first.startswith("llm:model-a:")
    assert len(first.rsplit(":", maxsplit=1)[-1]) == 16
    assert first != cache._generate_cache_key("model-b", "hello")


def test_expiration_uses_ttl_boundary(cache: LLMCache) -> None:
    """Recent entries remain valid while older entries expire."""
    now = datetime.now(UTC)

    assert cache._is_expired(now - timedelta(seconds=5), ttl=60) is False
    assert cache._is_expired(now - timedelta(seconds=61), ttl=60) is True


def test_l1_eviction_removes_oldest_entries(cache: LLMCache) -> None:
    """Eviction should remove the oldest ten percent after crossing the limit."""
    cache._l1_size = 10
    base = datetime.now(UTC)
    for index in range(11):
        cache._l1_cache[f"key-{index}"] = (str(index), base + timedelta(seconds=index))

    cache._evict_l1_if_needed()

    assert len(cache._l1_cache) == 10
    assert "key-0" not in cache._l1_cache


async def test_l1_hit_refreshes_recency_before_eviction(cache: LLMCache) -> None:
    """Reading an entry should protect it from the next LRU eviction."""
    cache._l1_size = 2
    await cache.set("model", "first", "one")
    await cache.set("model", "second", "two")

    assert await cache.get("model", "first") == "one"
    await cache.set("model", "third", "three")

    first_key = cache._generate_cache_key("model", "first")
    second_key = cache._generate_cache_key("model", "second")
    third_key = cache._generate_cache_key("model", "third")
    assert list(cache._l1_cache) == [first_key, third_key]
    assert second_key not in cache._l1_cache


async def test_disabled_cache_skips_reads_and_writes(
    cache: LLMCache,
    redis_client: AsyncMock,
) -> None:
    """Disabling the cache should bypass both levels."""
    cache._enabled = False

    await cache.set("model", "prompt", "response")

    assert await cache.get("model", "prompt") is None
    assert cache._l1_cache == {}
    redis_client.get.assert_not_awaited()
    redis_client.setex.assert_not_awaited()


async def test_set_populates_l1_and_l2_and_get_hits_l1(
    cache: LLMCache,
    redis_client: AsyncMock,
) -> None:
    """A set should populate both levels and subsequent reads should prefer L1."""
    await cache.set("model", "prompt", "response", temperature=0.3)

    key = cache._generate_cache_key("model", "prompt", temperature=0.3)
    assert cache._l1_cache[key][0] == "response"
    redis_client.setex.assert_awaited_once_with(key, 120, "response")

    assert await cache.get("model", "prompt", temperature=0.3) == "response"
    redis_client.get.assert_not_awaited()


async def test_get_removes_expired_l1_then_promotes_l2(
    cache: LLMCache,
    redis_client: AsyncMock,
) -> None:
    """An expired L1 entry should be replaced by the distributed value."""
    key = cache._generate_cache_key("model", "prompt")
    cache._l1_cache[key] = ("stale", datetime.now(UTC) - timedelta(seconds=61))
    redis_client.get.return_value = "fresh"

    result = await cache.get("model", "prompt")

    assert result == "fresh"
    assert cache._l1_cache[key][0] == "fresh"
    redis_client.get.assert_awaited_once_with(key)


async def test_get_returns_none_for_l2_miss(cache: LLMCache, redis_client: AsyncMock) -> None:
    """A miss at both cache levels should return None."""
    redis_client.get.return_value = None

    assert await cache.get("model", "missing") is None


async def test_get_treats_empty_string_as_l2_cache_hit(
    cache: LLMCache,
    redis_client: AsyncMock,
) -> None:
    """An intentionally empty model response is distinct from a Redis miss."""
    redis_client.get.return_value = ""

    assert await cache.get("model", "empty") == ""
    key = cache._generate_cache_key("model", "empty")
    assert cache._l1_cache[key][0] == ""


async def test_redis_read_failure_degrades_to_miss(
    cache: LLMCache,
    redis_client: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Redis read failures should not escape into the LLM request path."""
    redis_client.get.side_effect = RuntimeError("redis down")

    assert await cache.get("model", "prompt") is None
    assert "L2 cache get failed" in caplog.text


async def test_redis_write_failure_keeps_l1_value(
    cache: LLMCache,
    redis_client: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Redis write failures should retain the process-local cached value."""
    redis_client.setex.side_effect = RuntimeError("redis down")

    await cache.set("model", "prompt", "response")

    assert await cache.get("model", "prompt") == "response"
    assert "L2 cache set failed" in caplog.text


async def test_delete_removes_both_cache_levels(
    cache: LLMCache,
    redis_client: AsyncMock,
) -> None:
    """Deleting an entry should remove its local and distributed copies."""
    await cache.set("model", "prompt", "response")
    redis_client.reset_mock()
    key = cache._generate_cache_key("model", "prompt")

    await cache.delete("model", "prompt")

    assert key not in cache._l1_cache
    redis_client.delete.assert_awaited_once_with(key)


async def test_delete_swallows_redis_failure(
    cache: LLMCache,
    redis_client: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Deletion remains best effort when Redis is unavailable."""
    redis_client.delete.side_effect = RuntimeError("redis down")

    await cache.delete("model", "prompt")

    assert "L2 cache delete failed" in caplog.text


async def test_clear_removes_scanned_llm_keys(
    cache: LLMCache,
    redis_client: AsyncMock,
) -> None:
    """Clear should remove L1 state and all matching Redis keys."""
    cache._l1_cache["local"] = ("value", datetime.now(UTC))

    async def scan_iter(*, match: str):
        assert match == "llm:*"
        for key in ("llm:a:1", "llm:b:2"):
            yield key

    redis_client.scan_iter = scan_iter

    await cache.clear()

    assert cache._l1_cache == {}
    redis_client.delete.assert_awaited_once_with("llm:a:1", "llm:b:2")


async def test_clear_does_not_delete_when_scan_is_empty(
    cache: LLMCache,
    redis_client: AsyncMock,
) -> None:
    """An empty Redis scan should not issue an empty delete command."""

    async def scan_iter(*, match: str):
        assert match == "llm:*"
        if False:
            yield "unreachable"

    redis_client.scan_iter = scan_iter

    await cache.clear()

    redis_client.delete.assert_not_awaited()


async def test_clear_swallows_scan_failure(
    cache: LLMCache,
    redis_client: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Redis scan failures should not prevent local cache clearing."""
    cache._l1_cache["local"] = ("value", datetime.now(UTC))

    async def scan_iter(*, match: str):
        raise RuntimeError(f"scan failed for {match}")
        yield "unreachable"

    redis_client.scan_iter = scan_iter

    await cache.clear()

    assert cache._l1_cache == {}
    assert "L2 cache clear failed" in caplog.text


async def test_close_closes_redis_client(cache: LLMCache, redis_client: AsyncMock) -> None:
    """Closing the cache should release the Redis client."""
    await cache.close()

    redis_client.close.assert_awaited_once_with()


def test_get_llm_cache_builds_singleton_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The global factory should construct once with configured cache settings."""
    constructed: list[LLMCache] = []

    class StubCache:
        def __init__(self, *, l1_ttl: int, enabled: bool) -> None:
            self.l1_ttl = l1_ttl
            self.enabled = enabled
            constructed.append(self)  # type: ignore[arg-type]

    monkeypatch.setattr(cache_module, "LLMCache", StubCache)
    monkeypatch.setattr(
        cache_module,
        "get_settings",
        lambda: SimpleNamespace(llm_cache_ttl=45, llm_cache_enabled=False),
    )

    first = cache_module.get_llm_cache()
    second = cache_module.get_llm_cache()

    assert first is second
    assert first.l1_ttl == 45
    assert first.enabled is False
    assert len(constructed) == 1
