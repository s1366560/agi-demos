"""Explicit production target-host contribution for protocol-v2 distributions."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from src.domain.model.plugins.generated_v2 import ProfileSnapshotV2

from .composer import (
    ProfileCompositionV2Error,
    ProfileDocumentV2,
    compose_profile_v2,
    load_profile_document_v2,
)
from .protocol import parse_plugin_manifest_v2

_ROOT = Path(__file__).resolve().parents[4]
PRODUCTION_TARGET_PROFILE_V2_PATH = (
    _ROOT / "config/plugin-profiles/memstack-production-target-hosts.v2.yaml"
)
PRODUCTION_TARGET_MANIFEST_V2_PATHS = (
    _ROOT / "config/plugin-manifests-v2/memstack-native-target-hosts.v2.json",
    _ROOT / "config/plugin-manifests-v2/memstack-renderer-contributions.v2.json",
    _ROOT / "config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json",
)


def include_production_target_hosts_v2(
    document: ProfileDocumentV2,
    *,
    contribution_path: str | Path = PRODUCTION_TARGET_PROFILE_V2_PATH,
) -> ProfileDocumentV2:
    """Append the explicit multi-target host contribution to one base profile."""
    contribution = load_profile_document_v2(contribution_path)
    if contribution.patches:
        raise ProfileCompositionV2Error(
            "target_profile_patches_forbidden",
            "production target-host contribution cannot patch base profile entries",
        )
    existing = {entry.entry_id for entry in document.entries}
    duplicate = sorted(existing & {entry.entry_id for entry in contribution.entries})
    if duplicate:
        raise ProfileCompositionV2Error(
            "duplicate_entry_id",
            f"production target-host contribution repeats entries: {', '.join(duplicate)}",
        )
    return ProfileDocumentV2(
        profile_id=document.profile_id,
        entries=(*document.entries, *contribution.entries),
        patches=document.patches,
    )


def production_target_hosts_active_v2(
    snapshot: ProfileSnapshotV2,
    *,
    contribution_path: str | Path = PRODUCTION_TARGET_PROFILE_V2_PATH,
) -> bool:
    """Return whether every required production target-host entry is active."""
    required = load_profile_document_v2(contribution_path).entries
    entries = {entry.entry_id: entry for entry in snapshot.entries}
    return all(
        (active := entries.get(expected.entry_id)) is not None
        and active.enabled
        and active.plugin_ref == expected.plugin_ref
        and active.module_ref == expected.module_ref
        for expected in required
    )


def compose_production_target_upgrade_v2(
    snapshot: ProfileSnapshotV2,
    *,
    generation: int,
    contribution_path: str | Path = PRODUCTION_TARGET_PROFILE_V2_PATH,
    manifest_paths: Sequence[str | Path] = PRODUCTION_TARGET_MANIFEST_V2_PATHS,
) -> ProfileSnapshotV2:
    """Append target hosts to a retained pre-target snapshot without changing its other entries."""
    document = include_production_target_hosts_v2(
        ProfileDocumentV2(profile_id=snapshot.profile_id, entries=snapshot.entries),
        contribution_path=contribution_path,
    )
    manifests = {manifest.plugin_id: manifest for manifest in snapshot.manifests}
    for path in manifest_paths:
        manifest = parse_plugin_manifest_v2(json.loads(Path(path).read_text(encoding="utf-8")))
        existing = manifests.get(manifest.plugin_id)
        if existing is not None and existing != manifest:
            raise ProfileCompositionV2Error(
                "target_manifest_conflict",
                f"target manifest {manifest.plugin_id} conflicts with retained snapshot",
            )
        manifests[manifest.plugin_id] = manifest
    return compose_profile_v2(document, manifests, generation=generation)


__all__ = [
    "PRODUCTION_TARGET_MANIFEST_V2_PATHS",
    "PRODUCTION_TARGET_PROFILE_V2_PATH",
    "compose_production_target_upgrade_v2",
    "include_production_target_hosts_v2",
    "production_target_hosts_active_v2",
]
