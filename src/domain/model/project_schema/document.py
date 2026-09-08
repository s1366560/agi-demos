"""Immutable, validated schema snapshots and adjacent-revision checks.

These checks do not authorize a caller, persist a CAS, or infer a semantic merge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

from src.domain.model.project_schema.validation import (
    KINDS,
    MAX_DOCUMENT_BYTES,
    MAX_REVISION,
    ProjectSchemaError,
    validate_document,
)
from src.domain.shared_kernel import ValueObject


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectSchemaError
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ProjectSchemaError


@dataclass(frozen=True, kw_only=True)
class ProjectSchemaDocument(ValueObject):
    """Validated snapshot; nested JSON is stored immutably and copied on read."""

    _json: str = field(repr=False)

    def __post_init__(self) -> None:
        try:
            if type(self._json) is not str or len(self._json.encode("utf-8")) > MAX_DOCUMENT_BYTES:
                raise ProjectSchemaError
            value = json.loads(
                self._json, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
            validate_document(value)
            canonical = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            object.__setattr__(self, "_json", canonical)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
            raise ProjectSchemaError from error

    @classmethod
    def from_json(cls, raw: str) -> ProjectSchemaDocument:
        return cls(_json=raw)

    def to_json(self) -> str:
        return self._json

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._json))

    def validate_successor(
        self, *, previous: ProjectSchemaDocument | None, expected_revision: int
    ) -> None:
        """Validate an adjacent snapshot; the future repository must enforce CAS atomically."""
        current = self.to_dict()
        before = previous.to_dict() if previous is not None else None
        base_revision = before["revision"] if before is not None else 0
        if (
            type(expected_revision) is not int
            or expected_revision != base_revision
            or base_revision >= MAX_REVISION
            or current["revision"] != base_revision + 1
        ):
            raise ProjectSchemaError("project_schema_revision_conflict")
        if before is None:
            if current["tombstones"] or current["deleted"]:
                raise ProjectSchemaError("project_schema_transition_invalid")
            return
        if before["deleted"] or any(
            before[key] != current[key] for key in ("tenant_id", "project_id", "schema_id")
        ):
            raise ProjectSchemaError("project_schema_transition_invalid")
        old_live = {member["id"]: kind for key, kind in KINDS.items() for member in before[key]}
        new_live = {member["id"]: kind for key, kind in KINDS.items() for member in current[key]}
        old_dead = {item["id"]: item for item in before["tombstones"]}
        new_dead = {item["id"]: item for item in current["tombstones"]}
        valid = all(new_dead.get(key) == item for key, item in old_dead.items())
        valid = valid and all(
            key not in old_dead and (key not in old_live or old_live[key] == kind)
            for key, kind in new_live.items()
        )
        for key, kind in old_live.items():
            if key not in new_live:
                valid = valid and new_dead.get(key) == {
                    "id": key,
                    "kind": kind,
                    "deleted_revision": current["revision"],
                }
        valid = valid and all(
            key in old_dead
            or (
                key in old_live
                and item["kind"] == old_live[key]
                and item["deleted_revision"] == current["revision"]
            )
            for key, item in new_dead.items()
        )
        if not valid:
            raise ProjectSchemaError("project_schema_transition_invalid")
