"""V2 route effects for the Workspace Core internal Provider surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from fastapi.routing import APIRoute

from src.infrastructure.adapters.primary.web.workspace_core_provider import (
    router as workspace_core_provider_router,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ENTRY_V2 = "builtin-workspace-core-provider-http-routes"
WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_MODULE_V2 = (
    "builtin://memstack/http/workspace-core-provider-routes"
)
WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ROW_V2 = "workspace-core-runtime"


def _workspace_core_provider_route_v2(source: APIRoute) -> RouteDefinitionV2:
    methods = tuple(sorted(source.methods or ()))
    if not methods:
        raise RuntimeV2Error(
            "invalid_workspace_core_provider_route",
            f"Workspace Core Provider route {source.name} has no HTTP methods",
        )
    return RouteDefinitionV2(
        owner_entry_id=WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ENTRY_V2,
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
        include_in_schema=source.include_in_schema,
        replaces_builtin_row_id=WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ROW_V2,
    )


def workspace_core_provider_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return all internal Provider routes contributed by the retired hybrid helper."""
    return tuple(
        _workspace_core_provider_route_v2(route)
        for route in workspace_core_provider_router.routes
        if isinstance(route, APIRoute)
    )


def builtin_workspace_core_provider_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register internal Provider routes as reversible generation effects."""
    definitions = workspace_core_provider_route_definitions_v2()

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

        await context.effect(
            setup,
            label=WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ENTRY_V2,
        )

    return PluginDefinitionV2(
        module_ref=WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ENTRY_V2",
    "WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_MODULE_V2",
    "WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ROW_V2",
    "builtin_workspace_core_provider_http_routes_definition_v2",
    "workspace_core_provider_route_definitions_v2",
]
