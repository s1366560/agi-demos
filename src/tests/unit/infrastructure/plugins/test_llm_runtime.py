import pytest

from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.llm_runtime import (
    CredentialLease,
    LlmRouteResolutionError,
    LlmRouteResolver,
    ProviderMetadataRegistry,
    ProviderRouteConfig,
)


class Resolver:
    async def resolve(self, _scope, credential):
        return CredentialLease(value="secret-value", credential=credential)


def _resolver() -> LlmRouteResolver:
    return LlmRouteResolver(
        {
            "openai-compatible": ProviderRouteConfig(
                provider_id="openai-compatible",
                provider_type="openai_compatible",
                model_id="test-model",
                base_url="https://example.test",
                credential_ref="vault://llm/openai",
                credential_revision=4,
            )
        },
        Resolver(),
    )


@pytest.mark.unit
def test_route_resolves_without_credential_value() -> None:
    route = _resolver().resolve("openai-compatible")

    assert route.model_id == "test-model"
    assert route.credential.ref == "vault://llm/openai"
    assert route.credential.revision == 4


@pytest.mark.unit
async def test_credential_is_released_once_and_redacted() -> None:
    route = _resolver().resolve("openai-compatible")
    resolver = _resolver()
    scope = PluginScopeContext(tenant_id="tenant")

    lease_scope = await resolver.lease(scope, route)
    async with lease_scope as lease:
        assert repr(lease) == "CredentialLease(<redacted>)"
    with pytest.raises(RuntimeError, match="already released"):
        async with lease_scope:
            pass


@pytest.mark.unit
def test_unknown_provider_fails_loud() -> None:
    with pytest.raises(LlmRouteResolutionError, match="unknown LLM provider"):
        _resolver().resolve("missing")


@pytest.mark.unit
def test_provider_metadata_registry_is_deterministic() -> None:
    registry = ProviderMetadataRegistry()
    registry.register("z", {"kind": "llm"})
    registry.register("a", {"kind": "embedder"})

    assert registry.list() == ("a", "z")
