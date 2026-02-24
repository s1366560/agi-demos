"""Hybrid search on memory chunks using PostgreSQL (pgvector + FTS + RRF).

Combines vector similarity search and full-text search with
Reciprocal Rank Fusion, MMR re-ranking, and temporal decay.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.infrastructure.memory.mmr import mmr_rerank
from src.infrastructure.memory.query_expansion import extract_keywords
from src.infrastructure.memory.temporal_decay import apply_temporal_decay

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
        SqlChunkRepository,
    )
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService

RRF_K = 60  # Same K as existing HybridSearch


@dataclass
class ChunkSearchConfig:
    """Configuration for chunk hybrid search."""

    vector_weight: float = 0.7
    fts_weight: float = 0.3
    mmr_lambda: float = 0.7
    temporal_half_life_days: float = 30.0
    enable_mmr: bool = True
    enable_temporal_decay: bool = True
    enable_fts_fallback: bool = True


@dataclass
class ChunkSearchResult:
    """A single search result from chunk hybrid search."""

    id: str
    content: str
    score: float
    metadata: dict = field(default_factory=dict)
    category: str = "other"
    source_type: str | None = None
    source_id: str | None = None
    created_at: datetime | None = None


class ChunkHybridSearch:
    """Hybrid search engine on memory_chunks table.

    Combines pgvector cosine similarity with PostgreSQL full-text search,
    applies RRF fusion, MMR diversity re-ranking, and temporal decay.
    Falls back to FTS-only when embedding service is unavailable.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        config: ChunkSearchConfig | None = None,
    ) -> None:
        self._embedding = embedding_service
        self._session_factory = session_factory
        self._config = config or ChunkSearchConfig()

    async def _get_chunk_repo(self) -> SqlChunkRepository | None:
        """Create a chunk repository with a fresh DB session."""
        if self._session_factory is None:
            return None
        try:
            from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
                SqlChunkRepository,
            )

            session = self._session_factory()
            return SqlChunkRepository(session)
        except Exception as e:
            logger.warning(f"Failed to create chunk repo for search: {e}")
            return None

    async def search(
        self,
        query: str,
        project_id: str,
        limit: int = 6,
    ) -> list[ChunkSearchResult]:
        """Execute hybrid search with all enhancements.

        Args:
            query: User search query.
            project_id: Scope to project.
            limit: Maximum results to return.

        Returns:
            Ranked list of ChunkSearchResult.
        """
        chunk_repo = await self._get_chunk_repo()
        if chunk_repo is None:
            logger.warning("No chunk repo available for search")
            return []

        session = getattr(chunk_repo, "_session", None)
        try:
            return await self._do_search(chunk_repo, query, project_id, limit)
        finally:
            if session:
                await session.close()

    async def _do_search(
        self,
        chunk_repo: SqlChunkRepository,
        query: str,
        project_id: str,
        limit: int,
    ) -> list[ChunkSearchResult]:
        """Internal search logic with a live chunk_repo."""
        fetch_limit = limit * 3  # Over-fetch for MMR/decay filtering

        # 1. Vector search (with graceful fallback)
        vector_results: list[dict] = []
        query_embedding = await self._embedding.embed_text_safe(query)

        if query_embedding is not None:
            vector_results = await chunk_repo.vector_search(
                query_embedding, project_id, fetch_limit
            )
        elif not self._config.enable_fts_fallback:
            logger.error("Embedding failed and FTS fallback disabled")
            return []

        # 2. FTS search with keyword extraction
        keywords = extract_keywords(query)
        fts_query = " ".join(keywords) if keywords else query
        fts_results = await chunk_repo.fts_search(fts_query, project_id, fetch_limit)

        # 3. RRF fusion
        if vector_results and fts_results:
            merged = self._rrf_fusion(vector_results, fts_results)
        elif vector_results:
            merged = vector_results
        elif fts_results:
            merged = fts_results
        else:
            return []

        # 4. MMR re-ranking
        if self._config.enable_mmr and len(merged) > 1:
            merged = mmr_rerank(
                merged,
                lambda_=self._config.mmr_lambda,
                content_key="content",
                score_key="score",
            )

        # 5. Temporal decay
        if self._config.enable_temporal_decay:
            now = datetime.now(UTC)
            for item in merged:
                created_at = item.get("created_at")
                if created_at:
                    item["score"] = apply_temporal_decay(
                        item["score"],
                        created_at,
                        self._config.temporal_half_life_days,
                        now,
                    )

        # Sort by final score and limit
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)

        return [
            ChunkSearchResult(
                id=item["id"],
                content=item["content"],
                score=item.get("score", 0),
                metadata=item.get("metadata", {}),
                category=item.get("category", "other"),
                source_type=item.get("source_type"),
                source_id=item.get("source_id"),
                created_at=item.get("created_at"),
            )
            for item in merged[:limit]
        ]

    def _rrf_fusion(
        self,
        vector_results: list[dict],
        fts_results: list[dict],
    ) -> list[dict]:
        """Reciprocal Rank Fusion to merge vector and FTS results.

        RRF score = w_vec / (K + rank_vec) + w_fts / (K + rank_fts)
        """
        scores: dict[str, float] = {}
        items: dict[str, dict] = {}
        k = RRF_K

        for rank, item in enumerate(vector_results):
            item_id = item["id"]
            rrf_score = self._config.vector_weight / (k + rank + 1)
            scores[item_id] = scores.get(item_id, 0) + rrf_score
            items[item_id] = item

        for rank, item in enumerate(fts_results):
            item_id = item["id"]
            rrf_score = self._config.fts_weight / (k + rank + 1)
            scores[item_id] = scores.get(item_id, 0) + rrf_score
            if item_id not in items:
                items[item_id] = item

        # Apply fused scores
        result = []
        for item_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            item = dict(items[item_id])
            item["score"] = score
            result.append(item)

        return result
