"""Cross-client wire schema keeps existing sync/CRUD and rejects profile injection."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from scripts.generate_native_knowledge_contract import (
    RUST,
    TYPESCRIPT,
    load_definitions,
    referenced_names,
    render_rust,
    render_typescript,
)

ROOT = Path(__file__).resolve().parents[4]
SCHEMAS = ROOT / "shared/schemas/knowledge"
SCHEMA = json.loads((SCHEMAS / "native-knowledge.v1.schema.json").read_text())
CASES = json.loads((ROOT / "shared/fixtures/native-knowledge.v1.json").read_text())["requests"]
REGISTRY = Registry().with_resources(
    (document["$id"], Resource.from_contents(document))
    for path in SCHEMAS.glob("*.json")
    for document in [json.loads(path.read_text())]
)


def validator(reference: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": SCHEMA["$id"] + reference}, registry=REGISTRY)


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_existing_and_new_requests_follow_one_schema(case: dict) -> None:
    reference = SCHEMA["x-routes"][case["path"]]["request"]["$ref"]
    validator(reference).validate(case["request"])


@pytest.mark.unit
@pytest.mark.parametrize("field", ["profile", "vector", "credential_binding_digest", "lease_ms"])
def test_index_commands_reject_caller_profile_vector_and_lease_parameters(field: str) -> None:
    request = copy.deepcopy(next(case["request"] for case in CASES if case["name"] == "index_one"))
    request["command"][field] = "forged"
    assert not validator("#/$defs/NativeKnowledgeProcessingCommandRequest").is_valid(request)


@pytest.mark.unit
@pytest.mark.parametrize("revision", [-1, 0, 1.5, 9_007_199_254_740_992, "1"])
def test_semantic_requests_require_positive_exact_client_representable_revision(
    revision: object,
) -> None:
    request = copy.deepcopy(next(case["request"] for case in CASES if case["name"] == "semantic"))
    request["query"]["config_revision"] = revision
    assert not validator("#/$defs/NativeKnowledgeProcessingQueryRequest").is_valid(request)


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["configure_embedding", "promote_index"])
def test_nullable_cas_precondition_is_explicitly_present(operation: str) -> None:
    request = copy.deepcopy(next(case["request"] for case in CASES if case["name"] == operation))
    field = (
        "expected_config_revision"
        if operation == "configure_embedding"
        else "expected_active_build_id"
    )
    del request["command"][field]
    assert not validator("#/$defs/NativeKnowledgeProcessingCommandRequest").is_valid(request)


@pytest.mark.unit
def test_existing_crud_views_preserve_structured_entities_and_optional_embedding() -> None:
    memory = copy.deepcopy(
        next(case["request"]["mutation"]["memory"] for case in CASES if case["name"] == "create")
    )
    validator("#/$defs/NativeKnowledgeMutationMemory").validate(memory)
    memory["entities"] = ["unstructured"]
    assert not validator("#/$defs/NativeKnowledgeMutationMemory").is_valid(memory)
    definitions = load_definitions()
    assert {"get", "create", "update", "delete"} <= definitions["NativeKnowledgeRequestMap"][
        "properties"
    ].keys()


@pytest.mark.unit
def test_generated_rust_and_typescript_stay_bound_to_the_schema() -> None:
    definitions = load_definitions()
    assert RUST.read_text() == render_rust(definitions)
    rpc = {
        name: node
        for name, node in definitions.items()
        if name.endswith(("Map", "Query", "Request", "Command", "Mutation", "Envelope", "Response"))
    }
    data = {name: node for name, node in definitions.items() if name not in rpc}
    imports = sorted(set().union(*(referenced_names(node) for node in rpc.values())) & data.keys())
    assert TYPESCRIPT.with_name("nativeKnowledgeDataGenerated.ts").read_text() == render_typescript(
        data
    )
    assert TYPESCRIPT.with_name("nativeKnowledgeRpcGenerated.ts").read_text() == render_typescript(
        rpc, imports
    )
