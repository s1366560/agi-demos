"""Reversible HTTP route capability mounting with mandatory auth."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping, Sequence
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


@dataclass(frozen=True)
class HttpRouteCapabilityRow:
    """Persisted desired-state row projected to the assembler."""

    plugin_id: str
    method: str
    path: str
    permission: str
    authorization_mode: str
    enabled: bool = True


class HttpRouteCapabilityAppAssembler:
    """Reconcile declarative plugin HTTP routes onto a FastAPI application."""

    def __init__(
        self,
        mount_service: HttpRouteMountService,
        auth_dependencies: Mapping[HttpAuthorizationMode, Callable[..., Any]],
    ) -> None:
        self._mount_service = mount_service
        self._auth_dependencies = dict(auth_dependencies)
        self._mounted: dict[tuple[str, str], Disposable] = {}

    def reconcile(
        self,
        rows: Sequence[HttpRouteCapabilityRow],
        handlers: Mapping[tuple[str, str], HttpRouteHandler],
    ) -> tuple[int, int]:
        """Mount enabled rows and unmount stale rows atomically per route."""
        desired: dict[tuple[str, str], tuple[HttpRouteCapabilityRow, HttpRouteHandler]] = {}
        for row in rows:
            if not row.enabled:
                continue
            definition = _definition_from_row(row)
            key = definition.method.upper(), definition.path
            handler = handlers.get(key)
            if handler is None:
                raise HttpRouteMountError(
                    f"missing handler for {definition.method} {definition.path}"
                )
            if key in desired:
                raise HttpRouteMountError(
                    f"duplicate desired route: {definition.method} {definition.path}"
                )
            desired[key] = row, handler

        removed = 0
        for key in tuple(self._mounted):
            if key not in desired:
                self._mounted.pop(key)()
                removed += 1

        added = 0
        for key, (row, handler) in desired.items():
            if key in self._mounted:
                continue
            definition = _definition_from_row(row)
            auth_dependency = self._auth_dependencies.get(definition.authorization)
            self._mounted[key] = self._mount_service.mount(
                definition,
                handler,
                auth_dependency=auth_dependency,
            )
            added += 1
        return added, removed

    def dispose(self) -> None:
        """Unmount every route owned by this assembler."""
        for dispose in tuple(self._mounted.values()):
            dispose()
        self._mounted.clear()


def _definition_from_row(row: HttpRouteCapabilityRow) -> HttpRouteDefinition:
    try:
        authorization = HttpAuthorizationMode(row.authorization_mode)
    except ValueError as exc:
        raise HttpRouteMountError(
            f"unsupported route authorization mode: {row.authorization_mode}"
        ) from exc
    return HttpRouteDefinition(
        plugin_id=row.plugin_id,
        method=row.method,
        path=row.path,
        permission=row.permission,
        authorization=authorization,
    )
