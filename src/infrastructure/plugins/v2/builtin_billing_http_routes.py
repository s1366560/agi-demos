"""V2-owned production contributions for the tenant billing HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.billing import (
    get_billing_info,
    list_invoices,
    upgrade_plan,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

BILLING_HTTP_ROUTES_ENTRY_V2 = "builtin-billing-http-routes"
BILLING_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/billing-routes"
BILLING_HTTP_ROUTES_ROW_V2 = "billing"


def billing_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``billing`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=BILLING_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/billing",
            methods=("GET",),
            endpoint=get_billing_info,
            name="get_billing_info",
            tags=("billing",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=BILLING_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=BILLING_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/invoices",
            methods=("GET",),
            endpoint=list_invoices,
            name="list_invoices",
            tags=("billing",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=BILLING_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=BILLING_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/upgrade",
            methods=("POST",),
            endpoint=upgrade_plan,
            name="upgrade_plan",
            tags=("billing",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=BILLING_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_billing_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register tenant billing routes as reversible effects of one V2 Fiber."""
    definitions = billing_route_definitions_v2()

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

        await context.effect(setup, label="builtin-billing-http-routes")

    return PluginDefinitionV2(
        module_ref=BILLING_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(BILLING_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "BILLING_HTTP_ROUTES_ENTRY_V2",
    "BILLING_HTTP_ROUTES_MODULE_V2",
    "BILLING_HTTP_ROUTES_ROW_V2",
    "billing_route_definitions_v2",
    "builtin_billing_http_routes_definition_v2",
]
