"""
Response caching for LLM providers.

Provides caching of LLM responses to reduce costs and latency
for repeated queries.

Features:
- In-memory LRU cache with TTL
- Content-based cache keys (message hash)
- Per-provider cache isolation
- Cache statistics and monitoring

Example:
    cache = get_response_cache()

    # Check cache
    cached = await cache.get(messages, model="gpt-4")
    if cached:
        return cached

    # Generate and cache
    response = await llm_client.generate(messages)
    await cache.set(messages, response, model="gpt-4")
"""

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    """Configuration for response caching."""

    # Maximum number of entries in cache
    max_size: int = 1000

    # Time-to-live for cache entries (seconds)
    ttl_seconds: int = 3600  # 1 hour

    # Whether caching is enabled
    enabled: bool = True

    # Minimum response length to cache (avoid caching errors)
    min_response_length: int = 10


@dataclass
class CacheEntry:
    """A cached response entry."""

    response: dict[str, Any]
    created_at: float
    hits: int = 0
    last_accessed: float = field(default_factory=time.time)

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if entry has expired."""
        return (time.time() - self.created_at) > ttl_seconds


@dataclass
class CacheStats:
    """Cache statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class ResponseCache:
    """
    LRU cache for LLM responses with TTL support.

    Thread-safe implementation using OrderedDict for LRU ordering.
    """

    def __init__(self, config: Optional[CacheConfig] = None):
        """
        Initialize the cache.

        Args:
            config: Cache configuration
        """
        self.config = config or CacheConfig()
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = CacheStats()
        self._lock = Lock()

    def _generate_key(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        """
        Generate a cache key from request parameters.

        Args:
            messages: List of messages
            model: Model name
            temperature: Sampling temperature
            **kwargs: Additional parameters to include in key

        Returns:
            SHA256 hash of the request
        """
        # Normalize messages for consistent hashing
        normalized_messages = []
        for msg in messages:
            normalized_messages.append(
                {
                    "role": msg.get("role", ""),
                    "content": msg.get("content", ""),
                }
            )

        # Build key data
        key_data = {
            "messages": normalized_messages,
            "model": model,
            "temperature": temperature,
        }

        # Add relevant kwargs (exclude non-deterministic ones)
        for k, v in kwargs.items():
            if k not in ("stream", "timeout", "metadata"):
                try:
                    json.dumps(v)  # Ensure serializable
                    key_data[k] = v
                except (TypeError, ValueError):
                    pass

        # Generate hash
        key_json = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_json.encode()).hexdigest()

    async def get(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> Optional[dict[str, Any]]:
        """
        Get a cached response if available.

        Args:
            messages: List of messages
            model: Model name
            temperature: Sampling temperature
            **kwargs: Additional request parameters

        Returns:
            Cached response or None if not found/expired
        """
        if not self.config.enabled:
            return None

        # Temperature > 0 responses are non-deterministic, don't cache
        if temperature > 0:
            return None

        key = self._generate_key(messages, model, temperature, **kwargs)

        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats.misses += 1
                return None

            # Check expiration
            if entry.is_expired(self.config.ttl_seconds):
                del self._cache[key]
                self._stats.misses += 1
                self._stats.evictions += 1
                self._stats.size = len(self._cache)
                return None

            # Update access info and move to end (most recently used)
            entry.hits += 1
            entry.last_accessed = time.time()
            self._cache.move_to_end(key)

            self._stats.hits += 1
            logger.debug(f"Cache hit for model {model} (key: {key[:16]}...)")

            return entry.response

    async def set(
        self,
        messages: list[dict[str, Any]],
        response: dict[str, Any],
        model: str,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> None:
        """
        Cache a response.

        Args:
            messages: List of messages
            response: Response to cache
            model: Model name
            temperature: Sampling temperature
            **kwargs: Additional request parameters
        """
        if not self.config.enabled:
            return

        # Don't cache non-deterministic responses
        if temperature > 0:
            return

        # Don't cache short responses (likely errors)
        content = response.get("content", "")
        if len(str(content)) < self.config.min_response_length:
            return

        key = self._generate_key(messages, model, temperature, **kwargs)

        with self._lock:
            # Evict oldest entries if at capacity
            while len(self._cache) >= self.config.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                self._stats.evictions += 1

            # Add new entry
            self._cache[key] = CacheEntry(
                response=response,
                created_at=time.time(),
            )
            self._stats.size = len(self._cache)

            logger.debug(f"Cached response for model {model} (key: {key[:16]}...)")

    def invalidate(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> bool:
        """
        Invalidate a cached entry.

        Returns:
            True if entry was found and removed
        """
        key = self._generate_key(messages, model, temperature, **kwargs)

        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats.size = len(self._cache)
                return True
            return False

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._stats.size = 0
            logger.info("Response cache cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "hit_rate": f"{self._stats.hit_rate:.2%}",
                "evictions": self._stats.evictions,
                "size": self._stats.size,
                "max_size": self.config.max_size,
                "ttl_seconds": self.config.ttl_seconds,
                "enabled": self.config.enabled,
            }

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries removed
        """
        removed = 0
        with self._lock:
            expired_keys = [
                key
                for key, entry in self._cache.items()
                if entry.is_expired(self.config.ttl_seconds)
            ]
            for key in expired_keys:
                del self._cache[key]
                removed += 1

            if removed > 0:
                self._stats.evictions += removed
                self._stats.size = len(self._cache)
                logger.debug(f"Cleaned up {removed} expired cache entries")

        return removed


# Global cache instance
_response_cache: Optional[ResponseCache] = None


def get_response_cache() -> ResponseCache:
    """Get the global response cache."""
    global _response_cache
    if _response_cache is None:
        _response_cache = ResponseCache()
    return _response_cache


def reset_cache() -> None:
    """Reset the global cache (for testing)."""
    global _response_cache
    _response_cache = None
