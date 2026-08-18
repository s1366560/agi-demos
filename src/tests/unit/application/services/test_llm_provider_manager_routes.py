from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from src.application.services.llm_provider_manager import LLMProviderManager
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.resilience.health_checker import HealthCheckResult, HealthStatus
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.llm_adapters import (
    LlmAdapterProviderRegistry,
    LlmAdapterRequest,
)
from src.infrastructure.plugins.shadow_rollout import (
    queued_event_count,
    reset_shadow_rollout_queue_for_test,
)


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
async def test_llm_shadow_records_redacted_route_parity_for_selected_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_shadow_rollout_queue_for_test()
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(
            platform_plugin_llm_v2=False,
            platform_plugin_llm_shadow=True,
            platform_plugin_llm_shadow_percent=100,
            platform_plugin_shadow_scope_allowlist=None,
        ),
    )
    manager = LLMProviderManager()
    config = _provider_config()
    manager.register_provider(config)
    captured: list[object] = []

    def capture_event(event: object) -> bool:
        captured.append(event)
        return True

    monkeypatch.setattr(
        "src.infrastructure.plugins.shadow_rollout.enqueue_shadow_rollout_event",
        capture_event,
    )
    manager._record_llm_route_shadow(config, "tenant-rollout", None)

    assert len(captured) == 1
    record = captured[0]
    assert record.capability == "llm_routes"
    assert record.event_name == "llm.route"
    assert record.scope_id == "tenant-rollout"
    assert record.equal is True
    assert record.legacy_payload == record.typed_payload
    assert queued_event_count() == 0
    reset_shadow_rollout_queue_for_test()


@pytest.mark.unit
async def test_llm_shadow_excludes_unselected_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_shadow_rollout_queue_for_test()
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(
            platform_plugin_llm_v2=False,
            platform_plugin_llm_shadow=True,
            platform_plugin_llm_shadow_percent=0,
            platform_plugin_shadow_scope_allowlist=None,
        ),
    )
    manager = LLMProviderManager()
    config = _provider_config()
    manager.register_provider(config)

    manager._record_llm_route_shadow(config, "tenant-excluded", None)

    assert queued_event_count() == 0


@pytest.mark.unit
async def test_typed_adapter_provider_replaces_legacy_registry_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[LlmAdapterRequest] = []
    expected_client = cast(LLMClient, SimpleNamespace(name="adapter-result"))

    class AdapterProvider:
        def create_adapter(self, request: LlmAdapterRequest) -> LLMClient:
            requests.append(request)
            return expected_client

    class HealthyProviders:
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

    class OpenCircuitBreakers:
        def get(self, provider_type: ProviderType) -> Any:
            _ = provider_type
            return SimpleNamespace(can_execute=lambda: True, record_failure=lambda: None)

    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(
            platform_plugin_llm_v2=True,
            platform_plugin_llm_shadow=False,
        ),
    )
    manager = LLMProviderManager(
        circuit_breaker_registry=cast(Any, OpenCircuitBreakers()),
        health_checker=cast(Any, HealthyProviders()),
        adapter_provider=AdapterProvider(),
    )
    config = _provider_config()
    manager.register_provider(config)

    client = await manager.get_llm_client(preferred_provider=ProviderType.OPENAI)

    assert client is expected_client
    assert len(requests) == 1
    assert requests[0].route is not None
    assert requests[0].route.model_id == "test-model"
    assert requests[0].provider_config is config


@pytest.mark.unit
async def test_llm_legacy_removal_uses_only_registered_adapter_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_client = cast(LLMClient, SimpleNamespace(name="registered-adapter"))

    class RegisteredProvider:
        def create_adapter(self, request: LlmAdapterRequest) -> LLMClient:
            assert request.route is not None
            assert request.provider_config.provider_type == ProviderType.OPENAI
            return expected_client

    class LegacyProvider:
        def create_adapter(self, request: LlmAdapterRequest) -> LLMClient:
            raise AssertionError(f"legacy fallback must not run for {request.provider_config.id}")

    class HealthyProviders:
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

    class OpenCircuitBreakers:
        def get(self, provider_type: ProviderType) -> Any:
            _ = provider_type
            return SimpleNamespace(can_execute=lambda: True, record_failure=lambda: None)

    registry = LlmAdapterProviderRegistry()
    dispose = registry.register(
        "openai",
        RegisteredProvider(),
        owner="signed-llm-plugin",
    )
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(
            platform_plugin_llm_v2=True,
            platform_plugin_llm_remove_legacy=True,
            platform_plugin_llm_shadow=False,
        ),
    )
    manager = LLMProviderManager(
        circuit_breaker_registry=cast(Any, OpenCircuitBreakers()),
        health_checker=cast(Any, HealthyProviders()),
        adapter_provider=LegacyProvider(),
        adapter_registry=registry,
    )
    manager.register_provider(_provider_config())

    client = await manager.get_llm_client(preferred_provider=ProviderType.OPENAI)

    assert client is expected_client
    dispose()
    assert registry.get("openai") is None


@pytest.mark.unit
async def test_llm_legacy_removal_fails_loud_without_registered_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LegacyProvider:
        def create_adapter(self, request: LlmAdapterRequest) -> LLMClient:
            raise AssertionError(f"legacy fallback must not run for {request.provider_config.id}")

    class HealthyProviders:
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

    class OpenCircuitBreakers:
        def get(self, provider_type: ProviderType) -> Any:
            _ = provider_type
            return SimpleNamespace(can_execute=lambda: True, record_failure=lambda: None)

    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(
            platform_plugin_llm_v2=True,
            platform_plugin_llm_remove_legacy=True,
            platform_plugin_llm_shadow=False,
        ),
    )
    manager = LLMProviderManager(
        circuit_breaker_registry=cast(Any, OpenCircuitBreakers()),
        health_checker=cast(Any, HealthyProviders()),
        adapter_provider=LegacyProvider(),
        adapter_registry=LlmAdapterProviderRegistry(),
    )
    manager.register_provider(_provider_config())

    with pytest.raises(RuntimeError, match="legacy LLM adapter fallback is disabled"):
        await manager.get_llm_client(preferred_provider=ProviderType.OPENAI)


@pytest.mark.unit
def test_llm_legacy_removal_requires_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(
            platform_plugin_llm_v2=False,
            platform_plugin_llm_remove_legacy=True,
            platform_plugin_llm_shadow=False,
        ),
    )
    manager = LLMProviderManager(adapter_registry=LlmAdapterProviderRegistry())

    with pytest.raises(ValueError, match="requires LLM routes V2"):
        manager._adapter_provider_for("openai")


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
