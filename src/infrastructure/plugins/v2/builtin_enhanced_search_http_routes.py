"""V2-owned production contributions for the enhanced search HTTP rows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.enhanced_search import (
    get_search_capabilities,
    memory_search,
    search_advanced,
    search_by_community,
    search_by_graph_traversal,
    search_temporal,
    search_with_facets,
)
from src.infrastructure.adapters.primary.web.search_application_authority_v2 import (
    search_application_authority_dependency_v2,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ENHANCED_SEARCH_HTTP_ROUTES_ENTRY_V2 = "builtin-enhanced-search-http-routes"
ENHANCED_SEARCH_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/enhanced-search-routes"
ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2 = "enhanced-search"
ENHANCED_SEARCH_MEMORY_HTTP_ROUTES_ROW_V2 = "enhanced-search-memory"


def _enhanced_search_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    tag: str,
    row_id: str,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=ENHANCED_SEARCH_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=(tag,),
        response_model=dict[str, Any],
        replaces_builtin_row_id=row_id,
    )


def enhanced_search_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed enhanced-search inventory rows."""
    prefix = "/api/v1/search-enhanced"
    return (
        _enhanced_search_route_v2(
            path=f"{prefix}/advanced",
            methods=("POST",),
            endpoint=search_advanced,
            name="search_advanced",
            tag="search-enhanced",
            row_id=ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2,
        ),
        _enhanced_search_route_v2(
            path=f"{prefix}/graph-traversal",
            methods=("POST",),
            endpoint=search_by_graph_traversal,
            name="search_by_graph_traversal",
            tag="search-enhanced",
            row_id=ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2,
        ),
        _enhanced_search_route_v2(
            path=f"{prefix}/community",
            methods=("POST",),
            endpoint=search_by_community,
            name="search_by_community",
            tag="search-enhanced",
            row_id=ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2,
        ),
        _enhanced_search_route_v2(
            path=f"{prefix}/temporal",
            methods=("POST",),
            endpoint=search_temporal,
            name="search_temporal",
            tag="search-enhanced",
            row_id=ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2,
        ),
        _enhanced_search_route_v2(
            path=f"{prefix}/faceted",
            methods=("POST",),
            endpoint=search_with_facets,
            name="search_with_facets",
            tag="search-enhanced",
            row_id=ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2,
        ),
        _enhanced_search_route_v2(
            path=f"{prefix}/capabilities",
            methods=("GET",),
            endpoint=get_search_capabilities,
            name="get_search_capabilities",
            tag="search-enhanced",
            row_id=ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2,
        ),
        _enhanced_search_route_v2(
            path="/api/v1/memory/search",
            methods=("POST",),
            endpoint=memory_search,
            name="memory_search",
            tag="memory-search",
            row_id=ENHANCED_SEARCH_MEMORY_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_enhanced_search_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register enhanced search routes as reversible effects of one V2 Fiber."""
    definitions = enhanced_search_route_definitions_v2()

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

        await context.effect(setup, label=ENHANCED_SEARCH_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=ENHANCED_SEARCH_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ENHANCED_SEARCH_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ENHANCED_SEARCH_HTTP_ROUTES_ENTRY_V2",
    "ENHANCED_SEARCH_HTTP_ROUTES_MODULE_V2",
    "ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2",
    "ENHANCED_SEARCH_MEMORY_HTTP_ROUTES_ROW_V2",
    "builtin_enhanced_search_http_routes_definition_v2",
    "enhanced_search_route_definitions_v2",
    "get_current_user",
    "get_search_capabilities",
    "memory_search",
    "search_advanced",
    "search_application_authority_dependency_v2",
    "search_by_community",
    "search_by_graph_traversal",
    "search_temporal",
    "search_with_facets",
]
