"""Read-only structural inspection of legacy rows; no semantic migration verdict."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import Any, cast

from src.domain.model.project_schema.validation import (
    MAX_DOCUMENT_BYTES,
    MAX_MEMBERS,
    ProjectSchemaError,
    document_weight,
    identifier,
    schema_object,
    text,
    uuid,
)
from src.domain.shared_kernel import ValueObject


class SchemaRecordKind(StrEnum):
    PROJECT = "project"
    ENTITY_TYPE = "entity_type"
    EDGE_TYPE = "edge_type"
    MAPPING = "mapping"


@dataclass(frozen=True, kw_only=True)
class SchemaRecordReference(ValueObject):
    kind: SchemaRecordKind
    record_id: str


@dataclass(frozen=True, kw_only=True)
class LegacySchemaRecord(SchemaRecordReference):
    name: str | None = None
    description: str | None = None
    schema_json: str | None = None
    status: str | None = None
    source: str | None = None
    source_type: str | None = None
    target_type: str | None = None
    edge_type: str | None = None


@dataclass(frozen=True, kw_only=True)
class SchemaInspectionFinding(SchemaRecordReference):
    code: str
    field: str | None = None
    related_records: tuple[SchemaRecordReference, ...] = ()


@dataclass(frozen=True, kw_only=True)
class LegacySchemaInspection(ValueObject):
    tenant_id: str
    project_id: str
    entity_type_count: int
    edge_type_count: int
    mapping_count: int
    findings: tuple[SchemaInspectionFinding, ...]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProjectSchemaError
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ProjectSchemaError


def _definition(raw: str | None) -> dict[str, Any]:
    if raw is None:
        raise ProjectSchemaError
    value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    schema_object(value)
    return cast(dict[str, Any], value)


def _reference(record: LegacySchemaRecord) -> SchemaRecordReference:
    return SchemaRecordReference(kind=record.kind, record_id=record.record_id)


class _Inspection:
    """Private accumulator; the returned report contains immutable facts only."""

    def __init__(self) -> None:
        self.findings: list[SchemaInspectionFinding] = []

    def add(
        self,
        record: SchemaRecordReference,
        code: str,
        field: str | None = None,
        related: Sequence[LegacySchemaRecord] = (),
    ) -> None:
        self.findings.append(
            SchemaInspectionFinding(
                kind=record.kind,
                record_id=record.record_id,
                code=code,
                field=field,
                related_records=tuple(_reference(item) for item in related),
            )
        )

    def check(
        self,
        record: SchemaRecordReference,
        field: str,
        check: Callable[[], object],
        code: str = "legacy_schema_field_invalid",
    ) -> bool:
        try:
            check()
            return True
        except (ValueError, TypeError, OverflowError, RecursionError):
            self.add(record, code, field)
            return False

    def type_member(self, record: LegacySchemaRecord) -> dict[str, Any]:
        self.check(record, "name", lambda: text(record.name, 512))
        description = "" if record.description is None else record.description
        self.check(record, "description", lambda: text(description, 4096, nonempty=False))
        definition: dict[str, Any] = {}
        try:
            definition = _definition(record.schema_json)
        except (ValueError, TypeError, OverflowError, RecursionError):
            self.add(record, "legacy_schema_definition_invalid", "schema")
        return {
            "id": record.record_id,
            "name": record.name,
            "description": description,
            "schema": definition,
            "status": record.status,
            "source": record.source,
        }

    def mapping_member(
        self,
        record: LegacySchemaRecord,
        names: dict[SchemaRecordKind, dict[str, list[LegacySchemaRecord]]],
    ) -> dict[str, Any]:
        member: dict[str, Any] = {
            "id": record.record_id,
            "status": record.status,
            "source": record.source,
        }
        for field, kind in (
            ("source_type", SchemaRecordKind.ENTITY_TYPE),
            ("target_type", SchemaRecordKind.ENTITY_TYPE),
            ("edge_type", SchemaRecordKind.EDGE_TYPE),
        ):
            name = getattr(record, field)
            if not self.check(record, field, partial(text, name, 512)):
                continue
            matches = names[kind].get(name, [])
            if len(matches) != 1:
                code = (
                    "legacy_schema_reference_missing"
                    if not matches
                    else "legacy_schema_reference_ambiguous"
                )
                self.add(record, code, field, matches)
            else:
                member[field + "_id"] = matches[0].record_id
        return member


def _indexes(
    scan: _Inspection, records: Sequence[LegacySchemaRecord]
) -> dict[SchemaRecordKind, dict[str, list[LegacySchemaRecord]]]:
    by_id: dict[str, list[LegacySchemaRecord]] = defaultdict(list)
    names: dict[SchemaRecordKind, dict[str, list[LegacySchemaRecord]]] = {
        SchemaRecordKind.ENTITY_TYPE: defaultdict(list),
        SchemaRecordKind.EDGE_TYPE: defaultdict(list),
    }
    for record in records:
        by_id[record.record_id].append(record)
        scan.check(record, "id", partial(uuid, record.record_id), "legacy_schema_id_invalid")
        scan.check(record, "source", partial(text, record.source, 128))
        if record.status not in {"ENABLED", "DISABLED"}:
            scan.add(record, "legacy_schema_field_invalid", "status")
        if record.kind in names and record.name is not None:
            names[record.kind][record.name].append(record)
    for matching in by_id.values():
        if len(matching) > 1:
            scan.add(matching[0], "legacy_schema_id_collision", "id", matching)
    for matching_names in names.values():
        for matching in matching_names.values():
            if len(matching) > 1:
                scan.add(matching[0], "legacy_schema_name_collision", "name", matching)
    return names


def inspect_legacy_project_schema(
    *, tenant_id: str, project_id: str, records: Sequence[LegacySchemaRecord]
) -> LegacySchemaInspection:
    """Report exact structural defects; no UUID allocation, repair, or activation decision."""
    scan = _Inspection()
    project = SchemaRecordReference(kind=SchemaRecordKind.PROJECT, record_id=project_id)
    for field, value in (("tenant_id", tenant_id), ("project_id", project_id)):
        scan.check(project, field, partial(identifier, value), "legacy_schema_scope_invalid")
    if len(records) > MAX_MEMBERS:
        scan.add(project, "legacy_schema_member_limit_exceeded")
    names = _indexes(scan, records)
    members: dict[SchemaRecordKind, list[dict[str, Any]]] = {
        SchemaRecordKind.ENTITY_TYPE: [],
        SchemaRecordKind.EDGE_TYPE: [],
        SchemaRecordKind.MAPPING: [],
    }
    for record in records:
        member = (
            scan.mapping_member(record, names)
            if record.kind == SchemaRecordKind.MAPPING
            else scan.type_member(record)
        )
        members[record.kind].append(member)
    if not scan.findings:
        # Only an arithmetic envelope: UUID byte length is fixed; no identity is minted or exposed.
        weighted = {
            "format_version": 1,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "schema_id": "_" * 36,
            "revision": 1,
            "deleted": False,
            "entity_types": members[SchemaRecordKind.ENTITY_TYPE],
            "edge_types": members[SchemaRecordKind.EDGE_TYPE],
            "mappings": members[SchemaRecordKind.MAPPING],
            "tombstones": [],
        }
        if document_weight(weighted) > MAX_DOCUMENT_BYTES:
            scan.add(project, "legacy_schema_document_limit_exceeded")
    return LegacySchemaInspection(
        tenant_id=tenant_id,
        project_id=project_id,
        entity_type_count=len(members[SchemaRecordKind.ENTITY_TYPE]),
        edge_type_count=len(members[SchemaRecordKind.EDGE_TYPE]),
        mapping_count=len(members[SchemaRecordKind.MAPPING]),
        findings=tuple(scan.findings),
    )
