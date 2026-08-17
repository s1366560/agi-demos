from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.application.services.llm_provider_manager import LLMProviderManager
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.plugins.context import PluginScopeContext


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
