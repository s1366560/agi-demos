"""Internal commands reject ambiguous bootstrap and preserve their immutable intent."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from src.domain.model.project_schema.bootstrap import (
    ProjectSchemaBootstrapRejected,
    bootstrap_document,
)
from src.domain.model.project_schema.commands import (
    BootstrapProjectSchema,
    ProjectSchemaScope,
    ReplaceProjectSchema,
    require_legacy_representable,
)
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.inspection import LegacySchemaRecord, SchemaRecordKind
from src.domain.model.project_schema.validation import ProjectSchemaError

pytestmark = pytest.mark.unit

SCOPE = ProjectSchemaScope(tenant_id="tenant", project_id="project", actor_id="actor")
ENTITY = "00000000-0000-4000-8000-000000000002"
EDGE = "00000000-0000-4000-8000-000000000003"
MAP = "00000000-0000-4000-8000-000000000004"
SCHEMA = "00000000-0000-4000-8000-000000000001"


def records():
    return (
        LegacySchemaRecord(
            kind=SchemaRecordKind.ENTITY_TYPE,
            record_id=ENTITY,
            name="Person",
            schema_json='{"age":{"type":"number"}}',
            status="ENABLED",
            source="user",
        ),
        LegacySchemaRecord(
            kind=SchemaRecordKind.EDGE_TYPE,
            record_id=EDGE,
            name="KNOWS",
            schema_json="{}",
            status="DISABLED",
            source="system",
        ),
        LegacySchemaRecord(
            kind=SchemaRecordKind.MAPPING,
            record_id=MAP,
            source_type="Person",
            target_type="Person",
            edge_type="KNOWS",
            status="ENABLED",
            source="user",
        ),
    )


def test_bootstrap_preserves_ids_and_nullable_descriptions_without_mutating_records():
    original = records()
    result = bootstrap_document(scope=SCOPE, schema_id=SCHEMA, records=original).to_dict()
    assert result["entity_types"][0]["id"] == ENTITY
    assert result["edge_types"][0]["id"] == EDGE
    assert result["mappings"][0] == {
        "id": MAP,
        "source_type_id": ENTITY,
        "target_type_id": ENTITY,
        "edge_type_id": EDGE,
        "status": "ENABLED",
        "source": "user",
    }
    assert result["entity_types"][0]["description"] == ""
    assert original[0].description is None
    assert result["tombstones"] == [] and result["revision"] == 1


@pytest.mark.parametrize("defect", ["missing", "ambiguous", "uuid", "duplicate_json", "collision"])
def test_bootstrap_rejects_whole_batch_without_guessing(defect):
    source = list(records())
    if defect == "missing":
        source[2] = replace(source[2], source_type="person")
    elif defect == "ambiguous":
        source.append(replace(source[0], record_id=str(uuid4())))
    elif defect == "uuid":
        source[0] = replace(source[0], record_id="old-not-uuid")
    elif defect == "duplicate_json":
        source[0] = replace(source[0], schema_json='{"a":1,"a":2}')
    else:
        source[1] = replace(source[1], record_id=ENTITY)
    with pytest.raises(ProjectSchemaBootstrapRejected) as raised:
        bootstrap_document(scope=SCOPE, schema_id=SCHEMA, records=source)
    assert raised.value.inspection.findings
    assert source[2].record_id == MAP


def test_bootstrap_command_request_is_stable_and_explicitly_scoped():
    command = BootstrapProjectSchema(schema_id=SCHEMA, change_id=str(uuid4()))
    assert command.request_json(SCOPE) == command.request_json(SCOPE)
    assert json.loads(command.request_json(SCOPE))["expected_revision"] == 0
    assert command.request_json(replace(SCOPE, actor_id="other")) != command.request_json(SCOPE)


@pytest.mark.parametrize("revision", [True, 0, -1, 1.0, "1", 2147483648])
def test_replace_rejects_invalid_cas_precondition(revision):
    document = bootstrap_document(scope=SCOPE, schema_id=SCHEMA, records=records())
    with pytest.raises(ProjectSchemaError, match="project_schema_revision_conflict"):
        ReplaceProjectSchema(document=document, expected_revision=revision, change_id=str(uuid4()))


def test_replace_rejects_cross_scope_and_unrepresentable_name_or_triple():
    document = bootstrap_document(scope=SCOPE, schema_id=SCHEMA, records=records())
    command = ReplaceProjectSchema(document=document, expected_revision=1, change_id=str(uuid4()))
    with pytest.raises(ProjectSchemaError, match="project_schema_scope_mismatch"):
        command.request_json(replace(SCOPE, tenant_id="foreign"))
    for key in ("entity_types", "mappings"):
        value = document.to_dict()
        value[key].append({**value[key][0], "id": str(uuid4())})
        duplicate = ProjectSchemaDocument.from_json(json.dumps(value))
        with pytest.raises(ProjectSchemaError, match="project_schema_legacy_unrepresentable"):
            require_legacy_representable(duplicate)
