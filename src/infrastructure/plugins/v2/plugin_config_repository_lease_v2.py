"""Generation-pinned plugin configuration authority for background operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .plugin_config_services import (
    PLUGIN_CONFIG_APPLICATION_SERVICE_V2,
    PluginConfigApplicationResolverProtocolV2,
    PluginConfigApplicationServicesV2,
    PluginConfigRepositoryProtocolV2,
)
from .runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class PluginConfigRepositoryAuthorityV2:
    """Operation-owned repository and its immutable generation boundary."""

    operation: OperationContextV2
    repository: PluginConfigRepositoryProtocolV2


type PluginConfigRepositoryLeaseV2 = Callable[
    ...,
    AbstractAsyncContextManager[PluginConfigRepositoryAuthorityV2],
]


def _require_application_services_v2(value: object) -> PluginConfigApplicationServicesV2:
    if not isinstance(value, PluginConfigApplicationServicesV2):
        raise RuntimeV2Error(
            "invalid_plugin_config_application_services",
            "plugin config resolver returned invalid application services",
        )
    return value


def _require_repository_v2(value: object) -> PluginConfigRepositoryProtocolV2:
    if not isinstance(value, PluginConfigRepositoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_plugin_config_repository",
            "plugin config application services returned an invalid repository",
        )
    return value


@asynccontextmanager
async def lease_plugin_config_repository_v2(
    *,
    db: AsyncSession,
    tenant_id: str,
) -> AsyncIterator[PluginConfigRepositoryAuthorityV2]:
    """Resolve plugin config persistence under one independent background lease."""
    normalized_tenant_id = tenant_id.strip()
    if not normalized_tenant_id:
        raise RuntimeV2Error(
            "plugin_config_tenant_missing",
            "plugin config repository lease requires a non-empty tenant_id",
        )

    # boundary imports builtin definitions, so keep this import at the operation edge.
    from .boundary import (
        OPERATION_DB_SESSION_SERVICE_V2,
        OPERATION_IDENTITY_SERVICE_V2,
        OPERATION_METADATA_SERVICE_V2,
        current_process_generation_host_v2,
        pin_generation_v2,
    )

    host = current_process_generation_host_v2()
    async with pin_generation_v2(host) as generation:
        operation = OperationContextV2(
            generation=generation,
            operation_id=f"plugin-config-repository:{normalized_tenant_id}:{uuid4().hex}",
            scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=normalized_tenant_id),
        )
        async with operation:
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            _ = operation.provide(
                OPERATION_IDENTITY_SERVICE_V2,
                {"tenant_id": normalized_tenant_id},
            )
            _ = operation.provide(
                OPERATION_METADATA_SERVICE_V2,
                {
                    "kind": "background-authority",
                    "consumer": "plugin-config-repository",
                },
            )
            resolver = operation.require(PLUGIN_CONFIG_APPLICATION_SERVICE_V2)
            if not isinstance(resolver, PluginConfigApplicationResolverProtocolV2):
                raise RuntimeV2Error(
                    "invalid_plugin_config_application_resolver",
                    "resolved plugin config application service has an invalid implementation",
                )
            services = _require_application_services_v2(resolver.resolve(operation))
            repository = _require_repository_v2(services.repository)
            yield PluginConfigRepositoryAuthorityV2(
                operation=operation,
                repository=repository,
            )


__all__ = [
    "PluginConfigRepositoryAuthorityV2",
    "PluginConfigRepositoryLeaseV2",
    "lease_plugin_config_repository_v2",
]
