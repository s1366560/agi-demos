import pytest

from src.domain.model.plugins import parse_plugin_manifest
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry
from src.infrastructure.plugins import CapabilityRegistry
from src.infrastructure.plugins.compatibility import (
    activate_profile_snapshot,
    register_builtin_kernel_plugins,
)
from src.infrastructure.plugins.llm_adapters import (
    LlmAdapterProviderRegistry,
    RoutedLlmAdapterProvider,
)
from src.infrastructure.plugins.profile import compose_profile, parse_profile_document


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


@pytest.mark.unit
def test_profile_activation_registers_llm_adapter_provider_reversibly() -> None:
    manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "llm-openai-plugin",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "provides": [
                {
                    "kind": "llm_provider",
                    "id": "openai",
                    "contract": "llm_adapter:openai",
                    "permissions": ["llm.invoke"],
                }
            ],
        }
    )
    snapshot = compose_profile(
        parse_profile_document(
            {
                "profile": {
                    "id": "llm-adapter-test",
                    "layers": [{"id": "providers", "plugins": [{"id": "llm-openai-plugin"}]}],
                }
            }
        ),
        {"llm-openai-plugin": manifest},
    )
    capabilities = CapabilityRegistry()
    adapters = LlmAdapterProviderRegistry()

    dispose = activate_profile_snapshot(
        snapshot,
        capabilities,
        adapter_registry=adapters,
    )

    provider = adapters.get("openai")
    assert isinstance(provider, RoutedLlmAdapterProvider)
    assert capabilities.list_capabilities("llm-openai-plugin")[0].implementation is provider

    dispose()
    assert adapters.get("openai") is None
    assert capabilities.list_capabilities("llm-openai-plugin") == ()
