"""Fiber-owned route contribution definitions for protocol v2 staging."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_authority import (
    ROUTE_AUTHORITY_CATALOG_INJECT_V2,
    ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
    PluginRouteAuthorityV2,
    RouteAuthorityCatalogV2,
)
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ROUTE_TABLE_BUILDER_SERVICE_V2 = "service:http.route-table-builder"
ROUTE_TABLE_BUILDER_INJECT_V2 = "route_table"
ROUTE_TABLE_BUILDER_MODULE_V2 = "builtin://memstack/http/route-table-builder"


def route_table_builder_definition_v2(
    *,
    module_ref: str = ROUTE_TABLE_BUILDER_MODULE_V2,
    builder: RouteTableBuilderV2 | None = None,
    authority_catalog: RouteAuthorityCatalogV2 | None = None,
    contract_digest: str | None = None,
) -> PluginDefinitionV2:
    """Provide one builder owned by the staging generation's provider Fiber."""

    def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        _ = context.provide(
            ROUTE_TABLE_BUILDER_SERVICE_V2,
            builder or RouteTableBuilderV2(),
            label="route-table-builder",
        )
        catalog = authority_catalog
        if catalog is None and module_ref == ROUTE_TABLE_BUILDER_MODULE_V2:
            catalog = RouteAuthorityCatalogV2()
        if catalog is not None:
            _ = context.provide(
                ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
                catalog,
                label="route-authority-catalog",
            )

    return PluginDefinitionV2(
        module_ref=module_ref,
        contract_digest=contract_digest or generated_contract_digest_v2(module_ref),
        apply=apply,
    )


def route_contribution_definition_v2(
    *,
    module_ref: str,
    routes: Sequence[RouteDefinitionV2],
    authorities: Sequence[PluginRouteAuthorityV2] = (),
    contract_digest: str,
) -> PluginDefinitionV2:
    """Contribute static routes as reversible effects of one plugin entry Fiber."""
    definitions = tuple(routes)
    authority_rows = tuple(authorities)

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder, authority_catalog = _route_effect_services_v2(
            context,
            require_authority=bool(authority_rows),
        )
        _validate_route_effect_ownership_v2(
            context.entry_id,
            definitions,
            authority_rows,
        )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            return await _contribute_route_effects_v2(
                builder,
                authority_catalog,
                definitions,
                authority_rows,
            )

        await context.effect(setup, label="http-route-contributions")

    return PluginDefinitionV2(
        module_ref=module_ref,
        contract_digest=contract_digest,
        apply=apply,
    )


def _route_effect_services_v2(
    context: ContextV2,
    *,
    require_authority: bool,
) -> tuple[RouteTableBuilderV2, RouteAuthorityCatalogV2 | None]:
    builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
    if not isinstance(builder, RouteTableBuilderV2):
        raise RuntimeV2Error(
            "invalid_route_table_builder",
            "route_table inject is not a protocol v2 route table builder",
        )
    if not require_authority:
        return builder, None
    authority_catalog = context.require(ROUTE_AUTHORITY_CATALOG_INJECT_V2)
    if not isinstance(authority_catalog, RouteAuthorityCatalogV2):
        raise RuntimeV2Error(
            "invalid_route_authority_catalog",
            "route_authority inject is not a protocol v2 authority catalog",
        )
    return builder, authority_catalog


def _validate_route_effect_ownership_v2(
    entry_id: str,
    definitions: Sequence[RouteDefinitionV2],
    authorities: Sequence[PluginRouteAuthorityV2],
) -> None:
    for definition in definitions:
        if definition.owner_entry_id != entry_id:
            raise RuntimeV2Error(
                "route_owner_mismatch",
                f"route {definition.name} is not owned by entry {entry_id}",
            )
    definition_keys = {
        (method.upper(), definition.path, definition.owner_entry_id)
        for definition in definitions
        for method in definition.methods
    }
    for authority in authorities:
        if authority.owner_entry_id != entry_id:
            raise RuntimeV2Error(
                "route_authority_owner_mismatch",
                f"route authority is not owned by entry {entry_id}",
            )
        if (authority.method, authority.path, authority.owner_entry_id) not in definition_keys:
            raise RuntimeV2Error(
                "route_authority_effect_missing",
                f"route authority has no matching effect {authority.method} {authority.path}",
            )


async def _contribute_route_effects_v2(
    builder: RouteTableBuilderV2,
    authority_catalog: RouteAuthorityCatalogV2 | None,
    definitions: Sequence[RouteDefinitionV2],
    authorities: Sequence[PluginRouteAuthorityV2],
) -> tuple[Callable[[], Awaitable[None]], ...]:
    disposers: list[Callable[[], Awaitable[None]]] = []
    try:
        for definition in definitions:
            disposers.append(builder.contribute(definition))
        if authority_catalog is not None:
            for authority in authorities:
                disposers.append(authority_catalog.contribute(authority))
    except Exception:
        for dispose in reversed(disposers):
            await dispose()
        raise
    return tuple(disposers)


__all__ = [
    "ROUTE_AUTHORITY_CATALOG_INJECT_V2",
    "ROUTE_AUTHORITY_CATALOG_SERVICE_V2",
    "ROUTE_TABLE_BUILDER_INJECT_V2",
    "ROUTE_TABLE_BUILDER_MODULE_V2",
    "ROUTE_TABLE_BUILDER_SERVICE_V2",
    "route_contribution_definition_v2",
    "route_table_builder_definition_v2",
]
