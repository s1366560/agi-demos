"""SQLAlchemy repository for MemoryChunk persistence."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk

logger = logging.getLogger(__name__)


class SqlChunkRepository:
    """Repository for memory chunk CRUD and search operations."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, chunk: MemoryChunk) -> MemoryChunk:
        """Persist a memory chunk."""
        self._session.add(chunk)
        await self._session.flush()
        return chunk

    async def save_batch(self, chunks: list[MemoryChunk]) -> list[MemoryChunk]:
        """Persist multiple chunks in a single flush."""
        self._session.add_all(chunks)
        await self._session.flush()
        return chunks

    async def find_by_hash(self, content_hash: str, project_id: str) -> Optional[MemoryChunk]:
        """Find a chunk by content hash within a project."""
        query = select(MemoryChunk).where(
            MemoryChunk.content_hash == content_hash,
            MemoryChunk.project_id == project_id,
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def find_existing_hashes(self, hashes: list[str], project_id: str) -> set[str]:
        """Return the subset of content hashes that already exist in the project."""
        if not hashes:
            return set()
        query = select(MemoryChunk.content_hash).where(
            MemoryChunk.content_hash.in_(hashes),
            MemoryChunk.project_id == project_id,
        )
        result = await self._session.execute(query)
        return {row[0] for row in result.all()}

    async def find_by_source(
        self, source_type: str, source_id: str, project_id: str
    ) -> list[MemoryChunk]:
        """Find all chunks for a given source."""
        query = (
            select(MemoryChunk)
            .where(
                MemoryChunk.source_type == source_type,
                MemoryChunk.source_id == source_id,
                MemoryChunk.project_id == project_id,
            )
            .order_by(MemoryChunk.chunk_index)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def delete_by_source(self, source_type: str, source_id: str, project_id: str) -> int:
        """Delete all chunks for a given source. Returns count deleted."""
        stmt = delete(MemoryChunk).where(
            MemoryChunk.source_type == source_type,
            MemoryChunk.source_id == source_id,
            MemoryChunk.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.rowcount

    async def vector_search(
        self,
        query_embedding: list[float],
        project_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Search chunks by vector similarity using pgvector.

        Returns list of dicts with id, content, metadata, score, created_at.
        """
        sql = text("""
            SELECT id, content, metadata, created_at, category,
                   source_type, source_id,
                   1 - (embedding <=> :query_vec::vector) AS score
            FROM memory_chunks
            WHERE project_id = :project_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :query_vec::vector
            LIMIT :limit
        """)
        result = await self._session.execute(
            sql,
            {
                "query_vec": str(query_embedding),
                "project_id": project_id,
                "limit": limit,
            },
        )
        return [
            {
                "id": row.id,
                "content": row.content,
                "metadata": row.metadata,
                "score": float(row.score),
                "created_at": row.created_at,
                "category": row.category,
                "source_type": row.source_type,
                "source_id": row.source_id,
            }
            for row in result.fetchall()
        ]

    async def fts_search(
        self,
        query: str,
        project_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Search chunks using PostgreSQL full-text search.

        Uses plainto_tsquery with 'simple' config for language-agnostic matching.
        """
        sql = text("""
            SELECT id, content, metadata, created_at, category,
                   source_type, source_id,
                   ts_rank_cd(
                       to_tsvector('simple', content),
                       plainto_tsquery('simple', :query)
                   ) AS score
            FROM memory_chunks
            WHERE project_id = :project_id
              AND to_tsvector('simple', content) @@ plainto_tsquery('simple', :query)
            ORDER BY score DESC
            LIMIT :limit
        """)
        result = await self._session.execute(
            sql,
            {"query": query, "project_id": project_id, "limit": limit},
        )
        return [
            {
                "id": row.id,
                "content": row.content,
                "metadata": row.metadata,
                "score": float(row.score),
                "created_at": row.created_at,
                "category": row.category,
                "source_type": row.source_type,
                "source_id": row.source_id,
            }
            for row in result.fetchall()
        ]

    async def find_similar(
        self,
        embedding: list[float],
        project_id: str,
        threshold: float = 0.95,
        limit: int = 1,
    ) -> list[dict]:
        """Find chunks with similarity above threshold (for dedup)."""
        sql = text("""
            SELECT id, content,
                   1 - (embedding <=> :query_vec::vector) AS similarity
            FROM memory_chunks
            WHERE project_id = :project_id
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> :query_vec::vector) >= :threshold
            ORDER BY embedding <=> :query_vec::vector
            LIMIT :limit
        """)
        result = await self._session.execute(
            sql,
            {
                "query_vec": str(embedding),
                "project_id": project_id,
                "threshold": threshold,
                "limit": limit,
            },
        )
        return [
            {
                "id": row.id,
                "content": row.content,
                "similarity": float(row.similarity),
            }
            for row in result.fetchall()
        ]
