"""V2-owned production contribution for the builtin engines HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .engine_services import EngineCatalogProtocolV2
from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ENGINES_HTTP_ROUTES_ENTRY_V2 = "builtin-engines-http-routes"
ENGINES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/engines-routes"
ENGINES_HTTP_ROUTES_ROW_V2 = "engines"
ENGINE_CATALOG_INJECT_V2 = "catalog"


def engines_route_definitions_v2(
    catalog: EngineCatalogProtocolV2,
) -> tuple[RouteDefinitionV2, ...]:
    """Return the complete ``engines`` row bound to one generation catalog."""

    async def list_engines() -> list[dict[str, Any]]:
        return [engine.to_public_dict() for engine in catalog.list_engines()]

    return (
        RouteDefinitionV2(
            owner_entry_id=ENGINES_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/engines",
            methods=("GET",),
            endpoint=list_engines,
            name="list_engines",
            tags=("engines",),
            response_model=list[dict[str, Any]],
            replaces_builtin_row_id=ENGINES_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_engines_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the engines route as one reversible V2 Consumer effect."""

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )
        catalog = context.require(ENGINE_CATALOG_INJECT_V2)
        if not isinstance(catalog, EngineCatalogProtocolV2):
            raise RuntimeV2Error(
                "invalid_engine_catalog",
                "catalog inject is not a protocol v2 engine catalog",
            )
        definitions = engines_route_definitions_v2(catalog)

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

        await context.effect(setup, label=ENGINES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=ENGINES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ENGINES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ENGINES_HTTP_ROUTES_ENTRY_V2",
    "ENGINES_HTTP_ROUTES_MODULE_V2",
    "ENGINES_HTTP_ROUTES_ROW_V2",
    "ENGINE_CATALOG_INJECT_V2",
    "builtin_engines_http_routes_definition_v2",
    "engines_route_definitions_v2",
]
