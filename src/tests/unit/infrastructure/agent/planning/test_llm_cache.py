"""
Unit tests for LLMResponseCache.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.

Test Cases:
- test_cache_hit_returns_stored_response
- test_cache_miss_returns_none
- test_cache_set_stores_response
- test_cache_eviction_when_full
- test_cache_ttl_expiration
- test_cache_key_includes_query_and_context
- test_cache_clear_removes_all_entries
- test_cache_size_respects_max_size
- test_cache_get_updates_access_time
- test_cache_eviction_uses_lru_policy
"""

from unittest.mock import Mock, patch
import time

import pytest

from src.infrastructure.agent.planning.llm_cache import (
    LLMResponseCache,
    CacheEntry,
)


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_cache_entry_creation(self) -> None:
        """Test creating a cache entry."""
        entry = CacheEntry(
            response='{"test": "value"}',
            ttl=3600,
        )

        assert entry.response == '{"test": "value"}'
        assert entry.ttl == 3600
        assert entry.access_count == 0

    def test_cache_entry_is_expired_when_ttl_passed(self) -> None:
        """Test that entry is expired after TTL."""
        entry = CacheEntry(
            response='{"test": "value"}',
            ttl=1,  # 1 second TTL
        )

        assert not entry.is_expired()

        time.sleep(1.1)

        assert entry.is_expired()

    def test_cache_entry_is_expired_with_zero_ttl(self) -> None:
        """Test that entry with zero TTL is immediately expired."""
        entry = CacheEntry(
            response='{"test": "value"}',
            ttl=0,
        )

        assert entry.is_expired()

    def test_cache_entry_never_expires_with_negative_ttl(self) -> None:
        """Test that entry with negative TTL never expires."""
        entry = CacheEntry(
            response='{"test": "value"}',
            ttl=-1,  # Never expires
        )

        # Sleep a bit and check
        time.sleep(0.1)

        assert not entry.is_expired()

    def test_cache_entry_records_access(self) -> None:
        """Test that entry records access count."""
        entry = CacheEntry(
            response='{"test": "value"}',
            ttl=3600,
        )

        assert entry.access_count == 0
        assert entry.last_accessed_at is not None

        initial_time = entry.last_accessed_at

        entry.record_access()

        assert entry.access_count == 1
        assert entry.last_accessed_at >= initial_time


class TestLLMResponseCacheInit:
    """Tests for LLMResponseCache initialization."""

    def test_init_with_default_params(self) -> None:
        """Test creating cache with default parameters."""
        cache = LLMResponseCache()

        assert cache.max_size == 100
        assert cache.default_ttl == 3600
        assert len(cache) == 0

    def test_init_with_custom_params(self) -> None:
        """Test creating cache with custom parameters."""
        cache = LLMResponseCache(
            max_size=50,
            default_ttl=1800,
        )

        assert cache.max_size == 50
        assert cache.default_ttl == 1800

    def test_init_with_invalid_max_size_raises_error(self) -> None:
        """Test that invalid max_size raises ValueError."""
        with pytest.raises(ValueError):
            LLMResponseCache(max_size=0)

        with pytest.raises(ValueError):
            LLMResponseCache(max_size=-1)


class TestCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_cache_key_includes_query(self) -> None:
        """Test that cache key includes query."""
        cache = LLMResponseCache()

        key1 = cache._generate_key("test query")
        key2 = cache._generate_key("different query")

        assert key1 != key2

    def test_cache_key_includes_context(self) -> None:
        """Test that cache key includes context."""
        cache = LLMResponseCache()

        context = [{"role": "user", "content": "previous"}]

        key_with_context = cache._generate_key("query", conversation_context=context)
        key_without_context = cache._generate_key("query")

        assert key_with_context != key_without_context

    def test_cache_key_is_consistent(self) -> None:
        """Test that cache key is consistent for same inputs."""
        cache = LLMResponseCache()

        key1 = cache._generate_key("test query")
        key2 = cache._generate_key("test query")

        assert key1 == key2

    def test_cache_key_is_hash_string(self) -> None:
        """Test that cache key is a hash string."""
        cache = LLMResponseCache()

        key = cache._generate_key("test query")

        assert isinstance(key, str)
        assert len(key) == 64  # SHA256 hex digest length


