"""Unit tests for plugin runtime registry."""

from types import SimpleNamespace

import pytest

from src.infrastructure.agent.plugins.registry import (
    AgentPluginRegistry,
    ChannelAdapterBuildContext,
    PluginToolBuildContext,
)


@pytest.mark.unit
def test_register_tool_factory_rejects_duplicate_plugin_name() -> None:
    """Duplicate plugin tool registrations should fail by default."""
    registry = AgentPluginRegistry()
    registry.register_tool_factory("plugin-a", lambda _ctx: {"tool_a": object()})

    with pytest.raises(ValueError):
        registry.register_tool_factory("plugin-a", lambda _ctx: {"tool_b": object()})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_tools_collects_tools_and_conflict_diagnostics() -> None:
    """Registry should collect plugin tools and report name conflicts."""
    registry = AgentPluginRegistry()

    registry.register_tool_factory(
        "plugin-a",
        lambda _ctx: {
            "plugin_tool": SimpleNamespace(name="plugin_tool"),
            "shared_tool": SimpleNamespace(name="shared_tool"),
        },
    )

    plugin_tools, diagnostics = await registry.build_tools(
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            base_tools={"shared_tool": SimpleNamespace(name="shared_tool")},
        )
    )

    assert "plugin_tool" in plugin_tools
    assert "shared_tool" not in plugin_tools
    assert any(d.code == "tool_name_conflict" for d in diagnostics)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_channel_reload_calls_registered_hooks() -> None:
    """Channel reload hooks should be invoked with summary context."""
    registry = AgentPluginRegistry()
    captured = {}

    async def _hook(context) -> None:
        captured["plan"] = context.plan_summary
        captured["dry_run"] = context.dry_run

    registry.register_channel_reload_hook("plugin-a", _hook)

    diagnostics = await registry.notify_channel_reload(plan_summary={"add": 1}, dry_run=True)

    assert diagnostics == []
    assert captured["plan"] == {"add": 1}
    assert captured["dry_run"] is True


@pytest.mark.unit
def test_register_channel_adapter_factory_rejects_duplicate_channel_type() -> None:
    """Duplicate channel adapter registrations should fail by default."""
    registry = AgentPluginRegistry()
    registry.register_channel_adapter_factory("plugin-a", "feishu", lambda _ctx: object())

    with pytest.raises(ValueError):
        registry.register_channel_adapter_factory("plugin-b", "feishu", lambda _ctx: object())


@pytest.mark.unit
def test_register_channel_adapter_factory_persists_channel_metadata() -> None:
    """Registry should expose schema metadata for channel config UIs."""
    registry = AgentPluginRegistry()
    registry.register_channel_adapter_factory(
        "plugin-a",
        "feishu",
        lambda _ctx: object(),
        config_schema={"type": "object", "required": ["app_id"]},
        config_ui_hints={"app_id": {"label": "App ID"}},
        defaults={"connection_mode": "websocket"},
        secret_paths=["app_secret"],
    )

    metadata = registry.list_channel_type_metadata()["feishu"]
    assert metadata.plugin_name == "plugin-a"
    assert metadata.config_schema == {"type": "object", "required": ["app_id"]}
    assert metadata.config_ui_hints == {"app_id": {"label": "App ID"}}
    assert metadata.defaults == {"connection_mode": "websocket"}
    assert metadata.secret_paths == ["app_secret"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_channel_adapter_uses_registered_factory() -> None:
    """Channel adapter factory should build adapter for matching channel type."""
    registry = AgentPluginRegistry()
    expected_adapter = object()
    registry.register_channel_adapter_factory(
        "plugin-a",
        "feishu",
        lambda ctx: {"adapter": expected_adapter, "app_id": ctx.channel_config.app_id},
    )

    adapter, diagnostics = await registry.build_channel_adapter(
        ChannelAdapterBuildContext(
            channel_type="feishu",
            config_model=SimpleNamespace(id="cfg-1"),
            channel_config=SimpleNamespace(app_id="cli_xxx"),
        )
    )

    assert adapter == {"adapter": expected_adapter, "app_id": "cli_xxx"}
    assert any(d.code == "channel_adapter_loaded" for d in diagnostics)
