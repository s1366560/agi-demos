"""Immutable generation-aware HTTP/WebSocket tables for protocol v2 plugins."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import Any

from fastapi import FastAPI
from fastapi.params import Depends as DependsParam
from fastapi.routing import APIRoute
from starlette.responses import Response
from starlette.routing import BaseRoute, Match, Router, WebSocketRoute
from starlette.types import ASGIApp, Receive, Scope, Send

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .openapi import build_openapi_schema_v2
from .runtime import RuntimeV2Error

WEBSOCKET_ROUTE_METHOD_V2 = "WEBSOCKET"


@dataclass(frozen=True, kw_only=True)
class RouteDefinitionV2:
    """One immutable HTTP contribution owned by a plugin entry."""

    owner_entry_id: str
    path: str
    methods: tuple[str, ...]
    endpoint: Callable[..., Any]
    name: str
    dependencies: tuple[DependsParam, ...] = ()
    tags: tuple[str, ...] = ()
    status_code: int | None = None
    response_model: object | None = None
    response_class: type[Response] | None = None
    route_class_override: type[APIRoute] | None = None
    include_in_schema: bool = True
    replaces_builtin_row_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class WebSocketRouteDefinitionV2:
    """One immutable WebSocket contribution owned by a plugin entry."""

    owner_entry_id: str
    path: str
    endpoint: Callable[..., Any]
    name: str
    dependencies: tuple[DependsParam, ...] = ()
    replaces_builtin_row_id: str | None = None

    @property
    def methods(self) -> tuple[str, ...]:
        """Expose the structural key used for mixed builtin-row parity."""
        return (WEBSOCKET_ROUTE_METHOD_V2,)


type RouteContributionV2 = RouteDefinitionV2 | WebSocketRouteDefinitionV2


@dataclass(frozen=True, kw_only=True)
class OpenApiSnapshotV2:
    """OpenAPI schema published atomically with one route generation."""

    descriptor: PluginGenerationDescriptorV2
    schema: Mapping[str, Any]


class RouteTableV2:
    """Private FastAPI graph built once and never mutated after publication."""

    def __init__(self, definitions: Sequence[RouteContributionV2]) -> None:
        routes = tuple(definitions)
        _validate_routes(routes)
        app = FastAPI(
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
            title="MemStack Plugin Routes",
        )
        install_route_definitions_v2(app, routes)
        self._definitions = routes
        self._routes: tuple[BaseRoute, ...] = tuple(app.router.routes)
        self._app: ASGIApp = app
        self._openapi = MappingProxyType(build_openapi_schema_v2(app))

    @classmethod
    def from_fastapi_graph(
        cls,
        app: FastAPI,
        *,
        definitions: Sequence[RouteContributionV2] = (),
    ) -> RouteTableV2:
        """Freeze an already assembled private FastAPI graph without re-registering routes."""
        instance = cls.__new__(cls)
        instance._definitions = tuple(definitions)
        instance._routes = tuple(app.router.routes)
        instance._app = Router(routes=list(instance._routes))
        instance._openapi = MappingProxyType(build_openapi_schema_v2(app))
        return instance

    @property
    def definitions(self) -> tuple[RouteContributionV2, ...]:
        return self._definitions

    def openapi_snapshot(
        self,
        descriptor: PluginGenerationDescriptorV2,
    ) -> OpenApiSnapshotV2:
        return OpenApiSnapshotV2(descriptor=descriptor, schema=self._openapi)

    def match(self, scope: Scope) -> Match:
        """Return the strongest structural match without executing the private graph."""
        partial = False
        for route in self._routes:
            match, _child_scope = route.matches(scope)
            if match is Match.FULL:
                return Match.FULL
            if match is Match.PARTIAL:
                partial = True
        return Match.PARTIAL if partial else Match.NONE

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._app(scope, receive, send)


class RouteTableBuilderV2:
    """Mutable staging-only route contributions that freeze into one immutable table."""

    def __init__(self) -> None:
        self._definitions: list[RouteContributionV2] = []
        self._frozen: RouteTableV2 | None = None

    @property
    def definitions(self) -> tuple[RouteContributionV2, ...]:
        return tuple(self._definitions)

    def contribute(self, definition: RouteContributionV2) -> Callable[[], Awaitable[None]]:
        if self._frozen is not None:
            raise RuntimeV2Error(
                "route_table_frozen",
                "route contributions are closed after the generation table is frozen",
            )
        candidate = (*self._definitions, definition)
        _validate_routes(candidate)
        self._definitions.append(definition)

        async def dispose() -> None:
            if definition in self._definitions:
                self._definitions.remove(definition)

        return dispose

    def freeze(self) -> RouteTableV2:
        if self._frozen is None:
            self._frozen = RouteTableV2(self._definitions)
        return self._frozen


@dataclass(frozen=True, kw_only=True)
class RoutePublicationV2:
    descriptor: PluginGenerationDescriptorV2
    table: RouteTableV2
    openapi: OpenApiSnapshotV2


class RouteTableRegistryV2:
    """Atomically publish route/OpenAPI pairs while retaining leased generations."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_descriptor: dict[PluginGenerationDescriptorV2, RoutePublicationV2] = {}
        self._current: RoutePublicationV2 | None = None

    @property
    def current(self) -> RoutePublicationV2 | None:
        return self._current

    def stage(
        self,
        descriptor: PluginGenerationDescriptorV2,
        table: RouteTableV2,
    ) -> RoutePublicationV2:
        """Prepare a route/OpenAPI pair without changing the visible current table."""
        publication = RoutePublicationV2(
            descriptor=descriptor,
            table=table,
            openapi=table.openapi_snapshot(descriptor),
        )
        with self._lock:
            if descriptor in self._by_descriptor:
                raise RuntimeV2Error(
                    "route_generation_conflict",
                    "HTTP route table is already staged for the plugin generation",
                )
            self._by_descriptor[descriptor] = publication
        return publication

    def activate(self, publication: RoutePublicationV2) -> None:
        """Make one exactly staged route/OpenAPI pair visible without awaiting."""
        with self._lock:
            staged = self._by_descriptor.get(publication.descriptor)
            if staged is not publication:
                raise RuntimeV2Error(
                    "route_generation_not_staged",
                    "HTTP route table must be staged before activation",
                )
            self._current = publication

    def discard(self, publication: RoutePublicationV2) -> None:
        """Remove a failed, invisible staged publication."""
        with self._lock:
            staged = self._by_descriptor.get(publication.descriptor)
            if staged is publication and self._current is not publication:
                del self._by_descriptor[publication.descriptor]

    async def publish(
        self,
        descriptor: PluginGenerationDescriptorV2,
        table: RouteTableV2,
    ) -> RoutePublicationV2:
        publication = self.stage(descriptor, table)
        self.activate(publication)
        return publication

    def resolve(self, descriptor: PluginGenerationDescriptorV2) -> RoutePublicationV2:
        with self._lock:
            publication = self._by_descriptor.get(descriptor)
        if publication is None:
            raise RuntimeV2Error(
                "route_generation_unavailable",
                "HTTP route table is unavailable for the pinned plugin generation",
            )
        return publication

    async def retire(self, descriptor: PluginGenerationDescriptorV2) -> None:
        with self._lock:
            publication = self._by_descriptor.pop(descriptor, None)
            if self._current is publication:
                self._current = None


