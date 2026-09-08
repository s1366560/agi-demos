"""Original HTTP mutation intent is stable before and after CAS materialization."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from src.domain.model.project_schema.bootstrap import bootstrap_document
from src.domain.model.project_schema.http_mutations import (
    SchemaHttpMutation,
    SchemaHttpOperation,
    materialize_http_mutation,
)
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.tests.unit.domain.model.project_schema.test_commands import (
    EDGE,
    ENTITY,
    MAP,
    SCHEMA,
    SCOPE,
    records,
)

pytestmark = pytest.mark.unit
CREATED = "00000000-0000-4000-8000-000000000005"


def previous():
    return bootstrap_document(scope=SCOPE, schema_id=SCHEMA, records=records())


def mutation(operation, target=None, fields=None, expected="1", change=None):
    return SchemaHttpMutation.from_fields(
        scope=SCOPE,
        operation=SchemaHttpOperation(operation),
        target_id=target,
        fields=fields or {},
        expected_revision=expected,
        change_id=change or str(uuid4()),
    )


def test_original_intent_is_immutable_and_preserves_explicit_null():
    fields = {"description": None, "schema": {"nested": ["original"]}}
    command = mutation("update_entity_type", ENTITY, fields)
    original = command.request_json()
    fields["schema"]["nested"].append("caller changed after admission")
    assert command.request_json() == original
    assert json.loads(original)["fields"]["description"] is None
    omitted = mutation("update_entity_type", ENTITY, {}, change=command.change_id)
    assert omitted.request_json() != original


@pytest.mark.parametrize("expected,change", [(None, None), ("1", None), (None, str(uuid4()))])
def test_active_mutation_requires_both_headers(expected, change):
    command = replace(
        mutation("delete_edge_map", MAP), expected_revision=expected, change_id=change
    )
    with pytest.raises(ProjectSchemaError, match="project_schema_command_required"):
        command.request_json()


@pytest.mark.parametrize("expected", ["0", "-1", "1.0", " 1", "01", "2147483648", "１"])
def test_revision_header_is_an_exact_bounded_integer(expected):
    with pytest.raises(ProjectSchemaError, match="project_schema_precondition_invalid"):
        mutation("delete_edge_map", MAP, expected=expected).request_json()


@pytest.mark.parametrize(
    "operation,target,fields,collection",
    [
        ("create_entity_type", None, {"name": "Place"}, "entity_types"),
        ("update_entity_type", ENTITY, {"description": "new"}, "entity_types"),
        ("create_edge_type", None, {"name": "VISITS"}, "edge_types"),
        ("update_edge_type", EDGE, {"schema": {"weight": {"type": "Float"}}}, "edge_types"),
    ],
)
def test_type_mutations_preserve_identity_and_advance_once(operation, target, fields, collection):
    command = mutation(operation, target, fields)
    result = materialize_http_mutation(
        previous(), command.request_json(), created_id=CREATED if target is None else None
    )
    value = result.to_dict()
    assert value["revision"] == 2
    member = next(item for item in value[collection] if item["id"] == (target or CREATED))
    for key, field in fields.items():
        assert member[key] == field
    assert previous().to_dict()["revision"] == 1


@pytest.mark.parametrize(
    "operation,target", [("delete_entity_type", ENTITY), ("delete_edge_type", EDGE)]
)
def test_referenced_types_cannot_be_deleted_implicitly(operation, target):
    with pytest.raises(ProjectSchemaError, match="project_schema_type_referenced"):
        materialize_http_mutation(previous(), mutation(operation, target).request_json())


def test_explicit_mapping_delete_precedes_type_delete_and_keeps_tombstones():
    removed_map = materialize_http_mutation(
        previous(), mutation("delete_edge_map", MAP).request_json()
    )
    removed_entity = materialize_http_mutation(
        removed_map, mutation("delete_entity_type", ENTITY, expected="2").request_json()
    )
    result = materialize_http_mutation(
        removed_entity, mutation("delete_edge_type", EDGE, expected="3").request_json()
    ).to_dict()
    assert result["entity_types"] == result["edge_types"] == result["mappings"] == []
    assert len(result["tombstones"]) == 3
    assert {item["deleted_revision"] for item in result["tombstones"]} == {2, 3, 4}


def test_create_mapping_resolves_exact_names_inside_current_document():
    base = materialize_http_mutation(previous(), mutation("delete_edge_map", MAP).request_json())
    command = mutation(
        "create_edge_map",
        fields={"source_type": "Person", "target_type": "Person", "edge_type": "KNOWS"},
        expected="2",
    )
    value = materialize_http_mutation(base, command.request_json(), created_id=CREATED).to_dict()
    assert value["mappings"][0]["source_type_id"] == ENTITY
    assert value["mappings"][0]["edge_type_id"] == EDGE
    assert value["mappings"][0]["id"] == CREATED


def test_stale_revision_does_not_rebase_original_patch():
    with pytest.raises(ProjectSchemaError, match="project_schema_revision_conflict"):
        materialize_http_mutation(
            previous(),
            mutation(
                "update_entity_type", ENTITY, {"description": "stale"}, expected="2"
            ).request_json(),
        )
