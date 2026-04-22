"""Built-in memory runtime plugin."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, cast

from src.infrastructure.agent.memory.runtime import MemoryRuntimeProtocol
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry, PluginToolBuildContext
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi
from src.infrastructure.audit.audit_log_service import get_audit_service

if TYPE_CHECKING:
    from redis.asyncio import Redis

PLUGIN_NAME = "memory-runtime"

logger = logging.getLogger(__name__)


def _append_emitted_events(
    payload: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(payload)
    current = updated.get("emitted_events")
    emitted_events = list(current) if isinstance(current, list) else []
    emitted_events.extend(events)
    updated["emitted_events"] = emitted_events
    return updated


async def _log_memory_audit(
    *,
    action: str,
    payload: Mapping[str, Any],
    details: dict[str, Any],
) -> None:
    try:
        await get_audit_service().log_event(
            action=action,
            resource_type="runtime_hook",
            resource_id=f"{PLUGIN_NAME}:{payload.get('conversation_id') or 'unknown'}",
            actor="system",
            tenant_id=str(payload.get("tenant_id")) if payload.get("tenant_id") else None,
            details={
                "plugin_name": PLUGIN_NAME,
                "hook_name": payload.get("hook_identity", {}).get("hook_name"),
                "project_id": payload.get("project_id"),
                "conversation_id": payload.get("conversation_id"),
                **details,
            },
        )
    except Exception:
        logger.debug("Memory plugin audit logging failed", exc_info=True)


def _memory_runtime(payload: Mapping[str, Any]) -> MemoryRuntimeProtocol | None:
    runtime = payload.get("memory_runtime")
    if runtime is None:
        return None
    return cast("MemoryRuntimeProtocol", runtime)


async def _before_prompt_build(payload: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _memory_runtime(payload)
    if runtime is None:
        return dict(payload)
    try:
        result = await runtime.recall_for_prompt(
            user_message=str(payload.get("user_message", "")),
            project_id=str(payload.get("project_id", "")),
        )
        updated = dict(payload)
        updated["memory_context"] = result.memory_context
        return _append_emitted_events(updated, result.emitted_events)
    except Exception as exc:
        await _log_memory_audit(
            action="runtime_hook.memory_recall_failed",
            payload=payload,
            details={
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        raise


async def _on_context_overflow(payload: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _memory_runtime(payload)
    if runtime is None:
        return dict(payload)
    try:
        result = await runtime.flush_on_context_overflow(
            conversation_context=list(payload.get("conversation_context", [])),
            project_id=str(payload.get("project_id", "")),
            conversation_id=str(payload.get("conversation_id", "")),
        )
        return _append_emitted_events(payload, result.emitted_events)
    except Exception as exc:
        await _log_memory_audit(
            action="runtime_hook.memory_flush_failed",
            payload=payload,
            details={
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        raise


async def _after_turn_complete(payload: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _memory_runtime(payload)
    if runtime is None:
        return dict(payload)
    try:
        result = await runtime.capture_after_turn(
            user_message=str(payload.get("user_message", "")),
            final_content=str(payload.get("final_content", "")),
            project_id=str(payload.get("project_id", "")),
            conversation_id=str(payload.get("conversation_id", "")),
            conversation_context=list(payload.get("conversation_context", [])),
            success=bool(payload.get("success", False)),
            llm_client_override=payload.get("llm_client_override"),
        )
        return _append_emitted_events(payload, result.emitted_events)
    except Exception as exc:
        await _log_memory_audit(
            action="runtime_hook.memory_capture_failed",
            payload=payload,
            details={
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        raise


def _build_memory_tools(context: PluginToolBuildContext) -> dict[str, Any]:
    session_factory = context.session_factory
    graph_service = context.graph_service
    if session_factory is None or graph_service is None:
        return {}

    from src.infrastructure.agent.tools.memory_tools import (
        configure_memory_create,
        configure_memory_get,
        configure_memory_search,
        memory_create_tool,
        memory_delete_tool,
        memory_get_tool,
        memory_search_tool,
        memory_update_tool,
    )
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
    from src.infrastructure.memory.cached_embedding import CachedEmbeddingService
    from src.infrastructure.memory.chunk_search import ChunkHybridSearch

    embedding_service = getattr(graph_service, "embedder", None)
    cached_embedding = (
        CachedEmbeddingService(
            embedding_service,
            cast("Redis | None", context.redis_client),
        )
        if embedding_service
        else None
    )

    configure_memory_get(
        session_factory=session_factory,
        project_id=context.project_id,
    )
    configure_memory_create(
        session_factory=session_factory,
        graph_service=graph_service,
        project_id=context.project_id,
        tenant_id=context.tenant_id,
        embedding_service=cached_embedding,
    )
    if cached_embedding is not None:
        configure_memory_search(
            chunk_search=ChunkHybridSearch(
                cast("EmbeddingService", cached_embedding),
                session_factory,
            ),
            graph_service=graph_service,
            project_id=context.project_id,
        )
    else:
        configure_memory_search(
            chunk_search=None,
            graph_service=graph_service,
            project_id=context.project_id,
        )

    return {
        "memory_search": memory_search_tool,
        "memory_get": memory_get_tool,
        "memory_create": memory_create_tool,
        "memory_update": memory_update_tool,
        "memory_delete": memory_delete_tool,
    }


def register_builtin_memory_plugin(registry: AgentPluginRegistry) -> None:
    """Register the built-in memory runtime plugin."""
    api = PluginRuntimeApi(PLUGIN_NAME, registry=registry)
    _register_memory_plugin(api)


def _register_memory_plugin(api: PluginRuntimeApi) -> None:
    """Register memory runtime hooks and tools through the runtime API."""
    api.register_hook(
        "before_prompt_build",
        _before_prompt_build,
        hook_family="mutating",
        priority=25,
        display_name="Memory recall",
        description="Injects durable memory before prompt construction.",
        overwrite=True,
    )
    api.register_hook(
        "on_context_overflow",
        _on_context_overflow,
        hook_family="mutating",
        priority=25,
        display_name="Memory flush",
        description="Flushes durable memory before context compression drops earlier turns.",
        overwrite=True,
    )
    api.register_hook(
        "after_turn_complete",
        _after_turn_complete,
        hook_family="mutating",
        priority=25,
        display_name="Turn memory capture",
        description="Captures durable memory and schedules indexing after a completed turn.",
        overwrite=True,
    )
    api.register_tool_factory(
        _build_memory_tools,
        overwrite=True,
    )


class BuiltinMemoryRuntimePlugin:
    """Builtin plugin wrapper so discovery/runtime manager can inventory memory-runtime."""

    name = PLUGIN_NAME
    plugin_manifest: ClassVar[dict[str, str]] = {
        "id": PLUGIN_NAME,
        "kind": "runtime",
        "version": "builtin",
    }

    def setup(self, api: PluginRuntimeApi) -> None:
        _register_memory_plugin(api)
