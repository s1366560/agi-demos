"""Build the complete builtin HTTP/WS surface as a private v2 route generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.routing import BaseRoute

from src.infrastructure.plugins.route_loader import install_builtin_routes

from .http_routes import RouteTableV2


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteGraphV2:
    table: RouteTableV2
    mounted_row_ids: tuple[str, ...]
    route_signatures: tuple[tuple[str, str, tuple[str, ...]], ...]


def build_builtin_route_graph_v2(*, workspace_core_settings: object) -> BuiltinRouteGraphV2:
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
    return BuiltinRouteGraphV2(
        table=RouteTableV2.from_fastapi_graph(private_app),
        mounted_row_ids=mounted,
        route_signatures=route_signatures_v2(private_app.router.routes),
    )


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
