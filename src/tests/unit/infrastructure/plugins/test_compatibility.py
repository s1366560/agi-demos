import pytest

from src.infrastructure.agent.plugins.registry import AgentPluginRegistry
from src.infrastructure.plugins import CapabilityRegistry
from src.infrastructure.plugins.compatibility import register_builtin_kernel_plugins


@pytest.mark.unit
def test_builtin_registration_is_reversible_in_both_registries():
    legacy = AgentPluginRegistry()
    capabilities = CapabilityRegistry()

    dispose = register_builtin_kernel_plugins(
        capabilities,
        legacy,
        scope=None,
    )

    assert capabilities.list_capabilities("workspace-runtime")
    assert capabilities.list_capabilities("sisyphus-runtime")
    assert legacy.list_skill_factories()["workspace-runtime"]
    assert legacy.list_hooks()["on_session_start"]["workspace-runtime"]

    dispose()
    assert capabilities.list_capabilities("workspace-runtime") == ()
    assert capabilities.list_capabilities("sisyphus-runtime") == ()
    assert "workspace-runtime" not in legacy.list_skill_factories()
    assert "workspace-runtime" not in legacy.list_hooks().get("on_session_start", {})
    assert "sisyphus-runtime" not in legacy.list_hooks().get("on_session_start", {})
