"""V2-owned production contributions for the graph stores HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.infrastructure.adapters.primary.web.routers.graph_stores import (
    create_store,
    delete_store,
    get_store,
    list_store_types,
    list_stores,
    test_store_by_id,
    test_store_raw,
    update_store,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

GRAPH_STORES_HTTP_ROUTES_ENTRY_V2 = "builtin-graph-stores-http-routes"
GRAPH_STORES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/graph-stores-routes"
GRAPH_STORES_HTTP_ROUTES_ROW_V2 = "graph-stores"


def _graph_stores_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    status_code: int | None = None,
    response_model: object | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=GRAPH_STORES_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("graph-stores",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=GRAPH_STORES_HTTP_ROUTES_ROW_V2,
    )


def graph_stores_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``graph-stores`` inventory row."""
    collection_path = "/api/v1/graph-stores"
    item_path = f"{collection_path}/{{store_id}}"
    return (
        _graph_stores_route_v2(
            path=f"{collection_path}/types",
            methods=("GET",),
            endpoint=list_store_types,
            name="list_store_types",
            response_model=dict[str, Any],
        ),
        _graph_stores_route_v2(
            path=f"{collection_path}/test",
            methods=("POST",),
            endpoint=test_store_raw,
            name="test_store_raw",
            response_model=dict[str, Any],
        ),
        _graph_stores_route_v2(
            path=collection_path,
            methods=("POST",),
            endpoint=create_store,
            name="create_store",
            status_code=status.HTTP_201_CREATED,
            response_model=dict[str, Any],
        ),
        _graph_stores_route_v2(
            path=collection_path,
            methods=("GET",),
            endpoint=list_stores,
            name="list_stores",
            response_model=dict[str, Any],
        ),
        _graph_stores_route_v2(
            path=item_path,
            methods=("GET",),
            endpoint=get_store,
            name="get_store",
            response_model=dict[str, Any],
        ),
        _graph_stores_route_v2(
            path=item_path,
            methods=("PUT",),
            endpoint=update_store,
            name="update_store",
            response_model=dict[str, Any],
        ),
        _graph_stores_route_v2(
            path=item_path,
            methods=("DELETE",),
            endpoint=delete_store,
            name="delete_store",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _graph_stores_route_v2(
            path=f"{item_path}/test",
            methods=("POST",),
            endpoint=test_store_by_id,
            name="test_store_by_id",
            response_model=dict[str, Any],
        ),
    )


def builtin_graph_stores_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register graph stores routes as reversible effects of one V2 Fiber."""
    definitions = graph_stores_route_definitions_v2()

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

        await context.effect(setup, label=GRAPH_STORES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=GRAPH_STORES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(GRAPH_STORES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "GRAPH_STORES_HTTP_ROUTES_ENTRY_V2",
    "GRAPH_STORES_HTTP_ROUTES_MODULE_V2",
    "GRAPH_STORES_HTTP_ROUTES_ROW_V2",
    "builtin_graph_stores_http_routes_definition_v2",
    "graph_stores_route_definitions_v2",
]
