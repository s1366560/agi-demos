"""Compose the fixed local QA contribution without changing product release state."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, load_profile_document_v2


def include_local_knowledge_acceptance(
    document: ProfileDocumentV2, contribution_path: Path
) -> ProfileDocumentV2:
    contribution = load_profile_document_v2(contribution_path)
    if (
        contribution.profile_id != "memstack-local-knowledge-acceptance-v2"
        or contribution.patches
        or len(contribution.entries) != 1
    ):
        raise ValueError("local acceptance profile must contain exactly its fixed contribution")
    accepted = contribution.entries[0]
    original = next(entry for entry in document.entries if entry.entry_id == accepted.entry_id)
    if (
        original.entry_id != "builtin-desktop-sidecar-knowledge-authority"
        or original.enabled
        or original.config
        != {"release_contract": "knowledge-and-sync-v1", "release_state": "closed"}
        or accepted
        != replace(
            original,
            enabled=True,
            config={"acceptance_contract": "local-knowledge-acceptance-v1"},
        )
    ):
        raise ValueError("local acceptance may only replace the closed knowledge contribution")
    return replace(
        document,
        profile_id=contribution.profile_id,
        entries=tuple(
            accepted if entry.entry_id == accepted.entry_id else entry for entry in document.entries
        ),
    )
