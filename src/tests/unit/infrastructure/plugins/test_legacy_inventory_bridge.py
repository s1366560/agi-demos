"""Unit tests for the legacy (V1) to kernel (V2) inventory bridge."""

from __future__ import annotations

import pytest

from src.domain.model.plugins import (
    CapabilityKind,
    PluginManifest,
    PluginRuntimeKind,
    PluginTrust,
    ProvidedCapability,
)
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry
from src.infrastructure.plugins.context import CapabilityRegistry, PluginContext
from src.infrastructure.plugins.legacy_inventory_bridge import (
    LegacyInventoryBridge,
    LegacyPluginFacts,
)


def _bridge() -> tuple[AgentPluginRegistry, CapabilityRegistry, LegacyInventoryBridge]:
    legacy = AgentPluginRegistry()
    kernel = CapabilityRegistry()
    return legacy, kernel, LegacyInventoryBridge(legacy, kernel)


def _snapshot_keys(kernel: CapabilityRegistry) -> set[tuple[str, str, str]]:
    return {(row["plugin_id"], row["kind"], row["id"]) for row in kernel.snapshot()}


@pytest.mark.unit
def test_tool_factory_without_facts_mirrors_aggregate_capability() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_tool_factory("acme", lambda ctx: {})

    receipt = bridge.sync()

    assert receipt.mirrored_plugins == ("acme",)
    assert receipt.mirrored_capabilities == 1
    assert ("acme", "tool", "tool-factory") in _snapshot_keys(kernel)
    record = kernel.get(CapabilityKind.TOOL, "tool-factory", plugin_id="acme")
    assert record is not None
    assert record.contract == "tool-factory:acme"


@pytest.mark.unit
def test_tool_factory_with_facts_mirrors_each_declared_tool() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_tool_factory("acme", lambda ctx: {})
    facts = {"acme": LegacyPluginFacts(tool_names=("search", "browse"))}

    receipt = bridge.sync(facts=facts)

    assert receipt.mirrored_capabilities == 2
    assert ("acme", "tool", "search") in _snapshot_keys(kernel)
    assert ("acme", "tool", "browse") in _snapshot_keys(kernel)


@pytest.mark.unit
def test_skill_factory_with_facts_mirrors_skill_provider() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_skill_factory("acme", lambda ctx: [])
    facts = {"acme": LegacyPluginFacts(skill_ids=("deep-research",))}

    bridge.sync(facts=facts)

    assert ("acme", "skill_provider", "deep-research") in _snapshot_keys(kernel)


@pytest.mark.unit
def test_channel_adapter_mirrors_under_owning_plugin() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_channel_adapter_factory("acme", "feishu", lambda ctx: object())

    bridge.sync()

    record = kernel.get(CapabilityKind.CHANNEL, "feishu", plugin_id="acme")
    assert record is not None
    assert record.contract == "channel:feishu"


@pytest.mark.unit
def test_same_hook_name_across_plugins_is_namespaced() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_hook("alpha", "before_response", lambda payload: payload)
    legacy.register_hook("beta", "before_response", lambda payload: payload)

    bridge.sync()

    assert kernel.get(CapabilityKind.HOOK, "before_response", plugin_id="alpha") is not None
    assert kernel.get(CapabilityKind.HOOK, "before_response", plugin_id="beta") is not None


@pytest.mark.unit
def test_lifecycle_hooks_mirror_with_lifecycle_contract() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_lifecycle_hook("acme", "on_load", lambda: None)

    bridge.sync()

    record = kernel.get(CapabilityKind.HOOK, "lifecycle-on_load", plugin_id="acme")
    assert record is not None
    assert record.contract == "lifecycle:on_load"


@pytest.mark.unit
def test_http_cli_and_subagent_registrations_mirror() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_http_route("acme", "GET", "/plugins/acme/status", lambda: None)
    legacy.register_cli_command("acme", "acme-run", lambda payload: None)
    legacy.register_subagent_resolver_factory("acme", lambda ctx: None)

    receipt = bridge.sync()

    keys = _snapshot_keys(kernel)
    assert ("acme", "http_route", "get-plugins-acme-status") in keys
    assert ("acme", "cli_command", "acme-run") in keys
    assert ("acme", "subagent_provider", "subagent-resolver") in keys
    assert receipt.mirrored_capabilities == 3


