"""Strict bootstrap projection; existing IDs are never allocated, repaired or inferred."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from src.domain.model.project_schema.commands import ProjectSchemaScope, canonical_snapshot
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.inspection import (
    LegacySchemaInspection,
    LegacySchemaRecord,
    SchemaRecordKind,
    inspect_legacy_project_schema,
)
from src.domain.model.project_schema.validation import ProjectSchemaError, uuid


class ProjectSchemaBootstrapRejected(ProjectSchemaError):
    def __init__(self, inspection: LegacySchemaInspection) -> None:
        self.inspection = inspection
        super().__init__("project_schema_bootstrap_rejected")


def bootstrap_document(
    *, scope: ProjectSchemaScope, schema_id: str, records: Sequence[LegacySchemaRecord]
) -> ProjectSchemaDocument:
    uuid(schema_id)
    inspection = inspect_legacy_project_schema(
        tenant_id=scope.tenant_id, project_id=scope.project_id, records=records
    )
    if inspection.findings:
        raise ProjectSchemaBootstrapRejected(inspection)
    # Inspection proved canonical IDs, unique names and exact unambiguous references.
    entity_ids = {
        item.name: item.record_id for item in records if item.kind == SchemaRecordKind.ENTITY_TYPE
    }
    edge_ids = {
        item.name: item.record_id for item in records if item.kind == SchemaRecordKind.EDGE_TYPE
    }
    value: dict[str, Any] = {
        "format_version": 1,
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "schema_id": schema_id,
        "revision": 1,
        "deleted": False,
        "entity_types": [],
        "edge_types": [],
        "mappings": [],
        "tombstones": [],
    }
    for record in records:
        member: dict[str, Any] = {
            "id": record.record_id,
            "status": record.status,
            "source": record.source,
        }
        if record.kind == SchemaRecordKind.MAPPING:
            member.update(
                source_type_id=entity_ids[record.source_type],
                target_type_id=entity_ids[record.target_type],
                edge_type_id=edge_ids[record.edge_type],
            )
            value["mappings"].append(member)
        else:
            assert record.schema_json is not None
            member.update(
                name=record.name,
                description="" if record.description is None else record.description,
                schema=json.loads(record.schema_json),
            )
            key = "entity_types" if record.kind == SchemaRecordKind.ENTITY_TYPE else "edge_types"
            value[key].append(member)
    result = canonical_snapshot(
        ProjectSchemaDocument.from_json(json.dumps(value, ensure_ascii=False))
    )
    result.validate_successor(previous=None, expected_revision=0)
    return result
