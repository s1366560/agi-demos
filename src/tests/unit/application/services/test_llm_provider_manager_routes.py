"""Tests for request-time LLM route resolution and routed adapter ownership."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from src.application.services.llm_provider_manager import LLMProviderManager
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.domain.model.plugins import parse_plugin_manifest
from src.infrastructure.llm.resilience.health_checker import HealthCheckResult, HealthStatus
from src.infrastructure.plugins import CapabilityRegistry
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.llm_adapters import (
    LlmAdapterProviderRegistry,
    LlmAdapterRequest,
    RoutedLlmAdapterProvider,
    get_llm_adapter_provider_registry,
)
from src.infrastructure.plugins.profile import (
    compose_profile,
    control_envelope,
    parse_profile_document,
)
from src.infrastructure.plugins.runtime_host import PlatformPluginRuntimeHost


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id=uuid4(),
        name="OpenAI compatible",
        provider_type=ProviderType.OPENAI,
        llm_model="test-model",
        base_url="https://example.test/v1",
        config={"timeout_seconds": 2, "context_window": 64000},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        api_key_encrypted="encrypted",
    )


@pytest.fixture(autouse=True)
def _clean_global_adapter_registry() -> Any:
    """Keep default-constructed managers from leaking global registrations."""
    yield
    registry = get_llm_adapter_provider_registry()
    for record in registry.list():
        registry.unregister(record.provider_id, owner=record.owner)


class _HealthyProviders:
    def register_provider(
        self,
        provider_type: ProviderType,
        provider_config: ProviderConfig,
    ) -> None:
        _ = provider_type, provider_config

    def unregister_provider(self, provider_type: ProviderType) -> None:
        _ = provider_type

    async def get_health(self, provider_type: ProviderType) -> HealthCheckResult:
        return HealthCheckResult(
            provider_type=provider_type,
            status=HealthStatus.HEALTHY,
        )


class _OpenCircuitBreakers:
    def get(self, provider_type: ProviderType) -> Any:
        _ = provider_type
        return SimpleNamespace(can_execute=lambda: True, record_failure=lambda: None)


def _manager(
    registry: LlmAdapterProviderRegistry,
    *,
    routed_adapter_factory: Any = None,
) -> LLMProviderManager:
    return LLMProviderManager(
        circuit_breaker_registry=cast(Any, _OpenCircuitBreakers()),
        health_checker=cast(Any, _HealthyProviders()),
        adapter_registry=registry,
        routed_adapter_factory=routed_adapter_factory,
    )


@pytest.mark.unit
def test_route_facade_resolves_reference_without_secret() -> None:
    manager = LLMProviderManager()
    config = _provider_config()
    manager.register_provider(config)

    route = manager.resolve_route(ProviderType.OPENAI)

    assert route.model_id == "test-model"
    assert route.timeout_ms == 2000
    assert route.context_window == 64000
    assert route.credential.ref.startswith("vault://llm-provider/")
    assert "api_key" not in route.credential.ref
    assert manager.provider_metadata.get("openai")["model_id"] == "test-model"


@pytest.mark.unit
async def test_credential_lease_fails_closed_without_vault() -> None:
    manager = LLMProviderManager()
    manager.register_provider(_provider_config())
    route = manager.resolve_route(ProviderType.OPENAI)

    with pytest.raises(RuntimeError, match="credential vault is not configured"):
        await manager.lease_route_credential(
            PluginScopeContext(tenant_id="tenant"),
            route,
        )


@pytest.mark.unit
async def test_registered_plugin_adapter_serves_requests() -> None:
    requests: list[LlmAdapterRequest] = []
    expected_client = cast(LLMClient, SimpleNamespace(name="adapter-result"))

    class AdapterProvider:
        def create_adapter(self, request: LlmAdapterRequest) -> LLMClient:
            requests.append(request)
            return expected_client

    registry = LlmAdapterProviderRegistry()
    _ = registry.register("openai", AdapterProvider(), owner="signed-llm-plugin")
    manager = _manager(registry)
    config = _provider_config()
    manager.register_provider(config)

    client = await manager.get_llm_client(preferred_provider=ProviderType.OPENAI)

    assert client is expected_client
    assert len(requests) == 1
    assert requests[0].route is not None
    assert requests[0].route.model_id == "test-model"
    assert requests[0].provider_config is config


@pytest.mark.unit
async def test_manager_registers_routed_adapter_on_provider_lifecycle() -> None:
    expected_client = cast(LLMClient, SimpleNamespace(name="routed-runtime-client"))

    def routed_factory(**kwargs: Any) -> LLMClient:
        assert kwargs["config"].model == "test-model"
        assert kwargs["config"].base_url == "https://example.test/v1"
        return expected_client

    registry = LlmAdapterProviderRegistry()
    manager = _manager(registry, routed_adapter_factory=routed_factory)
    config = _provider_config()

    manager.register_provider(config)
    assert registry.owner_of("openai") == f"llm-provider:{config.id}"
    client = await manager.get_llm_client(preferred_provider=ProviderType.OPENAI)

    assert client is expected_client
    manager.unregister_provider(ProviderType.OPENAI)
    assert registry.get("openai") is None


@pytest.mark.unit
async def test_missing_adapter_provider_fails_closed() -> None:
    registry = LlmAdapterProviderRegistry()
    manager = _manager(registry)
    manager.register_provider(_provider_config())
    manager._unregister_routed_adapter(ProviderType.OPENAI)

    with pytest.raises(RuntimeError, match="no routed LLM adapter provider is registered"):
        await manager.get_llm_client(preferred_provider=ProviderType.OPENAI)


@pytest.mark.unit
def test_llm_adapter_registry_is_reversible_and_rejects_ownership_conflict() -> None:
    class Provider:
        def create_adapter(self, request: LlmAdapterRequest) -> LLMClient:
            _ = request
            return cast(LLMClient, SimpleNamespace(name="adapter"))

    registry = LlmAdapterProviderRegistry()
    first = registry.register("openai", Provider(), owner="plugin-a")
    with pytest.raises(ValueError, match="already owned by plugin-a"):
        registry.register("openai", Provider(), owner="plugin-b")

    first()
    assert registry.get("openai") is None
    second = registry.register("openai", Provider(), owner="plugin-b")
    assert registry.get("openai") is not None
    second()


@pytest.mark.unit
def test_routed_adapter_provider_builds_client_without_legacy_registry() -> None:
    manager = LLMProviderManager()
    config = _provider_config()
    manager.register_provider(config)
    route = manager.resolve_route(ProviderType.OPENAI)
    expected_client = cast(LLMClient, SimpleNamespace(name="routed-client"))
    captured: list[tuple[object, object]] = []

    def factory(**kwargs: Any) -> LLMClient:
        captured.append((kwargs["config"], kwargs["provider_config"]))
        return expected_client

    provider = RoutedLlmAdapterProvider(factory=factory)
    client = provider.create_adapter(
        LlmAdapterRequest(
            route=route,
            provider_config=config,
            llm_config=None,
            adapter_kwargs={},
        )
    )

    assert client is expected_client
    assert captured[0][0].model == "test-model"
    assert captured[0][0].base_url == "https://example.test/v1"
    assert captured[0][1] is config


@pytest.mark.unit
async def test_profile_activated_adapter_serves_requests_end_to_end() -> None:
    """Compose -> reconcile -> registry -> manager through the typed path."""
    expected_client = cast(LLMClient, SimpleNamespace(name="profile-activated-client"))
    built_configs: list[Any] = []

    def routed_factory(**kwargs: Any) -> LLMClient:
        built_configs.append(kwargs["config"])
        return expected_client

    manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "llm-openai",
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
                    "id": "profile-e2e",
                    "layers": [{"id": "providers", "plugins": [{"id": "llm-openai"}]}],
                }
            }
        ),
        {"llm-openai": manifest},
    )
    registry = LlmAdapterProviderRegistry()
    host = PlatformPluginRuntimeHost(
        capability_registry=CapabilityRegistry(),
        adapter_registry=registry,
        llm_adapter_factory=routed_factory,
    )
    receipt = host.apply(snapshot, control_envelope(snapshot, version=1))
    assert receipt.accepted
    assert registry.owner_of("openai") == "llm-openai"

    manager = _manager(registry)
    manager.register_provider(_provider_config())

    client = await manager.get_llm_client(preferred_provider=ProviderType.OPENAI)

    assert client is expected_client
    assert built_configs[0].model == "test-model"
    assert built_configs[0].base_url == "https://example.test/v1"

    host.dispose()
    assert registry.get("openai") is None
    with pytest.raises(RuntimeError, match="no routed LLM adapter provider is registered"):
        await manager.get_llm_client(preferred_provider=ProviderType.OPENAI)


@pytest.mark.unit
def test_reregistering_provider_with_new_config_id_hands_off_adapter_ownership() -> None:
    registry = LlmAdapterProviderRegistry()
    manager = LLMProviderManager(adapter_registry=registry)
    first = _provider_config()
    second = _provider_config()

    manager.register_provider(first)
    first_owner = registry.owner_of("openai")
    manager.register_provider(second)
    second_owner = registry.owner_of("openai")

    assert first_owner == f"llm-provider:{first.id}"
    assert second_owner == f"llm-provider:{second.id}"

    manager.unregister_provider(ProviderType.OPENAI)
    assert registry.get("openai") is None
