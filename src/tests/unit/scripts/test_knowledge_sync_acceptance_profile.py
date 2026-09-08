"""The explicit native sync QA profile changes one closed native entry only."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.generate_plugin_protocol_v2 import _bootstrap_profile, _builtin_manifest, _schema
from scripts.knowledge_sync_acceptance_profile import include_knowledge_sync_acceptance
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.target_profiles import include_production_target_hosts_v2

ROOT = Path(__file__).resolve().parents[4]
CONTRIBUTION = ROOT / "config/plugin-profiles/memstack-knowledge-sync-acceptance.v2.yaml"
ENTRY = "builtin-desktop-sidecar-knowledge-authority"


@pytest.mark.unit
def test_native_sync_qa_only_enables_native_entry_and_never_cloud_or_product_defaults() -> None:
    manifests = _builtin_manifest(_schema())
    product = _bootstrap_profile(manifests)
    accepted = _bootstrap_profile(manifests, sync_acceptance=True)
    assert accepted["profile_id"] == "memstack-knowledge-sync-acceptance-v2"
    assert product["manifests"] == accepted["manifests"]
    old_entries = {entry["entry_id"]: entry for entry in product["entries"]}
    for entry in accepted["entries"]:
        old = old_entries[entry["entry_id"]]
        if entry["entry_id"] == ENTRY:
            assert old["enabled"] is False
            assert entry == {
                **old,
                "enabled": True,
                "config": {"acceptance_contract": "knowledge-sync-acceptance-v1"},
            }
        else:
            assert entry == old
            if entry["entry_id"].startswith("builtin-cloud-knowledge-sync-"):
                assert entry["enabled"] is False
    assert (
        json.loads(
            (ROOT / "shared/profiles/memstack-knowledge-sync-acceptance.v2.json").read_text()
        )
        == accepted
    )


@pytest.mark.unit
def test_native_sync_qa_requires_closed_native_source() -> None:
    document = include_production_target_hosts_v2(
        load_profile_document_v2(ROOT / "config/plugin-profiles/memstack-default.v2.yaml")
    )
    changed = replace(
        document,
        entries=tuple(
            replace(entry, enabled=True) if entry.entry_id == ENTRY else entry
            for entry in document.entries
        ),
    )
    with pytest.raises(ValueError, match="exact closed"):
        include_knowledge_sync_acceptance(changed, CONTRIBUTION)


@pytest.mark.unit
def test_native_qa_purposes_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        _bootstrap_profile(
            _builtin_manifest(_schema()), local_acceptance=True, sync_acceptance=True
        )
