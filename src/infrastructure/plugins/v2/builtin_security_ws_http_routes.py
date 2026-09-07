"""V2-owned production contribution for the builtin security WebSocket row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.security_ws import security_ws

from .http_routes import RouteTableBuilderV2, WebSocketRouteDefinitionV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SECURITY_WS_HTTP_ROUTES_ENTRY_V2 = "builtin-security-ws-http-routes"
SECURITY_WS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/security-ws-routes"
SECURITY_WS_HTTP_ROUTES_ROW_V2 = "security-ws"


def security_ws_route_definitions_v2() -> tuple[WebSocketRouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``security-ws`` inventory row."""
    return (
        WebSocketRouteDefinitionV2(
            owner_entry_id=SECURITY_WS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/security/ws",
            endpoint=security_ws,
            name="security_ws",
            replaces_builtin_row_id=SECURITY_WS_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_security_ws_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the security WebSocket row as a reversible V2 route effect."""
    definitions = security_ws_route_definitions_v2()

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

        await context.effect(setup, label=SECURITY_WS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=SECURITY_WS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SECURITY_WS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SECURITY_WS_HTTP_ROUTES_ENTRY_V2",
    "SECURITY_WS_HTTP_ROUTES_MODULE_V2",
    "SECURITY_WS_HTTP_ROUTES_ROW_V2",
    "builtin_security_ws_http_routes_definition_v2",
    "security_ws_route_definitions_v2",
]
