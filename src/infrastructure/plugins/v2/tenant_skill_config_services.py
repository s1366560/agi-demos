"""Generation-owned Provider/Consumer seams for tenant skill configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.domain.ports.repositories.tenant_skill_config_repository import (
    TenantSkillConfigRepositoryPort,
)
from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
    SqlSkillRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_skill_config_repository import (
    SqlTenantSkillConfigRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TENANT_SKILL_CONFIG_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/tenant-skill-config-provider"
)
TENANT_SKILL_CONFIG_PROVIDER_SERVICE_V2 = "service:persistence.tenant-skill-config-provider"
TENANT_SKILL_CONFIG_APPLICATION_MODULE_V2 = (
    "builtin://memstack/application/tenant-skill-config-services"
)
TENANT_SKILL_CONFIG_APPLICATION_SERVICE_V2 = (
    "service:application.tenant-skill-config-services"
)
TENANT_SKILL_CONFIG_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class TenantSkillConfigApplicationServicesV2:
    """Operation-owned repositories used by tenant skill config handlers."""

    configs: TenantSkillConfigRepositoryPort
    skills: SkillRepositoryPort


@runtime_checkable
class TenantSkillConfigServiceFactoryProtocolV2(Protocol):
    """Build repositories without exposing SQL implementations to consumers."""

    def build(self, operation: OperationContextV2) -> TenantSkillConfigApplicationServicesV2: ...


@runtime_checkable
class TenantSkillConfigApplicationResolverProtocolV2(Protocol):
    """Resolve tenant skill config services through a declared Provider alias."""

    def resolve(
        self,
        operation: OperationContextV2,
    ) -> TenantSkillConfigApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlTenantSkillConfigServiceFactoryV2:
    """Bind tenant skill config repositories to the operation's AsyncSession."""

    def build(self, operation: OperationContextV2) -> TenantSkillConfigApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "tenant skill config services require an AsyncSession operation service",
            )
        return TenantSkillConfigApplicationServicesV2(
            configs=SqlTenantSkillConfigRepository(db),
            skills=SqlSkillRepository(db),
        )


@dataclass(frozen=True, kw_only=True)
class TenantSkillConfigApplicationResolverV2:
    """Consumer seam for an explicitly selected persistence Provider."""

    provider: TenantSkillConfigServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> TenantSkillConfigApplicationServicesV2:
        return self.provider.build(operation)


def _apply_tenant_skill_config_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("tenant skill config provider requires strategy operation-async-session")
    _ = context.provide(
        TENANT_SKILL_CONFIG_PROVIDER_SERVICE_V2,
        SqlTenantSkillConfigServiceFactoryV2(),
        label="tenant-skill-config-provider",
    )


def _apply_tenant_skill_config_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "tenant skill config resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(TENANT_SKILL_CONFIG_PROVIDER_INJECT_V2)
    if not isinstance(provider, TenantSkillConfigServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_tenant_skill_config_provider",
            "tenant skill config provider inject does not implement the factory contract",
        )
    _ = context.provide(
        TENANT_SKILL_CONFIG_APPLICATION_SERVICE_V2,
        TenantSkillConfigApplicationResolverV2(provider=provider),
        label="tenant-skill-config-application",
    )


def tenant_skill_config_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for tenant skill config."""
    return (
        PluginDefinitionV2(
            module_ref=TENANT_SKILL_CONFIG_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TENANT_SKILL_CONFIG_PROVIDER_MODULE_V2),
            apply=_apply_tenant_skill_config_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=TENANT_SKILL_CONFIG_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                TENANT_SKILL_CONFIG_APPLICATION_MODULE_V2
            ),
            apply=_apply_tenant_skill_config_application_v2,
        ),
    )


__all__ = [
    "TENANT_SKILL_CONFIG_APPLICATION_MODULE_V2",
    "TENANT_SKILL_CONFIG_APPLICATION_SERVICE_V2",
    "TENANT_SKILL_CONFIG_PROVIDER_INJECT_V2",
    "TENANT_SKILL_CONFIG_PROVIDER_MODULE_V2",
    "TENANT_SKILL_CONFIG_PROVIDER_SERVICE_V2",
    "SqlTenantSkillConfigServiceFactoryV2",
    "TenantSkillConfigApplicationResolverProtocolV2",
    "TenantSkillConfigApplicationResolverV2",
    "TenantSkillConfigApplicationServicesV2",
    "TenantSkillConfigServiceFactoryProtocolV2",
    "tenant_skill_config_service_definitions_v2",
]
