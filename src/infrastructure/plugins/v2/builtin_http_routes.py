"""Build the complete builtin HTTP/WS surface as a private v2 route generation."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.routing import BaseRoute, compile_path

from src.domain.model.plugins.generated_v2 import ScopeV2

from .http_routes import (
    RouteContributionV2,
    RouteTableBuilderV2,
    RouteTableV2,
    install_route_definitions_v2,
)
from .route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from .runtime import RuntimeGenerationV2, RuntimeV2Error

_ROOT_PREVIEW_CATCH_ALL = "/{path:path}"
# Authentication and the plugin management/recovery interfaces must survive a profile change.
KERNEL_ROUTE_GROUPS_V2 = frozenset({"auth", "platform-plugins", "plugin-marketplace"})


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteGraphV2:
    table: RouteTableV2
    mounted_row_ids: tuple[str, ...]
    static_mounted_row_ids: tuple[str, ...]
    v2_owned_row_ids: tuple[str, ...]
    route_signatures: tuple[tuple[str, str, tuple[str, ...]], ...]


def generation_route_definitions_v2(
    generation: RuntimeGenerationV2, scope: ScopeV2, *, optional: bool = False
) -> tuple[RouteContributionV2, ...] | None:
    """Seal the published builder and check each active entry that requested route effects."""
    contributors = {
        fiber.entry.entry_id
        for fiber in generation.fibers
        if any(
            item.service == ROUTE_TABLE_BUILDER_SERVICE_V2
            for item in fiber.contract.services.requires
        )
    }
    if (
        optional
        and not contributors
        and not any(
            item.service == ROUTE_TABLE_BUILDER_SERVICE_V2
            for fiber in generation.fibers
            for item in fiber.contract.services.provides
        )
    ):
        return None
    builder = generation.resolve(ROUTE_TABLE_BUILDER_SERVICE_V2, scope)
    if not isinstance(builder, RouteTableBuilderV2):
        raise RuntimeV2Error(
            "invalid_route_table_builder", "HTTP provider supplied an invalid route builder"
        )
    definitions = builder.seal()
    missing = contributors.difference(route.owner_entry_id for route in definitions)
    if missing:
        raise RuntimeV2Error(
            "required_route_contribution_missing",
            "active entries did not contribute their declared HTTP routes: "
            + ", ".join(sorted(missing)),
        )
    return definitions


def build_builtin_route_graph_v2(
    *,
    workspace_core_settings: object,
    route_definitions: Sequence[RouteContributionV2] = (),
    required_v2_row_ids: Collection[str] = (),
    dependency_overrides: Mapping[Callable[..., Any], Callable[..., Any]] | None = None,
) -> BuiltinRouteGraphV2:
    """Build one private graph exclusively from the generation's V2 contributions."""
    _ = workspace_core_settings
    private_app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        title="MemStack Builtin Routes V2",
    )
    if dependency_overrides:
        private_app.dependency_overrides.update(dict(dependency_overrides))
    definitions = tuple(route_definitions)
    row_owners = _builtin_row_owners_v2(definitions)
    missing_required = sorted(set(required_v2_row_ids) - set(row_owners))
    if missing_required:
        raise RuntimeV2Error(
            "required_route_contribution_missing",
            "required V2 route contributions are missing: " + ", ".join(missing_required),
        )
    ordered_definitions = _definitions_before_root_catch_all_v2(definitions)
    install_route_definitions_v2(private_app, ordered_definitions)
    mounted = _ordered_builtin_row_ids_v2(ordered_definitions)
    return BuiltinRouteGraphV2(
        table=RouteTableV2.from_fastapi_graph(
            private_app,
            definitions=ordered_definitions,
        ),
        mounted_row_ids=mounted,
        static_mounted_row_ids=(),
        v2_owned_row_ids=mounted,
        route_signatures=route_signatures_v2(private_app.router.routes),
    )


def _builtin_row_owners_v2(
    definitions: Sequence[RouteContributionV2],
) -> dict[str, str]:
    owners: dict[str, str] = {}
    for definition in definitions:
        row_id = definition.replaces_builtin_row_id
        if row_id is None:
            continue
        existing_owner = owners.setdefault(row_id, definition.owner_entry_id)
        if existing_owner != definition.owner_entry_id:
            raise RuntimeV2Error(
                "route_row_owner_conflict",
                f"V2 route row {row_id} must have exactly one owner",
            )
    return owners


def _definitions_before_root_catch_all_v2(
    definitions: Sequence[RouteContributionV2],
) -> tuple[RouteContributionV2, ...]:
    """Keep every declared route reachable ahead of the host-preview fallback."""
    regular = tuple(
        definition for definition in definitions if definition.path != _ROOT_PREVIEW_CATCH_ALL
    )
    catch_all = tuple(
        definition for definition in definitions if definition.path == _ROOT_PREVIEW_CATCH_ALL
    )
    compiled = tuple((definition, compile_path(definition.path)) for definition in regular)
    ordered: list[tuple[RouteContributionV2, tuple[Any, str, dict[str, Any]]]] = []
    for definition, compiled_path in compiled:
        _pattern, _format, parameters = compiled_path
        insertion = len(ordered)
        if not parameters:
            methods = set(definition.methods)
            for index, (previous, previous_path) in enumerate(ordered):
                previous_pattern, _previous_format, previous_parameters = previous_path
                if (
                    previous_parameters
                    and methods.intersection(previous.methods)
                    and previous_pattern.fullmatch(definition.path)
                ):
                    insertion = index
                    break
        ordered.insert(insertion, (definition, compiled_path))
    return (*(item for item, _compiled in ordered), *catch_all)


def _ordered_builtin_row_ids_v2(
    definitions: Sequence[RouteContributionV2],
) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for definition in definitions:
        row_id = definition.replaces_builtin_row_id
        if row_id is None or row_id in seen:
            continue
        seen.add(row_id)
        ordered.append(row_id)
    return tuple(ordered)


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
    "KERNEL_ROUTE_GROUPS_V2",
    "BuiltinRouteGraphV2",
    "build_builtin_route_graph_v2",
    "generation_route_definitions_v2",
    "route_signatures_v2",
]
