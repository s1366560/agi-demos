"""Unit tests for plugin runtime state store metadata persistence."""

import pytest

from src.infrastructure.agent.plugins.state_store import PluginStateStore


@pytest.mark.unit
def test_update_plugin_persists_manifest_metadata_lists(tmp_path) -> None:
    """update_plugin should persist normalized manifest metadata fields."""
    store = PluginStateStore(base_path=tmp_path)

    store.update_plugin(
        "demo-plugin",
        kind="channel",
        manifest_id="demo-plugin",
        channels=[" feishu ", "", "feishu"],
        providers=["provider-a"],
        skills=["skill-a", "skill-b"],
    )

    plugin_state = store.get_plugin("demo-plugin")
    assert plugin_state["kind"] == "channel"
    assert plugin_state["manifest_id"] == "demo-plugin"
    assert plugin_state["channels"] == ["feishu", "feishu"]
    assert plugin_state["providers"] == ["provider-a"]
    assert plugin_state["skills"] == ["skill-a", "skill-b"]


@pytest.mark.unit
def test_get_plugin_tenant_scope_falls_back_to_global_metadata(tmp_path) -> None:
    """Tenant-scoped reads should inherit global metadata when tenant value is missing."""
    store = PluginStateStore(base_path=tmp_path)
    store.update_plugin(
        "demo-plugin",
        kind="channel",
        manifest_id="global-demo-plugin",
        providers=["global-provider"],
    )
    store.update_plugin("demo-plugin", enabled=False, tenant_id="tenant-1")

    plugin_state = store.get_plugin("demo-plugin", tenant_id="tenant-1")
    assert plugin_state["enabled"] is False
    assert plugin_state["kind"] == "channel"
    assert plugin_state["manifest_id"] == "global-demo-plugin"
    assert plugin_state["providers"] == ["global-provider"]
