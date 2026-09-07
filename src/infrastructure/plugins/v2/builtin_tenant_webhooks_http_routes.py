"""V2-owned production contributions for the builtin tenant webhooks HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.infrastructure.adapters.primary.web.routers.tenant_webhooks import (
    WebhookResponse,
    create_webhook,
    delete_webhook,
    list_webhooks,
    update_webhook,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TENANT_WEBHOOKS_HTTP_ROUTES_ENTRY_V2 = "builtin-tenant-webhooks-http-routes"
TENANT_WEBHOOKS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/tenant-webhooks-routes"
TENANT_WEBHOOKS_HTTP_ROUTES_ROW_V2 = "tenant-webhooks"


def tenant_webhooks_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``tenant-webhooks`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=TENANT_WEBHOOKS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenant-webhooks/{tenant_id}",
            methods=("POST",),
            endpoint=create_webhook,
            name="create_webhook",
            tags=("Webhooks",),
            response_model=WebhookResponse,
            replaces_builtin_row_id=TENANT_WEBHOOKS_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=TENANT_WEBHOOKS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenant-webhooks/{tenant_id}",
            methods=("GET",),
            endpoint=list_webhooks,
            name="list_webhooks",
            tags=("Webhooks",),
            response_model=list[WebhookResponse],
            replaces_builtin_row_id=TENANT_WEBHOOKS_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=TENANT_WEBHOOKS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenant-webhooks/{webhook_id}",
            methods=("PUT",),
            endpoint=update_webhook,
            name="update_webhook",
            tags=("Webhooks",),
            response_model=WebhookResponse,
            replaces_builtin_row_id=TENANT_WEBHOOKS_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=TENANT_WEBHOOKS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenant-webhooks/{webhook_id}",
            methods=("DELETE",),
            endpoint=delete_webhook,
            name="delete_webhook",
            tags=("Webhooks",),
            status_code=status.HTTP_204_NO_CONTENT,
            replaces_builtin_row_id=TENANT_WEBHOOKS_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_tenant_webhooks_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the tenant webhooks row as reversible route effects of one V2 Fiber."""
    definitions = tenant_webhooks_route_definitions_v2()

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

        await context.effect(setup, label="builtin-tenant-webhooks-http-routes")

    return PluginDefinitionV2(
        module_ref=TENANT_WEBHOOKS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TENANT_WEBHOOKS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TENANT_WEBHOOKS_HTTP_ROUTES_ENTRY_V2",
    "TENANT_WEBHOOKS_HTTP_ROUTES_MODULE_V2",
    "TENANT_WEBHOOKS_HTTP_ROUTES_ROW_V2",
    "builtin_tenant_webhooks_http_routes_definition_v2",
    "tenant_webhooks_route_definitions_v2",
]
