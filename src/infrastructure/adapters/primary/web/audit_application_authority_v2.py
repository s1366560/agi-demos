# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned audit query services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.plugins.v2.audit_services import (
    AUDIT_APPLICATION_SERVICE_V2,
    AuditApplicationResolverProtocolV2,
    AuditQueryApplicationServicesV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AuditApplicationAuthorityV2:
    """Tenant request's immutable generation lease and audit query services."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: DBUser
    tenant_id: str
    services: AuditQueryApplicationServicesV2


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "-"


@asynccontextmanager
async def audit_application_authority_context_v2(
    *,
    request: Request,
    current_user: DBUser,
    db: AsyncSession,
    tenant_id: str,
) -> AsyncIterator[AuditApplicationAuthorityV2]:
    """Pin one generation and resolve tenant-scoped audit query services."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-audit:{uuid4()}",
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
            {
                "kind": "http-authority",
                "method": request.method,
                "path": _route_template(request),
            },
        )
        resolver = operation.require(AUDIT_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, AuditApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_audit_application_resolver",
                "audit application service has an invalid implementation",
            )
        yield AuditApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
            services=resolver.resolve(operation),
        )


async def audit_application_authority_dependency_v2(
    request: Request,
    tenant_id: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AuditApplicationAuthorityV2]:
    """Yield audit services from the generation pinned to this HTTP request."""
    async with audit_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=tenant_id,
    ) as authority:
        yield authority


__all__ = [
    "AuditApplicationAuthorityV2",
    "audit_application_authority_context_v2",
    "audit_application_authority_dependency_v2",
]
