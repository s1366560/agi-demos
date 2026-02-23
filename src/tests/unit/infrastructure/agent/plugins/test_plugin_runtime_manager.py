"""Unit tests for plugin runtime manager."""

import asyncio
import subprocess
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.plugins.discovery import DiscoveredPlugin
from src.infrastructure.agent.plugins.manager import PluginRuntimeManager
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry, PluginToolBuildContext
from src.infrastructure.agent.plugins.state_store import PluginStateStore


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_loaded_registers_discovered_plugins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """ensure_loaded should register discovered plugins into runtime registry."""

    class _Plugin:
        name = "demo-plugin"

        @staticmethod
        def setup(api) -> None:
            api.register_tool_factory(lambda _ctx: {"demo_tool": object()})

    registry = AgentPluginRegistry()
    manager = PluginRuntimeManager(registry=registry, state_store=PluginStateStore(base_path=tmp_path))
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.manager.discover_plugins",
        lambda **_kwargs: (
            [
                DiscoveredPlugin(
                    name="demo-plugin",
                    plugin=_Plugin(),
                    source="entrypoint",
                    package="demo-package",
                    version="0.1.0",
                )
            ],
            [],
        ),
    )

    diagnostics = await manager.ensure_loaded()
    plugin_tools, _ = await registry.build_tools(
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            base_tools={},
        )
    )

    assert "demo_tool" in plugin_tools
    assert any(d.code == "plugin_loaded" for d in diagnostics)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_loaded_passes_manifest_strict_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """ensure_loaded should pass strict_local_manifest option to discovery."""
    captured: dict[str, object] = {}

    def _discover_plugins(**kwargs):
        captured.update(kwargs)
        return [], []

    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.manager.discover_plugins",
        _discover_plugins,
    )
    manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=PluginStateStore(base_path=tmp_path),
        strict_local_manifest=True,
    )

    diagnostics = await manager.ensure_loaded()

    assert diagnostics == []
    assert captured.get("strict_local_manifest") is True


@pytest.mark.unit
def test_runtime_manager_reads_manifest_strict_flag_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Manager should read strict manifest toggle from environment when unset."""
    monkeypatch.setenv("MEMSTACK_PLUGIN_MANIFEST_STRICT", "true")
    manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=PluginStateStore(base_path=tmp_path),
    )

    assert manager._strict_local_manifest is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_plugin_enabled_persists_state_and_reloads(tmp_path) -> None:
    """set_plugin_enabled should persist state and trigger reload."""
    state_store = PluginStateStore(base_path=tmp_path)
    manager = PluginRuntimeManager(registry=AgentPluginRegistry(), state_store=state_store)
    manager.reload = AsyncMock(return_value=[])  # type: ignore[method-assign]

    await manager.set_plugin_enabled("demo-plugin", enabled=False)

    assert state_store.is_enabled("demo-plugin") is False
    manager.reload.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_plugin_enabled_tenant_scope_does_not_reload(tmp_path) -> None:
    """Tenant-scoped enable/disable should not trigger global runtime reload."""
    state_store = PluginStateStore(base_path=tmp_path)
    manager = PluginRuntimeManager(registry=AgentPluginRegistry(), state_store=state_store)
    manager.reload = AsyncMock(return_value=[])  # type: ignore[method-assign]

    await manager.set_plugin_enabled("demo-plugin", enabled=False, tenant_id="tenant-1")

    assert state_store.is_enabled("demo-plugin") is True
    assert state_store.is_enabled("demo-plugin", tenant_id="tenant-1") is False
    manager.reload.assert_not_awaited()


@pytest.mark.unit
def test_list_plugins_includes_state_only_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """list_plugins should include state records even when discovery misses plugin."""
    state_store = PluginStateStore(base_path=tmp_path)
    state_store.update_plugin(
        "archived-plugin",
        enabled=False,
        source="entrypoint",
        package="archived-package",
    )
    manager = PluginRuntimeManager(registry=AgentPluginRegistry(), state_store=state_store)

    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.manager.discover_plugins",
        lambda **_kwargs: ([], []),
    )

    plugins, diagnostics = manager.list_plugins()

    assert diagnostics == []
    archived = next((item for item in plugins if item["name"] == "archived-plugin"), None)
    assert archived == {
        "name": "archived-plugin",
        "source": "entrypoint",
        "package": "archived-package",
        "version": None,
        "kind": None,
        "manifest_id": None,
        "manifest_path": None,
        "channels": [],
        "providers": [],
        "skills": [],
        "enabled": False,
        "discovered": False,
    }


@pytest.mark.unit
def test_list_plugins_prefers_tenant_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Tenant list view should apply tenant-scoped enabled override."""
    state_store = PluginStateStore(base_path=tmp_path)
    state_store.set_plugin_enabled("demo-plugin", False, tenant_id="tenant-1")
    manager = PluginRuntimeManager(registry=AgentPluginRegistry(), state_store=state_store)

    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.manager.discover_plugins",
        lambda **_kwargs: (
            [
                DiscoveredPlugin(
                    name="demo-plugin",
                    plugin=object(),
                    source="entrypoint",
                    package="demo-package",
                    version="1.0.0",
                )
            ],
            [],
        ),
    )

    default_plugins, _ = manager.list_plugins()
    tenant_plugins, _ = manager.list_plugins(tenant_id="tenant-1")

    assert default_plugins[0]["enabled"] is True
    assert tenant_plugins[0]["enabled"] is False


