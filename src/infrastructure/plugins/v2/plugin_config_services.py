"""Generation-owned persistence seam for tenant plugin configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import PluginConfigModel
from src.infrastructure.adapters.secondary.persistence.plugin_config_repository import (
    PluginConfigRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

PLUGIN_CONFIG_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/plugin-config-repository-provider"
)
PLUGIN_CONFIG_PROVIDER_SERVICE_V2 = "service:persistence.plugin-config-repository-provider"
PLUGIN_CONFIG_APPLICATION_MODULE_V2 = "builtin://memstack/application/plugin-config-repository"
PLUGIN_CONFIG_APPLICATION_SERVICE_V2 = "service:application.plugin-config-repository"
PLUGIN_CONFIG_PROVIDER_INJECT_V2 = "repository_provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class PluginConfigRepositoryProtocolV2(Protocol):
    """Tenant plugin configuration persistence exposed to V2 Consumers."""

    async def get_by_tenant_and_plugin(
        self,
        tenant_id: str,
        plugin_name: str,
    ) -> PluginConfigModel | None: ...

    async def upsert(
        self,
        *,
        tenant_id: str,
        plugin_name: str,
        config: dict[str, object],
    ) -> PluginConfigModel: ...


@runtime_checkable
class PluginConfigRepositoryProviderProtocolV2(Protocol):
    """Build a plugin configuration repository from one operation boundary."""

    def build(self, operation: OperationContextV2) -> PluginConfigRepositoryProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlPluginConfigRepositoryProviderV2:
    """Construct SQL plugin configuration repositories from request-owned sessions."""

    strategy: str

    def build(self, operation: OperationContextV2) -> PluginConfigRepositoryProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Plugin config repository Provider requires an AsyncSession operation service",
            )
        return PluginConfigRepository(db)


@dataclass(frozen=True, kw_only=True)
class PluginConfigApplicationServicesV2:
    """Operation-owned plugin configuration persistence for application Consumers."""

    repository: PluginConfigRepositoryProtocolV2


@runtime_checkable
class PluginConfigApplicationResolverProtocolV2(Protocol):
    """Resolve plugin configuration persistence through the declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> PluginConfigApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class PluginConfigApplicationResolverV2:
    """Bind the Profile-selected repository Provider to one operation."""

    repository_provider: PluginConfigRepositoryProviderProtocolV2

    def resolve(self, operation: OperationContextV2) -> PluginConfigApplicationServicesV2:
        return PluginConfigApplicationServicesV2(
            repository=self.repository_provider.build(operation),
        )


def _apply_plugin_config_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "Plugin config repository Provider requires strategy request-async-session"
        )
    _ = context.provide(
        PLUGIN_CONFIG_PROVIDER_SERVICE_V2,
        SqlPluginConfigRepositoryProviderV2(strategy=strategy),
        label="plugin-config-repository-provider",
    )


def _apply_plugin_config_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "Plugin config repository application resolver requires operation-scoped-provider"
        )
    repository_provider = context.require(PLUGIN_CONFIG_PROVIDER_INJECT_V2)
    if not isinstance(repository_provider, PluginConfigRepositoryProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_plugin_config_repository_provider",
            "Plugin config repository Provider inject has an invalid implementation",
        )
    _ = context.provide(
        PLUGIN_CONFIG_APPLICATION_SERVICE_V2,
        PluginConfigApplicationResolverV2(repository_provider=repository_provider),
        label="plugin-config-application",
    )


def plugin_config_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the plugin configuration persistence Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=PLUGIN_CONFIG_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(PLUGIN_CONFIG_PROVIDER_MODULE_V2),
            apply=_apply_plugin_config_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=PLUGIN_CONFIG_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(PLUGIN_CONFIG_APPLICATION_MODULE_V2),
            apply=_apply_plugin_config_application_v2,
        ),
    )


__all__ = [
    "PLUGIN_CONFIG_APPLICATION_MODULE_V2",
    "PLUGIN_CONFIG_APPLICATION_SERVICE_V2",
    "PLUGIN_CONFIG_PROVIDER_INJECT_V2",
    "PLUGIN_CONFIG_PROVIDER_MODULE_V2",
    "PLUGIN_CONFIG_PROVIDER_SERVICE_V2",
    "PluginConfigApplicationResolverProtocolV2",
    "PluginConfigApplicationResolverV2",
    "PluginConfigApplicationServicesV2",
    "PluginConfigRepositoryProtocolV2",
    "PluginConfigRepositoryProviderProtocolV2",
    "SqlPluginConfigRepositoryProviderV2",
    "plugin_config_service_definitions_v2",
]
