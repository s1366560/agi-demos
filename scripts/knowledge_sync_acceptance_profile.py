"""Compose the fixed native sync QA contribution; cloud activation stays separate."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, load_profile_document_v2

PROFILE = "memstack-knowledge-sync-acceptance-v2"
PURPOSE = "knowledge-sync-acceptance-v1"
NATIVE = "builtin-desktop-sidecar-knowledge-authority"


def include_knowledge_sync_acceptance(
    document: ProfileDocumentV2, contribution_path: Path
) -> ProfileDocumentV2:
    if document.profile_id != "memstack-default-v2" or document.patches:
        raise ValueError("native sync acceptance requires the unpatched default product profile")
    contribution = load_profile_document_v2(contribution_path)
    accepted = {entry.entry_id: entry for entry in contribution.entries}
    if (
        contribution.profile_id != PROFILE
        or contribution.patches
        or len(contribution.entries) != 1
        or accepted.keys() != {NATIVE}
    ):
        raise ValueError("joint acceptance requires exactly its fixed native contribution")
    originals = {entry.entry_id: entry for entry in document.entries}
    for identifier, candidate in accepted.items():
        original = originals[identifier]
        config = original.config
        if identifier == NATIVE:
            if config != {"release_contract": "knowledge-and-sync-v1", "release_state": "closed"}:
                raise ValueError("joint acceptance requires closed native knowledge")
            config = {"acceptance_contract": PURPOSE}
        if original.enabled or candidate != replace(original, enabled=True, config=config):
            raise ValueError("joint acceptance may only enable its exact closed contributions")
    return replace(
        document,
        profile_id=PROFILE,
        entries=tuple(accepted.get(entry.entry_id, entry) for entry in document.entries),
    )