@pytest.mark.unit
def test_list_plugins_includes_manifest_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """list_plugins should expose manifest fields for discovered plugins."""
    manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=PluginStateStore(base_path=tmp_path),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.manager.discover_plugins",
        lambda **_kwargs: (
            [
                DiscoveredPlugin(
                    name="demo-plugin",
                    plugin=object(),
                    source="local",
                    version="0.2.0",
                    kind="channel",
                    manifest_id="demo-plugin",
                    manifest_path="/tmp/.memstack/plugins/demo/memstack.plugin.json",
                    channels=("feishu",),
                    providers=("demo-provider",),
                    skills=("demo-skill",),
                )
            ],
            [],
        ),
    )

    plugins, _ = manager.list_plugins()

    assert plugins[0]["kind"] == "channel"
    assert plugins[0]["manifest_id"] == "demo-plugin"
    assert plugins[0]["channels"] == ["feishu"]
    assert plugins[0]["providers"] == ["demo-provider"]
    assert plugins[0]["skills"] == ["demo-skill"]


@pytest.mark.unit
def test_list_plugins_applies_tenant_metadata_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Tenant-scoped metadata should override discovered manifest metadata."""
    state_store = PluginStateStore(base_path=tmp_path)
    state_store.update_plugin(
        "demo-plugin",
        tenant_id="tenant-1",
        kind="tenant-channel",
        manifest_id="tenant-demo-plugin",
        channels=["tenant-feishu"],
        providers=["tenant-provider"],
        skills=["tenant-skill"],
    )
    manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=state_store,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.manager.discover_plugins",
        lambda **_kwargs: (
            [
                DiscoveredPlugin(
                    name="demo-plugin",
                    plugin=object(),
                    source="local",
                    version="0.2.0",
                    kind="channel",
                    manifest_id="demo-plugin",
                    channels=("feishu",),
                    providers=("demo-provider",),
                    skills=("demo-skill",),
                )
            ],
            [],
        ),
    )

    default_plugins, _ = manager.list_plugins()
    tenant_plugins, _ = manager.list_plugins(tenant_id="tenant-1")

    assert default_plugins[0]["kind"] == "channel"
    assert default_plugins[0]["manifest_id"] == "demo-plugin"
    assert tenant_plugins[0]["kind"] == "tenant-channel"
    assert tenant_plugins[0]["manifest_id"] == "tenant-demo-plugin"
    assert tenant_plugins[0]["channels"] == ["tenant-feishu"]
    assert tenant_plugins[0]["providers"] == ["tenant-provider"]
    assert tenant_plugins[0]["skills"] == ["tenant-skill"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_plugin_enabled_rolls_back_when_reload_fails(tmp_path) -> None:
    """Global toggle should restore previous state when reload raises."""
    state_store = PluginStateStore(base_path=tmp_path)
    state_store.update_plugin("demo-plugin", enabled=True, source="entrypoint")
    manager = PluginRuntimeManager(registry=AgentPluginRegistry(), state_store=state_store)
    manager.reload = AsyncMock(side_effect=RuntimeError("reload failed"))  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await manager.set_plugin_enabled("demo-plugin", enabled=False)

    assert state_store.is_enabled("demo-plugin") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_plugin_rejects_unsafe_requirement(tmp_path) -> None:
    """install_plugin should reject URL/path based requirements."""
    manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=PluginStateStore(base_path=tmp_path),
    )

    result = await manager.install_plugin("https://example.com/evil.whl")

    assert result["success"] is False
    assert "blocked" in result["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_plugin_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """install_plugin should surface timeout failures."""
    manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=PluginStateStore(base_path=tmp_path),
    )
    async def _slow_to_thread(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr("src.infrastructure.agent.plugins.manager.asyncio.to_thread", _slow_to_thread)
    monkeypatch.setattr("src.infrastructure.agent.plugins.manager._INSTALL_TIMEOUT_SECONDS", 0.01)

    result = await manager.install_plugin("demo-package")

    assert result["success"] is False
    assert "timed out" in result["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_uninstall_plugin_requires_package_metadata(tmp_path) -> None:
    """Local/state-only plugins should not be uninstallable via pip."""
    manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=PluginStateStore(base_path=tmp_path),
    )
    manager.list_plugins = lambda **_kwargs: (  # type: ignore[method-assign]
        [
            {
                "name": "demo-plugin",
                "source": "local",
                "package": None,
                "version": None,
                "enabled": True,
                "discovered": True,
            }
        ],
        [],
    )

    result = await manager.uninstall_plugin("demo-plugin")

    assert result["success"] is False
    assert "package-managed" in result["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_uninstall_plugin_clears_global_and_tenant_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Successful uninstall should remove plugin state from global and tenant scopes."""
    state_store = PluginStateStore(base_path=tmp_path)
    state_store.update_plugin("demo-plugin", enabled=True, source="entrypoint", package="demo-package")
    state_store.update_plugin("demo-plugin", enabled=False, tenant_id="tenant-1")

    manager = PluginRuntimeManager(
        registry=AgentPluginRegistry(),
        state_store=state_store,
    )
    manager.list_plugins = lambda **_kwargs: (  # type: ignore[method-assign]
        [
            {
                "name": "demo-plugin",
                "source": "entrypoint",
                "package": "demo-package",
                "version": "1.0.0",
                "enabled": True,
                "discovered": True,
            }
        ],
        [],
    )
    manager.reload = AsyncMock(return_value=[])  # type: ignore[method-assign]

    async def _to_thread(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["pip", "uninstall", "demo-package"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr("src.infrastructure.agent.plugins.manager.asyncio.to_thread", _to_thread)

    result = await manager.uninstall_plugin("demo-plugin")

    assert result["success"] is True
    assert state_store.get_plugin("demo-plugin") == {}
    assert state_store.get_plugin("demo-plugin", tenant_id="tenant-1") == {}
