"""Local acceptance is an exact additive composition, never a product release edit."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.generate_plugin_protocol_v2 import _bootstrap_profile, _builtin_manifest, _schema
from scripts.local_knowledge_acceptance_profile import include_local_knowledge_acceptance
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.target_profiles import include_production_target_hosts_v2

ROOT = Path(__file__).resolve().parents[4]
CONTRIBUTION = ROOT / "config/plugin-profiles/memstack-local-knowledge-acceptance.v2.yaml"
ENTRY = "builtin-desktop-sidecar-knowledge-authority"


@pytest.mark.unit
def test_generated_acceptance_changes_only_fixed_knowledge_entry_and_profile_identity() -> None:
    manifests = _builtin_manifest(_schema())
    product = _bootstrap_profile(manifests)
    accepted = _bootstrap_profile(manifests, local_acceptance=True)
    assert product["profile_id"] == "memstack-default-v2"
    assert accepted["profile_id"] == "memstack-local-knowledge-acceptance-v2"
    assert product["digest"] != accepted["digest"]
    assert product["manifests"] == accepted["manifests"]
    old_entries = {entry["entry_id"]: entry for entry in product["entries"]}
    new_entries = {entry["entry_id"]: entry for entry in accepted["entries"]}
    assert old_entries.keys() == new_entries.keys()
    for identifier, old in old_entries.items():
        if identifier == ENTRY:
            assert old["enabled"] is False
            assert old["config"] == {
                "release_contract": "knowledge-and-sync-v1",
                "release_state": "closed",
            }
            assert new_entries[identifier] == {
                **old,
                "enabled": True,
                "config": {"acceptance_contract": "local-knowledge-acceptance-v1"},
            }
        else:
            assert new_entries[identifier] == old
    generated = ROOT / "shared/profiles/memstack-local-knowledge-acceptance.v2.json"
    assert json.loads(generated.read_text()) == accepted


@pytest.mark.unit
def test_acceptance_composition_refuses_a_product_profile_that_has_already_opened_knowledge() -> (
    None
):
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
    with pytest.raises(ValueError, match="only replace the closed"):
        include_local_knowledge_acceptance(changed, CONTRIBUTION)


@pytest.mark.unit
def test_formal_contract_preserves_closed_release_and_requires_exact_acceptance_purpose() -> None:
    manifest = json.loads(
        (ROOT / "config/plugin-manifests-v2/memstack-local-knowledge.v2.json").read_text()
    )
    validator = Draft202012Validator(manifest["modules"][0]["contract"]["config_schema"])
    assert validator.is_valid(
        {"release_contract": "knowledge-and-sync-v1", "release_state": "closed"}
    )
    assert validator.is_valid({"acceptance_contract": "local-knowledge-acceptance-v1"})
    for candidate in [
        {"release_contract": "knowledge-and-sync-v1", "release_state": "ready"},
        {"acceptance_contract": "local-knowledge-acceptance-v1", "allowed_actions": ["sync_push"]},
        {"acceptance_contract": "production"},
        {
            "release_contract": "knowledge-and-sync-v1",
            "release_state": "closed",
            "acceptance_contract": "local-knowledge-acceptance-v1",
        },
    ]:
        assert not validator.is_valid(candidate)
    schema = json.loads(
        (ROOT / "shared/schemas/knowledge/native-knowledge.v1.schema.json").read_text()
    )
    actions = set(schema["x-local-acceptance-actions"])
    assert {"create", "get", "process_one", "configuration", "text", "semantic"} <= actions
    assert actions.isdisjoint(
        {"sync_link", "sync_push", "sync_pull", "resolve_pull", "resolve_push"}
    )
