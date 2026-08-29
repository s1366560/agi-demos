# pyright: reportImportCycles=false, reportUnnecessaryIsInstance=false
"""FastAPI authority for generation-owned tenant plugin configuration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.plugin_config_services import (
    PLUGIN_CONFIG_APPLICATION_SERVICE_V2,
    PluginConfigApplicationResolverProtocolV2,
    PluginConfigRepositoryProtocolV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class PluginConfigHttpApplicationAuthorityV2:
    """Request-owned plugin configuration repository and disposable operation."""

    operation: OperationContextV2
    db: AsyncSession
    repository: PluginConfigRepositoryProtocolV2


@asynccontextmanager
async def plugin_config_http_application_authority_v2(
    *,
    request: Request,
    tenant_id: str,
    current_user: User,
    db: AsyncSession,
) -> AsyncIterator[PluginConfigHttpApplicationAuthorityV2]:
    """Yield plugin configuration persistence from the request's pinned generation."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-plugin-config:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": tenant_id, "user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(PLUGIN_CONFIG_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, PluginConfigApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_plugin_config_application_resolver",
                "Plugin config application service has an invalid resolver",
            )
        repository = resolver.resolve(operation).repository
        if not isinstance(repository, PluginConfigRepositoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_plugin_config_repository",
                "Plugin config Provider returned an invalid repository",
            )
        yield PluginConfigHttpApplicationAuthorityV2(
            operation=operation,
            db=db,
            repository=repository,
        )


__all__ = [
    "PluginConfigHttpApplicationAuthorityV2",
    "plugin_config_http_application_authority_v2",
]
