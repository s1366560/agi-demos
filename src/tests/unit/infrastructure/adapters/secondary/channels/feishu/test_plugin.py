"""Unit tests for Feishu channel plugin registration."""

from pathlib import Path

import pytest

from src.domain.model.channels.message import ChannelConfig
from src.infrastructure.adapters.secondary.channels.feishu import FeishuAdapter
from src.infrastructure.agent.plugins.discovery import discover_plugins
from src.infrastructure.agent.plugins.loader import AgentPluginLoader
from src.infrastructure.agent.plugins.registry import (
    AgentPluginRegistry,
    ChannelAdapterBuildContext,
)
from src.infrastructure.agent.plugins.state_store import PluginStateStore


@pytest.mark.unit
@pytest.mark.asyncio
async def test_feishu_plugin_registers_channel_adapter_factory() -> None:
    """Local Feishu plugin should register a factory that builds FeishuAdapter."""
    plugin_entry = Path.cwd() / ".memstack" / "plugins" / "feishu" / "plugin.py"
    assert plugin_entry.exists()

    discovered, discovery_diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=Path.cwd()),
        include_builtins=False,
        include_entrypoints=False,
        include_local_paths=True,
    )
    assert discovery_diagnostics == []
    feishu_plugins = [item for item in discovered if item.name == "feishu-channel-plugin"]
    assert len(feishu_plugins) == 1

    registry = AgentPluginRegistry()
    loader = AgentPluginLoader(registry=registry)
    diagnostics = await loader.load_plugins([feishu_plugins[0].plugin])
    assert diagnostics == []

    adapter, build_diagnostics = await registry.build_channel_adapter(
        ChannelAdapterBuildContext(
            channel_type="feishu",
            config_model=object(),
            channel_config=ChannelConfig(
                enabled=True,
                app_id="cli_test",
                app_secret="secret",
            ),
        )
    )

    assert isinstance(adapter, FeishuAdapter)
    assert any(d.code == "channel_adapter_loaded" for d in build_diagnostics)
