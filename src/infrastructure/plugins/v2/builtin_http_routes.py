"""Build the complete builtin HTTP/WS surface as a private v2 route generation."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.routing import BaseRoute

from src.infrastructure.plugins.route_loader import (
    BuiltinRouteRowOverride,
    RouteLoadError,
    install_builtin_routes,
)

from .http_routes import RouteDefinitionV2, RouteTableV2, install_route_definitions_v2

_ROOT_PREVIEW_CATCH_ALL = "/{path:path}"
REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS = frozenset({"project-my-work", "system", "tenant-webhooks"})


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteGraphV2:
    table: RouteTableV2
    mounted_row_ids: tuple[str, ...]
    static_mounted_row_ids: tuple[str, ...]
    v2_owned_row_ids: tuple[str, ...]
    route_signatures: tuple[tuple[str, str, tuple[str, ...]], ...]


def build_builtin_route_graph_v2(
    *,
    workspace_core_settings: object,
    route_definitions: Sequence[RouteDefinitionV2] = (),
    required_v2_row_ids: Collection[str] = (),
    dependency_overrides: Mapping[Callable[..., Any], Callable[..., Any]] | None = None,
) -> BuiltinRouteGraphV2:
    """Replay the authoritative 72-row inventory into an invisible private graph."""
    private_app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        title="MemStack Builtin Routes V2",
    )
    private_app.dependency_overrides.update(dict(dependency_overrides or {}))
    definitions = tuple(route_definitions)
    row_overrides = _builtin_row_overrides_v2(definitions)
    missing_required = sorted(set(required_v2_row_ids) - set(row_overrides))
    if missing_required:
        raise RouteLoadError(
            "required V2 builtin route row claims missing: " + ", ".join(missing_required)
        )
    mounted = install_builtin_routes(
        private_app,
        workspace_core_settings=workspace_core_settings,
        row_overrides=row_overrides,
    )
    standalone = tuple(
        definition for definition in definitions if definition.replaces_builtin_row_id is None
    )
    _install_generation_routes_before_root_catch_all(private_app, standalone)
    v2_owned = tuple(row_id for row_id in mounted if row_id in row_overrides)
    return BuiltinRouteGraphV2(
        table=RouteTableV2.from_fastapi_graph(private_app, definitions=definitions),
        mounted_row_ids=mounted,
        static_mounted_row_ids=tuple(row_id for row_id in mounted if row_id not in row_overrides),
        v2_owned_row_ids=v2_owned,
        route_signatures=route_signatures_v2(private_app.router.routes),
    )


def _builtin_row_overrides_v2(
    definitions: Sequence[RouteDefinitionV2],
) -> dict[str, BuiltinRouteRowOverride]:
    grouped: dict[str, list[RouteDefinitionV2]] = {}
    for definition in definitions:
        if definition.replaces_builtin_row_id is None:
            continue
        grouped.setdefault(definition.replaces_builtin_row_id, []).append(definition)

    overrides: dict[str, BuiltinRouteRowOverride] = {}
    for row_id, claimed in grouped.items():
        owners = {definition.owner_entry_id for definition in claimed}
        if len(owners) != 1:
            raise ValueError(f"builtin route row {row_id} must have exactly one V2 owner")
        frozen = tuple(claimed)
        keys = frozenset(
            (method.upper(), definition.path)
            for definition in frozen
            for method in definition.methods
        )

        def install(app: FastAPI, routes: tuple[RouteDefinitionV2, ...] = frozen) -> None:
            install_route_definitions_v2(app, routes)

        overrides[row_id] = BuiltinRouteRowOverride(
            row_id=row_id,
            route_keys=keys,
            install=install,
        )
    return overrides


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
    "REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS",
    "BuiltinRouteGraphV2",
    "build_builtin_route_graph_v2",
    "route_signatures_v2",
]
