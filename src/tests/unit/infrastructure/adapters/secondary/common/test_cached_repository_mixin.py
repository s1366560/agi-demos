"""
Unit tests for CachedRepositoryMixin.

Tests are written FIRST (TDD RED phase).
These tests MUST FAIL before implementation exists.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest


@dataclass
class TestEntity:
    """Test entity for caching."""

    id: str
    name: str
    tenant_id: str


class TestCachedRepositoryMixin:
    """Test suite for CachedRepositoryMixin."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.get = AsyncMock()
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        redis.exists = AsyncMock()
        redis.expire = AsyncMock()
        redis.keys = AsyncMock()
        return redis

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = AsyncMock()
        return session

    # === TEST: CachedRepositoryMixin class exists ===

    def test_cached_repository_mixin_class_exists(self):
        """Test that CachedRepositoryMixin class can be imported."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        assert CachedRepositoryMixin is not None

    # === TEST: Initialization ===

    def test_mixin_initialization(self, mock_redis):
        """Test mixin can be initialized with Redis client."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        repo = TestRepo(redis_client=mock_redis)
        assert repo._redis == mock_redis

    def test_mixin_with_custom_cache_prefix(self, mock_redis):
        """Test mixin with custom cache prefix."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        repo = TestRepo(redis_client=mock_redis, cache_prefix="custom:")
        assert repo._cache_prefix == "custom:"

    def test_mixin_with_custom_ttl(self, mock_redis):
        """Test mixin with custom TTL."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        repo = TestRepo(redis_client=mock_redis, cache_ttl_seconds=600)
        assert repo._cache_ttl == 600

    # === TEST: Cache key generation ===

    def test_generate_cache_key(self, mock_redis):
        """Test cache key generation."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            _cache_prefix = "test:"

        repo = TestRepo(redis_client=mock_redis)
        key = repo._cache_key("entity-123")

        assert key == "test:entity-123"

    def test_generate_cache_key_with_namespace(self, mock_redis):
        """Test cache key generation with namespace."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            _cache_prefix = "test:"

        repo = TestRepo(redis_client=mock_redis)
        key = repo._cache_key("entity-123", namespace="tenant-1")

        assert "tenant-1" in key
        assert "entity-123" in key

    # === TEST: Cache get operations ===

    @pytest.mark.asyncio
    async def test_cache_get_hit(self, mock_redis):
        """Test cache get returns cached entity."""
        import json

        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            async def _deserialize(self, data: str):
                return json.loads(data)

        entity = {"id": "123", "name": "Test"}
        mock_redis.get.return_value = json.dumps(entity).encode()

        repo = TestRepo(redis_client=mock_redis)
        result = await repo._cache_get("entity-123")

        assert result == entity
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_get_miss(self, mock_redis):
        """Test cache get returns None on cache miss."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        mock_redis.get.return_value = None

        repo = TestRepo(redis_client=mock_redis)
        result = await repo._cache_get("entity-123")

        assert result is None

    # === TEST: Cache set operations ===

    @pytest.mark.asyncio
    async def test_cache_set(self, mock_redis):
        """Test cache set stores entity."""
        import json

        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            async def _serialize(self, entity):
                return json.dumps(entity)

        entity = {"id": "123", "name": "Test"}

        repo = TestRepo(redis_client=mock_redis, cache_ttl_seconds=300)
        await repo._cache_set("entity-123", entity)

        mock_redis.set.assert_called_once()
        mock_redis.expire.assert_called_once_with("cache:entity-123", 300)

    @pytest.mark.asyncio
    async def test_cache_set_with_custom_ttl(self, mock_redis):
        """Test cache set with custom TTL."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            async def _serialize(self, entity):
                return entity

        repo = TestRepo(redis_client=mock_redis)
        await repo._cache_set("entity-123", {"id": "123"}, ttl=600)

        mock_redis.expire.assert_called_once_with("cache:entity-123", 600)

    # === TEST: Cache delete operations ===

    @pytest.mark.asyncio
    async def test_cache_delete(self, mock_redis):
        """Test cache delete removes entity."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        repo = TestRepo(redis_client=mock_redis)
        await repo._cache_delete("entity-123")

        mock_redis.delete.assert_called_once_with("cache:entity-123")

    @pytest.mark.asyncio
    async def test_cache_delete_by_pattern(self, mock_redis):
        """Test cache delete by pattern."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        mock_redis.keys.return_value = [
            b"cache:tenant-1:entity-1",
            b"cache:tenant-1:entity-2",
        ]

        repo = TestRepo(redis_client=mock_redis)
        await repo._cache_delete_pattern("tenant-1:*")

        mock_redis.keys.assert_called_once()
        assert mock_redis.delete.call_count == 2

    # === TEST: Cache invalidate operations ===

    @pytest.mark.asyncio
    async def test_cache_invalidate_tenant(self, mock_redis):
        """Test invalidating all cache for a tenant."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        mock_redis.keys.return_value = [b"cache:tenant-1:a", b"cache:tenant-1:b"]

        repo = TestRepo(redis_client=mock_redis)
        await repo.invalidate_tenant("tenant-1")

        mock_redis.keys.assert_called_once_with("cache:tenant-1:*")
        assert mock_redis.delete.call_count == 2

    # === TEST: Cached repository operations ===

    @pytest.mark.asyncio
    async def test_find_cached_returns_from_cache(self, mock_redis):
        """Test find_cached returns cached entity when available."""
        import json

        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            async def _deserialize(self, data: str):
                return json.loads(data)

        entity = {"id": "123", "name": "Cached"}
        mock_redis.get.return_value = json.dumps(entity).encode()

        repo = TestRepo(redis_client=mock_redis)
        result = await repo.find_cached("entity-123")

        assert result == entity

    @pytest.mark.asyncio
    async def test_find_cached_falls_back_to_db(self, mock_redis):
        """Test find_cached falls back to database on cache miss."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            async def _deserialize(self, data: str):
                return data

            async def _find_by_id(self, entity_id: str):
                return {"id": entity_id, "name": "From DB"}

        mock_redis.get.return_value = None

        repo = TestRepo(redis_client=mock_redis)
        result = await repo.find_cached("entity-123")

        assert result["name"] == "From DB"
        # Should have been cached
        mock_redis.set.assert_called_once()

    # === TEST: Serialization ===

    @pytest.mark.asyncio
    async def test_serialize_entity(self, mock_redis):
        """Test entity serialization."""
        import json

        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        entity = TestEntity(id="123", name="Test", tenant_id="tenant-1")
        repo = TestRepo(redis_client=mock_redis)

        result = await repo._serialize(entity)

        assert isinstance(result, str)
        data = json.loads(result)
        assert data["id"] == "123"
        assert data["name"] == "Test"

    @pytest.mark.asyncio
    async def test_deserialize_entity(self, mock_redis):
        """Test entity deserialization."""
        import json

        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            _entity_class = TestEntity

        repo = TestRepo(redis_client=mock_redis)
        data = json.dumps({"id": "123", "name": "Test", "tenant_id": "tenant-1"})

        result = await repo._deserialize(data)

        # Should return a TestEntity instance
        assert isinstance(result, TestEntity)
        assert result.id == "123"
        assert result.name == "Test"

    # === TEST: Edge cases ===

    @pytest.mark.asyncio
    async def test_cache_with_none_redis_skips_cache(self, mock_session):
        """Test that None Redis client skips cache operations."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            async def _find_by_id(self, entity_id: str):
                return {"id": entity_id, "name": "From DB"}

        repo = TestRepo(redis_client=None)
        result = await repo.find_cached("entity-123")

        assert result["name"] == "From DB"

    @pytest.mark.asyncio
    async def test_cache_set_with_none_entity_does_nothing(self, mock_redis):
        """Test that setting None entity does nothing."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        repo = TestRepo(redis_client=mock_redis)
        await repo._cache_set("entity-123", None)

        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_keys_with_special_characters(self, mock_redis):
        """Test cache key generation with special characters."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        repo = TestRepo(redis_client=mock_redis)
        key = repo._cache_key("entity:with:colons", namespace="tenant:1")

        # Key should be generated safely
        assert key is not None
        assert "entity:with:colons" in key or "entity" in key

    @pytest.mark.asyncio
    async def test_cache_exists(self, mock_redis):
        """Test checking if key exists in cache."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            pass

        mock_redis.exists.return_value = 1

        repo = TestRepo(redis_client=mock_redis)
        exists = await repo._cache_exists("entity-123")

        assert exists is True
        mock_redis.exists.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_clear_all(self, mock_redis):
        """Test clearing all cache entries."""
        from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
            CachedRepositoryMixin,
        )

        class TestRepo(CachedRepositoryMixin):
            _cache_prefix = "test:"

        mock_redis.keys.return_value = [b"test:a", b"test:b"]

        repo = TestRepo(redis_client=mock_redis)
        await repo.cache_clear()

        mock_redis.keys.assert_called_once_with("test:*")
        assert mock_redis.delete.call_count >= 1
