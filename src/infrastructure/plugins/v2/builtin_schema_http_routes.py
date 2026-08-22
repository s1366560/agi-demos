"""V2-owned production contributions for the project schema HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.schema import (
    EdgeTypeMapResponse,
    EdgeTypeResponse,
    EntityTypeResponse,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.schema import (
    create_edge_map,
    create_edge_type,
    create_entity_type,
    delete_edge_map,
    delete_edge_type,
    delete_entity_type,
    list_edge_maps,
    list_edge_types,
    list_entity_types,
    update_edge_type,
    update_entity_type,
)
from src.infrastructure.adapters.primary.web.schema_application_authority_v2 import (
    schema_application_authority_dependency_v2,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SCHEMA_HTTP_ROUTES_ENTRY_V2 = "builtin-schema-http-routes"
SCHEMA_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/schema-routes"
SCHEMA_HTTP_ROUTES_ROW_V2 = "schema"


def _schema_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None = None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=SCHEMA_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("schema",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=SCHEMA_HTTP_ROUTES_ROW_V2,
    )


def schema_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``schema`` inventory row."""
    prefix = "/api/v1/projects/{project_id}/schema"
    return (
        _schema_route_v2(
            path=f"{prefix}/entities",
            methods=("GET",),
            endpoint=list_entity_types,
            name="list_entity_types",
            response_model=list[EntityTypeResponse],
        ),
        _schema_route_v2(
            path=f"{prefix}/entities",
            methods=("POST",),
            endpoint=create_entity_type,
            name="create_entity_type",
            response_model=EntityTypeResponse,
        ),
        _schema_route_v2(
            path=f"{prefix}/entities/{{entity_id}}",
            methods=("PUT",),
            endpoint=update_entity_type,
            name="update_entity_type",
            response_model=EntityTypeResponse,
        ),
        _schema_route_v2(
            path=f"{prefix}/entities/{{entity_id}}",
            methods=("DELETE",),
            endpoint=delete_entity_type,
            name="delete_entity_type",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _schema_route_v2(
            path=f"{prefix}/edges",
            methods=("GET",),
            endpoint=list_edge_types,
            name="list_edge_types",
            response_model=list[EdgeTypeResponse],
        ),
        _schema_route_v2(
            path=f"{prefix}/edges",
            methods=("POST",),
            endpoint=create_edge_type,
            name="create_edge_type",
            response_model=EdgeTypeResponse,
        ),
        _schema_route_v2(
            path=f"{prefix}/edges/{{edge_id}}",
            methods=("PUT",),
            endpoint=update_edge_type,
            name="update_edge_type",
            response_model=EdgeTypeResponse,
        ),
        _schema_route_v2(
            path=f"{prefix}/edges/{{edge_id}}",
            methods=("DELETE",),
            endpoint=delete_edge_type,
            name="delete_edge_type",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _schema_route_v2(
            path=f"{prefix}/mappings",
            methods=("GET",),
            endpoint=list_edge_maps,
            name="list_edge_maps",
            response_model=list[EdgeTypeMapResponse],
        ),
        _schema_route_v2(
            path=f"{prefix}/mappings",
            methods=("POST",),
            endpoint=create_edge_map,
            name="create_edge_map",
            response_model=EdgeTypeMapResponse,
        ),
        _schema_route_v2(
            path=f"{prefix}/mappings/{{map_id}}",
            methods=("DELETE",),
            endpoint=delete_edge_map,
            name="delete_edge_map",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
    )


def builtin_schema_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register project schema routes as reversible effects of one V2 Fiber."""
    definitions = schema_route_definitions_v2()

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

        await context.effect(setup, label=SCHEMA_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=SCHEMA_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SCHEMA_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SCHEMA_HTTP_ROUTES_ENTRY_V2",
    "SCHEMA_HTTP_ROUTES_MODULE_V2",
    "SCHEMA_HTTP_ROUTES_ROW_V2",
    "builtin_schema_http_routes_definition_v2",
    "get_current_user",
    "schema_application_authority_dependency_v2",
    "schema_route_definitions_v2",
]
