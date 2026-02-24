"""
Multi-level LLM cache for distributed caching with intelligent cache key generation.

Cache Levels:
- L1: In-memory cache (process-local, fastest)
- L2: Redis cache (distributed across instances)
- L3: Persistent cache (optional, for very expensive queries)

This provides:
- Fast in-memory lookups for repeated queries
- Distributed caching for multi-instance deployments
- Intelligent cache key generation based on prompt + model
- TTL-based invalidation
- Cache size limits with LRU eviction
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

from src.configuration.config import get_settings

logger = logging.getLogger(__name__)


class LLMCache:
    """
    Multi-level LLM response cache.

    Provides intelligent caching for LLM responses with configurable TTL
    and size limits.
    """

    def __init__(
        self,
        l1_size: int = 100,
        l1_ttl: int = 300,  # 5 minutes
        l2_ttl: int = 3600,  # 1 hour
        enabled: bool = True,
    ) -> None:
        """
        Initialize the multi-level cache.

        Args:
            l1_size: Maximum number of entries in L1 cache
            l1_ttl: Time-to-live for L1 cache entries (seconds)
            l2_ttl: Time-to-live for L2 cache entries (seconds)
            enabled: Whether caching is enabled
        """
        self._l1_cache: dict[str, tuple[Any, datetime]] = {}
        self._l1_size = l1_size
        self._l1_ttl = l1_ttl
        self._l2_ttl = l2_ttl
        self._enabled = enabled
        self._redis_client = None

        # Initialize Redis client if available
        try:
            import redis.asyncio as redis

            settings = get_settings()
            self._redis_client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info("Redis cache client initialized")
        except ImportError:
            logger.warning("redis not available, L2 cache disabled")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}, L2 cache disabled")

    def _generate_cache_key(
        self,
        model: str,
        prompt: str | list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """
        Generate a consistent cache key for the request.

        Args:
            model: Model name/identifier
            prompt: Prompt string or list of messages
            **kwargs: Additional parameters that affect the response

        Returns:
            Cache key string
        """
        # Normalize prompt to string
        if isinstance(prompt, list):
            prompt_str = json.dumps(prompt, sort_keys=True)
        else:
            prompt_str = prompt

        # Create key components
        key_parts = [
            model,
            prompt_str,
            json.dumps(kwargs, sort_keys=True),
        ]

        # Hash for shorter keys
        key_hash = hashlib.sha256(":".join(key_parts).encode()).hexdigest()

        return f"llm:{model}:{key_hash[:16]}"

    def _is_expired(self, timestamp: datetime, ttl: int) -> bool:
        """Check if a cache entry has expired."""
        return (datetime.now(UTC) - timestamp).total_seconds() > ttl

    def _evict_l1_if_needed(self) -> None:
        """Evict oldest entries from L1 cache if size limit reached."""
        if len(self._l1_cache) > self._l1_size:
            # Sort by timestamp and remove oldest entries
            sorted_keys = sorted(
                self._l1_cache.keys(),
                key=lambda k: self._l1_cache[k][1],
            )
            # Remove 10% of entries
            to_remove = max(1, len(sorted_keys) // 10)
            for key in sorted_keys[:to_remove]:
                del self._l1_cache[key]
            logger.debug(f"Evicted {to_remove} entries from L1 cache")

    async def get(
        self,
        model: str,
        prompt: str | list[dict[str, Any]],
        **kwargs: Any,
    ) -> str | None:
        """
        Get cached response for the given prompt.

        Args:
            model: Model name/identifier
            prompt: Prompt string or list of messages
            **kwargs: Additional parameters

        Returns:
            Cached response if found and not expired, None otherwise
        """
        if not self._enabled:
            return None

        cache_key = self._generate_cache_key(model, prompt, **kwargs)

        # Check L1 cache
        if cache_key in self._l1_cache:
            response, timestamp = self._l1_cache[cache_key]
            if not self._is_expired(timestamp, self._l1_ttl):
                logger.debug(f"L1 cache hit: {cache_key}")
                return cast(str | None, response)
            else:
                # Expired, remove from L1
                del self._l1_cache[cache_key]

        # Check L2 cache (Redis)
        if self._redis_client:
            try:
                cached = await self._redis_client.get(cache_key)
                if cached:
                    logger.debug(f"L2 cache hit: {cache_key}")
                    # Populate L1 cache
                    self._l1_cache[cache_key] = (cached, datetime.now(UTC))
                    self._evict_l1_if_needed()
                    return cast(str | None, cached)
            except Exception as e:
                logger.warning(f"L2 cache get failed: {e}")

        return None

    async def set(
        self,
        model: str,
        prompt: str | list[dict[str, Any]],
        response: str,
        **kwargs: Any,
    ) -> None:
        """
        Cache the response for the given prompt.

        Args:
            model: Model name/identifier
            prompt: Prompt string or list of messages
            response: Response to cache
            **kwargs: Additional parameters
        """
        if not self._enabled:
            return

        cache_key = self._generate_cache_key(model, prompt, **kwargs)
        now = datetime.now(UTC)

        # Store in L1 cache
        self._l1_cache[cache_key] = (response, now)
        self._evict_l1_if_needed()

        # Store in L2 cache (Redis)
        if self._redis_client:
            try:
                await self._redis_client.setex(
                    cache_key,
                    self._l2_ttl,
                    response,
                )
                logger.debug(f"L2 cache set: {cache_key}")
            except Exception as e:
                logger.warning(f"L2 cache set failed: {e}")

    async def delete(
        self,
        model: str,
        prompt: str | list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        """
        Remove cached response for the given prompt.

        Args:
            model: Model name/identifier
            prompt: Prompt string or list of messages
            **kwargs: Additional parameters
        """
        cache_key = self._generate_cache_key(model, prompt, **kwargs)

        # Remove from L1
        if cache_key in self._l1_cache:
            del self._l1_cache[cache_key]

        # Remove from L2
        if self._redis_client:
            try:
                await self._redis_client.delete(cache_key)
            except Exception as e:
                logger.warning(f"L2 cache delete failed: {e}")

    async def clear(self) -> None:
        """Clear all cached entries."""
        self._l1_cache.clear()

        if self._redis_client:
            try:
                # Delete all LLM cache keys (requires scanning)
                keys = []
                async for key in self._redis_client.scan_iter(match="llm:*"):
                    keys.append(key)
                if keys:
                    await self._redis_client.delete(*keys)
                logger.info(f"Cleared {len(keys)} entries from L2 cache")
            except Exception as e:
                logger.warning(f"L2 cache clear failed: {e}")

    async def close(self) -> None:
        """Close the cache connection."""
        if self._redis_client:
            await self._redis_client.close()


# Global cache instance
_llm_cache: LLMCache | None = None


def get_llm_cache() -> LLMCache:
    """Get or create the global LLM cache instance."""
    global _llm_cache
    if _llm_cache is None:
        settings = get_settings()
        _llm_cache = LLMCache(
            l1_ttl=settings.llm_cache_ttl,
            enabled=settings.llm_cache_enabled,
        )
    return _llm_cache
