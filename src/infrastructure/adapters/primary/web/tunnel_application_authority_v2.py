# pyright: reportImportCycles=false
"""FastAPI security and generation authority for tunnel operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, Request, WebSocket, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import has_global_admin_access
from src.infrastructure.adapters.primary.web.websocket.auth import (
    authenticate_websocket_or_close,
    select_websocket_auth_subprotocol,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tunnel_services import (
    TUNNEL_APPLICATION_SERVICE_V2,
    TunnelApplicationResolverProtocolV2,
    TunnelApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class TunnelApplicationAuthorityV2:
    """One connection/request's immutable generation and tunnel services."""

    operation: OperationContextV2
    services: TunnelApplicationServicesV2
    subprotocol: str | None

    async def connect(self, websocket: WebSocket) -> None:
        await self.services.connect(websocket, subprotocol=self.subprotocol)

    def status(self) -> dict[str, int]:
        return {"active_connections": self.services.status().active_connections}


def _route_template_v2(request: Request | WebSocket) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "-"


@asynccontextmanager
async def tunnel_application_authority_context_v2(
    *,
    scope: ScopeV2,
    identity: Mapping[str, object],
    metadata: Mapping[str, object],
    subprotocol: str | None,
) -> AsyncIterator[TunnelApplicationAuthorityV2]:
    """Resolve tunnel services in a disposable operation on the pinned generation."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"tunnel:{uuid4()}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_IDENTITY_SERVICE_V2, dict(identity))
        _ = operation.provide(OPERATION_METADATA_SERVICE_V2, dict(metadata))
        resolver = operation.require(TUNNEL_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, TunnelApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_tunnel_application_resolver",
                "tunnel application service has an invalid implementation",
            )
        yield TunnelApplicationAuthorityV2(
            operation=operation,
            services=resolver.resolve(operation),
            subprotocol=subprotocol,
        )


async def tunnel_websocket_application_authority_dependency_v2(
    websocket: WebSocket,
    token: str | None = Query(None, description="Legacy API key query parameter"),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[TunnelApplicationAuthorityV2 | None]:
    """Authenticate before resolving a tenant-scoped connection authority."""
    principal = await authenticate_websocket_or_close(websocket, db, token)
    if principal is None:
        yield None
        return

    user_id, tenant_id = principal
    async with tunnel_application_authority_context_v2(
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=str(tenant_id)),
        identity={"tenant_id": str(tenant_id), "user_id": str(user_id)},
        metadata={
            "kind": "websocket-authority",
            "path": _route_template_v2(websocket),
        },
        subprotocol=select_websocket_auth_subprotocol(websocket),
    ) as authority:
        yield authority


async def tunnel_admin_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[TunnelApplicationAuthorityV2]:
    """Require persisted global-admin access before resolving root services."""
    if not await has_global_admin_access(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Admin access required"),
        )

    async with tunnel_application_authority_context_v2(
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        identity={"user_id": str(current_user.id)},
        metadata={
            "kind": "http-authority",
            "method": request.method,
            "path": _route_template_v2(request),
        },
        subprotocol=None,
    ) as authority:
        yield authority


__all__ = [
    "TunnelApplicationAuthorityV2",
    "tunnel_admin_application_authority_dependency_v2",
    "tunnel_application_authority_context_v2",
    "tunnel_websocket_application_authority_dependency_v2",
]
