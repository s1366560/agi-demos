"""Transitional projection of legacy HTTP desired state into v2 route effects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, cast

from fastapi import Depends

from src.domain.model.plugins.generated_v2 import ProfileEntryV2

from .composer import ProfileDocumentV2
from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_authority import (
    LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2,
    LEGACY_HTTP_ROUTE_BRIDGE_MODULE_V2,
    ROUTE_AUTHORITY_CATALOG_INJECT_V2,
    DesiredPluginRouteV2,
    PluginRouteAuthorityV2,
    RouteAuthorityCatalogV2,
    desired_plugin_routes_v2,
)
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

type InventoryProviderV2 = Callable[[], Mapping[str, Sequence[Any]]]
type AuthorizationFactoryV2 = Callable[["LegacyHttpRouteRowV2"], Callable[..., Any]]

LegacyHttpRouteRowV2 = DesiredPluginRouteV2


def project_legacy_http_routes_v2(
    document: ProfileDocumentV2,
    desired_rows: Sequence[Any],
) -> ProfileDocumentV2:
    """Replace the bridge entry's whole config row with canonical desired routes."""
    rows = _desired_legacy_http_routes_v2(cast(Sequence[object], desired_rows))
    positions = {
        entry.entry_id: index
        for index, entry in enumerate(document.entries)
        if entry.entry_id == LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2
    }
    if LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2 not in positions:
        raise ValueError(f"profile is missing required entry {LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2}")
    entries = list(document.entries)
    index = positions[LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2]
    entries[index] = replace(
        entries[index],
        config={"routes": [row.to_payload() for row in rows]},
    )
    return replace(document, entries=tuple(entries))


def configured_legacy_http_routes_v2(
    entries: Sequence[ProfileEntryV2],
) -> tuple[LegacyHttpRouteRowV2, ...]:
    """Read the canonical bridge row from one already validated profile snapshot."""
    matches = [entry for entry in entries if entry.entry_id == LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2]
    if len(matches) != 1:
        raise ValueError(
            f"profile must contain exactly one {LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2} entry"
        )
    return _rows_from_config(matches[0].config)


def legacy_http_route_bridge_definition_v2(
    *,
    inventory_provider: InventoryProviderV2 | None = None,
    authorization_factory: AuthorizationFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Convert one canonical bridge entry into reversible route-table contributions."""
    provide_inventory = inventory_provider or _legacy_inventory
    build_authorization = authorization_factory or _legacy_authorization

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        rows = _rows_from_config(config)
        if not rows:
            return
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )
        authority_catalog = context.require(ROUTE_AUTHORITY_CATALOG_INJECT_V2)
        if not isinstance(authority_catalog, RouteAuthorityCatalogV2):
            raise RuntimeV2Error(
                "invalid_route_authority_catalog",
                "route_authority inject is not a protocol v2 authority catalog",
            )
        inventory = _inventory_by_route(provide_inventory())
        definitions = tuple(
            _definition_from_row(
                context.entry_id,
                row,
                inventory=inventory,
                authorization_factory=build_authorization,
            )
            for row in rows
            if row.enabled
        )
        authorities = tuple(
            PluginRouteAuthorityV2(
                owner_entry_id=context.entry_id,
                plugin_id=row.plugin_id,
                method=row.method,
                path=row.path,
                permission=row.permission,
                authorization_mode=row.authorization_mode,
            )
            for row in rows
            if row.enabled
        )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition, authority in zip(definitions, authorities, strict=True):
                    disposers.append(builder.contribute(definition))
                    disposers.append(authority_catalog.contribute(authority))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label="legacy-http-route-contributions")

    return PluginDefinitionV2(
        module_ref=LEGACY_HTTP_ROUTE_BRIDGE_MODULE_V2,
        contract_digest=generated_contract_digest_v2(LEGACY_HTTP_ROUTE_BRIDGE_MODULE_V2),
        apply=apply,
    )


def _rows_from_config(config: Mapping[str, Any]) -> tuple[LegacyHttpRouteRowV2, ...]:
    if set(config) != {"routes"}:
        raise ValueError("legacy HTTP route bridge config must contain only routes")
    payload = config["routes"]
    if not isinstance(payload, list):
        raise ValueError("legacy HTTP route bridge routes must be a list")
    return _desired_legacy_http_routes_v2(
        cast(list[object], payload),
        require_canonical_order=True,
    )


def _desired_legacy_http_routes_v2(
    values: Sequence[object],
    *,
    require_canonical_order: bool = False,
) -> tuple[LegacyHttpRouteRowV2, ...]:
    try:
        return desired_plugin_routes_v2(
            values,
            require_canonical_order=require_canonical_order,
        )
    except ValueError as exc:
        message = str(exc)
        prefix = "unsafe desired plugin route:"
        if message.startswith(prefix):
            detail = message.removeprefix(prefix).strip()
            raise ValueError(f"unsafe legacy HTTP route definition: {detail}") from exc
        raise


def _inventory_by_route(
    registry_routes: Mapping[str, Sequence[Any]],
) -> dict[tuple[str, str], Any]:
    inventory: dict[tuple[str, str], Any] = {}
    owners: dict[tuple[str, str], str] = {}
    for routes in registry_routes.values():
        for route in routes:
            key = str(route.method).upper(), str(route.path)
            owner = str(route.plugin_name)
            existing_owner = owners.get(key)
            if existing_owner is not None and existing_owner != owner:
                raise RuntimeError(f"multiple plugins registered route {key[0]} {key[1]}")
            inventory[key] = route
            owners[key] = owner
    return inventory


def _definition_from_row(
    owner_entry_id: str,
    row: LegacyHttpRouteRowV2,
    *,
    inventory: Mapping[tuple[str, str], Any],
    authorization_factory: AuthorizationFactoryV2,
) -> RouteDefinitionV2:
    key = row.method, row.path
    registered = inventory.get(key)
    if registered is None or str(registered.plugin_name) != row.plugin_id:
        raise RuntimeError(f"route {row.method} {row.path} handler is not owned by {row.plugin_id}")
    authorization = authorization_factory(row)
    return RouteDefinitionV2(
        owner_entry_id=owner_entry_id,
        path=row.path,
        methods=(row.method,),
        endpoint=registered.handler,
        name=f"plugin:{row.plugin_id}:{row.permission}",
        dependencies=(Depends(authorization),),
        tags=tuple(str(tag) for tag in getattr(registered, "tags", ())),
    )


def _legacy_inventory() -> Mapping[str, Sequence[Any]]:
    from src.infrastructure.agent.plugins.registry import get_plugin_registry

    return get_plugin_registry().list_http_routes()


def _legacy_authorization(row: LegacyHttpRouteRowV2) -> Callable[..., Any]:
    from src.infrastructure.adapters.primary.web.startup.http_route_authorization_v2 import (
        build_route_authorization_dependency_v2,
    )

    return build_route_authorization_dependency_v2(
        plugin_id=row.plugin_id,
        permission=row.permission,
        authorization=row.authorization_mode,
        path=row.path,
    )


__all__ = [
    "LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2",
    "LEGACY_HTTP_ROUTE_BRIDGE_MODULE_V2",
    "LegacyHttpRouteRowV2",
    "configured_legacy_http_routes_v2",
    "legacy_http_route_bridge_definition_v2",
    "project_legacy_http_routes_v2",
]
