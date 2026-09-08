"""Legacy inspection reports structural facts without repairing or minting IDs."""

import json
from dataclasses import replace

import pytest

from src.domain.model.project_schema.inspection import (
    LegacySchemaRecord,
    SchemaRecordKind,
    inspect_legacy_project_schema,
)

ENTITY = LegacySchemaRecord(
    kind=SchemaRecordKind.ENTITY_TYPE,
    record_id="00000000-0000-4000-8000-000000000002",
    name="Person",
    description=None,
    schema_json='{"age":{"type":"integer"}}',
    status="ENABLED",
    source="user",
)
EDGE = replace(
    ENTITY,
    kind=SchemaRecordKind.EDGE_TYPE,
    record_id="00000000-0000-4000-8000-000000000003",
    name="KNOWS",
)
MAPPING = LegacySchemaRecord(
    kind=SchemaRecordKind.MAPPING,
    record_id="00000000-0000-4000-8000-000000000004",
    source_type="Person",
    target_type="Person",
    edge_type="KNOWS",
    status="ENABLED",
    source="llm_discovered",
)


def inspect(*records):
    return inspect_legacy_project_schema(tenant_id="tenant", project_id="project", records=records)


@pytest.mark.unit
def test_valid_legacy_values_are_not_rewritten():
    result = inspect(ENTITY, EDGE, MAPPING)
    assert result.findings == ()
    assert (result.entity_type_count, result.edge_type_count, result.mapping_count) == (1, 1, 1)
    assert ENTITY.description is None
    assert MAPPING.source_type == "Person"


@pytest.mark.unit
def test_id_collision_preserves_both_original_record_kinds():
    result = inspect(ENTITY, replace(EDGE, record_id=ENTITY.record_id))
    finding = next(item for item in result.findings if item.code == "legacy_schema_id_collision")
    assert {item.kind for item in finding.related_records} == {
        SchemaRecordKind.ENTITY_TYPE,
        SchemaRecordKind.EDGE_TYPE,
    }
    assert all(item.record_id == ENTITY.record_id for item in finding.related_records)


@pytest.mark.unit
def test_missing_reference_is_not_inferred_from_similar_name():
    result = inspect(ENTITY, EDGE, replace(MAPPING, target_type="person"))
    finding = next(
        item for item in result.findings if item.code == "legacy_schema_reference_missing"
    )
    assert finding.record_id == MAPPING.record_id
    assert finding.field == "target_type"


@pytest.mark.unit
def test_ambiguous_reference_is_not_chosen_by_order():
    duplicate = replace(ENTITY, record_id="00000000-0000-4000-8000-000000000009")
    result = inspect(ENTITY, duplicate, EDGE, MAPPING)
    assert "legacy_schema_name_collision" in {item.code for item in result.findings}
    ambiguous = [
        item for item in result.findings if item.code == "legacy_schema_reference_ambiguous"
    ]
    assert {item.field for item in ambiguous} == {"source_type", "target_type"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates,code,field",
    [
        ({"record_id": "old-non-uuid"}, "legacy_schema_id_invalid", "id"),
        ({"name": ""}, "legacy_schema_field_invalid", "name"),
        ({"description": "x" * 4097}, "legacy_schema_field_invalid", "description"),
        ({"source": "x" * 129}, "legacy_schema_field_invalid", "source"),
        ({"status": "unknown"}, "legacy_schema_field_invalid", "status"),
        ({"schema_json": None}, "legacy_schema_definition_invalid", "schema"),
        ({"schema_json": "null"}, "legacy_schema_definition_invalid", "schema"),
        ({"schema_json": '{"x":1,"x":2}'}, "legacy_schema_definition_invalid", "schema"),
        ({"schema_json": '{"x":NaN}'}, "legacy_schema_definition_invalid", "schema"),
        ({"schema_json": '{"x":9007199254740992}'}, "legacy_schema_definition_invalid", "schema"),
    ],
)
def test_invalid_field_reports_the_original_id(updates, code, field):
    record = replace(ENTITY, **updates)
    result = inspect(record)
    assert any(
        item.code == code and item.field == field and item.record_id == record.record_id
        for item in result.findings
    )


@pytest.mark.unit
def test_legacy_member_count_is_reported_without_truncation():
    records = tuple(
        replace(
            ENTITY, record_id=f"00000000-0000-4000-8000-{index + 100:012d}", name=f"Type {index}"
        )
        for index in range(1025)
    )
    result = inspect(*records)
    assert result.entity_type_count == 1025
    assert any(
        item.code == "legacy_schema_member_limit_exceeded" and item.record_id == "project"
        for item in result.findings
    )


@pytest.mark.unit
def test_aggregate_document_weight_is_checked_before_any_bootstrap():
    definition = json.dumps({"x": [0] * 1022})
    records = tuple(
        replace(
            ENTITY,
            record_id=f"00000000-0000-4000-8000-{index + 100:012d}",
            name=f"Type {index}",
            schema_json=definition,
        )
        for index in range(32)
    )
    result = inspect(*records)
    assert [item.code for item in result.findings] == ["legacy_schema_document_limit_exceeded"]


@pytest.mark.unit
def test_invalid_scope_and_missing_mapping_label_are_structural_errors():
    result = inspect_legacy_project_schema(
        tenant_id=" tenant",
        project_id="project",
        records=(ENTITY, EDGE, replace(MAPPING, target_type=None)),
    )
    assert ("legacy_schema_scope_invalid", "tenant_id") in {
        (item.code, item.field) for item in result.findings
    }
    assert ("legacy_schema_field_invalid", "target_type") in {
        (item.code, item.field) for item in result.findings
    }
