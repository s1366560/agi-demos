"""Immutable original mutation intent and structural patch materialization.

No scope discovery, semantic matching, retry rebasing, or persistence lives here.
Header validation is deliberately deferred until the executor knows project mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from src.domain.model.project_schema.commands import (
    ProjectSchemaScope,
    canonical_snapshot,
    require_legacy_representable,
)
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.validation import MAX_REVISION, ProjectSchemaError, uuid


class SchemaHttpOperation(StrEnum):
    CREATE_ENTITY = "create_entity_type"
    UPDATE_ENTITY = "update_entity_type"
    DELETE_ENTITY = "delete_entity_type"
    CREATE_EDGE = "create_edge_type"
    UPDATE_EDGE = "update_edge_type"
    DELETE_EDGE = "delete_edge_type"
    CREATE_MAP = "create_edge_map"
    DELETE_MAP = "delete_edge_map"


def _json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


@dataclass(frozen=True, kw_only=True)
class SchemaHttpMutation:
    scope: ProjectSchemaScope
    operation: SchemaHttpOperation
    target_id: str | None
    fields_json: str
    expected_revision: str | None
    change_id: str | None

    @classmethod
    def from_fields(
        cls,
        *,
        scope: ProjectSchemaScope,
        operation: SchemaHttpOperation,
        target_id: str | None,
        fields: dict[str, Any],
        expected_revision: str | None,
        change_id: str | None,
    ) -> SchemaHttpMutation:
        try:
            fields_json = _json(fields)
            _ = fields_json.encode("utf-8")
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ProjectSchemaError("project_schema_mutation_invalid") from error
        return cls(
            scope=scope,
            operation=operation,
            target_id=target_id,
            fields_json=fields_json,
            expected_revision=expected_revision,
            change_id=change_id,
        )

    @property
    def has_preconditions(self) -> bool:
        return self.expected_revision is not None or self.change_id is not None

    def request_json(self) -> str:
        if self.expected_revision is None or self.change_id is None:
            raise ProjectSchemaError("project_schema_command_required")
        raw = self.expected_revision
        if (
            not raw
            or not raw.isascii()
            or not raw.isdecimal()
            or raw.startswith("0")
            or len(raw) > 10
            or not 1 <= int(raw) <= MAX_REVISION
        ):
            raise ProjectSchemaError("project_schema_precondition_invalid")
        try:
            uuid(self.change_id)
        except ProjectSchemaError as error:
            raise ProjectSchemaError("project_schema_precondition_invalid") from error
        return _json(
            {
                "command": "http_mutation",
                "operation": self.operation.value,
                "tenant_id": self.scope.tenant_id,
                "project_id": self.scope.project_id,
                "actor_id": self.scope.actor_id,
                "target_id": self.target_id,
                "fields": json.loads(self.fields_json),
                "expected_revision": int(raw),
                "change_id": self.change_id,
            }
        )


@dataclass(frozen=True, kw_only=True)
class SchemaHttpReceipt:
    """Exact accepted response envelope; it is returned only after commit."""

    response_json: str

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.response_json)
        return value


def _collection(operation: SchemaHttpOperation) -> tuple[str, str]:
    if operation in {
        SchemaHttpOperation.CREATE_ENTITY,
        SchemaHttpOperation.UPDATE_ENTITY,
        SchemaHttpOperation.DELETE_ENTITY,
    }:
        return "entity_types", "entity_type"
    if operation in {
        SchemaHttpOperation.CREATE_EDGE,
        SchemaHttpOperation.UPDATE_EDGE,
        SchemaHttpOperation.DELETE_EDGE,
    }:
        return "edge_types", "edge_type"
    return "mappings", "mapping"


def _fields(
    request: dict[str, Any], *, create: bool, mapping: bool, delete: bool
) -> dict[str, Any]:
    raw_fields = request["fields"]
    allowed: set[str] = (
        set()
        if delete
        else (
            {"source_type", "target_type", "edge_type", "status", "source"}
            if mapping
            else (
                {"name", "description", "schema", "status", "source"}
                if create
                else {"description", "schema"}
            )
        )
    )
    required: set[str] = (
        ({"source_type", "target_type", "edge_type"} if mapping else {"name"}) if create else set()
    )
    if type(raw_fields) is not dict:
        raise ProjectSchemaError("project_schema_mutation_invalid")
    fields = cast(dict[str, Any], raw_fields)
    if not set(fields) <= allowed or not required <= set(fields):
        raise ProjectSchemaError("project_schema_mutation_invalid")
    return fields


def _mapping_ids(value: dict[str, Any], fields: dict[str, Any]) -> dict[str, str]:
    references: dict[str, str] = {}
    for name, collection, key in (
        ("source_type", "entity_types", "source_type_id"),
        ("target_type", "entity_types", "target_type_id"),
        ("edge_type", "edge_types", "edge_type_id"),
    ):
        matches = [item["id"] for item in value[collection] if item["name"] == fields[name]]
        if len(matches) != 1:
            raise ProjectSchemaError("project_schema_mapping_reference_not_found")
        references[key] = matches[0]
    if any(
        all(item[key] == member_id for key, member_id in references.items())
        for item in value["mappings"]
    ):
        raise ProjectSchemaError("project_schema_mapping_conflict")
    return references


def _created_member(
    value: dict[str, Any],
    fields: dict[str, Any],
    collection: str,
    kind: str,
    created_id: str,
) -> dict[str, Any]:
    member: dict[str, Any] = {
        "id": created_id,
        "status": fields.get("status", "ENABLED"),
        "source": fields.get("source", "user"),
    }
    if collection == "mappings":
        member.update(_mapping_ids(value, fields))
    else:
        if any(item["name"] == fields["name"] for item in value[collection]):
            raise ProjectSchemaError(f"project_schema_{kind}_conflict")
        member.update(
            name=fields["name"],
            description=fields["description"] if fields.get("description") is not None else "",
            schema=fields.get("schema", {}),
        )
    return member


def _target_uuid(value: object) -> None:
    try:
        uuid(value)
    except ProjectSchemaError as error:
        raise ProjectSchemaError("project_schema_mutation_invalid") from error


def materialize_http_mutation(
    previous: ProjectSchemaDocument,
    request_json: str,
    *,
    created_id: str | None = None,
) -> ProjectSchemaDocument:
    request = json.loads(request_json)
    value = previous.to_dict()
    if (request["tenant_id"], request["project_id"]) != (value["tenant_id"], value["project_id"]):
        raise ProjectSchemaError("project_schema_scope_mismatch")
    if request["expected_revision"] != value["revision"] or value["revision"] >= MAX_REVISION:
        raise ProjectSchemaError("project_schema_revision_conflict")
    if value["deleted"]:
        raise ProjectSchemaError("project_schema_deleted")
    operation = SchemaHttpOperation(request["operation"])
    collection, kind = _collection(operation)
    create = operation in {
        SchemaHttpOperation.CREATE_ENTITY,
        SchemaHttpOperation.CREATE_EDGE,
        SchemaHttpOperation.CREATE_MAP,
    }
    delete = operation in {
        SchemaHttpOperation.DELETE_ENTITY,
        SchemaHttpOperation.DELETE_EDGE,
        SchemaHttpOperation.DELETE_MAP,
    }
    fields = _fields(request, create=create, mapping=collection == "mappings", delete=delete)
    target = request["target_id"]
    if create:
        if target is not None or created_id is None:
            raise ProjectSchemaError("project_schema_mutation_invalid")
        uuid(created_id)
        member = _created_member(value, fields, collection, kind, created_id)
        value[collection].append(member)
    else:
        _target_uuid(target)
        if created_id is not None:
            raise ProjectSchemaError("project_schema_mutation_invalid")
        existing = next((item for item in value[collection] if item["id"] == target), None)
        if existing is None:
            raise ProjectSchemaError(f"project_schema_{kind}_not_found")
        if delete:
            if collection != "mappings" and any(
                target in (item["source_type_id"], item["target_type_id"], item["edge_type_id"])
                for item in value["mappings"]
            ):
                raise ProjectSchemaError("project_schema_type_referenced")
            value[collection] = [item for item in value[collection] if item["id"] != target]
            value["tombstones"].append(
                {"id": target, "kind": kind, "deleted_revision": value["revision"] + 1}
            )
        else:
            existing.update({key: item for key, item in fields.items() if item is not None})
    value["revision"] += 1
    # The stored predecessor was validated before this client-controlled patch.
    # Translate only candidate shape failures; storage corruption remains an error.
    try:
        document = canonical_snapshot(ProjectSchemaDocument.from_json(_json(value)))
        require_legacy_representable(document)
    except ProjectSchemaError as error:
        raise ProjectSchemaError("project_schema_mutation_invalid") from error
    document.validate_successor(previous=previous, expected_revision=request["expected_revision"])
    return document