@pytest.mark.unit
def test_unmapped_buckets_report_diagnostics() -> None:
    legacy, _kernel, bridge = _bridge()
    legacy.register_command("acme", "agent-cmd", lambda payload: None)
    legacy.register_service("acme", "svc", object())
    legacy.register_provider("acme", "prov", object())

    receipt = bridge.sync()

    assert receipt.mirrored_capabilities == 0
    codes = [diagnostic.code for diagnostic in receipt.diagnostics]
    assert codes.count("unmapped_legacy_capability") == 3


@pytest.mark.unit
def test_duplicate_capabilities_collapse_with_diagnostic() -> None:
    legacy, _kernel, bridge = _bridge()
    legacy.register_tool_factory("acme", lambda ctx: {})
    facts = {"acme": LegacyPluginFacts(tool_names=("search", "search"))}

    receipt = bridge.sync(facts=facts)

    assert receipt.mirrored_capabilities == 1
    assert any(d.code == "duplicate_capability" for d in receipt.diagnostics)


@pytest.mark.unit
def test_resync_replaces_generation_and_removed_plugins_unwind() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_tool_factory("acme", lambda ctx: {})
    legacy.register_hook("acme", "on_error", lambda payload: payload)
    bridge.sync()
    assert kernel.get(CapabilityKind.HOOK, "on_error", plugin_id="acme") is not None

    # Second sync with the same state keeps the inventory stable.
    receipt = bridge.sync()
    assert receipt.mirrored_capabilities == 2

    # Disabling the legacy plugin unwinds only its mirrored records.
    legacy.unregister_plugin("acme")
    receipt = bridge.sync()
    assert receipt.mirrored_plugins == ()
    assert _snapshot_keys(kernel) == set()
    assert any(d.code == "mirror_removed" for d in receipt.diagnostics)


@pytest.mark.unit
def test_foreign_owned_capability_is_not_replaced_or_removed() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_tool_factory("acme", lambda ctx: {})
    facts = {"acme": LegacyPluginFacts(tool_names=("search",))}
    bridge.sync(facts=facts)

    # A kernel path registers the same key outside the bridge.
    manifest = PluginManifest(
        schema_version=1,
        id="acme",
        version="1.0.0",
        runtime=PluginRuntimeKind.PYTHON_TRUSTED,
        trust=PluginTrust.BUILTIN,
        provides=(
            ProvidedCapability(kind=CapabilityKind.TOOL, id="search", contract="tool:search"),
        ),
    )
    bridge.close()  # simulate bridge teardown before kernel claim
    context = PluginContext(kernel, manifest)
    context.register_capability(CapabilityKind.TOOL, "search", object())

    receipt = bridge.sync(facts=facts)

    assert receipt.mirrored_capabilities == 0
    assert any(d.code == "foreign_capability_conflict" for d in receipt.diagnostics)
    record = kernel.get(CapabilityKind.TOOL, "search", plugin_id="acme")
    assert record is not None


@pytest.mark.unit
def test_close_unwinds_all_mirrored_registrations() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_tool_factory("acme", lambda ctx: {})
    legacy.register_hook("beta", "on_error", lambda payload: payload)
    bridge.sync()
    assert len(kernel.snapshot()) == 2

    bridge.close()

    assert kernel.snapshot() == []


@pytest.mark.unit
def test_unregister_plugin_removes_single_mirror() -> None:
    legacy, kernel, bridge = _bridge()
    legacy.register_tool_factory("acme", lambda ctx: {})
    legacy.register_tool_factory("beta", lambda ctx: {})
    bridge.sync()

    assert bridge.unregister_plugin("acme") is True
    assert bridge.unregister_plugin("acme") is False
    assert kernel.get(CapabilityKind.TOOL, "tool-factory", plugin_id="acme") is None
    assert kernel.get(CapabilityKind.TOOL, "tool-factory", plugin_id="beta") is not None


@pytest.mark.unit
def test_trust_mapping_follows_discovery_source() -> None:
    assert LegacyPluginFacts(source="builtin").trust is PluginTrust.BUILTIN
    assert LegacyPluginFacts(source="builtin manifest").trust is PluginTrust.BUILTIN
    assert LegacyPluginFacts(source="entrypoint").trust is PluginTrust.SIGNED
    assert LegacyPluginFacts(source="local").trust is PluginTrust.SIGNED
    assert LegacyPluginFacts().trust is PluginTrust.SIGNED
