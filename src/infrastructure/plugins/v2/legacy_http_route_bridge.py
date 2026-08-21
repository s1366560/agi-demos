"""Transitional projection of legacy HTTP desired state into v2 route effects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from fastapi import Depends

from src.domain.model.plugins.generated_v2 import ProfileEntryV2
from src.domain.ports.plugins import (
    HttpAuthorizationMode,
    HttpRouteDefinition,
    route_definition_is_safe,
)

from .composer import ProfileDocumentV2
from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2 = "legacy-http-route-bridge"
LEGACY_HTTP_ROUTE_BRIDGE_MODULE_V2 = "builtin://memstack/http/legacy-route-bridge"

type InventoryProviderV2 = Callable[[], Mapping[str, Sequence[Any]]]
type AuthorizationFactoryV2 = Callable[["LegacyHttpRouteRowV2"], Callable[..., Any]]


@dataclass(frozen=True, kw_only=True)
class LegacyHttpRouteRowV2:
    """Canonical JSON-safe route row copied from the transitional desired-state table."""

    plugin_id: str
    method: str
    path: str
    permission: str
    authorization_mode: str
    enabled: bool

    def to_payload(self) -> dict[str, str | bool]:
        return {
            "authorization_mode": self.authorization_mode,
            "enabled": self.enabled,
            "method": self.method,
            "path": self.path,
            "permission": self.permission,
            "plugin_id": self.plugin_id,
        }


def project_legacy_http_routes_v2(
    document: ProfileDocumentV2,
    desired_rows: Sequence[Any],
) -> ProfileDocumentV2:
    """Replace the bridge entry's whole config row with canonical desired routes."""
    rows = tuple(sorted((_row_from_object(row) for row in desired_rows), key=_row_key))
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
    rows = tuple(_row_from_mapping(item) for item in cast(list[object], payload))
    if rows != tuple(sorted(rows, key=_row_key)):
        raise ValueError("legacy HTTP route bridge routes must use canonical order")
    keys = [(row.method, row.path) for row in rows if row.enabled]
    if len(keys) != len(set(keys)):
        raise ValueError("legacy HTTP route bridge contains duplicate enabled routes")
    return rows


def _row_from_object(value: object) -> LegacyHttpRouteRowV2:
    return _validated_row(
        plugin_id=getattr(value, "plugin_id", None),
        method=getattr(value, "method", None),
        path=getattr(value, "path", None),
        permission=getattr(value, "permission", None),
        authorization_mode=getattr(value, "authorization_mode", None),
        enabled=getattr(value, "enabled", None),
    )


def _row_from_mapping(value: object) -> LegacyHttpRouteRowV2:
    if not isinstance(value, Mapping):
        raise ValueError("legacy HTTP route bridge route must be an object")
    typed_value = cast(Mapping[str, object], value)
    expected = {
        "authorization_mode",
        "enabled",
        "method",
        "path",
        "permission",
        "plugin_id",
    }
    if set(typed_value) != expected:
        raise ValueError("legacy HTTP route bridge route has invalid fields")
    return _validated_row(
        plugin_id=typed_value["plugin_id"],
        method=typed_value["method"],
        path=typed_value["path"],
        permission=typed_value["permission"],
        authorization_mode=typed_value["authorization_mode"],
        enabled=typed_value["enabled"],
    )


def _validated_row(
    *,
    plugin_id: object,
    method: object,
    path: object,
    permission: object,
    authorization_mode: object,
    enabled: object,
) -> LegacyHttpRouteRowV2:
    string_values = {
        "plugin_id": plugin_id,
        "method": method,
        "path": path,
        "permission": permission,
        "authorization_mode": authorization_mode,
    }
    if any(not isinstance(value, str) or not value.strip() for value in string_values.values()):
        raise ValueError("legacy HTTP route bridge string fields must be non-empty")
    if not isinstance(enabled, bool):
        raise ValueError("legacy HTTP route bridge enabled must be boolean")
    normalized_method = str(method).upper()
    try:
        authorization = HttpAuthorizationMode(str(authorization_mode))
    except ValueError as exc:
        raise ValueError(f"unsupported route authorization mode: {authorization_mode}") from exc
    definition = HttpRouteDefinition(
        plugin_id=str(plugin_id),
        method=normalized_method,
        path=str(path),
        permission=str(permission),
        authorization=authorization,
    )
    if not route_definition_is_safe(definition):
        raise ValueError(f"unsafe legacy HTTP route definition: {normalized_method} {path}")
    if authorization is HttpAuthorizationMode.AUTHENTICATED:
        raise ValueError("plugin routes must require tenant/project-scoped authorization")
    return LegacyHttpRouteRowV2(
        plugin_id=str(plugin_id),
        method=normalized_method,
        path=str(path),
        permission=str(permission),
        authorization_mode=authorization.value,
        enabled=enabled,
    )


def _row_key(row: LegacyHttpRouteRowV2) -> tuple[str, str, str]:
    return row.method, row.path, row.plugin_id


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
