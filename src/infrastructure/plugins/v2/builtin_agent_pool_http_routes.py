"""V2-owned Agent Pool admin and project HTTP contributions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from fastapi.datastructures import DefaultPlaceholder
from fastapi.routing import APIRoute

from src.infrastructure.agent.pool.api.project_router import create_project_pool_router
from src.infrastructure.agent.pool.api.router import create_pool_router

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_POOL_HTTP_ROUTES_ENTRY_V2 = "builtin-agent-pool-http-routes"
AGENT_POOL_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/agent-pool-routes"
AGENT_POOL_ADMIN_HTTP_ROUTES_ROW_V2 = "create-pool"
AGENT_POOL_PROJECT_HTTP_ROUTES_ROW_V2 = "create-project-pool"


def _agent_pool_route_v2(source: APIRoute, *, row_id: str) -> RouteDefinitionV2:
    methods = tuple(sorted(source.methods or ()))
    if not methods:
        raise RuntimeV2Error(
            "invalid_agent_pool_route",
            f"Agent Pool route {source.name} has no HTTP methods",
        )
    response_class = source.response_class
    typed_response_class = (
        None if isinstance(response_class, DefaultPlaceholder) else response_class
    )
    return RouteDefinitionV2(
        owner_entry_id=AGENT_POOL_HTTP_ROUTES_ENTRY_V2,
        path=source.path,
        methods=methods,
        endpoint=source.endpoint,
        name=source.name,
        dependencies=tuple(source.dependencies),
        tags=cast("tuple[str, ...]", tuple(source.tags)),
        summary=source.summary,
        description=source.description,
        response_description=source.response_description,
        responses=source.responses or None,
        deprecated=source.deprecated,
        operation_id=source.operation_id,
        openapi_extra=source.openapi_extra,
        callbacks=tuple(source.callbacks or ()),
        status_code=source.status_code,
        response_model=source.response_model,
        response_model_include=source.response_model_include,
        response_model_exclude=source.response_model_exclude,
        response_model_by_alias=source.response_model_by_alias,
        response_model_exclude_unset=source.response_model_exclude_unset,
        response_model_exclude_defaults=source.response_model_exclude_defaults,
        response_model_exclude_none=source.response_model_exclude_none,
        response_class=typed_response_class,
        include_in_schema=source.include_in_schema,
        replaces_builtin_row_id=row_id,
    )


def agent_pool_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return both complete Agent Pool rows in inventory order."""
    rows = (
        (AGENT_POOL_ADMIN_HTTP_ROUTES_ROW_V2, create_pool_router()),
        (AGENT_POOL_PROJECT_HTTP_ROUTES_ROW_V2, create_project_pool_router()),
    )
    return tuple(
        _agent_pool_route_v2(route, row_id=row_id)
        for row_id, router in rows
        for route in router.routes
        if isinstance(route, APIRoute)
    )


def builtin_agent_pool_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register both Agent Pool rows as reversible generation effects."""
    definitions = agent_pool_route_definitions_v2()

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

        await context.effect(setup, label=AGENT_POOL_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=AGENT_POOL_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_POOL_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "AGENT_POOL_ADMIN_HTTP_ROUTES_ROW_V2",
    "AGENT_POOL_HTTP_ROUTES_ENTRY_V2",
    "AGENT_POOL_HTTP_ROUTES_MODULE_V2",
    "AGENT_POOL_PROJECT_HTTP_ROUTES_ROW_V2",
    "agent_pool_route_definitions_v2",
    "builtin_agent_pool_http_routes_definition_v2",
]
