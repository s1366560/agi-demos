"""Unit tests for plugin_manager tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.mutation_ledger import MutationLedger
from src.infrastructure.agent.tools.plugin_manager import PluginManagerTool


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_list_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """list action should return discovered plugin summary."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: (
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

    tool = PluginManagerTool(tenant_id="tenant-1", project_id="project-1")
    result = await tool.execute(action="list")

    assert result["title"] == "Plugin runtime status"
    assert "demo-plugin" in result["output"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_disable_emits_toolset_changed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """disable action should emit toolset_changed pending event."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),
        set_plugin_enabled=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},
    )

    tool = PluginManagerTool(tenant_id="tenant-1", project_id="project-1")
    result = await tool.execute(action="disable", plugin_name="demo-plugin")
    pending = tool.consume_pending_events()

    assert result["title"] == "Plugin disabled"
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
    snapshots = [
        ([{"name": "demo-plugin", "enabled": True, "providers": ["base"]}], []),
        ([{"name": "demo-plugin", "enabled": True, "providers": ["base"]}], []),
        ([{"name": "demo-plugin", "enabled": False, "providers": ["base"]}], []),
    ]

    def _list_plugins(**_kwargs):
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
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},
    )

    tool = PluginManagerTool(tenant_id="tenant-1", project_id="project-1")
    result = await tool.execute(action="disable", plugin_name="demo-plugin")
    pending = tool.consume_pending_events()

    assert result["metadata"]["provenance"]["changed"] == ["demo-plugin"]
    assert pending[0]["data"]["details"]["provenance"]["changed"] == ["demo-plugin"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_disable_records_mutation_audit_and_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """disable action should attach mutation audit + rollback metadata."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),
        set_plugin_enabled=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},
    )

    tool = PluginManagerTool(
        tenant_id="tenant-1",
        project_id="project-1",
        mutation_ledger=MutationLedger(tmp_path / "mutation-ledger.json"),
    )
    result = await tool.execute(action="disable", plugin_name="demo-plugin")
    pending = tool.consume_pending_events()

    assert result["metadata"]["rollback"]["action"] == "enable"
    assert result["metadata"]["mutation_audit"]["status"] == "applied"
    assert result["metadata"]["mutation_transaction"]["status"] == "verified"
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
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),
        uninstall_plugin=AsyncMock(return_value={"success": True, "plugin_name": "demo-plugin"}),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},
    )

    tool = PluginManagerTool(tenant_id="tenant-1", project_id="project-1")
    result = await tool.execute(action="uninstall", plugin_name="demo-plugin")
    pending = tool.consume_pending_events()

    assert result["title"] == "Plugin uninstalled"
    fake_manager.uninstall_plugin.assert_awaited_once_with("demo-plugin")
    assert len(pending) == 1
    assert pending[0]["data"]["action"] == "uninstall"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_install_requires_requirement() -> None:
    """install action should validate requirement parameter."""
    tool = PluginManagerTool(tenant_id="tenant-1", project_id="project-1")

    result = await tool.execute(action="install")

    assert result["title"] == "Plugin Manager Failed"
    assert result["metadata"]["error"] == "requirement is required for install action"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_reload_dry_run_returns_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reload dry_run should return planner output without runtime mutation."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),
        reload=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )

    tool = PluginManagerTool(tenant_id="tenant-1", project_id="project-1")
    result = await tool.execute(action="reload", dry_run=True)

    assert result["title"] == "Plugin reload plan"
    assert result["metadata"]["dry_run"] is True
    assert result["metadata"]["reload_plan"]["action"] == "reload"
    fake_manager.reload.assert_not_awaited()
    assert tool.consume_pending_events() == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_blocks_repeated_mutation_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Repeated mutation fingerprint should be blocked by loop guard."""
    fake_manager = SimpleNamespace(
        list_plugins=lambda **_kwargs: ([{"name": "demo-plugin", "enabled": True}], []),
        set_plugin_enabled=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.get_plugin_runtime_manager",
        lambda: fake_manager,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.plugin_manager.SelfModifyingLifecycleOrchestrator.run_post_change",
        lambda **_kwargs: {"cache_invalidation": {}, "probe": {"status": "skipped"}},
    )
    tool = PluginManagerTool(
        tenant_id="tenant-1",
        project_id="project-1",
        mutation_ledger=MutationLedger(tmp_path / "mutation-ledger.json"),
        mutation_loop_threshold=1,
        mutation_loop_window_seconds=300,
    )

    first = await tool.execute(action="disable", plugin_name="demo-plugin")
    second = await tool.execute(action="disable", plugin_name="demo-plugin")

    assert first["title"] == "Plugin disabled"
    assert second["title"] == "Plugin Manager Failed"
    assert second["metadata"]["mutation_guard"]["blocked"] is True
    assert fake_manager.set_plugin_enabled.await_count == 1
