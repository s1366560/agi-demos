# pyright: reportImportCycles=false
"""FastAPI security and generation authority for Workspace Context operations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import verify_api_key_dependency
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import APIKey
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.workspace_context_services import (
    WORKSPACE_CONTEXT_APPLICATION_SERVICE_V2,
    WorkspaceContextApplicationResolverProtocolV2,
    WorkspaceContextApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class WorkspaceContextApplicationAuthorityV2:
    """One authenticated request's immutable generation and application services."""

    operation: OperationContextV2
    db: AsyncSession
    api_key: APIKey
    services: WorkspaceContextApplicationServicesV2


def _route_template_v2(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "-"


@asynccontextmanager
async def workspace_context_application_authority_context_v2(
    *,
    request: Request,
    api_key: APIKey,
    db: AsyncSession,
) -> AsyncIterator[WorkspaceContextApplicationAuthorityV2]:
    """Resolve Workspace Context services in a disposable root operation."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-workspace-context:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"user_id": str(api_key.user_id), "api_key_id": str(api_key.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "http-authority",
                "method": request.method,
                "path": _route_template_v2(request),
            },
        )
        resolver = operation.require(WORKSPACE_CONTEXT_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, WorkspaceContextApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_workspace_context_application_resolver",
                "Workspace Context application service has an invalid implementation",
            )
        yield WorkspaceContextApplicationAuthorityV2(
            operation=operation,
            db=db,
            api_key=api_key,
            services=resolver.resolve(operation),
        )


async def workspace_context_application_authority_dependency_v2(
    request: Request,
    api_key: APIKey = Depends(verify_api_key_dependency),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[WorkspaceContextApplicationAuthorityV2]:
    """Yield services from the generation pinned to this authenticated request."""
    async with workspace_context_application_authority_context_v2(
        request=request,
        api_key=api_key,
        db=db,
    ) as authority:
        yield authority


__all__ = [
    "WorkspaceContextApplicationAuthorityV2",
    "workspace_context_application_authority_context_v2",
    "workspace_context_application_authority_dependency_v2",
]
