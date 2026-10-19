"""Pure, schema-declared instance edits; callers supply verified installed manifests."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    DesiredBundleSetV2,
    PluginManifestV2,
    PluginModuleV2,
    ProfileEntryV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSnapshotV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    ScopeV2,
)

from .composer import load_profile_document_v2
from .layer_composer import desired_bundle_set_digest_v2, profile_source_digest_v2
from .runtime_context import RuntimeV2Error
from .runtime_contracts import entry_order_v2, preflight_entries_v2
from .scope import scope_key_v2, scope_v2_to_payload


def management_declaration_v2(module: PluginModuleV2) -> Mapping[str, Any]:
    value = module.contract.config_schema.get("x-memstack-management", {})
    return value if isinstance(value, Mapping) else {}


def compatible_replacements_v2(
    module: PluginModuleV2, manifests: Sequence[PluginManifestV2]
) -> list[dict[str, str]]:
    """Only verified installed modules with identical public contracts qualify."""
    return [
        {"plugin_id": manifest.plugin_id, "module_ref": candidate.module_ref}
        for manifest in manifests
        for candidate in manifest.modules
        if candidate.module_ref != module.module_ref
        and candidate.targets == module.targets
        and candidate.contract_digest == module.contract_digest
        and management_declaration_v2(candidate).get("editable") is True
    ]


def instance_rows_v2(
    snapshot: ProfileSnapshotV2,
    *,
    scope: ScopeV2,
    publication_status: str,
    active_snapshot: ProfileSnapshotV2 | None,
) -> list[dict[str, Any]]:
    modules = {
        (manifest.plugin_id, module.module_ref): module
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    active = (
        {}
        if active_snapshot is None
        else {entry.entry_id: entry for entry in active_snapshot.entries}
    )
    rows = []
    for entry in snapshot.entries:
        module = modules[(entry.plugin_ref, entry.module_ref)]
        declaration = management_declaration_v2(module)
        editable = declaration.get("editable") is True
        public = declaration.get("public_config") is True
        applied = active.get(entry.entry_id)
        same = applied == entry
        state = (
            ("active" if entry.enabled else "disabled")
            if same
            else "failed"
            if publication_status == "degraded"
            else "applying"
        )
        rows.append(
            {
                "entry_id": entry.entry_id,
                "plugin_id": entry.plugin_ref,
                "display_name": str(entry.config.get("id", entry.entry_id))
                if public
                else entry.entry_id,
                "module_ref": entry.module_ref,
                "enabled": entry.enabled,
                "config": deepcopy(dict(entry.config)) if public else {},
                "config_schema": deepcopy(dict(module.contract.config_schema)) if public else {},
                "editable": editable,
                "config_editable": editable and public,
                "reason_code": None if editable else "instance_managed_by_deployment",
                "inherited_from": None
                if entry.scope == scope
                else scope_v2_to_payload(entry.scope),
                "replacement_candidates": compatible_replacements_v2(module, snapshot.manifests)
                if editable
                else [],
                "state": {
                    "status": state,
                    "reason_code": "publication_failed" if state == "failed" else None,
                },
            }
        )
    return rows


def revise_instance_source_v2(
    *,
    source: ProfileSourceV2,
    desired: DesiredBundleSetV2,
    snapshot: ProfileSnapshotV2,
    scope: ScopeV2,
    expected_revision: int,
    changes: Sequence[Mapping[str, Any]],
) -> tuple[ProfileSourceV2, DesiredBundleSetV2]:
    if expected_revision != desired.revision:
        raise RuntimeV2Error("instance_revision_conflict", "configuration revision changed")
    if not changes:
        raise RuntimeV2Error("instance_changes_empty", "at least one instance change is required")
    entries = {entry.entry_id: entry for entry in snapshot.entries}
    modules = {
        (manifest.plugin_id, module.module_ref): module
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    replacements: list[ProfileEntryV2] = []
    seen: set[str] = set()
    for change in changes:
        key = change.get("entry_id")
        if not isinstance(key, str) or key not in entries or key in seen:
            raise RuntimeV2Error("instance_change_invalid", "unknown or repeated instance")
        if set(change) - {"entry_id", "enabled", "config", "replacement"}:
            raise RuntimeV2Error("instance_change_invalid", "unknown change fields")
        seen.add(key)
        entry = entries[key]
        module = modules[(entry.plugin_ref, entry.module_ref)]
        declaration = management_declaration_v2(module)
        if declaration.get("editable") is not True:
            raise RuntimeV2Error("instance_not_editable", "instance is deployment managed")
        enabled = change.get("enabled", entry.enabled)
        if type(enabled) is not bool:
            raise RuntimeV2Error("instance_change_invalid", "enabled must be boolean")
        config = change.get("config", entry.config)
        if "config" in change and declaration.get("public_config") is not True:
            raise RuntimeV2Error(
                "instance_config_private", "configuration requires credential management"
            )
        if not isinstance(config, Mapping):
            raise RuntimeV2Error("instance_change_invalid", "config must be an object")
        plugin_id, module_ref = entry.plugin_ref, entry.module_ref
        if "replacement" in change:
            replacement = change["replacement"]
            if replacement not in compatible_replacements_v2(module, snapshot.manifests):
                raise RuntimeV2Error(
                    "instance_replacement_incompatible", "replacement is not compatible"
                )
            plugin_id, module_ref = replacement["plugin_id"], replacement["module_ref"]
        replacements.append(
            replace(
                entry,
                scope=scope,
                enabled=enabled,
                config=deepcopy(dict(config)),
                plugin_ref=plugin_id,
                module_ref=module_ref,
            )
        )
    layer = ProfileLayerV2(
        layer_id=f"instance-configuration-{scope_key_v2(scope)}-{source.revision + 1}",
        kind=ProfileLayerKindV2(scope.kind.value),
        scope=scope,
        entries=(),
        replacements=tuple(replacements),
        disabled_entry_ids=(),
    )
    updated_source = replace(source, revision=source.revision + 1, layers=(*source.layers, layer))
    updated_source = replace(updated_source, digest=profile_source_digest_v2(updated_source))
    updated_desired = replace(
        desired,
        revision=desired.revision + 1,
        profile_source=ProfileSourceReferenceV2(
            source_id=updated_source.source_id,
            revision=updated_source.revision,
            digest=updated_source.digest,
        ),
    )
    return updated_source, replace(
        updated_desired, digest=desired_bundle_set_digest_v2(updated_desired)
    )


def validate_instance_candidate_v2(snapshot: ProfileSnapshotV2) -> None:
    """Validate the entire candidate, including dependencies on every target."""
    modules = {
        (manifest.plugin_id, module.module_ref): module
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    for target in DataPlaneTargetV2:
        entries = {
            entry.entry_id: entry
            for entry in snapshot.entries
            if target in modules[(entry.plugin_ref, entry.module_ref)].targets
        }
        selected = {
            key: modules[(entry.plugin_ref, entry.module_ref)] for key, entry in entries.items()
        }
        preflight_entries_v2(entries, selected)
        enabled = {key: entry for key, entry in entries.items() if entry.enabled}
        entry_order_v2(enabled, {key: selected[key] for key in enabled})
    _validate_renderer_contributions(snapshot)


_RENDERER_MODULES = {
    "builtin://memstack/web/renderer-contribution": "web",
    "builtin://memstack/web/renderer-feature": "web",
    "builtin://memstack/web/renderer-management": "web",
    "builtin://memstack/desktop/renderer-contribution": "desktop",
    "builtin://memstack/desktop/renderer-feature": "desktop",
    "builtin://memstack/desktop/renderer-management": "desktop",
}


def _contributions(entry: ProfileEntryV2) -> Sequence[Mapping[str, Any]]:
    if entry.module_ref not in _RENDERER_MODULES:
        return ()
    if entry.module_ref.endswith("/renderer-contribution"):
        return (entry.config,)
    return entry.config.get("contributions", ())  # type: ignore[no-any-return]


@lru_cache(maxsize=1)
def _compiled_artifacts() -> Mapping[tuple[str, str], str]:
    from .production_bundle import PRODUCTION_TARGET_PROFILE_PATH_V2

    return MappingProxyType(
        {
            (_RENDERER_MODULES[entry.module_ref], artifact): contribution["kind"]
            for entry in load_profile_document_v2(PRODUCTION_TARGET_PROFILE_PATH_V2).entries
            for contribution in _contributions(entry)
            for artifact in contribution["payload"]["artifact_refs"]
        }
    )


def _validate_renderer_contributions(snapshot: ProfileSnapshotV2) -> None:
    owners: set[tuple[str, str, str]] = set()
    artifact_owners: set[tuple[str, str]] = set()
    artifacts = _compiled_artifacts()
    for entry in snapshot.entries:
        if not entry.enabled or entry.module_ref not in _RENDERER_MODULES:
            continue
        target = _RENDERER_MODULES[entry.module_ref]
        for contribution in _contributions(entry):
            key = (target, contribution["kind"], contribution["id"])
            if key in owners:
                raise RuntimeV2Error("renderer_contribution_conflict", "duplicate renderer owner")
            owners.add(key)
            for artifact in contribution["payload"]["artifact_refs"]:
                artifact_key = (target, artifact)
                kind = artifacts.get(artifact_key)
                if kind is None:
                    raise RuntimeV2Error(
                        "renderer_artifact_unavailable", "renderer artifact is not compiled"
                    )
                if kind != contribution["kind"]:
                    raise RuntimeV2Error(
                        "renderer_artifact_kind_mismatch", "renderer artifact kind does not match"
                    )
                # Route aliases belong inside one artifact, not to another contribution.
                if artifact_key in artifact_owners:
                    raise RuntimeV2Error(
                        "renderer_artifact_conflict", "duplicate renderer artifact owner"
                    )
                artifact_owners.add(artifact_key)
