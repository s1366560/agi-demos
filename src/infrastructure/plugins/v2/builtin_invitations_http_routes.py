"""V2-owned production contributions for the tenant invitations HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.invitation_schemas import (
    CreateInvitationRequest,
    InvitationListResponse,
    InvitationResponse,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.invitations import (
    cancel_invitation as _cancel_invitation,
    create_invitation as _create_invitation,
    list_pending_invitations as _list_pending_invitations,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INVITATIONS_HTTP_ROUTES_ENTRY_V2 = "builtin-invitations-http-routes"
INVITATIONS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/invitations-routes"
INVITATIONS_HTTP_ROUTES_ROW_V2 = "invitations"


async def create_invitation_v2(
    tenant_id: str,
    body: CreateInvitationRequest,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    return await _create_invitation(tenant_id, body, current_user, db)


async def list_pending_invitations_v2(
    tenant_id: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> InvitationListResponse:
    return await _list_pending_invitations(tenant_id, current_user, db, limit, offset)


async def cancel_invitation_v2(
    tenant_id: str,
    invitation_id: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _cancel_invitation(tenant_id, invitation_id, current_user, db)


def invitations_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``invitations`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=INVITATIONS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/invitations",
            methods=("POST",),
            endpoint=create_invitation_v2,
            name="create_invitation",
            tags=("invitations",),
            status_code=status.HTTP_201_CREATED,
            response_model=InvitationResponse,
            replaces_builtin_row_id=INVITATIONS_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=INVITATIONS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/invitations",
            methods=("GET",),
            endpoint=list_pending_invitations_v2,
            name="list_pending_invitations",
            tags=("invitations",),
            response_model=InvitationListResponse,
            replaces_builtin_row_id=INVITATIONS_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=INVITATIONS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/invitations/{invitation_id}",
            methods=("DELETE",),
            endpoint=cancel_invitation_v2,
            name="cancel_invitation",
            tags=("invitations",),
            status_code=status.HTTP_204_NO_CONTENT,
            replaces_builtin_row_id=INVITATIONS_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_invitations_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the invitations row as reversible route effects of one V2 Fiber."""
    definitions = invitations_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label="builtin-invitations-http-routes")

    return PluginDefinitionV2(
        module_ref=INVITATIONS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(INVITATIONS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "INVITATIONS_HTTP_ROUTES_ENTRY_V2",
    "INVITATIONS_HTTP_ROUTES_MODULE_V2",
    "INVITATIONS_HTTP_ROUTES_ROW_V2",
    "builtin_invitations_http_routes_definition_v2",
    "cancel_invitation_v2",
    "create_invitation_v2",
    "invitations_route_definitions_v2",
    "list_pending_invitations_v2",
]
