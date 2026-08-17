"""Reversible HTTP route capability mounting with mandatory auth."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

from src.domain.ports.plugins import (
    HttpAuthorizationMode,
    HttpRouteDefinition,
    HttpRouteHandler,
    route_definition_is_safe,
)

Disposable = Callable[[], None]


class HttpRouteMountError(RuntimeError):
    """Raised when a route cannot be mounted safely."""


@dataclass(frozen=True)
class MountedHttpRoute:
    """Mounted route facts used for inventory and teardown."""

    definition: HttpRouteDefinition
    route: APIRoute


class HttpRouteMountService:
    """Mount and unmount plugin routes on a FastAPI application."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._mounted: dict[tuple[str, str], MountedHttpRoute] = {}

    def mount(
        self,
        definition: HttpRouteDefinition,
        handler: HttpRouteHandler,
        *,
        auth_dependency: Callable[..., Any] | None = None,
    ) -> Disposable:
        """Mount one route after enforcing authorization and duplicate checks."""
        if not route_definition_is_safe(definition):
            raise HttpRouteMountError(f"unsafe route definition: {definition}")
        if auth_dependency is None:
            raise HttpRouteMountError(f"route {definition.path} requires auth dependency")
        if definition.authorization == HttpAuthorizationMode.AUTHENTICATED:
            raise HttpRouteMountError(
                "plugin routes must require tenant/project-scoped authorization"
            )
        key = definition.method.upper(), definition.path
        if key in self._mounted:
            raise HttpRouteMountError(
                f"route already mounted: {definition.method} {definition.path}"
            )

        self._app.router.add_api_route(
            path=definition.path,
            endpoint=handler,
            methods=[definition.method.upper()],
            name=f"plugin:{definition.plugin_id}:{definition.permission}",
            summary=definition.summary or None,
            tags=list(definition.tags) or None,
            dependencies=[Depends(auth_dependency)],
        )
        route = self._app.router.routes[-1]
        if not isinstance(route, APIRoute):
            raise HttpRouteMountError("FastAPI did not create an APIRoute")
        mounted = MountedHttpRoute(definition=definition, route=route)
        self._mounted[key] = mounted

        def dispose() -> None:
            existing = self._mounted.pop(key, None)
            if existing is None:
                return
            with contextlib.suppress(ValueError):
                self._app.router.routes.remove(existing.route)

        return dispose

    def list_routes(self) -> tuple[MountedHttpRoute, ...]:
        """Return deterministic mounted plugin route inventory."""
        return tuple(self._mounted[key] for key in sorted(self._mounted))
