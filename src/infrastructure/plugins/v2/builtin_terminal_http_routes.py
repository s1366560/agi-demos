"""V2-owned production contributions for the builtin terminal HTTP/WS row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.terminal import (
    TerminalSessionResponse,
    close_terminal_session,
    create_terminal_session,
    list_terminal_sessions,
    terminal_websocket,
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

TERMINAL_HTTP_ROUTES_ENTRY_V2 = "builtin-terminal-http-routes"
TERMINAL_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/terminal-routes"
TERMINAL_HTTP_ROUTES_ROW_V2 = "terminal"
_TERMINAL_PREFIX_V2 = "/api/v1/terminal/{sandbox_id}"


def _terminal_http_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=TERMINAL_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("terminal",),
        response_model=response_model,
        replaces_builtin_row_id=TERMINAL_HTTP_ROUTES_ROW_V2,
    )


def terminal_route_definitions_v2() -> tuple[RouteContributionV2, ...]:
    """Return the complete, explicitly claimed ``terminal`` inventory row."""
    sessions = f"{_TERMINAL_PREFIX_V2}/sessions"
    return (
        _terminal_http_route_v2(
            path=f"{_TERMINAL_PREFIX_V2}/create",
            methods=("POST",),
            endpoint=create_terminal_session,
            name="create_terminal_session",
            response_model=TerminalSessionResponse,
        ),
        _terminal_http_route_v2(
            path=sessions,
            methods=("GET",),
            endpoint=list_terminal_sessions,
            name="list_terminal_sessions",
            response_model=list[TerminalSessionResponse],
        ),
        _terminal_http_route_v2(
            path=f"{sessions}/{{session_id}}",
            methods=("DELETE",),
            endpoint=close_terminal_session,
            name="close_terminal_session",
            response_model=dict[str, Any],
        ),
        WebSocketRouteDefinitionV2(
            owner_entry_id=TERMINAL_HTTP_ROUTES_ENTRY_V2,
            path=f"{_TERMINAL_PREFIX_V2}/ws",
            endpoint=terminal_websocket,
            name="terminal_websocket",
            replaces_builtin_row_id=TERMINAL_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_terminal_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the terminal row as reversible route effects of one V2 Fiber."""
    definitions = terminal_route_definitions_v2()

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

        await context.effect(setup, label=TERMINAL_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=TERMINAL_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TERMINAL_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TERMINAL_HTTP_ROUTES_ENTRY_V2",
    "TERMINAL_HTTP_ROUTES_MODULE_V2",
    "TERMINAL_HTTP_ROUTES_ROW_V2",
    "builtin_terminal_http_routes_definition_v2",
    "terminal_route_definitions_v2",
]
