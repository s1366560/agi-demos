"""Explicit production activation overlay for the Workspace Core V2 primitive."""

from __future__ import annotations

from dataclasses import replace

from src.domain.model.plugins.generated_v2 import ProfileEntryV2, ProfileSnapshotV2

from .composer import ProfileDocumentV2, compose_profile_v2
from .runtime import RuntimeV2Error
from .workspace_core_runtime import WORKSPACE_CORE_RUNTIME_MODULE_V2

WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2 = "builtin-workspace-core-runtime"
_WORKSPACE_CORE_PLUGIN_ID_V2 = "memstack-runtime-kernel"


def activate_workspace_core_shadow_v2(document: ProfileDocumentV2) -> ProfileDocumentV2:
    """Explicitly enable the canonical primitive in one fresh production candidate."""
    entry = _workspace_core_entry_v2(document.entries)
    if entry.enabled:
        return document
    return replace(
        document,
        entries=tuple(
            replace(item, enabled=True) if item.entry_id == entry.entry_id else item
            for item in document.entries
        ),
    )


def workspace_core_shadow_active_v2(snapshot: ProfileSnapshotV2) -> bool:
    """Return whether the exact Workspace Core primitive is enabled in a snapshot."""
    return any(
        entry.entry_id == WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2
        and entry.plugin_ref == _WORKSPACE_CORE_PLUGIN_ID_V2
        and entry.module_ref == WORKSPACE_CORE_RUNTIME_MODULE_V2
        and entry.enabled
        for entry in snapshot.entries
    )


def compose_workspace_core_shadow_upgrade_v2(
    snapshot: ProfileSnapshotV2,
    *,
    generation: int,
) -> ProfileSnapshotV2:
    """Republish a disabled primitive baseline as a new active generation."""
    entry = _workspace_core_entry_v2(snapshot.entries)
    if entry.enabled:
        raise RuntimeV2Error(
            "workspace_core_runtime_baseline_not_disabled",
            "Workspace Core shadow upgrade requires a disabled V2 primitive baseline",
        )
    document = activate_workspace_core_shadow_v2(
        ProfileDocumentV2(
            profile_id=snapshot.profile_id,
            entries=snapshot.entries,
        )
    )
    return compose_profile_v2(
        document,
        {manifest.plugin_id: manifest for manifest in snapshot.manifests},
        generation=generation,
    )


def _workspace_core_entry_v2(entries: tuple[ProfileEntryV2, ...]) -> ProfileEntryV2:
    entry = next(
        (item for item in entries if item.entry_id == WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2),
        None,
    )
    if entry is None:
        raise RuntimeV2Error(
            "workspace_core_runtime_entry_missing",
            "Workspace Core shadow activation requires the disabled V2 primitive baseline",
        )
    if (
        entry.plugin_ref != _WORKSPACE_CORE_PLUGIN_ID_V2
        or entry.module_ref != WORKSPACE_CORE_RUNTIME_MODULE_V2
    ):
        raise RuntimeV2Error(
            "workspace_core_runtime_entry_mismatch",
            "Workspace Core shadow entry does not reference the canonical V2 primitive",
        )
    return entry


__all__ = [
    "WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2",
    "activate_workspace_core_shadow_v2",
    "compose_workspace_core_shadow_upgrade_v2",
    "workspace_core_shadow_active_v2",
]
