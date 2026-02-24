"""
Cached implementation of WorkflowPatternRepository using Redis (T087).

Provides caching layer for workflow patterns to improve performance
when frequently accessing patterns for matching.
"""

import json
import logging
from datetime import UTC
from typing import Any

from src.domain.model.agent.workflow_pattern import WorkflowPattern
from src.domain.ports.repositories.workflow_pattern_repository import WorkflowPatternRepositoryPort

logger = logging.getLogger(__name__)


class CachedWorkflowPatternRepository(WorkflowPatternRepositoryPort):
    """
    Cached implementation of WorkflowPatternRepository using Redis.

    Caching strategy:
    - Cache key pattern: "workflow_pattern:{pattern_id}"
    - Tenant list key: "workflow_patterns:tenant:{tenant_id}"
    - TTL: 1 hour for individual patterns, 15 minutes for tenant lists
    - Write-through: Updates write to both cache and backing repository
    - Cache invalidation: List operations are cached and invalidated on updates
    """

    def __init__(
        self,
        backing_repository: WorkflowPatternRepositoryPort,
        redis_client: Any,
        pattern_ttl: int = 3600,  # 1 hour
        list_ttl: int = 900,  # 15 minutes
    ) -> None:
        """
        Initialize cached repository.

        Args:
            backing_repository: The underlying repository to cache
            redis_client: Redis client for caching
            pattern_ttl: TTL for individual pattern cache entries (seconds)
            list_ttl: TTL for tenant list cache entries (seconds)
        """
        self._backing = backing_repository
        self._redis = redis_client
        self._pattern_ttl = pattern_ttl
        self._list_ttl = list_ttl

    async def create(self, pattern: WorkflowPattern) -> WorkflowPattern:
        """Create a pattern and cache it."""
        # Create in backing store
        created = await self._backing.create(pattern)

        # Cache the new pattern
        await self._cache_pattern(created)

        # Invalidate tenant list cache
        await self._invalidate_tenant_list(pattern.tenant_id)

        return created

    async def get_by_id(self, pattern_id: str) -> WorkflowPattern | None:
        """Get a pattern by ID, using cache if available."""
        # Try cache first
        cached = await self._get_cached_pattern(pattern_id)
        if cached:
            return cached

        # Cache miss - fetch from backing store
        pattern = await self._backing.get_by_id(pattern_id)
        if pattern:
            await self._cache_pattern(pattern)

        return pattern

    async def update(self, pattern: WorkflowPattern) -> WorkflowPattern:
        """Update a pattern and update cache."""
        # Update in backing store
        updated = await self._backing.update(pattern)

        # Update cache
        await self._cache_pattern(updated)

        # Invalidate tenant list cache
        await self._invalidate_tenant_list(pattern.tenant_id)

        return updated

    async def delete(self, pattern_id: str) -> None:
        """Delete a pattern and remove from cache."""
        # Get pattern first to invalidate tenant list
        pattern = await self.get_by_id(pattern_id)
        tenant_id = pattern.tenant_id if pattern else None

        # Delete from backing store
        await self._backing.delete(pattern_id)

        # Remove from cache
        cache_key = self._pattern_cache_key(pattern_id)
        await self._redis.delete(cache_key)

        # Invalidate tenant list cache
        if tenant_id:
            await self._invalidate_tenant_list(tenant_id)

    async def list_by_tenant(
        self,
        tenant_id: str,
    ) -> list[WorkflowPattern]:
        """List patterns for a tenant, using cache if available."""
        # Try cache first
        cached = await self._get_cached_tenant_list(tenant_id)
        if cached is not None:
            return cached

        # Cache miss - fetch from backing store
        patterns = await self._backing.list_by_tenant(tenant_id)

        # Cache the list
        await self._cache_tenant_list(tenant_id, patterns)

        return patterns

    async def find_by_name(
        self,
        tenant_id: str,
        name: str,
    ) -> WorkflowPattern | None:
        """
        Find a pattern by name within a tenant.

        This bypasses cache for name lookups as they're less frequent.
        """
        return await self._backing.find_by_name(tenant_id, name)

    async def increment_usage_count(
        self,
        pattern_id: str,
    ) -> WorkflowPattern:
        """Increment usage count and update cache."""
        # Get pattern first
        pattern = await self.get_by_id(pattern_id)
        if not pattern:
            raise ValueError(f"Pattern not found: {pattern_id}")

        # Create updated pattern
        from datetime import datetime

        updated_pattern = WorkflowPattern(
            id=pattern.id,
            tenant_id=pattern.tenant_id,
            name=pattern.name,
            description=pattern.description,
            steps=pattern.steps,
            success_rate=pattern.success_rate,
            usage_count=pattern.usage_count + 1,
            created_at=pattern.created_at,
            updated_at=datetime.now(UTC),
            metadata=pattern.metadata,
        )

        # Update in backing store and cache
        return await self.update(updated_pattern)

    # Cache helper methods

    def _pattern_cache_key(self, pattern_id: str) -> str:
        """Generate cache key for a pattern."""
        return f"workflow_pattern:{pattern_id}"

    def _tenant_list_cache_key(self, tenant_id: str) -> str:
        """Generate cache key for a tenant's pattern list."""
        return f"workflow_patterns:tenant:{tenant_id}"

    async def _cache_pattern(self, pattern: WorkflowPattern) -> None:
        """Cache a pattern."""
        try:
            cache_key = self._pattern_cache_key(pattern.id)
            data = json.dumps(pattern.to_dict())
            await self._redis.set(cache_key, data, ex=self._pattern_ttl)
        except Exception as e:
            logger.warning(f"Failed to cache pattern {pattern.id}: {e}")

    async def _get_cached_pattern(self, pattern_id: str) -> WorkflowPattern | None:
        """Get a pattern from cache."""
        try:
            cache_key = self._pattern_cache_key(pattern_id)
            data = await self._redis.get(cache_key)
            if data:
                return WorkflowPattern.from_dict(json.loads(data))
        except Exception as e:
            logger.warning(f"Failed to get cached pattern {pattern_id}: {e}")
        return None

    async def _cache_tenant_list(self, tenant_id: str, patterns: list[WorkflowPattern]) -> None:
        """Cache a tenant's pattern list."""
        try:
            cache_key = self._tenant_list_cache_key(tenant_id)
            data = json.dumps([p.to_dict() for p in patterns])
            await self._redis.set(cache_key, data, ex=self._list_ttl)
        except Exception as e:
            logger.warning(f"Failed to cache tenant {tenant_id} pattern list: {e}")

    async def _get_cached_tenant_list(self, tenant_id: str) -> list[WorkflowPattern] | None:
        """Get a tenant's pattern list from cache."""
        try:
            cache_key = self._tenant_list_cache_key(tenant_id)
            data = await self._redis.get(cache_key)
            if data:
                return [WorkflowPattern.from_dict(d) for d in json.loads(data)]
        except Exception as e:
            logger.warning(f"Failed to get cached tenant {tenant_id} pattern list: {e}")
        return None

    async def _invalidate_tenant_list(self, tenant_id: str) -> None:
        """Invalidate the tenant list cache."""
        try:
            cache_key = self._tenant_list_cache_key(tenant_id)
            await self._redis.delete(cache_key)
        except Exception as e:
            logger.warning(f"Failed to invalidate tenant {tenant_id} list cache: {e}")
