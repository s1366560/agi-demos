"""Publication retains legacy actions while the same release gate remains closed."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from scripts.generate_native_knowledge_contract import RUST, SCHEMA, TYPESCRIPT, load_definitions
from scripts.native_knowledge_capability_catalog import render_capability_catalog

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.unit
def test_capability_action_catalog_and_closed_fixture_match_shared_contract() -> None:
    schema = json.loads(SCHEMA.read_text())
    definitions = load_definitions()
    rust, ts = render_capability_catalog(schema, definitions)
    assert RUST.with_name("capabilities_generated.rs").read_text() == rust
    assert TYPESCRIPT.with_name("nativeKnowledgeCapabilityActionsGenerated.ts").read_text() == ts
    assert len(schema["x-capability-actions"]) == 51
    assert set(
        definitions["NativeKnowledgeCapabilityEntry"]["properties"]["allowed_actions"]["items"][
            "enum"
        ]
    ) == set(schema["x-capability-actions"])
    for action in ("failed_processing", "failed_index", "processing_audits"):
        assert schema["x-capability-actions"][action] == "read"
    old_writes = {
        "create",
        "update",
        "delete",
        "sync_link",
        "sync_push",
        "sync_pull",
        "resolve_pull",
        "resolve_push",
        "resume_resolution",
        "reconcile_resolution",
    }
    expected_writes = (
        old_writes | definitions["NativeKnowledgeProcessingCommandMap"]["properties"].keys()
    )
    assert {
        name for name, access in schema["x-capability-actions"].items() if access == "write"
    } == expected_writes
    registry = Registry().with_resources(
        (document["$id"], Resource.from_contents(document))
        for path in SCHEMA.parent.glob("*.json")
        for document in [json.loads(path.read_text())]
    )
    validator = Draft202012Validator(
        {"$ref": schema["$id"] + "#/$defs/NativeKnowledgeCapabilitiesResponse"}, registry=registry
    )
    fixture = json.loads(
        (ROOT / "shared/fixtures/native-knowledge-capabilities.v1.json").read_text()
    )
    validator.validate(fixture)
    assert fixture["result"]["allowed_actions"] == []
    assert fixture["result"]["provenance"] == "observed"
    fixture["result"]["allowed_actions"] = ["processing-command"]
    assert not validator.is_valid(fixture)


@pytest.mark.unit
@pytest.mark.parametrize("change", ["remove_legacy", "add_unknown", "change_query_access"])
def test_action_catalog_rejects_missing_legacy_or_mismatched_processing_access(change: str) -> None:
    schema = copy.deepcopy(json.loads(SCHEMA.read_text()))
    if change == "remove_legacy":
        del schema["x-capability-actions"]["sync_status"]
    elif change == "add_unknown":
        schema["x-capability-actions"]["processing-query"] = "read"
    else:
        schema["x-capability-actions"]["semantic"] = "write"
    with pytest.raises(ValueError):
        render_capability_catalog(schema, load_definitions())
