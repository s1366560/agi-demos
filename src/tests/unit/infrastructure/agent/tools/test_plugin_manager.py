"""Unit tests for plugin_manager tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plugin_manager_uninstall_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uninstall action should call runtime uninstall and emit toolset_changed event."""
    fake_manager = SimpleNamespace(
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
