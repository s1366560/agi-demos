"""Generation-owned sandbox services for HTTP, WebSocket, and background operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_from_desktop_proxy,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.sandbox_operation_services import (
    SANDBOX_OPERATION_APPLICATION_SERVICE_V2,
    SandboxOperationApplicationResolverProtocolV2,
    SandboxOperationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class SandboxApplicationAuthorityV2:
    """Operation-owned sandbox services resolved from one exact generation."""

    operation: OperationContextV2
    db: AsyncSession
    services: SandboxOperationServicesV2


@asynccontextmanager
async def sandbox_operation_authority_v2(
    *,
    db: AsyncSession,
    operation_id: str,
    scope: ScopeV2,
    identity: Mapping[str, object],
    metadata: Mapping[str, object],
) -> AsyncIterator[SandboxApplicationAuthorityV2]:
    """Resolve sandbox services within a disposable current-generation operation."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=operation_id,
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(OPERATION_IDENTITY_SERVICE_V2, dict(identity))
        _ = operation.provide(OPERATION_METADATA_SERVICE_V2, dict(metadata))
        resolver = operation.require(SANDBOX_OPERATION_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, SandboxOperationApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_sandbox_application_resolver",
                "sandbox application service has an invalid implementation",
            )
        yield SandboxApplicationAuthorityV2(
            operation=operation,
            db=db,
            services=resolver.resolve(operation),
        )


async def sandbox_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[SandboxApplicationAuthorityV2]:
    """Yield request-owned sandbox services from the pinned HTTP generation."""
    scope = await _connection_scope_v2(request=request, db=db)
    async with sandbox_operation_authority_v2(
        db=db,
        operation_id=f"http-sandbox-application:{uuid4()}",
        scope=scope,
        identity={
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "user_id": current_user.id,
        },
        metadata={
            "kind": "http-authority",
            "method": request.method,
            "path": request.url.path,
        },
    ) as authority:
        yield authority


async def sandbox_application_proxy_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user_from_desktop_proxy),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[SandboxApplicationAuthorityV2]:
    """Yield sandbox services for cookie/query-authenticated HTTP proxy requests."""
    scope = await _connection_scope_v2(request=request, db=db)
    async with sandbox_operation_authority_v2(
        db=db,
        operation_id=f"http-sandbox-proxy:{uuid4()}",
        scope=scope,
        identity={
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "user_id": current_user.id,
        },
        metadata={
            "kind": "http-proxy-authority",
            "method": request.method,
            "path": request.url.path,
        },
    ) as authority:
        yield authority


async def sandbox_application_websocket_authority_dependency_v2(
    websocket: WebSocket,
    current_user: User = Depends(get_current_user_from_desktop_proxy),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[SandboxApplicationAuthorityV2]:
    """Yield connection-owned sandbox services from the pinned WebSocket generation."""
    scope = await _connection_scope_v2(request=websocket, db=db)
    async with sandbox_operation_authority_v2(
        db=db,
        operation_id=f"websocket-sandbox-application:{uuid4()}",
        scope=scope,
        identity={
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "user_id": current_user.id,
        },
        metadata={"kind": "websocket-authority", "path": websocket.url.path},
    ) as authority:
        yield authority


async def _connection_scope_v2(
    *,
    request: Request | WebSocket,
    db: AsyncSession,
) -> ScopeV2:
    tenant_id = _scope_id_v2(
        request.path_params.get("tenant_id") or request.query_params.get("tenant_id")
    )
    project_id = _scope_id_v2(
        request.path_params.get("project_id") or request.query_params.get("project_id")
    )
    if project_id is not None:
        result = await db.execute(
            refresh_select_statement(select(Project.tenant_id).where(Project.id == project_id))
        )
        project_tenant_id = _scope_id_v2(result.scalar_one_or_none())
        if project_tenant_id is None:
            raise RuntimeV2Error(
                "sandbox_operation_project_not_found",
                "sandbox project scope could not be resolved",
            )
        if tenant_id is not None and tenant_id != project_tenant_id:
            raise RuntimeV2Error(
                "sandbox_operation_scope_mismatch",
                "sandbox project does not belong to the requested tenant scope",
            )
        tenant_id = project_tenant_id
    if tenant_id is not None and project_id is not None:
        return ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    if tenant_id is not None:
        return ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
    return ScopeV2(kind=ScopeKindV2.ROOT)


def _scope_id_v2(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "SandboxApplicationAuthorityV2",
    "sandbox_application_authority_dependency_v2",
    "sandbox_application_proxy_authority_dependency_v2",
    "sandbox_application_websocket_authority_dependency_v2",
    "sandbox_operation_authority_v2",
]
