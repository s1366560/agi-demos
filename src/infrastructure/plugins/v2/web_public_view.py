"""Authenticated browser view projection; this is not a workload publication or ACK authority.

The three builtin definitions below explicitly declare their WHOLE config browser-public.
The declaration is repository metadata, not inferred from field names or supplied manifests.
Only their generated, digest-attested closed schemas may validate published configuration.
View identity binds only the public revision and content, never a private source digest.
HTTP authentication and non-root scope authorization belong to the caller and are not provided here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    PluginModuleV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
    ScopeKindV2,
)

from .protocol import canonical_json_v2, parse_profile_snapshot_v2, profile_snapshot_v2_to_payload
from .runtime_context import RuntimeV2Error
from .runtime_contracts import (
    ModuleCatalogEntryV2,
    entry_order_v2,
    generated_target_catalog_v2,
    preflight_entries_v2,
    validate_contract_digests_v2,
)

_BROWSER_PUBLIC_CONFIG_MODULES_V2 = frozenset(
    {
        "builtin://memstack/web/renderer-host",
        "builtin://memstack/web/renderer-contribution-registry",
        "builtin://memstack/web/renderer-contribution",
    }
)
_PUBLIC_PERMISSIONS_V2 = frozenset({"ui.conversation.renderer", "ui.render"})


def project_web_public_view_v2(snapshot_payload: object, *, authority_id: str) -> dict[str, Any]:
    """Return a digest-bound root Web view for an already authenticated opaque scope identity."""
    if (
        not isinstance(authority_id, str)
        or not authority_id
        or authority_id.strip() != authority_id
    ):
        raise RuntimeV2Error("web_view_authority_invalid", "Web view authority is required")
    try:
        snapshot = parse_profile_snapshot_v2(snapshot_payload)
        catalog = generated_target_catalog_v2(DataPlaneTargetV2.WEB)
    except (ValueError, RuntimeV2Error, KeyError, TypeError):
        raise RuntimeV2Error("web_view_source_invalid", "Web view source is invalid") from None
    module_rows = {
        (manifest.plugin_id, module.module_ref): (manifest, module)
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    entries = {}
    modules = {}
    for entry in snapshot.entries:
        manifest, module = module_rows[(entry.plugin_ref, entry.module_ref)]
        if DataPlaneTargetV2.WEB not in module.targets:
            continue
        if entry.module_ref not in _BROWSER_PUBLIC_CONFIG_MODULES_V2:
            raise RuntimeV2Error(
                "web_view_module_not_public", "Web module has no public config declaration"
            )
        if entry.scope.kind is not ScopeKindV2.ROOT:
            raise RuntimeV2Error(
                "web_view_scope_unauthorized", "Non-root Web scope authorization is not implemented"
            )
        _attest_public_module(module, catalog, manifest.plugin_id, manifest.version)
        if module.contract.config_schema.get("additionalProperties") is not False:
            raise RuntimeV2Error(
                "web_view_config_not_closed", "Public Web config schema must be closed"
            )
        if not set(entry.permissions).issubset(_PUBLIC_PERMISSIONS_V2):
            raise RuntimeV2Error(
                "web_view_permission_not_public", "Web entry permission is not public"
            )
        entries[entry.entry_id] = entry
        modules[entry.entry_id] = module
    for entry in entries.values():
        if entry.parent_entry_id is not None and entry.parent_entry_id not in entries:
            raise RuntimeV2Error(
                "web_view_parent_not_public", "Web entry requires a non-public parent"
            )
    # Validate disabled rows too, so no unvalidated configuration crosses the browser boundary.
    try:
        preflight_entries_v2(entries, modules)
        enabled = {key: entry for key, entry in entries.items() if entry.enabled}
        entry_order_v2(enabled, {key: modules[key] for key in enabled})
    except RuntimeV2Error:
        raise RuntimeV2Error(
            "web_view_configuration_invalid", "Web view configuration is invalid"
        ) from None
    wire = _public_snapshot(snapshot, entries)
    view_digest = wire["digest"]
    view_id = _digest(
        {
            "protocol": "authenticated-web-view-v2",
            "authority": authority_id,
            "source_revision": snapshot.generation,
            "view_digest": view_digest,
        }
    )
    return {"schema_version": 2, "target": "web", "view_id": view_id, "snapshot": wire}


def _attest_public_module(
    module: PluginModuleV2,
    catalog: Mapping[str, ModuleCatalogEntryV2],
    plugin_id: str,
    version: str,
) -> None:
    try:
        validate_contract_digests_v2(
            module,
            catalog_entry=catalog[module.module_ref],
            plugin_id=plugin_id,
            plugin_version=version,
        )
    except (RuntimeV2Error, KeyError, ValueError):
        raise RuntimeV2Error("web_view_source_invalid", "Web view source is invalid") from None


def _public_snapshot(
    snapshot: ProfileSnapshotV2, entries: Mapping[str, ProfileEntryV2]
) -> dict[str, Any]:
    wire = profile_snapshot_v2_to_payload(snapshot)
    wire["profile_id"] = "web-public-view-v2"
    wire["entries"] = [entry for entry in wire["entries"] if entry["entry_id"] in entries]
    public_ids = {
        entry["entry_id"]: f"web-entry-{index}" for index, entry in enumerate(wire["entries"])
    }
    for entry in wire["entries"]:
        if entry["permissions"] or entry["quotas"] or entry["isolate"]:
            raise RuntimeV2Error(
                "web_view_entry_metadata_not_public", "Web entry metadata is not declared public"
            )
        entry["entry_id"] = public_ids[entry["entry_id"]]
        if entry["parent_entry_id"] is not None:
            entry["parent_entry_id"] = public_ids[entry["parent_entry_id"]]
    retained = {(entry.plugin_ref, entry.module_ref) for entry in entries.values()}
    manifests = []
    for manifest in wire["manifests"]:
        public_modules = [
            module
            for module in manifest["modules"]
            if (manifest["plugin_id"], module["module_ref"]) in retained
        ]
        if not public_modules:
            continue
        if manifest["quotas"] or not set(manifest["permissions"]).issubset(_PUBLIC_PERMISSIONS_V2):
            raise RuntimeV2Error(
                "web_view_manifest_metadata_not_public",
                "Web manifest metadata is not declared public",
            )
        if manifest["runtime"] != "frontend" or manifest["trust"] != "builtin":
            raise RuntimeV2Error(
                "web_view_manifest_metadata_not_public", "Web manifest runtime or trust is invalid"
            )
        for module in public_modules:
            # These optional source-provided annotations are not executable artifact identity.
            module["artifact"]["provenance"] = None
            module["artifact"]["signature"] = None
        manifests.append(
            {
                "schema_version": 2,
                "plugin_id": manifest["plugin_id"],
                "version": manifest["version"],
                "runtime": "frontend",
                "trust": "builtin",
                "modules": public_modules,
                "permissions": manifest["permissions"],
                "quotas": {},
            }
        )
    wire["manifests"] = manifests
    wire.pop("digest")
    view_digest = _digest(wire)
    wire["digest"] = view_digest
    parse_profile_snapshot_v2(wire)
    return wire


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_v2(payload)).hexdigest()
