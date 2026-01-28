"""
LLM Response Cache for Plan Mode detection.

This module provides the LLMResponseCache class which caches
LLM classification results to avoid redundant API calls.

Uses SHA256 hashing for cache keys and LRU eviction policy.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CacheEntry:
    """
    A single cache entry.

    Attributes:
        response: The cached LLM response
        ttl: Time-to-live in seconds (-1 for never expires)
        created_at: Creation timestamp
        last_accessed_at: Last access timestamp
        access_count: Number of times this entry was accessed
    """

    response: str
    ttl: int
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    access_count: int = 0

    def is_expired(self) -> bool:
        """
        Check if this entry has expired.

        Returns:
            True if expired, False otherwise
        """
        if self.ttl < 0:
            # Negative TTL means never expires
            return False
        if self.ttl == 0:
            # Zero TTL means immediately expired
            return True

        age = time.time() - self.created_at
        return age >= self.ttl

    def record_access(self) -> None:
        """Record that this entry was accessed."""
        self.access_count += 1
        self.last_accessed_at = time.time()


class LLMResponseCache:
    """
    Cache for LLM classification responses.

    Uses SHA256 hash-based keys and LRU eviction policy.
    Thread-safe for single-threaded async use.

    Attributes:
        max_size: Maximum number of entries (default: 100)
        default_ttl: Default TTL in seconds (default: 3600)
    """

    def __init__(
        self,
        max_size: int = 100,
        default_ttl: int = 3600,
    ) -> None:
        """
        Initialize the cache.

        Args:
            max_size: Maximum number of cache entries
            default_ttl: Default TTL in seconds (-1 for never expires)

        Raises:
            ValueError: If max_size is less than 1
        """
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")

        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def _generate_key(
        self,
        query: str,
        conversation_context: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Generate a cache key from query and context.

        Args:
            query: The user query
            conversation_context: Optional conversation history

        Returns:
            SHA256 hex digest
        """
        # Create a deterministic string from inputs
        key_data = {"query": query}

        if conversation_context:
            # Include only the last 5 messages for context
            key_data["context"] = conversation_context[-5:]

        # Serialize to JSON and hash
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()

    def get(
        self,
        query: str,
        conversation_context: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[str]:
        """
        Get a cached response.

        Args:
            query: The user query
            conversation_context: Optional conversation history

        Returns:
            Cached response or None if not found/expired
        """
        key = self._generate_key(query, conversation_context)

        if key not in self._cache:
            self._misses += 1
            return None

        entry = self._cache[key]

        # Check if expired
        if entry.is_expired():
            # Remove expired entry
            del self._cache[key]
            self._misses += 1
            return None

        # Record access and move to end (for LRU)
        entry.record_access()
        self._cache.move_to_end(key)

        self._hits += 1
        return entry.response

    def set(
        self,
        query: str,
        response: str,
        conversation_context: Optional[List[Dict[str, str]]] = None,
        ttl: Optional[int] = None,
    ) -> None:
        """
        Store a response in the cache.

        Args:
            query: The user query
            response: The LLM response to cache
            conversation_context: Optional conversation history
            ttl: Time-to-live in seconds (uses default_ttl if None)
        """
        key = self._generate_key(query, conversation_context)

        # Use provided TTL or default
        if ttl is None:
            ttl = self.default_ttl

        # Create entry
        entry = CacheEntry(response=response, ttl=ttl)

        # Check if we need to evict
        if key not in self._cache and len(self._cache) >= self.max_size:
            self._evict_lru()

        # Store entry (or update existing)
        self._cache[key] = entry
        self._cache.move_to_end(key)

    def _evict_lru(self) -> None:
        """Evict the least recently used entry."""
        if self._cache:
            # Pop first item (oldest)
            self._cache.popitem(last=False)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }

    def __len__(self) -> int:
        """Return the number of entries in the cache."""
        return len(self._cache)
