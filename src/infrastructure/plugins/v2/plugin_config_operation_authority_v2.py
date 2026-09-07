"""PluginConfig authority nested inside an already-pinned V2 operation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from .boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from .plugin_config_services import (
    PluginConfigApplicationResolverProtocolV2,
    PluginConfigApplicationServicesV2,
    PluginConfigRepositoryProtocolV2,
)
from .runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class PluginConfigOperationAuthorityV2:
    """Repository resolved from a disposable child of one pinned operation."""

    operation: OperationContextV2
    repository: PluginConfigRepositoryProtocolV2


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
async def plugin_config_child_operation_authority_v2(
    *,
    parent_operation: OperationContextV2,
    resolver: PluginConfigApplicationResolverProtocolV2,
    db: AsyncSession,
    consumer: str,
) -> AsyncIterator[PluginConfigOperationAuthorityV2]:
    """Resolve a repository without leaving the parent's immutable generation."""
    normalized_consumer = consumer.strip()
    if not normalized_consumer:
        raise RuntimeV2Error(
            "plugin_config_consumer_missing",
            "plugin config child authority requires a non-empty consumer",
        )
    if not isinstance(resolver, PluginConfigApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_plugin_config_application_resolver",
            "plugin config child authority received an invalid resolver",
        )

    scope = parent_operation.context.scope
    if not scope.tenant_id:
        raise RuntimeV2Error(
            "plugin_config_tenant_missing",
            "plugin config child authority requires a tenant-scoped parent operation",
        )
    raw_identity = parent_operation.require(OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(raw_identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "plugin config parent operation identity must be an object",
        )
    if raw_identity.get("tenant_id") != scope.tenant_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "plugin config parent identity does not match its tenant scope",
        )
    if any(not isinstance(key, str) for key in raw_identity):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "plugin config parent operation identity keys must be strings",
        )
    identity = dict(cast("Mapping[str, object]", raw_identity))

    operation = OperationContextV2(
        generation=parent_operation.generation,
        operation_id=f"{normalized_consumer}:{uuid4().hex}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(OPERATION_IDENTITY_SERVICE_V2, identity)
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "child-authority",
                "consumer": normalized_consumer,
                "parent_operation_id": parent_operation.operation_id,
            },
        )
        services = _require_application_services_v2(resolver.resolve(operation))
        repository = _require_repository_v2(services.repository)
        yield PluginConfigOperationAuthorityV2(
            operation=operation,
            repository=repository,
        )


__all__ = [
    "PluginConfigOperationAuthorityV2",
    "plugin_config_child_operation_authority_v2",
]
