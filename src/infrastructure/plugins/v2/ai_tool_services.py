"""Generation-owned tenant and LLM seams for lightweight AI tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.factories import create_llm_client
from src.domain.llm_providers.llm_types import LLMClient
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import UserTenant

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AI_TOOL_TENANT_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/ai-tool-tenant-provider"
AI_TOOL_TENANT_PROVIDER_SERVICE_V2 = "service:persistence.ai-tool-tenant-provider"
AI_TOOL_APPLICATION_MODULE_V2 = "builtin://memstack/application/ai-tool-services"
AI_TOOL_APPLICATION_SERVICE_V2 = "service:application.ai-tool-services"
AI_TOOL_TENANT_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

AiToolClientFactoryV2 = Callable[[str | None], Awaitable[LLMClient | None]]


class AiToolServiceErrorV2(Exception):
    """Base class for typed lightweight AI-tool failures."""


class AiToolClientUnavailableV2(AiToolServiceErrorV2):
    """The active tenant has no usable generation-owned LLM client."""


@runtime_checkable
class AiToolTenantPersistenceProtocolV2(Protocol):
    """Resolve the tenant used by lightweight AI operations."""

    async def resolve_tenant_id(
        self,
        *,
        user_id: str,
        declared_tenant_id: str | None,
    ) -> str | None: ...


@dataclass(frozen=True, kw_only=True)
class SqlAiToolTenantPersistenceV2:
    """SQL tenant resolver bound to exactly one operation-owned session."""

    _session: AsyncSession

    async def resolve_tenant_id(
        self,
        *,
        user_id: str,
        declared_tenant_id: str | None,
    ) -> str | None:
        if declared_tenant_id is not None:
            normalized = declared_tenant_id.strip()
            if normalized:
                return normalized
        result = await self._session.execute(
            refresh_select_statement(
                select(UserTenant.tenant_id).where(UserTenant.user_id == user_id).limit(1)
            )
        )
        tenant_id = result.scalar_one_or_none()
        return tenant_id if isinstance(tenant_id, str) else None


@dataclass(frozen=True, kw_only=True)
class AiToolApplicationServicesV2:
    """Resolve one tenant-bound LLM client without static router fallback."""

    persistence: AiToolTenantPersistenceProtocolV2
    client_factory: AiToolClientFactoryV2

    async def resolve_client(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
    ) -> LLMClient:
        resolved_tenant_id = await self.persistence.resolve_tenant_id(
            user_id=user_id,
            declared_tenant_id=tenant_id,
        )
        client = await self.client_factory(resolved_tenant_id)
        if client is None:
            raise AiToolClientUnavailableV2
        return client


@runtime_checkable
class AiToolTenantServiceFactoryProtocolV2(Protocol):
    """Provider contract hiding concrete tenant persistence construction."""

    def build(self, operation: OperationContextV2) -> AiToolTenantPersistenceProtocolV2: ...


@runtime_checkable
class AiToolApplicationResolverProtocolV2(Protocol):
    """Resolve operation-owned AI-tool services through a declared alias."""

    def resolve(self, operation: OperationContextV2) -> AiToolApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAiToolTenantServiceFactoryV2:
    """Build tenant persistence from the operation's exact AsyncSession."""

    strategy: str

    def build(self, operation: OperationContextV2) -> AiToolTenantPersistenceProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "ai-tool services require an AsyncSession operation service",
            )
        return SqlAiToolTenantPersistenceV2(_session=db)


@dataclass(frozen=True, kw_only=True)
class AiToolApplicationResolverV2:
    """Resolve operation-owned AI-tool services without exposing the Provider."""

    provider: AiToolTenantServiceFactoryProtocolV2
    client_factory: AiToolClientFactoryV2

    def resolve(self, operation: OperationContextV2) -> AiToolApplicationServicesV2:
        return AiToolApplicationServicesV2(
            persistence=self.provider.build(operation),
            client_factory=self.client_factory,
        )


async def _create_ai_tool_client_v2(tenant_id: str | None) -> LLMClient | None:
    return cast(LLMClient | None, await create_llm_client(tenant_id))


def _apply_ai_tool_tenant_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("ai-tool tenant provider requires strategy request-async-session")
    _ = context.provide(
        AI_TOOL_TENANT_PROVIDER_SERVICE_V2,
        SqlAiToolTenantServiceFactoryV2(strategy=strategy),
        label="ai-tool-tenant-provider",
    )


def _apply_ai_tool_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("ai-tool application resolver requires strategy operation-scoped-provider")
    provider = context.require(AI_TOOL_TENANT_PROVIDER_INJECT_V2)
    if not isinstance(provider, AiToolTenantServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_ai_tool_tenant_provider",
            "ai-tool tenant provider inject does not implement the factory contract",
        )
    _ = context.provide(
        AI_TOOL_APPLICATION_SERVICE_V2,
        AiToolApplicationResolverV2(
            provider=provider,
            client_factory=_create_ai_tool_client_v2,
        ),
        label="ai-tool-application",
    )


def ai_tool_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the AI-tool tenant Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=AI_TOOL_TENANT_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AI_TOOL_TENANT_PROVIDER_MODULE_V2),
            apply=_apply_ai_tool_tenant_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AI_TOOL_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AI_TOOL_APPLICATION_MODULE_V2),
            apply=_apply_ai_tool_application_v2,
        ),
    )


__all__ = [
    "AI_TOOL_APPLICATION_MODULE_V2",
    "AI_TOOL_APPLICATION_SERVICE_V2",
    "AI_TOOL_TENANT_PROVIDER_INJECT_V2",
    "AI_TOOL_TENANT_PROVIDER_MODULE_V2",
    "AI_TOOL_TENANT_PROVIDER_SERVICE_V2",
    "AiToolApplicationResolverProtocolV2",
    "AiToolApplicationResolverV2",
    "AiToolApplicationServicesV2",
    "AiToolClientFactoryV2",
    "AiToolClientUnavailableV2",
    "AiToolServiceErrorV2",
    "AiToolTenantPersistenceProtocolV2",
    "AiToolTenantServiceFactoryProtocolV2",
    "SqlAiToolTenantPersistenceV2",
    "SqlAiToolTenantServiceFactoryV2",
    "ai_tool_service_definitions_v2",
]
