from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.audit_query_service import AuditQueryService
from src.infrastructure.adapters.secondary.persistence.sql_audit_repository import (
    SqlAuditRepository,
)
from src.infrastructure.agent.memory.runtime import MemoryRuntimeResult
from src.infrastructure.agent.plugins.manager import PluginRuntimeManager
from src.infrastructure.agent.plugins.memory_plugin import register_builtin_memory_plugin
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry, PluginToolBuildContext
from src.infrastructure.agent.plugins.state_store import PluginStateStore
from src.infrastructure.audit.audit_log_service import AuditLogService


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_plugin_before_prompt_build_delegates_to_runtime() -> None:
    registry = AgentPluginRegistry()
    register_builtin_memory_plugin(registry)
    runtime = SimpleNamespace(
        recall_for_prompt=AsyncMock(
            return_value=MemoryRuntimeResult(
                memory_context="remembered context",
                emitted_events=[{"type": "memory_recalled", "data": {"count": 1}}],
            )
        )
    )

    result = await registry.apply_hook(
        "before_prompt_build",
        payload={
            "memory_runtime": runtime,
            "project_id": "proj-1",
            "user_message": "hello",
        },
    )

    assert result.payload["memory_context"] == "remembered context"
    assert result.payload["emitted_events"] == [{"type": "memory_recalled", "data": {"count": 1}}]
    runtime.recall_for_prompt.assert_awaited_once_with(
        user_message="hello",
        project_id="proj-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_plugin_tool_factory_builds_memory_tools() -> None:
    registry = AgentPluginRegistry()
    register_builtin_memory_plugin(registry)

    configure_get = MagicMock()
    configure_create = MagicMock()
    configure_search = MagicMock()
    memory_search_tool = MagicMock(name="memory_search_tool")
    memory_get_tool = MagicMock(name="memory_get_tool")
    memory_create_tool = MagicMock(name="memory_create_tool")
    memory_update_tool = MagicMock(name="memory_update_tool")
    memory_delete_tool = MagicMock(name="memory_delete_tool")

    with (
        patch(
            "src.infrastructure.agent.tools.memory_tools.configure_memory_get",
            configure_get,
        ),
        patch(
            "src.infrastructure.agent.tools.memory_tools.configure_memory_create",
            configure_create,
        ),
        patch(
            "src.infrastructure.agent.tools.memory_tools.configure_memory_search",
            configure_search,
        ),
        patch(
            "src.infrastructure.agent.tools.memory_tools.memory_search_tool",
            memory_search_tool,
        ),
        patch(
            "src.infrastructure.agent.tools.memory_tools.memory_get_tool",
            memory_get_tool,
        ),
        patch(
            "src.infrastructure.agent.tools.memory_tools.memory_create_tool",
            memory_create_tool,
        ),
        patch(
            "src.infrastructure.agent.tools.memory_tools.memory_update_tool",
            memory_update_tool,
        ),
        patch(
            "src.infrastructure.agent.tools.memory_tools.memory_delete_tool",
            memory_delete_tool,
        ),
        patch(
            "src.infrastructure.memory.cached_embedding.CachedEmbeddingService",
            return_value="cached-embedder",
        ),
        patch(
            "src.infrastructure.memory.chunk_search.ChunkHybridSearch",
            return_value="chunk-search",
        ),
    ):
        plugin_tools, diagnostics = await registry.build_tools(
            PluginToolBuildContext(
                tenant_id="tenant-1",
                project_id="proj-1",
                base_tools={},
                graph_service=SimpleNamespace(embedder=object()),
                redis_client=None,
                session_factory=MagicMock(name="session-factory"),
            )
        )

    assert configure_get.called
    assert configure_create.called
    assert configure_search.call_args.kwargs["chunk_search"] == "chunk-search"
    assert plugin_tools == {
        "memory_search": memory_search_tool,
        "memory_get": memory_get_tool,
        "memory_create": memory_create_tool,
        "memory_update": memory_update_tool,
        "memory_delete": memory_delete_tool,
    }
    assert any(item.code == "plugin_loaded" for item in diagnostics)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hook_name", "action", "payload", "runtime_attr"),
    [
        (
            "before_prompt_build",
            "runtime_hook.memory_recall_failed",
            {
                "project_id": "proj-1",
                "tenant_id": "tenant-1",
                "conversation_id": "conv-1",
                "user_message": "hello",
            },
            "recall_for_prompt",
        ),
        (
            "on_context_overflow",
            "runtime_hook.memory_flush_failed",
            {
                "project_id": "proj-1",
                "tenant_id": "tenant-1",
                "conversation_id": "conv-1",
                "conversation_context": [{"role": "user", "content": "hello"}],
            },
            "flush_on_context_overflow",
        ),
        (
            "after_turn_complete",
            "runtime_hook.memory_capture_failed",
            {
                "project_id": "proj-1",
                "tenant_id": "tenant-1",
                "conversation_id": "conv-1",
                "conversation_context": [],
                "user_message": "hello",
                "final_content": "done",
                "success": True,
            },
            "capture_after_turn",
        ),
    ],
)
async def test_memory_plugin_failures_persist_runtime_hook_audit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    hook_name: str,
    action: str,
    payload: dict[str, object],
    runtime_attr: str,
) -> None:
    @asynccontextmanager
    async def _session_factory():
        yield db_session

    monkeypatch.setattr(
        "src.infrastructure.audit.audit_log_service.async_session_factory",
        _session_factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.memory_plugin.get_audit_service",
        lambda: AuditLogService(backend="database"),
    )

    registry = AgentPluginRegistry()
    register_builtin_memory_plugin(registry)

    runtime = SimpleNamespace(
        recall_for_prompt=AsyncMock(return_value=MemoryRuntimeResult()),
        flush_on_context_overflow=AsyncMock(return_value=MemoryRuntimeResult()),
        capture_after_turn=AsyncMock(return_value=MemoryRuntimeResult()),
    )
    getattr(runtime, runtime_attr).side_effect = RuntimeError("boom")

    result = await registry.apply_hook(
        hook_name,
        payload={
            **payload,
            "memory_runtime": runtime,
        },
    )

    assert any(diag.code == "hook_handler_failed" for diag in result.diagnostics)

    service = AuditQueryService(audit_repo=SqlAuditRepository(db_session))
    items, total = await service.list_runtime_hook_entries(
        "tenant-1",
        action=action,
        hook_name=hook_name,
    )
    summary = await service.summarize_runtime_hook_entries(
        "tenant-1",
        action=action,
        hook_name=hook_name,
    )

    assert total == 1
    assert len(items) == 1
    assert summary["total"] == 1
    assert summary["action_counts"][action] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_plugin_respects_tenant_disable_for_hooks_and_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state_store = PluginStateStore(base_path=tmp_path)
    state_store.set_plugin_enabled("memory-runtime", False, tenant_id="tenant-1")
    runtime_manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=state_store,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.manager.get_plugin_runtime_manager",
        lambda: runtime_manager,
    )

    registry = AgentPluginRegistry()
    register_builtin_memory_plugin(registry)
    runtime = SimpleNamespace(
        recall_for_prompt=AsyncMock(return_value=MemoryRuntimeResult(memory_context="remembered")),
    )

    hook_result = await registry.apply_hook(
        "before_prompt_build",
        payload={
            "tenant_id": "tenant-1",
            "memory_runtime": runtime,
            "project_id": "proj-1",
            "user_message": "hello",
        },
    )
    plugin_tools, diagnostics = await registry.build_tools(
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="proj-1",
            base_tools={},
            graph_service=SimpleNamespace(embedder=object()),
            redis_client=None,
            session_factory=MagicMock(name="session-factory"),
        )
    )

    assert hook_result.payload.get("memory_context") is None
    assert any(item.code == "plugin_disabled" for item in hook_result.diagnostics)
    runtime.recall_for_prompt.assert_not_awaited()
    assert plugin_tools == {}
    assert any(item.code == "plugin_disabled" for item in diagnostics)
