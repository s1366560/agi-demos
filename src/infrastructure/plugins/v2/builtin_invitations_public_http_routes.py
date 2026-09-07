"""V2-owned production contributions for the public invitations HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.application.schemas.invitation_schemas import (
    InvitationResponse,
    InvitationVerifyResponse,
)
from src.infrastructure.adapters.primary.web.routers.invitations import (
    accept_invitation,
    verify_invitation,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INVITATIONS_PUBLIC_HTTP_ROUTES_ENTRY_V2 = "builtin-invitations-public-http-routes"
INVITATIONS_PUBLIC_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/invitations-public-routes"
INVITATIONS_PUBLIC_HTTP_ROUTES_ROW_V2 = "invitations-public"


def invitations_public_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``invitations-public`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=INVITATIONS_PUBLIC_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/invitations/verify/{token}",
            methods=("GET",),
            endpoint=verify_invitation,
            name="verify_invitation",
            tags=("invitations",),
            response_model=InvitationVerifyResponse,
            replaces_builtin_row_id=INVITATIONS_PUBLIC_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=INVITATIONS_PUBLIC_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/invitations/accept/{token}",
            methods=("POST",),
            endpoint=accept_invitation,
            name="accept_invitation",
            tags=("invitations",),
            response_model=InvitationResponse,
            replaces_builtin_row_id=INVITATIONS_PUBLIC_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_invitations_public_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register public invitation routes as reversible effects of one V2 Fiber."""
    definitions = invitations_public_route_definitions_v2()

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

        await context.effect(setup, label="builtin-invitations-public-http-routes")

    return PluginDefinitionV2(
        module_ref=INVITATIONS_PUBLIC_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(INVITATIONS_PUBLIC_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "INVITATIONS_PUBLIC_HTTP_ROUTES_ENTRY_V2",
    "INVITATIONS_PUBLIC_HTTP_ROUTES_MODULE_V2",
    "INVITATIONS_PUBLIC_HTTP_ROUTES_ROW_V2",
    "builtin_invitations_public_http_routes_definition_v2",
    "invitations_public_route_definitions_v2",
]
