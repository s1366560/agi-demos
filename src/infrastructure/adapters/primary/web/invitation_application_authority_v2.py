# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned invitation services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.invitation_services import (
    INVITATION_APPLICATION_SERVICE_V2,
    InvitationApplicationResolverProtocolV2,
    InvitationApplicationServicesV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class InvitationApplicationAuthorityV2:
    """Request's immutable generation lease and invitation services."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: DBUser | None
    tenant_id: str | None
    services: InvitationApplicationServicesV2


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "-"


@asynccontextmanager
async def invitation_application_authority_context_v2(
    *,
    request: Request,
    current_user: DBUser | None,
    db: AsyncSession,
    tenant_id: str | None,
) -> AsyncIterator[InvitationApplicationAuthorityV2]:
    """Pin one generation and resolve operation-scoped invitation services."""
    scope = (
        ScopeV2(kind=ScopeKindV2.ROOT)
        if tenant_id is None
        else ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
    )
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-invitations:{uuid4()}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        identity: dict[str, str] = {}
        if current_user is not None:
            identity["user_id"] = str(current_user.id)
        if tenant_id is not None:
            identity["tenant_id"] = tenant_id
        _ = operation.provide(OPERATION_IDENTITY_SERVICE_V2, identity)
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "http-authority",
                "method": request.method,
                "path": _route_template(request),
            },
        )
        resolver = operation.require(INVITATION_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, InvitationApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_invitation_application_resolver",
                "invitation application service has an invalid implementation",
            )
        yield InvitationApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
            services=resolver.resolve(operation),
        )


__all__ = [
    "InvitationApplicationAuthorityV2",
    "invitation_application_authority_context_v2",
]
