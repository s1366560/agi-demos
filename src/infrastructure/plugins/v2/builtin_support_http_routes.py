"""V2-owned production contributions for both support HTTP aliases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.support import (
    close_support_ticket,
    create_support_ticket,
    get_support_ticket,
    list_support_tickets,
    update_support_ticket,
)
from src.infrastructure.adapters.primary.web.support_ticket_application_authority_v2 import (
    support_ticket_application_authority_dependency_v2,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SUPPORT_HTTP_ROUTES_ENTRY_V2 = "builtin-support-http-routes"
SUPPORT_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/support-routes"
SUPPORT_HTTP_ROUTE_ROW_IDS_V2 = ("support", "support-2")


def _support_alias_route_definitions_v2(
    *,
    prefix: str,
    row_id: str,
) -> tuple[RouteDefinitionV2, ...]:
    def route(
        *,
        path: str,
        methods: tuple[str, ...],
        endpoint: Callable[..., Any],
        name: str,
    ) -> RouteDefinitionV2:
        return RouteDefinitionV2(
            owner_entry_id=SUPPORT_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}{path}",
            methods=methods,
            endpoint=endpoint,
            name=name,
            tags=("support",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=row_id,
        )

    return (
        route(
            path="/tickets",
            methods=("POST",),
            endpoint=create_support_ticket,
            name="create_support_ticket",
        ),
        route(
            path="/tickets",
            methods=("GET",),
            endpoint=list_support_tickets,
            name="list_support_tickets",
        ),
        route(
            path="/tickets/{ticket_id}",
            methods=("GET",),
            endpoint=get_support_ticket,
            name="get_support_ticket",
        ),
        route(
            path="/tickets/{ticket_id}",
            methods=("PUT",),
            endpoint=update_support_ticket,
            name="update_support_ticket",
        ),
        route(
            path="/tickets/{ticket_id}/close",
            methods=("POST",),
            endpoint=close_support_ticket,
            name="close_support_ticket",
        ),
    )


def support_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return both complete support rows in inventory declaration order."""
    return (
        *_support_alias_route_definitions_v2(prefix="/api/v1/support", row_id="support"),
        *_support_alias_route_definitions_v2(prefix="/support", row_id="support-2"),
    )


def builtin_support_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register both support aliases as one reversible V2 effect."""
    definitions = support_route_definitions_v2()

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

        await context.effect(setup, label=SUPPORT_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=SUPPORT_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SUPPORT_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SUPPORT_HTTP_ROUTES_ENTRY_V2",
    "SUPPORT_HTTP_ROUTES_MODULE_V2",
    "SUPPORT_HTTP_ROUTE_ROW_IDS_V2",
    "builtin_support_http_routes_definition_v2",
    "get_current_user",
    "support_route_definitions_v2",
    "support_ticket_application_authority_dependency_v2",
]
