"""V2-owned production contribution for the builtin voice WebSocket row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.voice_websocket import voice_chat_endpoint

from .http_routes import RouteTableBuilderV2, WebSocketRouteDefinitionV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

VOICE_WEBSOCKET_HTTP_ROUTES_ENTRY_V2 = "builtin-voice-websocket-http-routes"
VOICE_WEBSOCKET_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/voice-websocket-routes"
VOICE_WEBSOCKET_HTTP_ROUTES_ROW_V2 = "voice-websocket"


def voice_websocket_route_definitions_v2() -> tuple[WebSocketRouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``voice-websocket`` inventory row."""
    return (
        WebSocketRouteDefinitionV2(
            owner_entry_id=VOICE_WEBSOCKET_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/voice/chat",
            endpoint=voice_chat_endpoint,
            name="voice_chat_endpoint",
            replaces_builtin_row_id=VOICE_WEBSOCKET_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_voice_websocket_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the voice WebSocket row as a reversible V2 route effect."""
    definitions = voice_websocket_route_definitions_v2()

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

        await context.effect(setup, label=VOICE_WEBSOCKET_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=VOICE_WEBSOCKET_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(VOICE_WEBSOCKET_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "VOICE_WEBSOCKET_HTTP_ROUTES_ENTRY_V2",
    "VOICE_WEBSOCKET_HTTP_ROUTES_MODULE_V2",
    "VOICE_WEBSOCKET_HTTP_ROUTES_ROW_V2",
    "builtin_voice_websocket_http_routes_definition_v2",
    "voice_websocket_route_definitions_v2",
]
