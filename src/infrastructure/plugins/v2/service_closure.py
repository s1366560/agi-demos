"""Structural Python service projection for an explicitly selected scope authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    ProfileSnapshotV2,
    ScopeV2,
    ServiceRequiredV2,
)

from .protocol import (
    build_profile_snapshot_v2,
    parse_profile_snapshot_v2,
    profile_snapshot_v2_to_payload,
)
from .route_authority import ROUTE_AUTHORITY_CATALOG_SERVICE_V2
from .route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from .runtime import project_snapshot_entries_v2
from .runtime_context import RuntimeV2Error, scope_contains_v2
from .runtime_contracts import (
    entry_dependencies_v2,
    entry_order_v2,
    preflight_entries_v2,
    resolve_entry_service_provider_v2,
)
from .scope import validate_scope_v2

_GLOBAL_ROUTE_SERVICES = frozenset(
    {ROUTE_AUTHORITY_CATALOG_SERVICE_V2, ROUTE_TABLE_BUILDER_SERVICE_V2}
)


def project_service_closure_v2(
    snapshot: ProfileSnapshotV2,
    *,
    scope: ScopeV2,
    required_services: Sequence[ServiceRequiredV2],
    isolate: Mapping[str, str] | None = None,
) -> ProfileSnapshotV2:
    """Project a composed snapshot; callers retain authentication and publication ownership.

    Service roots are explicit protocol declarations, never inferred from entry names.
    Entries and module contracts/artifact references retain their original scope and content.
    """
    canonical_scope = validate_scope_v2(scope)
    snapshot = parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(snapshot))
    entries = {
        entry.entry_id: entry
        for entry in project_snapshot_entries_v2(snapshot, DataPlaneTargetV2.PYTHON)
        if entry.enabled and scope_contains_v2(entry.scope, canonical_scope)
    }
    modules_by_key = {
        (manifest.plugin_id, module.module_ref): module
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    modules = {
        key: modules_by_key[(entry.plugin_ref, entry.module_ref)] for key, entry in entries.items()
    }
    pending = [
        resolve_entry_service_provider_v2(
            entries,
            modules,
            entry_id="scope-service-consumer",
            service=requirement.service,
            version=requirement.version,
            scope=canonical_scope,
            isolate=isolate or {},
        )
        for requirement in required_services
    ]
    selected: set[str] = set()
    while pending:
        entry_id = pending.pop()
        if entry_id in selected:
            continue
        if entry_id not in entries:
            raise RuntimeV2Error(
                "missing_parent_entry", "service closure requires an unavailable parent entry"
            )
        contract = modules[entry_id].contract
        if any(
            declaration.service in _GLOBAL_ROUTE_SERVICES
            for declaration in (*contract.services.provides, *contract.services.requires)
        ):
            raise RuntimeV2Error(
                "scope_global_route_service",
                "scoped service closure includes a global route service",
            )
        selected.add(entry_id)
        pending.extend(
            sorted(entry_dependencies_v2(entries, modules, entry_ids=(entry_id,))[entry_id])
        )
    selected_entries = {key: entry for key, entry in entries.items() if key in selected}
    selected_modules = {key: modules[key] for key in selected_entries}
    preflight_entries_v2(selected_entries, selected_modules)
    _ = entry_order_v2(selected_entries, selected_modules)
    module_keys = {(entry.plugin_ref, entry.module_ref) for entry in selected_entries.values()}
    manifests = tuple(
        replace(
            manifest,
            modules=tuple(
                module
                for module in manifest.modules
                if (manifest.plugin_id, module.module_ref) in module_keys
            ),
        )
        for manifest in snapshot.manifests
        if any(
            (manifest.plugin_id, module.module_ref) in module_keys for module in manifest.modules
        )
    )
    return build_profile_snapshot_v2(
        profile_id=snapshot.profile_id,
        generation=snapshot.generation,
        manifests=manifests,
        entries=tuple(selected_entries.values()),
    )
