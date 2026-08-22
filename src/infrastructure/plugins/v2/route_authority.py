"""Generation-scoped proof that legacy HTTP routes are owned by V2 Bundle entries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import NoReturn, cast

from src.domain.model.plugins.generated_v2 import PluginModuleV2, ProfileEntryV2, ProfileSnapshotV2
from src.domain.ports.plugins import (
    HttpAuthorizationMode,
    HttpRouteDefinition,
    route_definition_is_safe,
)

from .http_routes import RouteDefinitionV2

LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2 = "legacy-http-route-bridge"
LEGACY_HTTP_ROUTE_BRIDGE_MODULE_V2 = "builtin://memstack/http/legacy-route-bridge"
ROUTE_AUTHORITY_CATALOG_SERVICE_V2 = "service:http.route-authority-catalog"
ROUTE_AUTHORITY_CATALOG_INJECT_V2 = "route_authority"
ROUTE_TABLE_BUILDER_SERVICE_V2 = "service:http.route-table-builder"
ROUTE_TABLE_BUILDER_INJECT_V2 = "route_table"
ROUTE_SERVICE_VERSION_V2 = "1.0.0"


@dataclass(frozen=True, kw_only=True)
class DesiredPluginRouteV2:
    """Canonical secret-free projection of one transitional desired route row."""

    plugin_id: str
    method: str
    path: str
    permission: str
    authorization_mode: str
    enabled: bool

    def to_payload(self) -> dict[str, str | bool]:
        return {
            "plugin_id": self.plugin_id,
            "method": self.method,
            "path": self.path,
            "permission": self.permission,
            "authorization_mode": self.authorization_mode,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, kw_only=True)
class PluginRouteAuthorityV2:
    """Exact V2 entry ownership metadata paired with one concrete route effect."""

    owner_entry_id: str
    plugin_id: str
    method: str
    path: str
    permission: str
    authorization_mode: str

    def __post_init__(self) -> None:
        validated = _validated_route_fields_v2(
            plugin_id=self.plugin_id,
            method=self.method,
            path=self.path,
            permission=self.permission,
            authorization_mode=self.authorization_mode,
            enabled=True,
        )
        if self.method != validated.method:
            raise ValueError("route authority method must use canonical uppercase form")
        if not self.owner_entry_id.strip():
            raise ValueError("route authority owner_entry_id must be non-empty")

    @property
    def key(self) -> tuple[str, str]:
        return self.method, self.path

    def to_payload(self) -> dict[str, str]:
        return {
            "owner_entry_id": self.owner_entry_id,
            "plugin_id": self.plugin_id,
            "method": self.method,
            "path": self.path,
            "permission": self.permission,
            "authorization_mode": self.authorization_mode,
        }


@dataclass(frozen=True, kw_only=True)
class RouteAuthoritySnapshotV2:
    authorities: tuple[PluginRouteAuthorityV2, ...]


class RouteAuthorityCatalogV2:
    """Mutable only while a generation stages; every contribution has a disposer."""

    def __init__(self) -> None:  # pyright: ignore[reportMissingSuperCall]
        self._authorities: list[PluginRouteAuthorityV2] = []
        self._frozen: RouteAuthoritySnapshotV2 | None = None

    @property
    def authorities(self) -> tuple[PluginRouteAuthorityV2, ...]:
        return tuple(self._authorities)

    def contribute(
        self,
        authority: PluginRouteAuthorityV2,
    ) -> Callable[[], Awaitable[None]]:
        if self._frozen is not None:
            raise ValueError("route authority catalog is frozen")
        if any(item.key == authority.key for item in self._authorities):
            raise ValueError(f"duplicate route authority {authority.method} {authority.path}")
        self._authorities.append(authority)

        async def dispose() -> None:
            if authority in self._authorities:
                self._authorities.remove(authority)

        return dispose

    def freeze(self) -> RouteAuthoritySnapshotV2:
        if self._frozen is None:
            self._frozen = RouteAuthoritySnapshotV2(authorities=self.authorities)
        return self._frozen


@dataclass(frozen=True, kw_only=True)
class BundleRouteAuthorityBindingV2:
    method: str
    path: str
    source_plugin_id: str
    target_entry_id: str
    target_plugin_ref: str
    target_module_ref: str

    def to_payload(self) -> dict[str, str]:
        return {
            "method": self.method,
            "path": self.path,
            "source_plugin_id": self.source_plugin_id,
            "target_entry_id": self.target_entry_id,
            "target_plugin_ref": self.target_plugin_ref,
            "target_module_ref": self.target_module_ref,
        }


@dataclass(frozen=True, kw_only=True)
class BundleRouteAuthorityEvidenceV2:
    profile_id: str
    generation: int
    snapshot_digest: str
    ready: bool
    legacy_bridge_enabled: bool
    required_route_count: int
    bound_route_count: int
    bindings: tuple[BundleRouteAuthorityBindingV2, ...]
    reasons: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "profile_id": self.profile_id,
            "generation": self.generation,
            "snapshot_digest": self.snapshot_digest,
            "ready": self.ready,
            "legacy_bridge_enabled": self.legacy_bridge_enabled,
            "required_route_count": self.required_route_count,
            "bound_route_count": self.bound_route_count,
            "bindings": [binding.to_payload() for binding in self.bindings],
            "reasons": list(self.reasons),
        }


def desired_plugin_routes_v2(
    values: Sequence[object],
    *,
    require_canonical_order: bool = False,
) -> tuple[DesiredPluginRouteV2, ...]:
    """Normalize ORM or mapping rows without inferring ownership from text."""
    rows = tuple(_desired_plugin_route_v2(value) for value in values)
    ordered = tuple(sorted(rows, key=lambda row: (row.method, row.path, row.plugin_id)))
    if require_canonical_order and rows != ordered:
        raise ValueError("desired plugin routes must use canonical order")
    keys = [(row.method, row.path) for row in ordered if row.enabled]
    if len(keys) != len(set(keys)):
        raise ValueError("desired plugin routes contain duplicate enabled method/path pairs")
    return ordered


def verify_bundle_route_authority_v2(
    *,
    snapshot: ProfileSnapshotV2,
    route_definitions: Sequence[RouteDefinitionV2],
    authorities: Sequence[PluginRouteAuthorityV2],
    desired_rows: Sequence[object],
) -> BundleRouteAuthorityEvidenceV2:
    """Prove every active V1 row maps to one explicit, non-bridge V2 route effect."""
    desired = tuple(row for row in desired_plugin_routes_v2(desired_rows) if row.enabled)
    entries = {entry.entry_id: entry for entry in snapshot.entries}
    modules = {
        (manifest.plugin_id, module.module_ref): module
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    definitions_by_key = {
        (method.upper(), definition.path): definition
        for definition in route_definitions
        for method in definition.methods
    }
    authorities_by_key: dict[tuple[str, str], PluginRouteAuthorityV2] = {}
    reasons: list[str] = []
    for candidate_authority in authorities:
        if candidate_authority.key in authorities_by_key:
            reasons.append(
                f"route_authority_duplicate:{candidate_authority.method} {candidate_authority.path}"
            )
            continue
        authorities_by_key[candidate_authority.key] = candidate_authority

    bridge_enabled = any(
        entry.entry_id == LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2 and entry.enabled
        for entry in snapshot.entries
    )
    if bridge_enabled:
        reasons.append("legacy_bridge_enabled")

    bindings: list[BundleRouteAuthorityBindingV2] = []
    for row in desired:
        key = row.method, row.path
        label = f"{row.method} {row.path}"
        authority = authorities_by_key.get(key)
        if authority is None:
            reasons.append(f"route_authority_missing:{label}")
            continue
        if (
            authority.plugin_id != row.plugin_id
            or authority.permission != row.permission
            or authority.authorization_mode != row.authorization_mode
        ):
            reasons.append(f"route_authority_mismatch:{label}")
            continue
        binding, binding_reasons = _binding_for_route_authority_v2(
            row=row,
            authority=authority,
            entries=entries,
            modules=modules,
            definitions_by_key=definitions_by_key,
        )
        reasons.extend(binding_reasons)
        if binding is not None:
            bindings.append(binding)

    stable_reasons = tuple(dict.fromkeys(reasons))
    return BundleRouteAuthorityEvidenceV2(
        profile_id=snapshot.profile_id,
        generation=snapshot.generation,
        snapshot_digest=snapshot.digest,
        ready=not stable_reasons and len(bindings) == len(desired),
        legacy_bridge_enabled=bridge_enabled,
        required_route_count=len(desired),
        bound_route_count=len(bindings),
        bindings=tuple(bindings),
        reasons=stable_reasons,
    )


def _binding_for_route_authority_v2(
    *,
    row: DesiredPluginRouteV2,
    authority: PluginRouteAuthorityV2,
    entries: Mapping[str, ProfileEntryV2],
    modules: Mapping[tuple[str, str], PluginModuleV2],
    definitions_by_key: Mapping[tuple[str, str], RouteDefinitionV2],
) -> tuple[BundleRouteAuthorityBindingV2 | None, tuple[str, ...]]:
    label = f"{row.method} {row.path}"
    entry = entries.get(authority.owner_entry_id)
    if entry is None:
        return None, (f"route_owner_entry_missing:{authority.owner_entry_id}",)
    owner_reason = _route_owner_reason_v2(entry, authority, label=label)
    if owner_reason is not None:
        return None, (owner_reason,)
    module = modules.get((entry.plugin_ref, entry.module_ref))
    if module is None:
        return None, (f"route_owner_module_missing:{authority.owner_entry_id}",)
    binding_reasons = _route_service_binding_reasons_v2(entry, module)
    if binding_reasons:
        return None, binding_reasons
    definition = definitions_by_key.get((row.method, row.path))
    if definition is None or definition.owner_entry_id != authority.owner_entry_id:
        return None, (f"route_effect_missing:{label}",)
    return (
        BundleRouteAuthorityBindingV2(
            method=row.method,
            path=row.path,
            source_plugin_id=row.plugin_id,
            target_entry_id=entry.entry_id,
            target_plugin_ref=entry.plugin_ref,
            target_module_ref=entry.module_ref,
        ),
        (),
    )


def _route_owner_reason_v2(
    entry: ProfileEntryV2,
    authority: PluginRouteAuthorityV2,
    *,
    label: str,
) -> str | None:
    if not entry.enabled:
        return f"route_owner_entry_inactive:{authority.owner_entry_id}"
    if (
        entry.entry_id == LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2
        or entry.module_ref == LEGACY_HTTP_ROUTE_BRIDGE_MODULE_V2
    ):
        return f"route_owner_is_legacy_bridge:{label}"
    if entry.plugin_ref != authority.plugin_id:
        return f"route_owner_plugin_mismatch:{authority.owner_entry_id}"
    return None


def _route_service_binding_reasons_v2(
    entry: ProfileEntryV2,
    module: PluginModuleV2,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for alias, service in (
        (ROUTE_TABLE_BUILDER_INJECT_V2, ROUTE_TABLE_BUILDER_SERVICE_V2),
        (ROUTE_AUTHORITY_CATALOG_INJECT_V2, ROUTE_AUTHORITY_CATALOG_SERVICE_V2),
    ):
        if not any(
            requirement.alias == alias
            and requirement.service == service
            and requirement.version == ROUTE_SERVICE_VERSION_V2
            for requirement in module.contract.services.requires
        ):
            reasons.append(f"route_owner_contract_missing:{entry.entry_id}:{service}")
        if entry.inject.get(alias) != service:
            reasons.append(f"route_owner_inject_missing:{entry.entry_id}:{alias}:{service}")
    return tuple(reasons)


def _desired_plugin_route_v2(value: object) -> DesiredPluginRouteV2:
    if isinstance(value, Mapping):
        raw = cast(Mapping[str, object], value)
        expected = {
            "authorization_mode",
            "enabled",
            "method",
            "path",
            "permission",
            "plugin_id",
        }
        if set(raw) != expected:
            raise ValueError("desired plugin route has invalid fields")
        return _validated_route_fields_v2(
            plugin_id=raw["plugin_id"],
            method=raw["method"],
            path=raw["path"],
            permission=raw["permission"],
            authorization_mode=raw["authorization_mode"],
            enabled=raw["enabled"],
        )
    return _validated_route_fields_v2(
        plugin_id=getattr(value, "plugin_id", None),
        method=getattr(value, "method", None),
        path=getattr(value, "path", None),
        permission=getattr(value, "permission", None),
        authorization_mode=getattr(value, "authorization_mode", None),
        enabled=getattr(value, "enabled", None),
    )


def _validated_route_fields_v2(
    *,
    plugin_id: object,
    method: object,
    path: object,
    permission: object,
    authorization_mode: object,
    enabled: object,
) -> DesiredPluginRouteV2:
    strings = (plugin_id, method, path, permission, authorization_mode)
    if any(not isinstance(value, str) or not value.strip() for value in strings):
        _fail("desired plugin route string fields must be non-empty")
    if not isinstance(enabled, bool):
        _fail("desired plugin route enabled must be boolean")
    normalized_method = cast(str, method).upper()
    try:
        authorization = HttpAuthorizationMode(cast(str, authorization_mode))
    except ValueError as exc:
        raise ValueError(f"unsupported route authorization mode: {authorization_mode}") from exc
    definition = HttpRouteDefinition(
        plugin_id=cast(str, plugin_id),
        method=normalized_method,
        path=cast(str, path),
        permission=cast(str, permission),
        authorization=authorization,
    )
    if not route_definition_is_safe(definition):
        _fail(f"unsafe desired plugin route: {normalized_method} {path}")
    if authorization is HttpAuthorizationMode.AUTHENTICATED:
        _fail("plugin routes must require tenant/project-scoped authorization")
    return DesiredPluginRouteV2(
        plugin_id=definition.plugin_id,
        method=definition.method,
        path=definition.path,
        permission=definition.permission,
        authorization_mode=authorization.value,
        enabled=enabled,
    )


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


__all__ = [
    "LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2",
    "LEGACY_HTTP_ROUTE_BRIDGE_MODULE_V2",
    "ROUTE_AUTHORITY_CATALOG_INJECT_V2",
    "ROUTE_AUTHORITY_CATALOG_SERVICE_V2",
    "ROUTE_TABLE_BUILDER_INJECT_V2",
    "BundleRouteAuthorityBindingV2",
    "BundleRouteAuthorityEvidenceV2",
    "DesiredPluginRouteV2",
    "PluginRouteAuthorityV2",
    "RouteAuthorityCatalogV2",
    "RouteAuthoritySnapshotV2",
    "desired_plugin_routes_v2",
    "verify_bundle_route_authority_v2",
]
