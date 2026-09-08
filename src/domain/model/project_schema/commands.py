"""Explicit internal schema commands; no transport, activation policy or semantic merge."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.validation import (
    MAX_REVISION,
    ProjectSchemaError,
    identifier,
    uuid,
)


class ProjectSchemaAction(StrEnum):
    READ = "read"
    BOOTSTRAP = "bootstrap"
    REPLACE = "replace"


@dataclass(frozen=True, kw_only=True)
class ProjectSchemaScope:
    tenant_id: str
    project_id: str
    actor_id: str

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.project_id, self.actor_id):
            identifier(value)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, kw_only=True)
class BootstrapProjectSchema:
    schema_id: str
    change_id: str

    def __post_init__(self) -> None:
        uuid(self.schema_id)
        uuid(self.change_id)

    def request_json(self, scope: ProjectSchemaScope) -> str:
        return _json(
            {
                "command": "bootstrap",
                "tenant_id": scope.tenant_id,
                "project_id": scope.project_id,
                "actor_id": scope.actor_id,
                "schema_id": self.schema_id,
                "change_id": self.change_id,
                "expected_revision": 0,
            }
        )


@dataclass(frozen=True, kw_only=True)
class ReplaceProjectSchema:
    document: ProjectSchemaDocument
    expected_revision: int
    change_id: str

    def __post_init__(self) -> None:
        uuid(self.change_id)
        if (
            type(self.expected_revision) is not int
            or not 1 <= self.expected_revision <= MAX_REVISION
        ):
            raise ProjectSchemaError("project_schema_revision_conflict")

    def request_json(self, scope: ProjectSchemaScope) -> str:
        value = self.document.to_dict()
        if (value["tenant_id"], value["project_id"]) != (scope.tenant_id, scope.project_id):
            raise ProjectSchemaError("project_schema_scope_mismatch")
        return _json(
            {
                "command": "replace",
                "tenant_id": scope.tenant_id,
                "project_id": scope.project_id,
                "actor_id": scope.actor_id,
                "schema_id": value["schema_id"],
                "change_id": self.change_id,
                "expected_revision": self.expected_revision,
                # Preserve the validated command document, including its supplied array order.
                "document": value,
            }
        )


@dataclass(frozen=True, kw_only=True)
class ProjectSchemaReceipt:
    """Exact persisted response text; returning it implies the command transaction committed."""

    receipt_json: str

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.receipt_json)
        return value


def canonical_snapshot(document: ProjectSchemaDocument) -> ProjectSchemaDocument:
    value = document.to_dict()
    for key in ("entity_types", "edge_types", "mappings", "tombstones"):
        value[key].sort(key=lambda item: item["id"])
    return ProjectSchemaDocument.from_json(_json(value))


def require_legacy_representable(document: ProjectSchemaDocument) -> None:
    """Temporary SQL/name-keyed consumer limits, never semantic deduplication."""
    value = document.to_dict()
    for key in ("entity_types", "edge_types"):
        names = [item["name"] for item in value[key]]
        if len(names) != len(set(names)):
            raise ProjectSchemaError("project_schema_legacy_unrepresentable")
    triples = [
        (item["source_type_id"], item["target_type_id"], item["edge_type_id"])
        for item in value["mappings"]
    ]
    if len(triples) != len(set(triples)):
        raise ProjectSchemaError("project_schema_legacy_unrepresentable")
