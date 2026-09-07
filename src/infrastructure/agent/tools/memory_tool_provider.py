"""Builtin memory-tool source independent of the retired V1 plugin registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def build_memory_tools(
    *,
    tenant_id: str,
    project_id: str,
    graph_service: Any,
    redis_client: Any,
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> dict[str, Any]:
    """Build the builtin memory CRUD tools for one worker scope."""
    from src.configuration.config import get_settings

    if get_settings().agent_memory_tool_provider_mode == "disabled":
        return {}
    if not tenant_id.strip() or not project_id.strip():
        raise ValueError("memory tools require tenant_id and project_id")
    if session_factory is None or graph_service is None:
        return {}

    from src.infrastructure.agent.tools.memory_tools import (
        make_memory_tools,
    )
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
    from src.infrastructure.memory.cached_embedding import CachedEmbeddingService
    from src.infrastructure.memory.chunk_search import ChunkHybridSearch

    embedding_service = getattr(graph_service, "embedder", None)
    cached_embedding = (
        CachedEmbeddingService(
            embedding_service,
            cast("Redis | None", redis_client),
        )
        if embedding_service
        else None
    )

    chunk_search = (
        ChunkHybridSearch(
            cast("EmbeddingService", cached_embedding),
            session_factory,
        )
        if cached_embedding is not None
        else None
    )
    return make_memory_tools(
        tenant_id=tenant_id,
        project_id=project_id,
        session_factory=session_factory,
        graph_service=graph_service,
        chunk_search=chunk_search,
        embedding_service=cached_embedding,
    )


__all__ = ["build_memory_tools"]
