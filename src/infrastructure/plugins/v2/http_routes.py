"""Immutable generation-aware HTTP route tables for protocol v2 plugins."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from fastapi import FastAPI
from fastapi.params import Depends as DependsParam
from starlette.types import ASGIApp, Receive, Scope, Send

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .boundary import current_generation_v2
from .runtime import RuntimeV2Error


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
    include_in_schema: bool = True


@dataclass(frozen=True, kw_only=True)
class OpenApiSnapshotV2:
    """OpenAPI schema published atomically with one route generation."""

    descriptor: PluginGenerationDescriptorV2
    schema: Mapping[str, Any]


class RouteTableV2:
    """Private FastAPI graph built once and never mutated after publication."""

    def __init__(self, definitions: Sequence[RouteDefinitionV2]) -> None:
        routes = tuple(definitions)
        _validate_routes(routes)
        app = FastAPI(
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
            title="MemStack Plugin Routes",
        )
        for route in routes:
            app.add_api_route(
                route.path,
                route.endpoint,
                methods=list(route.methods),
                name=route.name,
                dependencies=list(route.dependencies),
                tags=list(route.tags),
                status_code=route.status_code,
                response_model=route.response_model,
                include_in_schema=route.include_in_schema,
            )
        self._definitions = routes
        self._app: ASGIApp = app
        self._openapi = MappingProxyType(app.openapi())

    @property
    def definitions(self) -> tuple[RouteDefinitionV2, ...]:
        return self._definitions

    def openapi_snapshot(
        self,
        descriptor: PluginGenerationDescriptorV2,
    ) -> OpenApiSnapshotV2:
        return OpenApiSnapshotV2(descriptor=descriptor, schema=self._openapi)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._app(scope, receive, send)


@dataclass(frozen=True, kw_only=True)
class RoutePublicationV2:
    descriptor: PluginGenerationDescriptorV2
    table: RouteTableV2
    openapi: OpenApiSnapshotV2


class RouteTableRegistryV2:
    """Atomically publish route/OpenAPI pairs while retaining leased generations."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_digest: dict[str, RoutePublicationV2] = {}
        self._current: RoutePublicationV2 | None = None

    @property
    def current(self) -> RoutePublicationV2 | None:
        return self._current

    async def publish(
        self,
        descriptor: PluginGenerationDescriptorV2,
        table: RouteTableV2,
    ) -> RoutePublicationV2:
        publication = RoutePublicationV2(
            descriptor=descriptor,
            table=table,
            openapi=table.openapi_snapshot(descriptor),
        )
        async with self._lock:
            self._by_digest[descriptor.digest] = publication
            self._current = publication
        return publication

    def resolve(self, descriptor: PluginGenerationDescriptorV2) -> RoutePublicationV2:
        publication = self._by_digest.get(descriptor.digest)
        if publication is None or publication.descriptor != descriptor:
            raise RuntimeV2Error(
                "route_generation_unavailable",
                "HTTP route table is unavailable for the pinned plugin generation",
            )
        return publication

    async def retire(self, descriptor: PluginGenerationDescriptorV2) -> None:
        async with self._lock:
            publication = self._by_digest.get(descriptor.digest)
            if publication is not None and publication.descriptor == descriptor:
                del self._by_digest[descriptor.digest]
            if self._current is publication:
                self._current = None


class GenerationRouteDispatcherV2:
    """Stable outer ASGI dispatcher that resolves the request's pinned generation."""

    def __init__(self, registry: RouteTableRegistryV2) -> None:
        self._registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        descriptor = current_generation_v2().descriptor
        publication = self._registry.resolve(descriptor)
        await publication.table(scope, receive, send)


def _validate_routes(routes: tuple[RouteDefinitionV2, ...]) -> None:
    seen: set[tuple[str, str]] = set()
    for route in routes:
        if not route.owner_entry_id.strip() or not route.name.strip():
            raise ValueError("route owner and name must be non-empty")
        if not route.path.startswith("/"):
            raise ValueError("route path must start with /")
        if not route.methods:
            raise ValueError("route methods must be non-empty")
        for method in route.methods:
            normalized = method.upper()
            key = normalized, route.path
            if key in seen:
                raise RuntimeV2Error(
                    "route_conflict",
                    f"duplicate v2 route {normalized} {route.path}",
                )
            seen.add(key)


__all__ = [
    "GenerationRouteDispatcherV2",
    "OpenApiSnapshotV2",
    "RouteDefinitionV2",
    "RoutePublicationV2",
    "RouteTableRegistryV2",
    "RouteTableV2",
]
