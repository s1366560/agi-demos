"""Cached embedding service with Redis L1+L2 caching.

Wraps the existing EmbeddingService with a two-level cache:
- L1: In-process dict (fast, limited size)
- L2: Redis (distributed, TTL-based)

Cache key format: emb:{model}:{sha256(text)}
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService

_DEFAULT_L1_SIZE = 500
_DEFAULT_L2_TTL = 86400  # 24 hours


class CachedEmbeddingService:
    """Embedding service with Redis-backed caching.

    Wraps an existing EmbeddingService to avoid redundant API calls.
    Uses the same L1+L2 pattern as LLMCache.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        redis_client: Optional[Redis] = None,
        model_name: str = "default",
        l1_size: int = _DEFAULT_L1_SIZE,
        l2_ttl: int = _DEFAULT_L2_TTL,
    ):
        self._inner = embedding_service
        self._redis = redis_client
        self._model_name = model_name
        self._l1: OrderedDict[str, list[float]] = OrderedDict()
        self._l1_size = l1_size
        self._l2_ttl = l2_ttl
        self._stats = {"l1_hits": 0, "l2_hits": 0, "misses": 0}

    @property
    def embedding_dim(self) -> int:
        return self._inner.embedding_dim

    def _cache_key(self, text: str) -> str:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"emb:{self._model_name}:{text_hash}"

    def _l1_get(self, key: str) -> Optional[list[float]]:
        if key in self._l1:
            self._l1.move_to_end(key)
            return self._l1[key]
        return None

    def _l1_put(self, key: str, value: list[float]) -> None:
        self._l1[key] = value
        self._l1.move_to_end(key)
        while len(self._l1) > self._l1_size:
            self._l1.popitem(last=False)

    async def _l2_get(self, key: str) -> Optional[list[float]]:
        if not self._redis:
            return None
        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug(f"Redis cache read error: {e}")
        return None

    async def _l2_put(self, key: str, value: list[float]) -> None:
        if not self._redis:
            return
        try:
            await self._redis.setex(key, self._l2_ttl, json.dumps(value))
        except Exception as e:
            logger.debug(f"Redis cache write error: {e}")

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding with L1 + L2 caching."""
        if not text or not text.strip():
            return [0.0] * self.embedding_dim

        key = self._cache_key(text)

        # L1 check
        cached = self._l1_get(key)
        if cached is not None:
            self._stats["l1_hits"] += 1
            return cached

        # L2 check
        cached = await self._l2_get(key)
        if cached is not None:
            self._stats["l2_hits"] += 1
            self._l1_put(key, cached)
            return cached

        # Compute new embedding
        self._stats["misses"] += 1
        embedding = await self._inner.embed_text(text)

        # Write back to caches
        self._l1_put(key, embedding)
        await self._l2_put(key, embedding)

        return embedding

    async def embed_text_safe(self, text: str) -> Optional[list[float]]:
        """Generate embedding with graceful fallback.

        Returns None instead of raising on failure, enabling FTS-only fallback.
        """
        try:
            return await self.embed_text(text)
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to FTS-only: {e}")
            return None

    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 100,
    ) -> list[list[float]]:
        """Batch embed with per-item caching."""
        results: list[list[float]] = []
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # Check cache for each text
        for i, text in enumerate(texts):
            key = self._cache_key(text)
            cached = self._l1_get(key)
            if cached is not None:
                results.append(cached)
                self._stats["l1_hits"] += 1
                continue
            cached = await self._l2_get(key)
            if cached is not None:
                self._l1_put(key, cached)
                results.append(cached)
                self._stats["l2_hits"] += 1
                continue
            results.append([])  # placeholder
            uncached_indices.append(i)
            uncached_texts.append(text)

        # Batch compute uncached embeddings
        if uncached_texts:
            self._stats["misses"] += len(uncached_texts)
            embeddings = await self._inner.embed_batch(uncached_texts, batch_size=batch_size)
            for idx, embedding in zip(uncached_indices, embeddings):
                results[idx] = embedding
                key = self._cache_key(texts[idx])
                self._l1_put(key, embedding)
                await self._l2_put(key, embedding)

        return results

    def get_stats(self) -> dict[str, int]:
        """Return cache hit/miss statistics."""
        return dict(self._stats)