class TestCacheGetSet:
    """Tests for cache get/set operations."""

    def test_cache_hit_returns_stored_response(self) -> None:
        """Test that cache hit returns stored response."""
        cache = LLMResponseCache()

        cache.set("query", '{"result": "value"}')

        result = cache.get("query")

        assert result == '{"result": "value"}'

    def test_cache_miss_returns_none(self) -> None:
        """Test that cache miss returns None."""
        cache = LLMResponseCache()

        result = cache.get("non-existent query")

        assert result is None

    def test_cache_set_stores_response(self) -> None:
        """Test that cache set stores response."""
        cache = LLMResponseCache()

        cache.set("query", '{"result": "value"}')

        assert len(cache) == 1

    def test_cache_set_with_custom_ttl(self) -> None:
        """Test that cache set with custom TTL."""
        cache = LLMResponseCache()

        cache.set("query", '{"result": "value"}', ttl=10)

        # Should not be expired yet
        result = cache.get("query")
        assert result == '{"result": "value"}'

    def test_cache_get_with_context(self) -> None:
        """Test cache get with context."""
        cache = LLMResponseCache()

        context = [{"role": "user", "content": "previous"}]

        cache.set("query", '{"result": "value"}', conversation_context=context)

        result = cache.get("query", conversation_context=context)

        assert result == '{"result": "value"}'

    def test_cache_get_with_wrong_context_returns_none(self) -> None:
        """Test that cache with wrong context returns None."""
        cache = LLMResponseCache()

        context1 = [{"role": "user", "content": "previous"}]
        context2 = [{"role": "user", "content": "different"}]

        cache.set("query", '{"result": "value"}', conversation_context=context1)

        result = cache.get("query", conversation_context=context2)

        assert result is None

    def test_cache_get_updates_access_time(self) -> None:
        """Test that cache get updates access time."""
        cache = LLMResponseCache()

        cache.set("query", '{"result": "value"}')

        # Get the entry directly to check access
        key = cache._generate_key("query")
        initial_count = cache._cache[key].access_count

        cache.get("query")

        assert cache._cache[key].access_count == initial_count + 1


class TestCacheEviction:
    """Tests for cache eviction policies."""

    def test_cache_eviction_when_full(self) -> None:
        """Test that cache evicts entries when full."""
        cache = LLMResponseCache(max_size=3)

        cache.set("query1", '{"result": 1}')
        cache.set("query2", '{"result": 2}')
        cache.set("query3", '{"result": 3}')

        assert len(cache) == 3

        # Adding one more should evict one
        cache.set("query4", '{"result": 4}')

        assert len(cache) == 3

    def test_cache_eviction_uses_lru_policy(self) -> None:
        """Test that cache evicts least recently used entry."""
        cache = LLMResponseCache(max_size=3)

        cache.set("query1", '{"result": 1}')
        cache.set("query2", '{"result": 2}')
        cache.set("query3", '{"result": 3}')

        # Access query1 to make it more recently used
        cache.get("query1")

        # Access query2
        cache.get("query2")

        # Add query4, should evict query3 (least recently used)
        cache.set("query4", '{"result": 4}')

        assert cache.get("query1") is not None
        assert cache.get("query2") is not None
        assert cache.get("query3") is None  # Evicted
        assert cache.get("query4") is not None

    def test_cache_size_respects_max_size(self) -> None:
        """Test that cache never exceeds max_size."""
        cache = LLMResponseCache(max_size=5)

        for i in range(10):
            cache.set(f"query{i}", f'{{"result": {i}}}')

        assert len(cache) <= 5


