"""Bind the durable memory-update job to the process graph and chunk index."""

from __future__ import annotations

from typing import Any, cast

from src.application.services.memory_update_jobs import ExtractionQueued, GraphNotReady

_graph_service: object | None = None
_embedding_service: object | None = None
_session_factory: object | None = None


def bind_memory_update_runtime(
    *,
    graph_service: object,
    embedding_service: object,
    session_factory: object,
) -> None:
    """Remember the services a restarted process should use for recovery."""
    global _graph_service, _embedding_service, _session_factory
    _graph_service = graph_service
    _embedding_service = embedding_service
    _session_factory = session_factory


def memory_update_runtime_ready() -> bool:
    return _graph_service is not None and _session_factory is not None


def clear_memory_update_runtime() -> None:
    """Drop a process binding so a later test or shutdown starts unbound."""
    global _graph_service, _embedding_service, _session_factory
    _graph_service = None
    _embedding_service = None
    _session_factory = None


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
    add_episode = getattr(graph_service, "add_episode", None)
    if not callable(add_episode):
        raise GraphNotReady("graph runtime cannot accept episodes")
    result = await add_episode(episode)
    status = str(getattr(result, "status", "") or "")
    if status.upper() == "PENDING":
        raise ExtractionQueued("graph queued the episode")


async def index_with_session(
    payload: dict[str, Any],
    session_factory: object | None,
    embedding_service: object | None,
) -> None:
    """Replace searchable chunks for the saved revision."""
    if session_factory is None:
        raise GraphNotReady("session factory is not bound")
    from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
        SqlChunkRepository,
    )
    from src.infrastructure.memory.chunk_sync import upsert_memory_chunks

    if not callable(session_factory):
        raise GraphNotReady("session factory is not bound")
    session = session_factory()
    try:
        await upsert_memory_chunks(
            SqlChunkRepository(session),
            memory_id=str(payload.get("memory_id") or ""),
            content=str(payload.get("content") or ""),
            project_id=str(payload.get("project_id") or ""),
            category=str(payload.get("category") or "fact"),
            metadata={"tenant_id": payload.get("tenant_id")},
            embedding_service=cast("Any", embedding_service),
        )
        await session.commit()
    finally:
        await session.close()


async def bound_extract(payload: dict[str, Any]) -> None:
    await extract_with_graph(payload, _graph_service)


async def bound_index(payload: dict[str, Any]) -> None:
    await index_with_session(payload, _session_factory, _embedding_service)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
