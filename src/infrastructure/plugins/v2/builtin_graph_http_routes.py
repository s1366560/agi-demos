"""V2-owned production contributions for the graph HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.graph_application_authority_v2 import (
    graph_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.graph import (
    get_community,
    get_community_members,
    get_entity,
    get_entity_relationships,
    get_entity_types,
    get_graph,
    get_subgraph,
    list_communities,
    list_entities,
    rebuild_communities,
)
from src.infrastructure.adapters.primary.web.workflow_application_authority_v2 import (
    workflow_engine_authority_dependency_v2,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

GRAPH_HTTP_ROUTES_ENTRY_V2 = "builtin-graph-http-routes"
GRAPH_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/graph-routes"
GRAPH_HTTP_ROUTES_ROW_V2 = "graph"


def _graph_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=GRAPH_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("graph",),
        response_model=dict[str, Any],
        replaces_builtin_row_id=GRAPH_HTTP_ROUTES_ROW_V2,
    )


def graph_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``graph`` inventory row."""
    prefix = "/api/v1/graph"
    return (
        _graph_route_v2(
            path=f"{prefix}/communities/",
            methods=("GET",),
            endpoint=list_communities,
            name="list_communities",
        ),
        _graph_route_v2(
            path=f"{prefix}/entities/",
            methods=("GET",),
            endpoint=list_entities,
            name="list_entities",
        ),
        _graph_route_v2(
            path=f"{prefix}/entities/types",
            methods=("GET",),
            endpoint=get_entity_types,
            name="get_entity_types",
        ),
        _graph_route_v2(
            path=f"{prefix}/entities/{{entity_id}}",
            methods=("GET",),
            endpoint=get_entity,
            name="get_entity",
        ),
        _graph_route_v2(
            path=f"{prefix}/entities/{{entity_id}}/relationships",
            methods=("GET",),
            endpoint=get_entity_relationships,
            name="get_entity_relationships",
        ),
        _graph_route_v2(
            path=f"{prefix}/memory/graph",
            methods=("GET",),
            endpoint=get_graph,
            name="get_graph",
        ),
        _graph_route_v2(
            path=f"{prefix}/memory/graph/subgraph",
            methods=("POST",),
            endpoint=get_subgraph,
            name="get_subgraph",
        ),
        _graph_route_v2(
            path=f"{prefix}/communities/{{community_id}}",
            methods=("GET",),
            endpoint=get_community,
            name="get_community",
        ),
        _graph_route_v2(
            path=f"{prefix}/communities/{{community_id}}/members",
            methods=("GET",),
            endpoint=get_community_members,
            name="get_community_members",
        ),
        _graph_route_v2(
            path=f"{prefix}/communities/rebuild",
            methods=("POST",),
            endpoint=rebuild_communities,
            name="rebuild_communities",
        ),
    )


def builtin_graph_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register graph routes as reversible effects of one V2 Fiber."""
    definitions = graph_route_definitions_v2()

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

        await context.effect(setup, label=GRAPH_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=GRAPH_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(GRAPH_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "GRAPH_HTTP_ROUTES_ENTRY_V2",
    "GRAPH_HTTP_ROUTES_MODULE_V2",
    "GRAPH_HTTP_ROUTES_ROW_V2",
    "builtin_graph_http_routes_definition_v2",
    "get_current_user",
    "graph_application_authority_dependency_v2",
    "graph_route_definitions_v2",
    "workflow_engine_authority_dependency_v2",
]
