"""Generation-owned Provider/Consumer seams for tenant agent configuration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.repositories.tenant_agent_config_repository import (
    TenantAgentConfigRepositoryPort,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_authority_repository import (
    SqlTenantAgentConfigAuthorityRepository,
    TenantAgentConfigAuthoritySnapshot,
    TenantAgentConfigAuthorityWrite,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
    SqlTenantAgentConfigRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/tenant-agent-config-provider"
)
TENANT_AGENT_CONFIG_PROVIDER_SERVICE_V2 = "service:persistence.tenant-agent-config-provider"
TENANT_AGENT_CONFIG_APPLICATION_MODULE_V2 = (
    "builtin://memstack/application/tenant-agent-config-services"
)
TENANT_AGENT_CONFIG_APPLICATION_SERVICE_V2 = "service:application.tenant-agent-config-services"
TENANT_AGENT_CONFIG_SESSIONS_INJECT_V2 = "sessions"
TENANT_AGENT_CONFIG_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

type TenantAgentConfigSessionFactoryV2 = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@runtime_checkable
class AsyncSessionFactoryProviderProtocolV2(Protocol):
    """Structural contract for the generation-selected session factory."""

    @property
    def factory(self) -> TenantAgentConfigSessionFactoryV2: ...


@runtime_checkable
class TenantAgentConfigAuthorityRepositoryProtocolV2(Protocol):
    """Transactional revision authority used without exposing its SQL constructor."""

    async def get_revision(self, tenant_id: str) -> int: ...

    async def lock_for_update(
        self,
        tenant_id: str,
        *,
        expected_revision: int,
    ) -> TenantAgentConfigAuthoritySnapshot: ...

    async def persist(
        self,
        snapshot: TenantAgentConfigAuthoritySnapshot,
        config: TenantAgentConfig,
    ) -> TenantAgentConfigAuthorityWrite: ...


@dataclass(frozen=True, kw_only=True)
class TenantAgentConfigApplicationServicesV2:
    """Operation-owned repositories used by tenant agent config handlers."""

    configs: TenantAgentConfigRepositoryPort
    authority: TenantAgentConfigAuthorityRepositoryProtocolV2


@runtime_checkable
class TenantAgentConfigServiceFactoryProtocolV2(Protocol):
    """Build HTTP repositories and load runtime policy through one Provider."""

    def build(self, operation: OperationContextV2) -> TenantAgentConfigApplicationServicesV2: ...

    async def load(self, tenant_id: str) -> TenantAgentConfig: ...


@runtime_checkable
class TenantAgentConfigApplicationResolverProtocolV2(Protocol):
    """Consumer seam for the generation-selected config Provider."""

    def resolve(
        self,
        operation: OperationContextV2,
    ) -> TenantAgentConfigApplicationServicesV2: ...

    async def load(self, tenant_id: str) -> TenantAgentConfig: ...


@dataclass(frozen=True, kw_only=True)
class SqlTenantAgentConfigServiceFactoryV2:
    """Bind SQL repositories to operation or generation-owned sessions."""

    sessions: AsyncSessionFactoryProviderProtocolV2

    def build(self, operation: OperationContextV2) -> TenantAgentConfigApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "tenant agent config services require an AsyncSession operation service",
            )
        return TenantAgentConfigApplicationServicesV2(
            configs=SqlTenantAgentConfigRepository(db),
            authority=SqlTenantAgentConfigAuthorityRepository(db),
        )

    async def load(self, tenant_id: str) -> TenantAgentConfig:
        """Load runtime policy without silently masking persistence failures."""
        try:
            async with self.sessions.factory() as db:
                config = await SqlTenantAgentConfigRepository(db).get_by_tenant(tenant_id)
        except RuntimeV2Error:
            raise
        except (RuntimeError, SQLAlchemyError) as exc:
            raise RuntimeV2Error(
                "tenant_agent_config_load_failed",
                "tenant agent configuration persistence is unavailable",
            ) from exc
        return config or TenantAgentConfig.create_default(tenant_id=tenant_id)


@dataclass(frozen=True, kw_only=True)
class TenantAgentConfigApplicationResolverV2:
    """Application Consumer for one explicitly injected persistence Provider."""

    provider: TenantAgentConfigServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> TenantAgentConfigApplicationServicesV2:
        return self.provider.build(operation)

    async def load(self, tenant_id: str) -> TenantAgentConfig:
        return await self.provider.load(tenant_id)


def current_tenant_agent_config_application_resolver_v2(
    tenant_id: str,
) -> TenantAgentConfigApplicationResolverProtocolV2:
    """Resolve runtime policy only from the generation pinned to this operation."""
    from .boundary import current_generation_v2

    resolver = current_generation_v2().resolve(
        TENANT_AGENT_CONFIG_APPLICATION_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id),
    )
    if not isinstance(resolver, TenantAgentConfigApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_tenant_agent_config_application_resolver",
            "tenant agent config application service has an invalid implementation",
        )
    return resolver


def _apply_tenant_agent_config_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-and-generation-session":
        raise ValueError(
            "tenant agent config provider requires strategy operation-and-generation-session"
        )
    sessions = context.require(TENANT_AGENT_CONFIG_SESSIONS_INJECT_V2)
    if not isinstance(sessions, AsyncSessionFactoryProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_tenant_agent_config_sessions",
            "tenant agent config sessions inject has an invalid implementation",
        )
    _ = context.provide(
        TENANT_AGENT_CONFIG_PROVIDER_SERVICE_V2,
        SqlTenantAgentConfigServiceFactoryV2(sessions=sessions),
        label="tenant-agent-config-provider",
    )


def _apply_tenant_agent_config_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-and-runtime-provider":
        raise ValueError(
            "tenant agent config resolver requires strategy operation-and-runtime-provider"
        )
    provider = context.require(TENANT_AGENT_CONFIG_PROVIDER_INJECT_V2)
    if not isinstance(provider, TenantAgentConfigServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_tenant_agent_config_provider",
            "tenant agent config provider inject does not implement the factory contract",
        )
    _ = context.provide(
        TENANT_AGENT_CONFIG_APPLICATION_SERVICE_V2,
        TenantAgentConfigApplicationResolverV2(provider=provider),
        label="tenant-agent-config-application",
    )


def tenant_agent_config_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for tenant agent config."""
    return (
        PluginDefinitionV2(
            module_ref=TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2),
            apply=_apply_tenant_agent_config_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=TENANT_AGENT_CONFIG_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TENANT_AGENT_CONFIG_APPLICATION_MODULE_V2),
            apply=_apply_tenant_agent_config_application_v2,
        ),
    )


__all__ = [
    "TENANT_AGENT_CONFIG_APPLICATION_MODULE_V2",
    "TENANT_AGENT_CONFIG_APPLICATION_SERVICE_V2",
    "TENANT_AGENT_CONFIG_PROVIDER_INJECT_V2",
    "TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2",
    "TENANT_AGENT_CONFIG_PROVIDER_SERVICE_V2",
    "TENANT_AGENT_CONFIG_SESSIONS_INJECT_V2",
    "AsyncSessionFactoryProviderProtocolV2",
    "SqlTenantAgentConfigServiceFactoryV2",
    "TenantAgentConfigApplicationResolverProtocolV2",
    "TenantAgentConfigApplicationResolverV2",
    "TenantAgentConfigApplicationServicesV2",
    "TenantAgentConfigAuthorityRepositoryProtocolV2",
    "TenantAgentConfigServiceFactoryProtocolV2",
    "TenantAgentConfigSessionFactoryV2",
    "current_tenant_agent_config_application_resolver_v2",
    "tenant_agent_config_service_definitions_v2",
]
