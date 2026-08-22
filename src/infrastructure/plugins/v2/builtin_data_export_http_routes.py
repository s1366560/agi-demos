"""V2-owned production contributions for the data export HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.graph_application_authority_v2 import (
    graph_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.data_export import (
    cleanup_data,
    export_data,
    get_graph_stats,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

DATA_EXPORT_HTTP_ROUTES_ENTRY_V2 = "builtin-data-export-http-routes"
DATA_EXPORT_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/data-export-routes"
DATA_EXPORT_HTTP_ROUTES_ROW_V2 = "data-export"


def data_export_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``data-export`` inventory row."""
    prefix = "/api/v1/data"
    return (
        RouteDefinitionV2(
            owner_entry_id=DATA_EXPORT_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/export",
            methods=("POST",),
            endpoint=export_data,
            name="export_data",
            tags=("data",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=DATA_EXPORT_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=DATA_EXPORT_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/stats",
            methods=("GET",),
            endpoint=get_graph_stats,
            name="get_graph_stats",
            tags=("data",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=DATA_EXPORT_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=DATA_EXPORT_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/cleanup",
            methods=("POST",),
            endpoint=cleanup_data,
            name="cleanup_data",
            tags=("data",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=DATA_EXPORT_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_data_export_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register data export routes as reversible effects of one V2 Fiber."""
    definitions = data_export_route_definitions_v2()

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

        await context.effect(setup, label=DATA_EXPORT_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=DATA_EXPORT_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(DATA_EXPORT_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "DATA_EXPORT_HTTP_ROUTES_ENTRY_V2",
    "DATA_EXPORT_HTTP_ROUTES_MODULE_V2",
    "DATA_EXPORT_HTTP_ROUTES_ROW_V2",
    "builtin_data_export_http_routes_definition_v2",
    "data_export_route_definitions_v2",
    "get_current_user",
    "graph_application_authority_dependency_v2",
]
