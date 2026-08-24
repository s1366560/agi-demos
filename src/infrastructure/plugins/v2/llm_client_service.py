"""Generation-owned tenant LLM client factory and background-operation lease."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.domain.llm_providers.llm_types import LLMClient

TENANT_LLM_CLIENT_FACTORY_MODULE_V2 = "builtin://memstack/llm/tenant-client-factory"
TENANT_LLM_CLIENT_FACTORY_SERVICE_V2 = "service:llm.tenant-client-factory"


@runtime_checkable
class TenantLlmClientFactoryProtocolV2(Protocol):
    async def create(self, *, db: AsyncSession, tenant_id: str) -> LLMClient: ...


class TenantLlmClientFactoryV2:
    """Resolve one tenant provider and create its native client without fallback."""

    async def create(self, *, db: AsyncSession, tenant_id: str) -> LLMClient:
        if not tenant_id.strip():
            raise RuntimeV2Error(
                "llm_tenant_missing",
                "tenant LLM client resolution requires a non-empty tenant_id",
            )

        from src.application.services.provider_resolution_service import (
            ProviderResolutionService,
        )
        from src.domain.llm_providers.models import OperationType
        from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
        from src.infrastructure.llm.model_catalog import get_model_catalog_service
        from src.infrastructure.persistence.llm_providers_repository import (
            SQLAlchemyProviderRepository,
        )

        repository = SQLAlchemyProviderRepository(session=db)
        provider = await ProviderResolutionService(repository).resolve_provider(
            tenant_id=tenant_id,
            operation_type=OperationType.LLM,
        )
        return create_litellm_client(provider, catalog=get_model_catalog_service())


def _apply_tenant_llm_client_factory_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config:
        raise ValueError("tenant LLM client factory does not accept config")
    context.provide(
        TENANT_LLM_CLIENT_FACTORY_SERVICE_V2,
        TenantLlmClientFactoryV2(),
        label="tenant-llm-client-factory",
    )


def builtin_tenant_llm_client_factory_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=TENANT_LLM_CLIENT_FACTORY_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TENANT_LLM_CLIENT_FACTORY_MODULE_V2),
        apply=_apply_tenant_llm_client_factory_v2,
    )


@asynccontextmanager
async def lease_tenant_llm_client_v2(
    *,
    db: AsyncSession,
    tenant_id: str,
) -> AsyncIterator[LLMClient]:
    """Hold one immutable generation while a background consumer uses its client."""
    if not tenant_id.strip():
        raise RuntimeV2Error(
            "llm_tenant_missing",
            "tenant LLM client lease requires a non-empty tenant_id",
        )

    from .boundary import current_process_generation_host_v2, pin_generation_v2

    host = current_process_generation_host_v2()
    async with pin_generation_v2(host) as generation:
        factory = generation.resolve(
            TENANT_LLM_CLIENT_FACTORY_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id),
        )
        if not isinstance(factory, TenantLlmClientFactoryProtocolV2):
            raise RuntimeV2Error(
                "llm_client_factory_invalid",
                "resolved tenant LLM client factory does not implement create",
            )
        yield await factory.create(db=db, tenant_id=tenant_id)


__all__ = [
    "TENANT_LLM_CLIENT_FACTORY_MODULE_V2",
    "TENANT_LLM_CLIENT_FACTORY_SERVICE_V2",
    "TenantLlmClientFactoryProtocolV2",
    "TenantLlmClientFactoryV2",
    "builtin_tenant_llm_client_factory_definition_v2",
    "lease_tenant_llm_client_v2",
]
