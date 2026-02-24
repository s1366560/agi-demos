"""Memory index service for chunk lifecycle management.

Handles chunking, embedding, and indexing of memories,
conversations, and episodes into the memory_chunks table.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Optional

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
        embedding_service: EmbeddingService,
    ):
        self._chunk_repo = chunk_repo
        self._embedding = embedding_service

    async def index_memory(
        self,
        memory_id: str,
        content: str,
        project_id: str,
        category: str = "other",
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
        return await self._index_chunks(chunks, "memory", memory_id, project_id, category)

    async def index_conversation(
        self,
        conversation_id: str,
        messages: list[dict],
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
    ) -> int:
        """Common chunk indexing logic with batch operations."""
        from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk

        if not chunks:
            return 0

        # Batch dedup: single query for all hashes
        all_hashes = [c.content_hash for c in chunks]
        existing_hashes: set[str] = set()
        if hasattr(self._chunk_repo, "find_existing_hashes"):
            existing_hashes = await self._chunk_repo.find_existing_hashes(all_hashes, project_id)
        else:
            # Fallback to per-chunk lookup
            for h in all_hashes:
                if await self._chunk_repo.find_by_hash(h, project_id):
                    existing_hashes.add(h)

        new_chunks = [c for c in chunks if c.content_hash not in existing_hashes]
        if not new_chunks:
            logger.info(f"All {len(chunks)} chunks already exist for {source_type}/{source_id}")
            return 0

        # Batch embedding
        texts = [c.text for c in new_chunks]
        embeddings: list[Optional[list[float]]] = [None] * len(texts)
        try:
            if hasattr(self._embedding, "embed_batch"):
                embeddings = await self._embedding.embed_batch(texts)
            elif hasattr(self._embedding, "embed_text_safe"):
                for i, text in enumerate(texts):
                    embeddings[i] = await self._embedding.embed_text_safe(text)
            else:
                for i, text in enumerate(texts):
                    embeddings[i] = await self._embedding.embed_text(text)
        except Exception as e:
            logger.warning(f"Batch embedding failed: {e}")

        # Build chunk models
        db_chunks = []
        for i, chunk in enumerate(new_chunks):
            db_chunks.append(
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
                    },
                    category=category,
                )
            )

        # Batch save
        if db_chunks:
            if hasattr(self._chunk_repo, "save_batch"):
                await self._chunk_repo.save_batch(db_chunks)
            else:
                for c in db_chunks:
                    await self._chunk_repo.save(c)

        created = len(db_chunks)
        logger.info(f"Indexed {created}/{len(chunks)} chunks for {source_type}/{source_id}")
        return created
