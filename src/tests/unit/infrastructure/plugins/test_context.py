import pytest

from src.domain.model.plugins import CapabilityKind, parse_plugin_manifest
from src.infrastructure.plugins import CapabilityRegistry, PluginContext


def _manifest(plugin_id: str = "test-plugin"):
    return parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": plugin_id,
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "provides": [
                {"kind": "tool", "id": "demo_tool"},
                {"kind": "hook", "id": "before_response"},
            ],
        }
    )


@pytest.mark.unit
def test_context_registrations_are_reversible_in_reverse_order():
    registry = CapabilityRegistry()
    context = PluginContext(registry, _manifest())

    dispose_tool = context.register_tool("demo_tool", object())
    context.on("before_response", lambda payload: payload)
    assert [record["id"] for record in registry.snapshot()] == [
        "before_response",
        "demo_tool",
    ]

    context.close()
    assert registry.snapshot() == []
    assert context.closed
    dispose_tool()
    assert registry.snapshot() == []


@pytest.mark.unit
def test_undeclared_capability_is_rejected():
    registry = CapabilityRegistry()
    context = PluginContext(registry, _manifest())

    with pytest.raises(ValueError, match="does not declare"):
        context.register_tool("undeclared_tool", object())


@pytest.mark.unit
def test_conflicting_capability_owner_is_rejected():
    registry = CapabilityRegistry()
    first_manifest = _manifest("first-plugin")
    registry.register(
        first_manifest,
        CapabilityKind.TOOL,
        "demo_tool",
        object(),
        namespace=False,
    )

    second_manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "second-plugin",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "provides": [{"kind": "tool", "id": "demo_tool"}],
        }
    )
    with pytest.raises(RuntimeError, match="already owned by first-plugin"):
        registry.register(
            second_manifest,
            CapabilityKind.TOOL,
            "demo_tool",
            object(),
            namespace=False,
        )


@pytest.mark.unit
def test_context_only_returns_authorized_secret_references():
    registry = CapabilityRegistry()
    context = PluginContext(
        registry,
        _manifest(),
        secret_grants={"llm": "vault://tenant/llm"},
    )

    assert context.secret_ref("llm") == "vault://tenant/llm"
    with pytest.raises(PermissionError, match="not granted secret missing"):
        context.secret_ref("missing")


@pytest.mark.unit
def test_capability_lookup_by_contract_and_kind():
    registry = CapabilityRegistry()
    implementation = object()
    context = PluginContext(registry, _manifest())
    context.register_capability(CapabilityKind.TOOL, "demo_tool", implementation)

    assert (
        registry.get(CapabilityKind.TOOL, "demo_tool", plugin_id="test-plugin").implementation
        is implementation
    )
    assert registry.get_by_contract("tool:demo_tool").plugin_id == "test-plugin"