class TestCacheTTL:
    """Tests for cache TTL expiration."""

    def test_cache_ttl_expiration(self) -> None:
        """Test that cache respects TTL expiration."""
        cache = LLMResponseCache(default_ttl=1)  # 1 second TTL

        cache.set("query", '{"result": "value"}')

        # Should be available immediately
        assert cache.get("query") == '{"result": "value"}'

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired now
        assert cache.get("query") is None

    def test_cache_zero_ttl_expires_immediately(self) -> None:
        """Test that zero TTL expires immediately."""
        cache = LLMResponseCache()

        cache.set("query", '{"result": "value"}', ttl=0)

        # Should be expired immediately
        assert cache.get("query") is None

    def test_cache_negative_ttl_never_expires(self) -> None:
        """Test that negative TTL means never expires."""
        cache = LLMResponseCache()

        cache.set("query", '{"result": "value"}', ttl=-1)

        # Wait a bit
        time.sleep(0.1)

        # Should still be available
        assert cache.get("query") == '{"result": "value"}'


class TestCacheClear:
    """Tests for cache clear operations."""

    def test_cache_clear_removes_all_entries(self) -> None:
        """Test that clear removes all entries."""
        cache = LLMResponseCache()

        cache.set("query1", '{"result": 1}')
        cache.set("query2", '{"result": 2}')
        cache.set("query3", '{"result": 3}')

        assert len(cache) == 3

        cache.clear()

        assert len(cache) == 0

    def test_cache_clear_allows_new_entries(self) -> None:
        """Test that clear allows adding new entries."""
        cache = LLMResponseCache()

        cache.set("query1", '{"result": 1}')
        cache.clear()
        cache.set("query2", '{"result": 2}')

        assert cache.get("query2") == '{"result": 2}'


class TestCacheStats:
    """Tests for cache statistics."""

    def test_cache_stats_returns_hit_rate(self) -> None:
        """Test that cache stats includes hit rate."""
        cache = LLMResponseCache()

        cache.set("query1", '{"result": 1}')
        cache.set("query2", '{"result": 2}')

        cache.get("query1")  # Hit
        cache.get("query3")  # Miss
        cache.get("query2")  # Hit
        cache.get("query4")  # Miss

        stats = cache.get_stats()

        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5

    def test_cache_stats_returns_size(self) -> None:
        """Test that cache stats includes size."""
        cache = LLMResponseCache()

        cache.set("query1", '{"result": 1}')
        cache.set("query2", '{"result": 2}')

        stats = cache.get_stats()

        assert stats["size"] == 2

    def test_cache_hit_rate_with_no_access(self) -> None:
        """Test hit rate with no access."""
        cache = LLMResponseCache()

        stats = cache.get_stats()

        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0


class TestEdgeCases:
    """Tests for edge cases."""

    def test_cache_with_empty_query(self) -> None:
        """Test cache with empty query."""
        cache = LLMResponseCache()

        cache.set("", '{"result": "value"}')

        result = cache.get("")

        assert result == '{"result": "value"}'

    def test_cache_with_unicode_query(self) -> None:
        """Test cache with unicode query."""
        cache = LLMResponseCache()

        cache.set("实现用户认证", '{"result": "value"}')

        result = cache.get("实现用户认证")

        assert result == '{"result": "value"}'

    def test_cache_with_very_long_query(self) -> None:
        """Test cache with very long query."""
        cache = LLMResponseCache()

        long_query = "a" * 10000

        cache.set(long_query, '{"result": "value"}')

        result = cache.get(long_query)

        assert result == '{"result": "value"}'

    def test_cache_set_overwrites_existing(self) -> None:
        """Test that set overwrites existing entry."""
        cache = LLMResponseCache()

        cache.set("query", '{"result": "old"}')
        cache.set("query", '{"result": "new"}')

        result = cache.get("query")

        assert result == '{"result": "new"}'
