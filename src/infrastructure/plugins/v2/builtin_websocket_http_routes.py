"""V2-owned production contributions for the builtin agent WebSocket row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.websocket.router import (
    agent_websocket_endpoint,
    get_dispatcher_stats,
)

from .http_routes import (
    RouteContributionV2,
    RouteDefinitionV2,
    RouteTableBuilderV2,
    WebSocketRouteDefinitionV2,
)
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

WEBSOCKET_HTTP_ROUTES_ENTRY_V2 = "builtin-websocket-http-routes"
WEBSOCKET_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/websocket-routes"
WEBSOCKET_HTTP_ROUTES_ROW_V2 = "websocket"


def websocket_route_definitions_v2() -> tuple[RouteContributionV2, ...]:
    """Return the complete, explicitly claimed ``websocket`` inventory row."""
    return (
        WebSocketRouteDefinitionV2(
            owner_entry_id=WEBSOCKET_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/agent/ws",
            endpoint=agent_websocket_endpoint,
            name="agent_websocket_endpoint",
            replaces_builtin_row_id=WEBSOCKET_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=WEBSOCKET_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/agent/dispatcher-stats",
            methods=("GET",),
            endpoint=get_dispatcher_stats,
            name="get_dispatcher_stats",
            tags=("agent-websocket",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=WEBSOCKET_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_websocket_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the agent WebSocket row as reversible effects of one V2 Fiber."""
    definitions = websocket_route_definitions_v2()

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

        await context.effect(setup, label=WEBSOCKET_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=WEBSOCKET_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WEBSOCKET_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "WEBSOCKET_HTTP_ROUTES_ENTRY_V2",
    "WEBSOCKET_HTTP_ROUTES_MODULE_V2",
    "WEBSOCKET_HTTP_ROUTES_ROW_V2",
    "builtin_websocket_http_routes_definition_v2",
    "websocket_route_definitions_v2",
]
