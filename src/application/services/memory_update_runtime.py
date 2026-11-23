"""Extract and index using the services held by one durable job lease."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from src.application.services.memory_update_jobs import ExtractionQueued, GraphNotReady

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from src.domain.model.memory.episode import Episode


@runtime_checkable
class _EpisodeWriter(Protocol):
    async def add_episode(self, episode: Episode) -> object: ...


async def extract_with_graph(payload: dict[str, Any], graph_service: object | None) -> None:
    """Extract through the graph adapter. A queued adapter does not mean completion."""
    if graph_service is None:
        raise GraphNotReady("graph runtime is not bound")
    from datetime import UTC, datetime

    from src.domain.model.memory.episode import Episode, SourceType

    episode = Episode(
        content=str(payload.get("content") or ""),
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=str(payload.get("title") or payload.get("memory_id") or ""),
        metadata={
            "memory_id": payload.get("memory_id"),
            "tenant_id": payload.get("tenant_id"),
            "project_id": payload.get("project_id"),
            "user_id": payload.get("user_id"),
            "source_revision": payload.get("source_revision"),
            "reprocess": True,
        },
        tenant_id=_text(payload.get("tenant_id")),
        project_id=_text(payload.get("project_id")),
        user_id=_text(payload.get("user_id")),
    )
    if not isinstance(graph_service, _EpisodeWriter):
        raise GraphNotReady("graph runtime cannot accept episodes")
    result = await graph_service.add_episode(episode)
    status = str(getattr(result, "status", "") or "")
    if status.upper() == "PENDING":
        raise ExtractionQueued("graph queued the episode")


async def index_with_session(
    payload: dict[str, Any],
    session_factory: Callable[[], AsyncSession] | None,
    embedding_service: object | None,
) -> None:
    """Replace searchable chunks for the saved revision."""
    if session_factory is None:
        raise GraphNotReady("session factory is not bound")
    from sqlalchemy import select

    from src.domain.model.memory.processing import MemoryProcessingSource
    from src.infrastructure.adapters.secondary.persistence.models import Memory
    from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
        SqlChunkRepository,
    )
    from src.infrastructure.memory.chunk_sync import upsert_memory_chunks

    source = MemoryProcessingSource.from_payload(payload)
    if source is None:
        return
    session = session_factory()
    try:
        current_revision = select(Memory.id).where(
            Memory.id == source.memory_id,
            Memory.project_id == source.project_id,
            Memory.version == source.revision,
            Memory.task_id == source.task_id,
            Memory.status == "ENABLED",
        )
        if await session.scalar(current_revision) is None:
            return
        await upsert_memory_chunks(
            SqlChunkRepository(session),
            memory_id=str(payload.get("memory_id") or ""),
            content=str(payload.get("content") or ""),
            project_id=str(payload.get("project_id") or ""),
            category=str(payload.get("category") or "fact"),
            metadata={"tenant_id": payload.get("tenant_id")},
            embedding_service=cast("Any", embedding_service),
        )
        # Generate embeddings without locking memory edits. Fence only the final commit so
        # chunks from a superseded or deleted revision roll back with the session.
        if await session.scalar(current_revision.with_for_update()) is not None:
            await session.commit()
    finally:
        await session.close()


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
