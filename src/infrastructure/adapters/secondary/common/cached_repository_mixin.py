"""
CachedRepositoryMixin for Redis caching integration.

Provides:
- Transparent caching of repository operations
- Cache key generation with namespacing
- Serialization/deserialization of entities
- Cache invalidation by tenant or pattern
- Null-safe operations (works without Redis)
"""

import json
import logging
from typing import Any, Optional, TypeVar

from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=DeclarativeBase)


class CachedRepositoryMixin:
    """
    Mixin class for adding Redis caching to repositories.

    Provides methods for caching entities with automatic serialization,
    cache invalidation, and null-safe operation.

    Example:
        class MyRepository(CachedRepositoryMixin, BaseRepository):
            def __init__(self, session, redis_client=None):
                BaseRepository.__init__(self, session)
                CachedRepositoryMixin.__init__(
                    self,
                    redis_client=redis_client,
                    cache_prefix="my_entity:",
                )
    """

    # Default configuration (can be overridden in subclasses)
    _cache_prefix: str = "cache:"
    _cache_ttl: int = 300  # 5 minutes default
    _entity_class: Optional[type] = None

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        cache_prefix: Optional[str] = None,
        cache_ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Initialize the caching mixin.

        Args:
            redis_client: Redis client (optional, caching disabled if None)
            cache_prefix: Prefix for all cache keys
            cache_ttl_seconds: Default TTL for cached entries
        """
        self._redis = redis_client
        if cache_prefix is not None:
            self._cache_prefix = cache_prefix
        if cache_ttl_seconds is not None:
            self._cache_ttl = cache_ttl_seconds

    # === Cache key generation ===

    def _cache_key(
        self,
        entity_id: str,
        namespace: Optional[str] = None,
    ) -> str:
        """
        Generate a cache key for an entity.

        Args:
            entity_id: Entity identifier
            namespace: Optional namespace (e.g., tenant_id)

        Returns:
            Cache key string
        """
        if namespace:
            return f"{self._cache_prefix}{namespace}:{entity_id}"
        return f"{self._cache_prefix}{entity_id}"

    # === Cache operations ===

    async def _cache_get(
        self,
        entity_id: str,
        namespace: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Get entity from cache.

        Args:
            entity_id: Entity identifier
            namespace: Optional namespace

        Returns:
            Deserialized entity or None if not found
        """
        if self._redis is None:
            return None

        key = self._cache_key(entity_id, namespace)
        data = await self._redis.get(key)

        if data is None:
            return None

        # Deserialize the cached data
        if isinstance(data, bytes):
            data = data.decode("utf-8")

        return await self._deserialize(data)

    async def _cache_set(
        self,
        entity_id: str,
        entity: Any,
        namespace: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        """
        Store entity in cache.

        Args:
            entity_id: Entity identifier
            entity: Entity to cache
            namespace: Optional namespace
            ttl: Time-to-live in seconds (uses default if None)
        """
        if self._redis is None or entity is None:
            return

        key = self._cache_key(entity_id, namespace)
        data = await self._serialize(entity)

        await self._redis.set(key, data)
        await self._redis.expire(key, ttl or self._cache_ttl)

    async def _cache_delete(
        self,
        entity_id: str,
        namespace: Optional[str] = None,
    ) -> None:
        """
        Delete entity from cache.

        Args:
            entity_id: Entity identifier
            namespace: Optional namespace
        """
        if self._redis is None:
            return

        key = self._cache_key(entity_id, namespace)
        await self._redis.delete(key)

    async def _cache_delete_pattern(
        self,
        pattern: str,
    ) -> None:
        """
        Delete all cache entries matching a pattern.

        Args:
            pattern: Key pattern to match (e.g., "tenant-1:*")
        """
        if self._redis is None:
            return

        full_pattern = f"{self._cache_prefix}{pattern}"
        keys = await self._redis.keys(full_pattern)

        if keys:
            # Delete each key individually
            for key in keys:
                await self._redis.delete(key)

    async def _cache_exists(
        self,
        entity_id: str,
        namespace: Optional[str] = None,
    ) -> bool:
        """
        Check if entity exists in cache.

        Args:
            entity_id: Entity identifier
            namespace: Optional namespace

        Returns:
            True if cached, False otherwise
        """
        if self._redis is None:
            return False

        key = self._cache_key(entity_id, namespace)
        result = await self._redis.exists(key)
        return result > 0

    # === Cached repository operations ===

    async def find_cached(
        self,
        entity_id: str,
        namespace: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Find entity with cache fallback.

        Args:
            entity_id: Entity identifier
            namespace: Optional namespace

        Returns:
            Entity from cache or database
        """
        # Try cache first
        cached = await self._cache_get(entity_id, namespace)
        if cached is not None:
            return cached

        # Cache miss - fall back to database
        entity = await self._find_by_id(entity_id)

        if entity is not None:
            # Cache the result
            await self._cache_set(entity_id, entity, namespace)

        return entity

    # === Cache invalidation ===

    async def invalidate_tenant(
        self,
        tenant_id: str,
    ) -> None:
        """
        Invalidate all cache entries for a tenant.

        Args:
            tenant_id: Tenant identifier
        """
        await self._cache_delete_pattern(f"{tenant_id}:*")

    async def cache_clear(self) -> None:
        """
        Clear all cache entries for this repository.
        """
        if self._redis is None:
            return

        # Find all keys with our prefix
        pattern = f"{self._cache_prefix}*"
        keys = await self._redis.keys(pattern)

        if keys:
            await self._redis.delete(*keys)

    # === Serialization ===

    async def _serialize(self, entity: Any) -> str:
        """
        Serialize entity for storage.

        Default implementation uses JSON.
        Override for custom serialization.

        Args:
            entity: Entity to serialize

        Returns:
            Serialized string
        """
        if entity is None:
            return ""

        if isinstance(entity, dict):
            return json.dumps(entity)

        if hasattr(entity, "__dict__"):
            return json.dumps({k: v for k, v in entity.__dict__.items() if not k.startswith("_")})

        return json.dumps(str(entity))

    async def _deserialize(self, data: str) -> Any:
        """
        Deserialize entity from storage.

        Default implementation uses JSON.
        Override for custom deserialization.

        Args:
            data: Serialized string

        Returns:
            Deserialized entity
        """
        if not data:
            return None

        parsed = json.loads(data)

        # If an entity class is defined, try to instantiate it
        if self._entity_class is not None and isinstance(parsed, dict):
            try:
                return self._entity_class(**parsed)
            except Exception:
                pass  # Fall back to returning dict

        return parsed
