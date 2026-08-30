"""Explicit production activation overlay for the Workspace Core V2 primitive."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from src.domain.model.plugins.generated_v2 import (
    PluginManifestV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
)

from .composer import ProfileDocumentV2, compose_profile_v2, load_profile_document_v2
from .protocol import parse_plugin_manifest_v2
from .runtime import RuntimeV2Error
from .workspace_contract_actor_services import (
    WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2,
)
from .workspace_core_runtime import WORKSPACE_CORE_RUNTIME_MODULE_V2
from .workspace_prompt_context_services import WORKSPACE_PROMPT_CONTEXT_MODULE_V2

WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2 = "builtin-workspace-core-runtime"
WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2 = (
    "builtin-workspace-core-contract-actor-resolver"
)
WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2 = "builtin-workspace-core-prompt-context"
_WORKSPACE_CORE_PLUGIN_ID_V2 = "memstack-runtime-kernel"
_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_DEFAULT_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def activate_workspace_core_shadow_v2(document: ProfileDocumentV2) -> ProfileDocumentV2:
    """Explicitly enable the complete Workspace Core capability in one candidate."""
    runtime = _workspace_core_entry_v2(document.entries)
    resolver = _workspace_contract_actor_resolver_entry_v2(document.entries)
    prompt_context = _workspace_prompt_context_entry_v2(document.entries)
    if runtime.enabled and resolver.enabled and prompt_context.enabled:
        return document
    entry_ids = {runtime.entry_id, resolver.entry_id, prompt_context.entry_id}
    return replace(
        document,
        entries=tuple(
            replace(item, enabled=True) if item.entry_id in entry_ids else item
            for item in document.entries
        ),
    )


def workspace_core_shadow_active_v2(snapshot: ProfileSnapshotV2) -> bool:
    """Return whether the complete Workspace Core V2 capability is enabled."""
    entries = {entry.entry_id: entry for entry in snapshot.entries}
    expected = (
        (WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2, WORKSPACE_CORE_RUNTIME_MODULE_V2),
        (
            WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2,
            WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2,
        ),
        (WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2, WORKSPACE_PROMPT_CONTEXT_MODULE_V2),
    )
    return all(
        (entry := entries.get(entry_id)) is not None
        and entry.enabled
        and entry.plugin_ref == _WORKSPACE_CORE_PLUGIN_ID_V2
        and entry.module_ref == module_ref
        for entry_id, module_ref in expected
    )


def compose_workspace_core_shadow_upgrade_v2(
    snapshot: ProfileSnapshotV2,
    *,
    generation: int,
) -> ProfileSnapshotV2:
    """Upsert the complete capability into an older retained snapshot."""
    runtime = _workspace_core_entry_v2(snapshot.entries)
    if workspace_core_shadow_active_v2(snapshot):
        raise RuntimeV2Error(
            "workspace_core_runtime_baseline_not_disabled",
            "Workspace Core shadow upgrade requires an incomplete V2 capability baseline",
        )
    existing_resolver = next(
        (
            item
            for item in snapshot.entries
            if item.entry_id == WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2
        ),
        None,
    )
    if existing_resolver is not None:
        _ = _workspace_contract_actor_resolver_entry_v2(snapshot.entries)
    existing_prompt_context = next(
        (
            item
            for item in snapshot.entries
            if item.entry_id == WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2
        ),
        None,
    )
    if existing_prompt_context is not None:
        _ = _workspace_prompt_context_entry_v2(snapshot.entries)

    canonical = load_profile_document_v2(_DEFAULT_PROFILE_PATH)
    canonical_resolver = _workspace_contract_actor_resolver_entry_v2(canonical.entries)
    canonical_prompt_context = _workspace_prompt_context_entry_v2(canonical.entries)
    entries = _upsert_workspace_core_entries_v2(
        snapshot.entries,
        (
            replace(runtime, enabled=True),
            replace(canonical_resolver, enabled=True),
            replace(canonical_prompt_context, enabled=True),
        ),
    )
    manifests = _replace_kernel_manifest_v2(snapshot.manifests)
    return compose_profile_v2(
        ProfileDocumentV2(profile_id=snapshot.profile_id, entries=entries),
        {manifest.plugin_id: manifest for manifest in manifests},
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


def _workspace_contract_actor_resolver_entry_v2(
    entries: tuple[ProfileEntryV2, ...],
) -> ProfileEntryV2:
    entry = next(
        (
            item
            for item in entries
            if item.entry_id == WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2
        ),
        None,
    )
    if entry is None:
        raise RuntimeV2Error(
            "workspace_core_contract_actor_resolver_entry_missing",
            "Workspace Core shadow activation requires the contract actor resolver entry",
        )
    if (
        entry.plugin_ref != _WORKSPACE_CORE_PLUGIN_ID_V2
        or entry.module_ref != WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2
    ):
        raise RuntimeV2Error(
            "workspace_core_contract_actor_resolver_entry_mismatch",
            "Workspace Core contract actor resolver entry is not canonical",
        )
    return entry


def _workspace_prompt_context_entry_v2(
    entries: tuple[ProfileEntryV2, ...],
) -> ProfileEntryV2:
    entry = next(
        (item for item in entries if item.entry_id == WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2),
        None,
    )
    if entry is None:
        raise RuntimeV2Error(
            "workspace_prompt_context_entry_missing",
            "Workspace Core shadow activation requires the prompt-context entry",
        )
    if (
        entry.plugin_ref != _WORKSPACE_CORE_PLUGIN_ID_V2
        or entry.module_ref != WORKSPACE_PROMPT_CONTEXT_MODULE_V2
    ):
        raise RuntimeV2Error(
            "workspace_prompt_context_entry_mismatch",
            "Workspace Core prompt-context entry is not canonical",
        )
    return entry


def _upsert_workspace_core_entries_v2(
    existing: tuple[ProfileEntryV2, ...],
    desired: tuple[ProfileEntryV2, ...],
) -> tuple[ProfileEntryV2, ...]:
    desired_ids = {entry.entry_id for entry in desired}
    first_existing_index = next(
        (index for index, entry in enumerate(existing) if entry.entry_id in desired_ids),
        len(existing),
    )
    insertion = sum(
        1 for entry in existing[:first_existing_index] if entry.entry_id not in desired_ids
    )
    merged = [entry for entry in existing if entry.entry_id not in desired_ids]
    merged[insertion:insertion] = desired
    return tuple(merged)


def _replace_kernel_manifest_v2(
    existing: tuple[PluginManifestV2, ...],
) -> tuple[PluginManifestV2, ...]:
    current = parse_plugin_manifest_v2(
        json.loads(_DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    )
    if current.plugin_id != _WORKSPACE_CORE_PLUGIN_ID_V2:
        raise RuntimeV2Error(
            "workspace_core_manifest_mismatch",
            "Workspace Core upgrade manifest is not the canonical runtime kernel",
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
    "WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2",
    "WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2",
    "WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2",
    "activate_workspace_core_shadow_v2",
    "compose_workspace_core_shadow_upgrade_v2",
    "workspace_core_shadow_active_v2",
]
