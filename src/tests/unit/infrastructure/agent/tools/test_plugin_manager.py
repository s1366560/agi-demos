"""Unit tests for plugin_manager tool (@tool_define version)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.mutation_ledger import MutationLedger
from src.infrastructure.agent.tools.plugin_manager import (
    plugin_manager_tool,
)


def _make_ctx(**overrides: Any) -> ToolContext:
    """Create a minimal ToolContext for testing."""
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_list_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """list action should return discovered plugin summary."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: (  # type: ignore[arg-type]
            [
                {
                    "name": "demo-plugin",
                    "source": "entrypoint",
                    "package": "demo-package",
                    "version": "0.1.0",
                    "enabled": True,
                    "discovered": True,
                }
            ],
            [],
        )
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_tenant_id",
        "tenant-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_project_id",
        "project-1",
    )

    ctx = _make_ctx()
    result = await plugin_manager_tool.execute(ctx, action="list")

    assert result.title == "Plugin runtime status"
    assert "demo-plugin" in result.output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_disable_emits_toolset_changed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """disable action should emit toolset_changed pending event."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),  # type: ignore[arg-type]
        set_plugin_enabled=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_tenant_id",
        "tenant-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_project_id",
        "project-1",
    )

    ctx = _make_ctx()
    result = await plugin_manager_tool.execute(ctx, action="disable", plugin_name="demo-plugin")
    pending = ctx.consume_pending_events()

    assert result.title == "Plugin disabled"
    fake_manager.set_plugin_enabled.assert_awaited_once_with(
        "demo-plugin",
        enabled=False,
        tenant_id="tenant-1",
    )
    assert len(pending) == 1
    assert pending[0]["type"] == "toolset_changed"
    assert pending[0]["data"]["action"] == "disable"
    assert pending[0]["data"]["trace_id"].startswith("plugin_manager:")
    assert "action=disable" in pending[0]["data"]["mutation_fingerprint"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_disable_includes_provenance_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """disable action should include before/after provenance summary in metadata and events."""
    snapshots: list[tuple[list[dict[str, Any]], list[Any]]] = [
        ([{"name": "demo-plugin", "enabled": True, "providers": ["base"]}], []),
        ([{"name": "demo-plugin", "enabled": True, "providers": ["base"]}], []),
        ([{"name": "demo-plugin", "enabled": False, "providers": ["base"]}], []),
    ]

    def _list_plugins(**_kwargs: Any) -> tuple[list[dict[str, Any]], list[Any]]:
        if len(snapshots) == 1:
            return snapshots[0]
        return snapshots.pop(0)

    fake_manager = SimpleNamespace(
        list_plugins=_list_plugins,
        set_plugin_enabled=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_tenant_id",
        "tenant-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_project_id",
        "project-1",
    )

    ctx = _make_ctx()
    result = await plugin_manager_tool.execute(ctx, action="disable", plugin_name="demo-plugin")
    pending = ctx.consume_pending_events()

    assert result.metadata["provenance"]["changed"] == ["demo-plugin"]
    assert pending[0]["data"]["details"]["provenance"]["changed"] == ["demo-plugin"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_disable_records_mutation_audit_and_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """disable action should attach mutation audit + rollback metadata."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),  # type: ignore[arg-type]
        set_plugin_enabled=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_tenant_id",
        "tenant-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_project_id",
        "project-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_mutation_ledger",
        MutationLedger(tmp_path / "mutation-ledger.json"),
    )

    ctx = _make_ctx()
    result = await plugin_manager_tool.execute(ctx, action="disable", plugin_name="demo-plugin")
    pending = ctx.consume_pending_events()

    assert result.metadata["rollback"]["action"] == "enable"
    assert result.metadata["mutation_audit"]["status"] == "applied"
    assert result.metadata["mutation_transaction"]["status"] == "verified"
    assert pending[0]["data"]["details"]["mutation_audit"]["status"] == "applied"
    assert pending[0]["data"]["details"]["rollback"]["action"] == "enable"
    assert pending[0]["data"]["details"]["mutation_transaction"]["status"] == "verified"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_uninstall_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uninstall action should call runtime uninstall and emit toolset_changed event."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),  # type: ignore[arg-type]
        uninstall_plugin=AsyncMock(return_value={"success": True, "plugin_name": "demo-plugin"}),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_tenant_id",
        "tenant-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_project_id",
        "project-1",
    )

    ctx = _make_ctx()
    result = await plugin_manager_tool.execute(ctx, action="uninstall", plugin_name="demo-plugin")
    pending = ctx.consume_pending_events()

    assert result.title == "Plugin uninstalled"
    fake_manager.uninstall_plugin.assert_awaited_once_with("demo-plugin")
    assert len(pending) == 1
    assert pending[0]["data"]["action"] == "uninstall"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_install_requires_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """install action should validate requirement parameter."""
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_tenant_id",
        "tenant-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_project_id",
        "project-1",
    )

    ctx = _make_ctx()
    result = await plugin_manager_tool.execute(ctx, action="install")

    assert result.title == "Plugin Manager Failed"
    assert result.metadata["error"] == "requirement is required for install action"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_reload_dry_run_returns_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reload dry_run should return planner output without runtime mutation."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),  # type: ignore[arg-type]
        reload=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_tenant_id",
        "tenant-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_project_id",
        "project-1",
    )

    ctx = _make_ctx()
    result = await plugin_manager_tool.execute(ctx, action="reload", dry_run=True)

    assert result.title == "Plugin reload plan"
    assert result.metadata["dry_run"] is True
    assert result.metadata["reload_plan"]["action"] == "reload"
    fake_manager.reload.assert_not_awaited()
    assert ctx.consume_pending_events() == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_blocks_repeated_mutation_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Repeated mutation fingerprint should be blocked by loop guard."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),  # type: ignore[arg-type]
        set_plugin_enabled=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_tenant_id",
        "tenant-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_project_id",
        "project-1",
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_mutation_ledger",
        MutationLedger(tmp_path / "mutation-ledger.json"),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_loop_threshold",
        1,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager._pm_loop_window_seconds",
        300,
    )

    ctx1 = _make_ctx()
    first = await plugin_manager_tool.execute(ctx1, action="disable", plugin_name="demo-plugin")
    ctx2 = _make_ctx()
    second = await plugin_manager_tool.execute(ctx2, action="disable", plugin_name="demo-plugin")

    assert first.title == "Plugin disabled"
    assert second.title == "Plugin Manager Failed"
    assert second.metadata["mutation_guard"]["blocked"] is True
    assert fake_manager.set_plugin_enabled.await_count == 1
