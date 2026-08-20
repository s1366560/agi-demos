"""Stable outer HTTP dispatcher and OpenAPI view for plugin generations."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from starlette.types import Receive, Scope, Send

from src.infrastructure.plugins.v2.http_routes import (
    GenerationRouteDispatcherV2,
    RouteTableRegistryV2,
)


class ApplicationGenerationRouteDispatcherV2:
    """Resolve the current route registry from outer application state per request."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = scope.get("app")
        registry = getattr(getattr(app, "state", None), "platform_plugin_route_registry_v2", None)
        if not isinstance(registry, RouteTableRegistryV2):
            raise RuntimeError("plugin route registry v2 is not initialized")
        if scope["type"] == "websocket":
            publication = registry.current
            if publication is None:
                raise RuntimeError("plugin route generation v2 is not published")
            await publication.table(scope, receive, send)
            return
        await GenerationRouteDispatcherV2(registry)(scope, receive, send)


def mount_generation_http_dispatcher_v2(app: FastAPI) -> None:
    """Mount one stable catch-all dispatcher and bind docs to its current publication."""
    original_openapi = app.openapi

    def generation_openapi() -> dict[str, Any]:
        registry = getattr(app.state, "platform_plugin_route_registry_v2", None)
        if isinstance(registry, RouteTableRegistryV2) and registry.current is not None:
            return dict(registry.current.openapi.schema)
        return original_openapi()

    cast(Any, app).openapi = generation_openapi
    app.mount("/", ApplicationGenerationRouteDispatcherV2(), name="plugin-generation-v2")


__all__ = [
    "ApplicationGenerationRouteDispatcherV2",
    "mount_generation_http_dispatcher_v2",
]
