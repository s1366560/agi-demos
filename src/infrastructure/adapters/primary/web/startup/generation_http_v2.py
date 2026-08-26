"""Stable outer HTTP dispatcher and OpenAPI view for plugin generations."""

from __future__ import annotations

from typing import Any, cast, override

from fastapi import FastAPI
from starlette.datastructures import URLPath
from starlette.routing import BaseRoute, Match, NoMatchFound
from starlette.types import Receive, Scope, Send

from src.infrastructure.plugins.v2.http_routes import (
    GenerationRouteDispatcherV2,
    RouteTableRegistryV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


class ApplicationGenerationRouteDispatcherV2(BaseRoute):
    """Selectively dispatch routes contributed by the current plugin generation."""

    name = "plugin-generation-v2"

    def __init__(self, app: FastAPI) -> None:
        super().__init__()
        self._outer_app = app

    def _registry(self) -> RouteTableRegistryV2:
        registry = getattr(
            self._outer_app.state,
            "platform_plugin_route_registry_v2",
            None,
        )
        if not isinstance(registry, RouteTableRegistryV2):
            raise RuntimeError("plugin route registry v2 is not initialized")
        return registry

    @override
    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] not in {"http", "websocket"}:
            return Match.NONE, {}
        from src.infrastructure.plugins.v2.boundary import current_generation_v2

        registry = self._registry()
        try:
            descriptor = current_generation_v2().descriptor
        except RuntimeV2Error as error:
            if error.code != "generation_not_pinned":
                raise
            publication = registry.current
            if publication is None:
                raise RuntimeError("plugin route registry v2 has no current publication") from error
        else:
            publication = registry.resolve(descriptor)
        match = publication.table.match(scope)
        return match, {"endpoint": self} if match is not Match.NONE else {}

    @override
    def url_path_for(self, name: str, /, **path_params: object) -> URLPath:
        if name != self.name or path_params:
            raise NoMatchFound(name, path_params)
        return URLPath(path="/", protocol="http")

    @override
    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        registry = self._registry()
        await GenerationRouteDispatcherV2(registry)(scope, receive, send)


def mount_generation_http_dispatcher_v2(app: FastAPI) -> None:
    """Install one stable selective dispatcher and bind docs to its publication."""
    original_openapi = app.openapi

    def generation_openapi() -> dict[str, Any]:
        registry = getattr(app.state, "platform_plugin_route_registry_v2", None)
        if isinstance(registry, RouteTableRegistryV2) and registry.current is not None:
            from src.infrastructure.plugins.v2.boundary import current_generation_v2

            try:
                descriptor = current_generation_v2().descriptor
            except RuntimeV2Error as error:
                if error.code != "generation_not_pinned":
                    raise
                publication = registry.current
            else:
                publication = registry.resolve(descriptor)
            return dict(publication.openapi.schema)
        return original_openapi()

    cast(Any, app).openapi = generation_openapi
    app.router.routes.append(ApplicationGenerationRouteDispatcherV2(app))


__all__ = [
    "ApplicationGenerationRouteDispatcherV2",
    "mount_generation_http_dispatcher_v2",
]
