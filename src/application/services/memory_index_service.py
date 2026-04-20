"""Memory index service for chunk lifecycle management.

Handles chunking, embedding, and indexing of memories,
conversations, and episodes into the memory_chunks table.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, cast

from src.infrastructure.memory.chunker import TextChunk, chunk_text

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
        SqlChunkRepository,
    )
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService


class MemoryIndexService:
    """Manages the lifecycle of memory chunk indexing.

    Chunks content, computes embeddings, and persists to the
    memory_chunks table via SqlChunkRepository.
    """

    def __init__(
        self,
        chunk_repo: SqlChunkRepository,
        embedding_service: EmbeddingService | None,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._embedding = embedding_service

    async def index_memory(
        self,
        memory_id: str,
        content: str,
        project_id: str,
        category: str = "other",
        metadata: dict[str, Any] | None = None,
        max_tokens: int = 400,
    ) -> int:
        """Index a memory's content as chunks.

        Args:
            memory_id: ID of the source memory.
            content: Full text content to chunk and index.
            project_id: Project scope.
            category: Memory category.
            max_tokens: Max tokens per chunk.

        Returns:
            Number of chunks created.
        """
        if not content or not content.strip():
            return 0

        # Delete existing chunks for this memory (re-index)
        await self._chunk_repo.delete_by_source("memory", memory_id, project_id)

        chunks = chunk_text(content, max_tokens=max_tokens)
        return await self._index_chunks(
            chunks,
            "memory",
            memory_id,
            project_id,
            category,
            metadata=metadata,
        )

    async def index_conversation(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        project_id: str,
        max_tokens: int = 400,
    ) -> int:
        """Index a conversation transcript as chunks.

        Args:
            conversation_id: ID of the conversation.
            messages: List of message dicts with 'role' and 'content'.
            project_id: Project scope.
            max_tokens: Max tokens per chunk.

        Returns:
            Number of chunks created.
        """
        if not messages:
            return 0

        # Build transcript text
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                lines.append(f"[{role}] {content}")

        if not lines:
            return 0

        text = "\n".join(lines)

        # Delete existing chunks (re-index)
        await self._chunk_repo.delete_by_source("conversation", conversation_id, project_id)

        chunks = chunk_text(text, max_tokens=max_tokens)
        return await self._index_chunks(
            chunks, "conversation", conversation_id, project_id, "other"
        )

    async def index_episode(
        self,
        episode_id: str,
        content: str,
        project_id: str,
        max_tokens: int = 400,
    ) -> int:
        """Index an episode's content as chunks.

        Args:
            episode_id: ID of the source episode.
            content: Episode content.
            project_id: Project scope.
            max_tokens: Max tokens per chunk.

        Returns:
            Number of chunks created.
        """
        if not content or not content.strip():
            return 0

        await self._chunk_repo.delete_by_source("episode", episode_id, project_id)

        chunks = chunk_text(content, max_tokens=max_tokens)
        return await self._index_chunks(chunks, "episode", episode_id, project_id, "other")

    async def _index_chunks(
        self,
        chunks: list[TextChunk],
        source_type: str,
        source_id: str,
        project_id: str,
        category: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Common chunk indexing logic with batch operations."""
        if not chunks:
            return 0

        new_chunks = await self._dedup_chunks(chunks, project_id)
        if not new_chunks:
            logger.info(f"All {len(chunks)} chunks already exist for {source_type}/{source_id}")
            return 0

        embeddings = await self._embed_chunks(new_chunks)
        db_chunks = self._build_chunk_models(
            new_chunks,
            embeddings,
            project_id,
            source_type,
            source_id,
            category,
            extra_metadata=metadata,
        )
        await self._save_chunks(db_chunks)

        created = len(db_chunks)
        logger.info(f"Indexed {created}/{len(chunks)} chunks for {source_type}/{source_id}")
        return created

    async def _dedup_chunks(
        self,
        chunks: list[TextChunk],
        project_id: str,
    ) -> list[TextChunk]:
        """Filter duplicate chunks within a single source payload.

        We intentionally do not deduplicate across other sources in the same
        project because `memory_chunks` are scoped by `source_type/source_id`.
        Cross-source dedup would make one memory lose its searchable chunks if
        another memory happened to contain identical text.
        """
        _ = project_id
        seen_hashes: set[str] = set()
        unique_chunks: list[TextChunk] = []
        for chunk in chunks:
            if chunk.content_hash in seen_hashes:
                continue
            seen_hashes.add(chunk.content_hash)
            unique_chunks.append(chunk)
        return unique_chunks

    async def _embed_chunks(
        self,
        chunks: list[TextChunk],
    ) -> list[list[float] | None]:
        """Compute embeddings for a list of chunks."""
        texts = [c.text for c in chunks]
        embeddings: list[list[float] | None] = [None] * len(texts)
        if self._embedding is None:
            return embeddings
        try:
            if hasattr(self._embedding, "embed_batch_safe"):
                embeddings = await self._embedding.embed_batch_safe(texts)
            elif hasattr(self._embedding, "embed_batch"):
                embeddings = cast(
                    list[list[float] | None], await self._embedding.embed_batch(texts)
                )
            elif hasattr(self._embedding, "embed_text_safe"):
                for i, text in enumerate(texts):
                    embeddings[i] = await self._embedding.embed_text_safe(text)
            else:
                for i, text in enumerate(texts):
                    embeddings[i] = await self._embedding.embed_text(text)
        except Exception as e:
            logger.warning(f"Batch embedding failed: {e}")
        return embeddings

    @staticmethod
    def _build_chunk_models(
        chunks: list[TextChunk],
        embeddings: list[list[float] | None],
        project_id: str,
        source_type: str,
        source_id: str,
        category: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Build MemoryChunk ORM instances from chunks and embeddings."""
        from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk

        return [
            MemoryChunk(
                id=str(uuid.uuid4()),
                project_id=project_id,
                source_type=source_type,
                source_id=source_id,
                chunk_index=chunk.chunk_index,
                content=chunk.text,
                content_hash=chunk.content_hash,
                embedding=embeddings[i],
                metadata_={
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    **(extra_metadata or {}),
                },
                category=category,
            )
            for i, chunk in enumerate(chunks)
        ]

    async def _save_chunks(self, db_chunks: list[Any]) -> None:
        """Persist chunk models to the repository."""
        if not db_chunks:
            return
        if hasattr(self._chunk_repo, "save_batch"):
            await self._chunk_repo.save_batch(db_chunks)
        else:
            for c in db_chunks:
                await self._chunk_repo.save(c)
