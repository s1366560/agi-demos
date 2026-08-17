import pytest

from src.infrastructure.agent.plugins.registry import AgentPluginRegistry


@pytest.mark.unit
def test_unregister_plugin_removes_only_owned_registrations():
    registry = AgentPluginRegistry()

    async def _handler(_payload):
        return None

    registry.register_tool_factory("plugin-a", lambda _ctx: {"tool": object()})
    registry.register_hook("plugin-a", "before_response", _handler)
    registry.register_tool_factory("plugin-b", lambda _ctx: {"other": object()})
    registry.register_hook("plugin-b", "before_response", _handler)

    removed = registry.unregister_plugin("plugin-a")

    assert "tool_factory" in removed
    assert "hook" in removed
    assert set(registry.list_tool_factories()) == {"plugin-b"}
    assert set(registry.list_hooks()["before_response"]) == {"plugin-b"}


@pytest.mark.unit
def test_unregister_plugin_is_idempotent():
    registry = AgentPluginRegistry()
    registry.register_tool_factory("plugin-a", lambda _ctx: {})

    assert registry.unregister_plugin("plugin-a") == ["tool_factory"]
    assert registry.unregister_plugin("plugin-a") == []