class GenerationRouteDispatcherV2:
    """Stable outer ASGI dispatcher that resolves the request's pinned generation."""

    def __init__(self, registry: RouteTableRegistryV2) -> None:
        self._registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        from .boundary import current_generation_v2

        descriptor = current_generation_v2().descriptor
        publication = self._registry.resolve(descriptor)
        await publication.table(scope, receive, send)


def _validate_routes(routes: tuple[RouteContributionV2, ...]) -> None:
    seen: set[tuple[str, str]] = set()
    for route in routes:
        if not route.owner_entry_id.strip() or not route.name.strip():
            raise ValueError("route owner and name must be non-empty")
        if not route.path.startswith("/"):
            raise ValueError("route path must start with /")
        if not route.methods:
            raise ValueError("route methods must be non-empty")
        if route.replaces_builtin_row_id is not None and not route.replaces_builtin_row_id.strip():
            raise ValueError("replaced builtin route row id must be non-empty")
        if isinstance(route, RouteDefinitionV2) and any(
            method.upper() == WEBSOCKET_ROUTE_METHOD_V2 for method in route.methods
        ):
            raise ValueError("HTTP route methods cannot use the WebSocket structural key")
        for method in route.methods:
            normalized = method.upper()
            key = normalized, route.path
            if key in seen:
                raise RuntimeV2Error(
                    "route_conflict",
                    f"duplicate v2 route {normalized} {route.path}",
                )
            seen.add(key)


def install_route_definitions_v2(
    app: FastAPI,
    definitions: Sequence[RouteContributionV2],
) -> None:
    """Atomically validate and mount staged HTTP/WebSocket contributions."""
    routes = tuple(definitions)
    _validate_routes(routes)
    existing: set[tuple[str, str]] = set()
    for mounted in app.router.routes:
        path = getattr(mounted, "path", None)
        if not isinstance(path, str):
            continue
        methods = getattr(mounted, "methods", None)
        if methods:
            existing.update((str(method).upper(), path) for method in methods)
        elif isinstance(mounted, WebSocketRoute):
            existing.add((WEBSOCKET_ROUTE_METHOD_V2, path))
    for route in routes:
        for method in route.methods:
            key = method.upper(), route.path
            if key in existing:
                raise RuntimeV2Error(
                    "route_conflict",
                    f"v2 route conflicts with private graph {key[0]} {key[1]}",
                )
    for route in routes:
        if isinstance(route, WebSocketRouteDefinitionV2):
            app.add_api_websocket_route(
                route.path,
                route.endpoint,
                name=route.name,
                dependencies=list(route.dependencies),
            )
            continue
        response_options: dict[str, Any] = {}
        if route.response_class is not None:
            response_options["response_class"] = route.response_class
        if route.route_class_override is not None:
            response_options["route_class_override"] = route.route_class_override
        app.router.add_api_route(
            route.path,
            route.endpoint,
            methods=list(route.methods),
            name=route.name,
            dependencies=list(route.dependencies),
            tags=list(route.tags),
            status_code=route.status_code,
            response_model=route.response_model,
            include_in_schema=route.include_in_schema,
            **response_options,
        )


__all__ = [
    "WEBSOCKET_ROUTE_METHOD_V2",
    "GenerationRouteDispatcherV2",
    "OpenApiSnapshotV2",
    "RouteContributionV2",
    "RouteDefinitionV2",
    "RoutePublicationV2",
    "RouteTableBuilderV2",
    "RouteTableRegistryV2",
    "RouteTableV2",
    "WebSocketRouteDefinitionV2",
    "install_route_definitions_v2",
]
