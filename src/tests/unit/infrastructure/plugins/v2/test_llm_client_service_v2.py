"""Generation-owned tenant LLM client coverage."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.llm_providers.models import OperationType
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.llm_client_service import (
    TENANT_LLM_CLIENT_FACTORY_SERVICE_V2,
    TenantLlmClientFactoryV2,
    lease_tenant_llm_client_v2,
)

pytestmark = pytest.mark.unit


async def test_factory_resolves_exact_tenant_provider_and_native_client() -> None:
    db = object()
    repository = object()
    provider = object()
    client = object()
    catalog = object()
    resolver = SimpleNamespace(resolve_provider=AsyncMock(return_value=provider))

    with (
        patch(
            "src.infrastructure.persistence.llm_providers_repository."
            "SQLAlchemyProviderRepository",
            return_value=repository,
        ) as repository_type,
        patch(
            "src.application.services.provider_resolution_service.ProviderResolutionService",
            return_value=resolver,
        ) as resolver_type,
        patch(
            "src.infrastructure.llm.model_catalog.get_model_catalog_service",
            return_value=catalog,
        ),
        patch(
            "src.infrastructure.llm.litellm.litellm_client.create_litellm_client",
            return_value=client,
        ) as create_client,
    ):
        result = await TenantLlmClientFactoryV2().create(db=db, tenant_id="tenant-a")

    assert result is client
    repository_type.assert_called_once_with(session=db)
    resolver_type.assert_called_once_with(repository)
    resolver.resolve_provider.assert_awaited_once_with(
        tenant_id="tenant-a",
        operation_type=OperationType.LLM,
    )
    create_client.assert_called_once_with(provider, catalog=catalog)


async def test_client_lease_holds_exact_generation_for_complete_consumer_scope() -> None:
    client = object()
    factory = SimpleNamespace(create=AsyncMock(return_value=client))
    generation = SimpleNamespace(
        descriptor=PluginGenerationDescriptorV2(
            profile_id="profile-v2",
            generation=7,
            digest="a" * 64,
        ),
        resolve=Mock(return_value=factory),
    )
    lease = _Lease(generation)
    host = SimpleNamespace(acquire=AsyncMock(return_value=lease))
    install_process_generation_host_v2(host)
    try:
        async with lease_tenant_llm_client_v2(db="db", tenant_id="tenant-a") as resolved:
            assert resolved is client
            assert lease.active is True
            service, scope = generation.resolve.call_args.args
            assert service == TENANT_LLM_CLIENT_FACTORY_SERVICE_V2
            assert scope.kind is ScopeKindV2.TENANT
            assert scope.tenant_id == "tenant-a"
    finally:
        clear_process_generation_host_v2(host)

    assert lease.active is False
    factory.create.assert_awaited_once_with(db="db", tenant_id="tenant-a")


class _Lease:
    def __init__(self, generation: object) -> None:
        self.generation = generation
        self.active = False

    async def __aenter__(self) -> object:
        self.active = True
        return self.generation

    async def __aexit__(self, *_args: object) -> None:
        self.active = False
