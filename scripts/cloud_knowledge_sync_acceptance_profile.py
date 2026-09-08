"""Compose an isolated Cloud sync QA profile and standard generation vectors."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    parse_profile_snapshot_v2,
    profile_snapshot_v2_to_payload,
)

if TYPE_CHECKING:
    from pathlib import Path

    from src.domain.model.plugins.generated_v2 import ProfileSnapshotV2

CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_PROFILE = "memstack-cloud-knowledge-sync-acceptance-v2"
CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_ENTRIES = frozenset(
    {
        "builtin-cloud-knowledge-sync-repository",
        "builtin-cloud-knowledge-sync-application",
        "builtin-cloud-knowledge-sync-http-routes",
    }
)


def include_cloud_knowledge_sync_acceptance(
    document: ProfileDocumentV2, contribution_path: Path
) -> ProfileDocumentV2:
    if document.profile_id != "memstack-default-v2" or document.patches:
        raise ValueError("cloud acceptance requires the unpatched default product profile")
    contribution = load_profile_document_v2(contribution_path)
    if (
        contribution.profile_id != CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_PROFILE
        or contribution.patches
        or len(contribution.entries) != 3
        or frozenset(entry.entry_id for entry in contribution.entries)
        != CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_ENTRIES
    ):
        raise ValueError("cloud acceptance requires exactly its three fixed contributions")
    originals = [
        entry
        for entry in document.entries
        if entry.entry_id in CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_ENTRIES
    ]
    if len(originals) != 3 or frozenset(entry.entry_id for entry in originals) != (
        CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_ENTRIES
    ):
        raise ValueError("cloud acceptance requires all three product contributions")
    accepted = {entry.entry_id: entry for entry in contribution.entries}
    for original in originals:
        if original.enabled or accepted[original.entry_id] != replace(original, enabled=True):
            raise ValueError("cloud acceptance may only enable the closed cloud contributions")
    return replace(
        document,
        profile_id=contribution.profile_id,
        entries=tuple(accepted.get(entry.entry_id, entry) for entry in document.entries),
    )


def cloud_knowledge_sync_generation_vectors(snapshot: ProfileSnapshotV2) -> dict[str, object]:
    """Derive runtime identities with the existing canonical protocol, not a second serializer."""
    snapshot = parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(snapshot))
    if snapshot.profile_id != CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_PROFILE or snapshot.generation != 1:
        raise ValueError("cloud generation vectors require the fixed generation-one QA template")
    descriptors: list[dict[str, str | int]] = []
    for generation in (1, 81, 82):
        projected = build_profile_snapshot_v2(
            profile_id=snapshot.profile_id,
            generation=generation,
            manifests=snapshot.manifests,
            entries=snapshot.entries,
        )
        descriptors.append(
            {
                "profile_id": projected.profile_id,
                "generation": projected.generation,
                "digest": projected.digest,
            }
        )
    return {
        "schema_version": 1,
        "profile_id": snapshot.profile_id,
        "template_generation": snapshot.generation,
        "template_digest": snapshot.digest,
        "descriptors": descriptors,
    }
