"""Explicit desired-state projection for the Agent Pool V2 capability."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from src.domain.model.plugins.generated_v2 import (
    PluginManifestV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
)

from .agent_pool_runtime import AGENT_POOL_RUNTIME_MODULE_V2
from .composer import ProfileDocumentV2, compose_profile_v2, load_profile_document_v2
from .protocol import parse_plugin_manifest_v2
from .runtime import RuntimeV2Error

AGENT_POOL_RUNTIME_ENTRY_ID_V2 = "builtin-agent-pool-runtime"
AGENT_POOL_HTTP_ROUTES_ENTRY_ID_V2 = "builtin-agent-pool-http-routes"
AGENT_POOL_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/agent-pool-routes"
_AGENT_POOL_PLUGIN_ID_V2 = "memstack-runtime-kernel"
_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_DEFAULT_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def project_agent_pool_runtime_v2(
    document: ProfileDocumentV2,
    *,
    enabled: bool,
    config: dict[str, object],
) -> ProfileDocumentV2:
    """Project deployment settings into a fresh complete candidate."""
    runtime = _canonical_entry_v2(
        document.entries,
        entry_id=AGENT_POOL_RUNTIME_ENTRY_ID_V2,
        module_ref=AGENT_POOL_RUNTIME_MODULE_V2,
    )
    return replace(
        document,
        entries=tuple(
            replace(item, enabled=enabled, config=dict(config))
            if item.entry_id == runtime.entry_id
            else item
            for item in document.entries
        ),
    )


def agent_pool_runtime_matches_v2(
    snapshot: ProfileSnapshotV2,
    *,
    enabled: bool,
    config: dict[str, object],
) -> bool:
    """Return whether the exact runtime desired state is already durable."""
    return any(
        entry.entry_id == AGENT_POOL_RUNTIME_ENTRY_ID_V2
        and entry.plugin_ref == _AGENT_POOL_PLUGIN_ID_V2
        and entry.module_ref == AGENT_POOL_RUNTIME_MODULE_V2
        and entry.enabled is enabled
        and dict(entry.config) == config
        for entry in snapshot.entries
    )


def agent_pool_profile_matches_v2(
    snapshot: ProfileSnapshotV2,
    *,
    enabled: bool,
    config: dict[str, object],
) -> bool:
    """Check runtime state plus the required two-row HTTP contribution."""
    route_entry_active = any(
        entry.entry_id == AGENT_POOL_HTTP_ROUTES_ENTRY_ID_V2
        and entry.plugin_ref == _AGENT_POOL_PLUGIN_ID_V2
        and entry.module_ref == AGENT_POOL_HTTP_ROUTES_MODULE_V2
        and entry.enabled
        for entry in snapshot.entries
    )
    manifest = next(
        (item for item in snapshot.manifests if item.plugin_id == _AGENT_POOL_PLUGIN_ID_V2),
        None,
    )
    module_refs = (
        {module.module_ref for module in manifest.modules} if manifest is not None else set()
    )
    return (
        agent_pool_runtime_matches_v2(snapshot, enabled=enabled, config=config)
        and route_entry_active
        and AGENT_POOL_RUNTIME_MODULE_V2 in module_refs
        and AGENT_POOL_HTTP_ROUTES_MODULE_V2 in module_refs
    )


def compose_agent_pool_profile_upgrade_v2(
    snapshot: ProfileSnapshotV2,
    *,
    generation: int,
    enabled: bool,
    config: dict[str, object],
    profile_path: str | Path = _DEFAULT_PROFILE_PATH,
    manifest_path: str | Path = _DEFAULT_MANIFEST_PATH,
) -> ProfileSnapshotV2:
    """Add or replace the complete Agent Pool capability in an older snapshot."""
    canonical = load_profile_document_v2(profile_path)
    runtime = _canonical_entry_v2(
        canonical.entries,
        entry_id=AGENT_POOL_RUNTIME_ENTRY_ID_V2,
        module_ref=AGENT_POOL_RUNTIME_MODULE_V2,
    )
    routes = _canonical_entry_v2(
        canonical.entries,
        entry_id=AGENT_POOL_HTTP_ROUTES_ENTRY_ID_V2,
        module_ref=AGENT_POOL_HTTP_ROUTES_MODULE_V2,
    )
    desired_runtime = replace(runtime, enabled=enabled, config=dict(config))
    entries = _upsert_entries_v2(snapshot.entries, desired_runtime, routes)
    manifests = _replace_kernel_manifest_v2(snapshot.manifests, manifest_path)
    return compose_profile_v2(
        ProfileDocumentV2(profile_id=snapshot.profile_id, entries=entries),
        {manifest.plugin_id: manifest for manifest in manifests},
        generation=generation,
    )


def _canonical_entry_v2(
    entries: tuple[ProfileEntryV2, ...],
    *,
    entry_id: str,
    module_ref: str,
) -> ProfileEntryV2:
    entry = next((item for item in entries if item.entry_id == entry_id), None)
    if entry is None:
        raise RuntimeV2Error(
            "agent_pool_profile_entry_missing",
            f"Agent Pool profile is missing required entry {entry_id}",
        )
    if entry.plugin_ref != _AGENT_POOL_PLUGIN_ID_V2 or entry.module_ref != module_ref:
        raise RuntimeV2Error(
            "agent_pool_profile_entry_mismatch",
            f"Agent Pool entry {entry_id} does not reference its canonical V2 module",
        )
    return entry


def _upsert_entries_v2(
    existing: tuple[ProfileEntryV2, ...],
    runtime: ProfileEntryV2,
    routes: ProfileEntryV2,
) -> tuple[ProfileEntryV2, ...]:
    replacements = {runtime.entry_id: runtime, routes.entry_id: routes}
    merged = [replacements.pop(entry.entry_id, entry) for entry in existing]
    insertion = next(
        (
            index
            for index, entry in enumerate(merged)
            if entry.entry_id == "legacy-http-route-bridge"
        ),
        len(merged),
    )
    missing = [entry for entry in (runtime, routes) if entry.entry_id in replacements]
    merged[insertion:insertion] = missing
    return tuple(merged)


def _replace_kernel_manifest_v2(
    existing: tuple[PluginManifestV2, ...],
    manifest_path: str | Path,
) -> tuple[PluginManifestV2, ...]:
    current = parse_plugin_manifest_v2(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
    if current.plugin_id != _AGENT_POOL_PLUGIN_ID_V2:
        raise RuntimeV2Error(
            "agent_pool_manifest_mismatch",
            "Agent Pool upgrade manifest is not the canonical runtime kernel",
        )
    replaced = False
    manifests: list[PluginManifestV2] = []
    for manifest in existing:
        if manifest.plugin_id == current.plugin_id:
            manifests.append(current)
            replaced = True
        else:
            manifests.append(manifest)
    if not replaced:
        manifests.append(current)
    return tuple(manifests)


__all__ = [
    "AGENT_POOL_HTTP_ROUTES_ENTRY_ID_V2",
    "AGENT_POOL_HTTP_ROUTES_MODULE_V2",
    "AGENT_POOL_RUNTIME_ENTRY_ID_V2",
    "agent_pool_profile_matches_v2",
    "agent_pool_runtime_matches_v2",
    "compose_agent_pool_profile_upgrade_v2",
    "project_agent_pool_runtime_v2",
]
