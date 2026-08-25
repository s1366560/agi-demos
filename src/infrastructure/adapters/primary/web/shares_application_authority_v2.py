# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned memory-share services."""

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
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.shares_services import (
    SHARES_APPLICATION_SERVICE_V2,
    SharesApplicationResolverProtocolV2,
    SharesApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class SharesApplicationAuthorityV2:
    """Request's immutable generation lease and memory-share services."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: DBUser | None
    services: SharesApplicationServicesV2


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "-"


@asynccontextmanager
async def shares_application_authority_context_v2(
    *,
    request: Request,
    current_user: DBUser | None,
    db: AsyncSession,
) -> AsyncIterator[SharesApplicationAuthorityV2]:
    """Pin one generation and resolve root-scoped share services."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-shares:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        identity = {"user_id": str(current_user.id)} if current_user is not None else {}
        _ = operation.provide(OPERATION_IDENTITY_SERVICE_V2, identity)
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "http-authority",
                "method": request.method,
                "path": _route_template(request),
            },
        )
        resolver = operation.require(SHARES_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, SharesApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_shares_application_resolver",
                "shares application service has an invalid implementation",
            )
        yield SharesApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            services=resolver.resolve(operation),
        )


async def shares_application_authority_dependency_v2(
    request: Request,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[SharesApplicationAuthorityV2]:
    """Yield authenticated share services pinned to this HTTP request."""
    async with shares_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
    ) as authority:
        yield authority


async def public_shares_application_authority_dependency_v2(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[SharesApplicationAuthorityV2]:
    """Yield anonymous share services without adding an authentication dependency."""
    async with shares_application_authority_context_v2(
        request=request,
        current_user=None,
        db=db,
    ) as authority:
        yield authority


__all__ = [
    "SharesApplicationAuthorityV2",
    "public_shares_application_authority_dependency_v2",
    "shares_application_authority_context_v2",
    "shares_application_authority_dependency_v2",
]
