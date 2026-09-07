"""V2-owned production contributions for the builtin maintenance HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.maintenance import (
    check_embedding_dimensions,
    deduplicate_entities,
    get_embedding_status,
    get_maintenance_status,
    get_native_embedding_status,
    incremental_refresh,
    invalidate_stale_edges,
    migrate_embeddings,
    optimize_graph,
    rebuild_embeddings,
    validate_embeddings,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

MAINTENANCE_HTTP_ROUTES_ENTRY_V2 = "builtin-maintenance-http-routes"
MAINTENANCE_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/maintenance-routes"
MAINTENANCE_HTTP_ROUTES_ROW_V2 = "maintenance"
_MAINTENANCE_PREFIX_V2 = "/api/v1/maintenance"


def _maintenance_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=MAINTENANCE_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("maintenance",),
        response_model=response_model,
        replaces_builtin_row_id=MAINTENANCE_HTTP_ROUTES_ROW_V2,
    )


def maintenance_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``maintenance`` inventory row."""
    prefix = _MAINTENANCE_PREFIX_V2
    mapping: tuple[tuple[str, tuple[str, ...], Callable[..., Any], str, object | None], ...] = (
        (
            f"{prefix}/refresh/incremental",
            ("POST",),
            incremental_refresh,
            "incremental_refresh",
            dict[str, Any],
        ),
        (
            f"{prefix}/deduplicate",
            ("POST",),
            deduplicate_entities,
            "deduplicate_entities",
            dict[str, Any],
        ),
        (
            f"{prefix}/invalidate-edges",
            ("POST",),
            invalidate_stale_edges,
            "invalidate_stale_edges",
            dict[str, Any],
        ),
        (
            f"{prefix}/status",
            ("GET",),
            get_maintenance_status,
            "get_maintenance_status",
            dict[str, Any],
        ),
        (f"{prefix}/optimize", ("POST",), optimize_graph, "optimize_graph", Any),
        (
            f"{prefix}/embeddings/status",
            ("GET",),
            get_embedding_status,
            "get_embedding_status",
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/rebuild",
            ("POST",),
            rebuild_embeddings,
            "rebuild_embeddings",
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/dimensions/check",
            ("GET",),
            check_embedding_dimensions,
            "check_embedding_dimensions",
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/validate",
            ("GET",),
            validate_embeddings,
            "validate_embeddings",
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/native/status",
            ("GET",),
            get_native_embedding_status,
            "get_native_embedding_status",
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/native/migrate",
            ("POST",),
            migrate_embeddings,
            "migrate_embeddings",
            dict[str, Any],
        ),
    )
    return tuple(
        _maintenance_route_v2(
            path=path,
            methods=methods,
            endpoint=endpoint,
            name=name,
            response_model=response_model,
        )
        for path, methods, endpoint, name, response_model in mapping
    )


def builtin_maintenance_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register maintenance routes as reversible effects of one V2 Fiber."""
    definitions = maintenance_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label=MAINTENANCE_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=MAINTENANCE_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(MAINTENANCE_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "MAINTENANCE_HTTP_ROUTES_ENTRY_V2",
    "MAINTENANCE_HTTP_ROUTES_MODULE_V2",
    "MAINTENANCE_HTTP_ROUTES_ROW_V2",
    "builtin_maintenance_http_routes_definition_v2",
    "maintenance_route_definitions_v2",
]
