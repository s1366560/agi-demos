"""MemStack built-in retrieval backend over memory_chunks + pgvector + FTS."""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import text

from src.domain.model.retrieval_store import RetrievalChunk, RetrievalSearchResult
from src.domain.ports.services.retrieval_store_port import RetrievalStorePort
from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk
from src.infrastructure.memory.chunk_search import ChunkHybridSearch

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class MemstackPgvectorRetrievalStore(RetrievalStorePort):
    """Local retrieval store backed by the existing ``memory_chunks`` table."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_service = embedding_service

    async def initialize_schema(self) -> None:
        async with self._session_factory() as session:
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()

    async def index_chunks(self, chunks: list[RetrievalChunk]) -> int:
        if not chunks:
            return 0
        from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
            SqlChunkRepository,
        )

        async with self._session_factory() as session:
            repo = SqlChunkRepository(session)
            cleared_sources: set[tuple[str, str, str]] = set()
            count = 0
            for chunk in chunks:
                source_key = (chunk.source_type, chunk.source_id, chunk.project_id)
                if source_key not in cleared_sources:
                    await repo.delete_by_source(chunk.source_type, chunk.source_id, chunk.project_id)
                    cleared_sources.add(source_key)
                embedding = chunk.embedding
                if embedding is None and self._embedding_service is not None:
                    embedding = await self._embedding_service.embed_text_safe(chunk.content)
                content_hash = sha256(chunk.content.encode("utf-8")).hexdigest()
                model = MemoryChunk(
                    id=chunk.id or str(uuid4()),
                    project_id=chunk.project_id,
                    source_type=chunk.source_type,
                    source_id=chunk.source_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_hash=content_hash,
                    embedding=embedding,
                    metadata_=chunk.metadata,
                    importance=chunk.importance,
                    category=chunk.category,
                )
                await repo.save(model)
                count += 1
            await session.commit()
            return count

    async def delete_source(self, source_type: str, source_id: str, project_id: str) -> int:
        from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
            SqlChunkRepository,
        )

        async with self._session_factory() as session:
            repo = SqlChunkRepository(session)
            deleted = await repo.delete_by_source(source_type, source_id, project_id)
            await session.commit()
            return deleted

    async def hybrid_search(
        self,
        query: str,
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        if self._embedding_service is None:
            logger.warning("MemstackPgvectorRetrievalStore has no embedding service")
            return []
        search = ChunkHybridSearch(
            embedding_service=self._embedding_service,
            session_factory=self._session_factory,
        )
        results = await search.search(query, project_id, limit=limit, category=category)
        return [
            RetrievalSearchResult(
                id=item.id,
                content=item.content,
                score=item.score,
                metadata=item.metadata,
                source_type=item.source_type,
                source_id=item.source_id,
                category=item.category,
                created_at=item.created_at,
            )
            for item in results
        ]

    async def vector_search(
        self,
        query_vector: list[float],
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
            SqlChunkRepository,
        )

        async with self._session_factory() as session:
            repo = SqlChunkRepository(session)
            rows = await repo.vector_search(query_vector, project_id, limit, category=category)
        return [self._row_to_result(row) for row in rows]

    async def fulltext_search(
        self,
        query: str,
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
            SqlChunkRepository,
        )

        async with self._session_factory() as session:
            repo = SqlChunkRepository(session)
            rows = await repo.fts_search(query, project_id, limit, category=category)
        return [self._row_to_result(row) for row in rows]

    async def health_probe(self) -> bool:
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.debug("memstack_pgvector health probe failed", exc_info=True)
            return False

    async def detect_version(self) -> str:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            version = result.scalar_one_or_none()
        return str(version or "postgres")

    async def close(self) -> None:
        return None

    @staticmethod
    def _row_to_result(row: dict[str, Any]) -> RetrievalSearchResult:
        return RetrievalSearchResult(
            id=str(row.get("id", "")),
            content=str(row.get("content", "")),
            score=float(row.get("score", 0.0) or 0.0),
            metadata=dict(row.get("metadata") or {}),
            source_type=row.get("source_type"),
            source_id=row.get("source_id"),
            category=str(row.get("category") or "other"),
            created_at=row.get("created_at"),
        )
