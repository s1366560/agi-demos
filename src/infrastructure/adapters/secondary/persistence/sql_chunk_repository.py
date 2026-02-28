"""SQLAlchemy repository for MemoryChunk persistence."""

from __future__ import annotations

import logging
from typing import Any, cast

from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk

logger = logging.getLogger(__name__)


class SqlChunkRepository:
    """Repository for memory chunk CRUD and search operations."""

    def __init__(self, session: AsyncSession) -> None:
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

    async def find_by_hash(self, content_hash: str, project_id: str) -> MemoryChunk | None:
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
        return cast(CursorResult[Any], result).rowcount or 0

    async def vector_search(
        self,
        query_embedding: list[float],
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search chunks by vector similarity using pgvector.

        Returns list of dicts with id, content, metadata, score, created_at.
        """
        # Use CAST(... AS vector) instead of SQLAlchemy
        # misinterpreting the PostgreSQL :: cast as part of the bind param name.
        vec_str = str(query_embedding)
        category_clause = "AND category = :category" if category else ""
        sql = text(f"""
            SELECT id, content, metadata, created_at, category,
                   source_type, source_id,
                   1 - (embedding <=> CAST(:qvec AS vector)) AS score
            FROM memory_chunks
            WHERE project_id = :project_id
              AND embedding IS NOT NULL
              {category_clause}
            ORDER BY embedding <=> CAST(:qvec_sort AS vector)
            LIMIT :limit
        """).bindparams(
            bindparam("qvec", value=vec_str),
            bindparam("qvec_sort", value=vec_str),
            bindparam("project_id", value=project_id),
            bindparam("limit", value=limit),
            *(
                [bindparam("category", value=category)]
                if category
                else []
            ),
        )
        result = await self._session.execute(sql)
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
        category: str | None = None,
        keywords: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search chunks using PostgreSQL full-text search with ILIKE fallback.

        Uses to_tsquery with OR joins when keywords are provided (better for CJK).
        Falls back to plainto_tsquery for the raw query string.
        If tsvector returns no results, falls back to ILIKE keyword matching.

        Args:
            query: Raw search query string.
            project_id: Scope to project.
            limit: Max results.
            category: Optional category filter.
            keywords: Pre-extracted keywords for OR-based tsquery.
                      When provided, builds to_tsquery('simple', 'kw1 | kw2 | ...').
                      When None, uses plainto_tsquery('simple', query) as before.
        """
        category_clause = "AND category = :category" if category else ""

        # Build tsquery expression: prefer OR-joined keywords for CJK support
        if keywords:
            # Sanitize keywords for to_tsquery: only keep alphanumeric and CJK chars
            safe_kws = [kw for kw in keywords if kw.strip()]
            if safe_kws:
                tsquery_expr = "to_tsquery('simple', :query)"
                # Build OR-joined tsquery string: 'kw1' | 'kw2' | ...
                tsquery_value = " | ".join(safe_kws)
            else:
                tsquery_expr = "plainto_tsquery('simple', :query)"
                tsquery_value = query
        else:
            tsquery_expr = "plainto_tsquery('simple', :query)"
            tsquery_value = query

        sql = text(f"""
            SELECT id, content, metadata, created_at, category,
                   source_type, source_id,
                   ts_rank_cd(
                       to_tsvector('simple', content),
                       {tsquery_expr}
                   ) AS score
            FROM memory_chunks
            WHERE project_id = :project_id
              AND to_tsvector('simple', content) @@ {tsquery_expr}
              {category_clause}
            ORDER BY score DESC
            LIMIT :limit
        """)
        params: dict[str, Any] = {"query": tsquery_value, "project_id": project_id, "limit": limit}
        if category:
            params["category"] = category
        result = await self._session.execute(
            sql,
            params,
        )
        rows = result.fetchall()

        # Fallback to ILIKE for CJK/short queries where tsvector fails
        if not rows:
            # Use pre-extracted keywords if available, else naive split
            fb_keywords = keywords if keywords else [k.strip() for k in query.split() if len(k.strip()) >= 2]
            if not fb_keywords:
                fb_keywords = [query.strip()]
            # Build OR-based ILIKE conditions for each keyword
            conditions = " OR ".join(f"content ILIKE :kw{i}" for i in range(len(fb_keywords)))
            fb_params: dict[str, Any] = {f"kw{i}": f"%{kw}%" for i, kw in enumerate(fb_keywords)}
            fb_params["project_id"] = project_id
            fb_params["limit"] = limit
            fb_category_clause = "AND category = :category" if category else ""
            if category:
                fb_params["category"] = category
            # Compute score as ratio of matched keywords to total keywords
            keyword_count = len(fb_keywords)
            match_cases = " + ".join(
                f"CASE WHEN content ILIKE :kw{i} THEN 1 ELSE 0 END"
                for i in range(keyword_count)
            )
            fb_params["kw_total"] = float(keyword_count)
            fallback_sql = text(f"""
                SELECT id, content, metadata, created_at, category,
                       source_type, source_id,
                       ({match_cases}) / :kw_total AS score
                FROM memory_chunks
                WHERE project_id = :project_id
                  AND ({conditions})
                  {fb_category_clause}
                ORDER BY score DESC, created_at DESC
                LIMIT :limit
            """)
            result = await self._session.execute(fallback_sql, fb_params)
            rows = result.fetchall()

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
            for row in rows
        ]

    async def find_similar(
        self,
        embedding: list[float],
        project_id: str,
        threshold: float = 0.95,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        """Find chunks with similarity above threshold (for dedup)."""
        # Use CAST(... AS vector) instead of ::vector to avoid SQLAlchemy
        # misinterpreting the PostgreSQL :: cast as part of the bind param name.
        vec_str = str(embedding)
        sql = text("""
            SELECT id, content,
                   1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
            FROM memory_chunks
            WHERE project_id = :project_id
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> CAST(:qvec_filter AS vector)) >= :threshold
            ORDER BY embedding <=> CAST(:qvec_sort AS vector)
            LIMIT :limit
        """).bindparams(
            bindparam("qvec", value=vec_str),
            bindparam("qvec_filter", value=vec_str),
            bindparam("qvec_sort", value=vec_str),
            bindparam("project_id", value=project_id),
            bindparam("threshold", value=threshold),
            bindparam("limit", value=limit),
        )
        result = await self._session.execute(sql)
        return [
            {
                "id": row.id,
                "content": row.content,
                "similarity": float(row.similarity),
            }
            for row in result.fetchall()
        ]
