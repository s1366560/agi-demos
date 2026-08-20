"""Build the complete builtin HTTP/WS surface as a private v2 route generation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.routing import BaseRoute

from src.infrastructure.plugins.route_loader import install_builtin_routes

from .http_routes import RouteDefinitionV2, RouteTableV2, install_route_definitions_v2

_ROOT_PREVIEW_CATCH_ALL = "/{path:path}"


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteGraphV2:
    table: RouteTableV2
    mounted_row_ids: tuple[str, ...]
    route_signatures: tuple[tuple[str, str, tuple[str, ...]], ...]


def build_builtin_route_graph_v2(
    *,
    workspace_core_settings: object,
    route_definitions: Sequence[RouteDefinitionV2] = (),
) -> BuiltinRouteGraphV2:
    """Replay the authoritative 72-row inventory into an invisible private graph."""
    private_app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        title="MemStack Builtin Routes V2",
    )
    mounted = install_builtin_routes(
        private_app,
        workspace_core_settings=workspace_core_settings,
    )
    definitions = tuple(route_definitions)
    _install_generation_routes_before_root_catch_all(private_app, definitions)
    return BuiltinRouteGraphV2(
        table=RouteTableV2.from_fastapi_graph(private_app, definitions=definitions),
        mounted_row_ids=mounted,
        route_signatures=route_signatures_v2(private_app.router.routes),
    )


def _install_generation_routes_before_root_catch_all(
    app: FastAPI,
    definitions: Sequence[RouteDefinitionV2],
) -> None:
    """Keep declared routes reachable ahead of the host-preview fallback."""
    if not definitions:
        return
    existing_count = len(app.router.routes)
    install_route_definitions_v2(app, definitions)
    contributed = app.router.routes[existing_count:]
    del app.router.routes[existing_count:]
    insertion_index = next(
        (
            index
            for index, route in enumerate(app.router.routes)
            if getattr(route, "path", None) == _ROOT_PREVIEW_CATCH_ALL
        ),
        len(app.router.routes),
    )
    app.router.routes[insertion_index:insertion_index] = contributed


def route_signatures_v2(
    routes: list[BaseRoute],
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Return ordered structural route signatures for parity checks."""
    signatures: list[tuple[str, str, tuple[str, ...]]] = []
    for route in routes:
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        name = str(getattr(route, "name", ""))
        raw_methods: Any = getattr(route, "methods", None)
        methods = tuple(sorted(str(method) for method in raw_methods)) if raw_methods else ()
        signatures.append((path, name, methods))
    return tuple(signatures)


__all__ = [
    "BuiltinRouteGraphV2",
    "build_builtin_route_graph_v2",
    "route_signatures_v2",
]
