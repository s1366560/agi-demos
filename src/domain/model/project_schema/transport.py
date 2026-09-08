"""Closed cloud commands and bounded receipt transport; no synchronization policy."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, cast

from src.domain.model.project_schema.commands import ReplaceProjectSchema
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.validation import (
    MAX_REVISION,
    ProjectSchemaError,
    closed,
    revision,
    uuid,
)

MAX_TRANSPORT_BYTES = 2 * 1024 * 1024
MAX_HISTORY_ITEMS = 100


class _NegativeZero(int):
    """Preserve the -0 token for strict envelope integers until document parsing."""


def _integer_token(value: str) -> int:
    return _NegativeZero(0) if value == "-0" else int(value)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ValueError("nonfinite JSON constant")


def _portable(value: object, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("JSON depth exceeded")
    if isinstance(value, dict):
        for key, child in cast(dict[str, object], value).items():
            _ = key.encode("utf-8")
            _portable(child, depth + 1)
    elif isinstance(value, list):
        for child in cast(list[object], value):
            _portable(child, depth + 1)
    elif isinstance(value, str):
        _ = value.encode("utf-8")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite JSON number")


def parse_transport(raw: bytes) -> dict[str, Any]:
    try:
        if len(raw) > MAX_TRANSPORT_BYTES:
            raise ValueError("transport size exceeded")
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_constant=_constant,
            parse_int=_integer_token,
        )
        if not isinstance(value, dict):
            raise ValueError("expected object")
        result = cast(dict[str, Any], value)
        _portable(result)
        return result
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise ProjectSchemaError("project_schema_transport_invalid") from error


def parse_replace(value: dict[str, Any]) -> ReplaceProjectSchema:
    closed(value, {"document", "expected_revision", "change_id"})
    return ReplaceProjectSchema(
        document=ProjectSchemaDocument.from_json(
            json.dumps(value["document"], ensure_ascii=False, separators=(",", ":"))
        ),
        expected_revision=value["expected_revision"],
        change_id=value["change_id"],
    )


@dataclass(frozen=True, kw_only=True)
class SchemaReceiptQuery:
    schema_id: str
    change_id: str

    def __post_init__(self) -> None:
        uuid(self.schema_id)
        uuid(self.change_id)

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> SchemaReceiptQuery:
        closed(value, {"schema_id", "change_id"})
        return cls(**value)


@dataclass(frozen=True, kw_only=True)
class SchemaHistoryQuery:
    schema_id: str
    after_revision: int
    limit: int

    def __post_init__(self) -> None:
        uuid(self.schema_id)
        if type(self.after_revision) is not int or not 0 <= self.after_revision <= MAX_REVISION:
            raise ProjectSchemaError("project_schema_cursor_invalid")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_HISTORY_ITEMS:
            raise ProjectSchemaError("project_schema_limit_invalid")

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> SchemaHistoryQuery:
        closed(value, {"schema_id", "after_revision", "limit"})
        return cls(**value)


def validate_stored_receipt(
    raw: str, *, tenant_id: str, project_id: str, schema_id: str, change_id: str
) -> dict[str, Any]:
    """Corrupt persistence is an internal failure, never a client's invalid request."""
    try:
        value = parse_transport(raw.encode("utf-8"))
        closed(value, {"schema_id", "revision", "sequence", "change_id", "document"})
        revision(value["revision"])
        revision(value["sequence"])
        uuid(value["change_id"])
        document = ProjectSchemaDocument.from_json(
            json.dumps(value["document"], ensure_ascii=False, separators=(",", ":"))
        )
        snapshot = document.to_dict()
        if (
            value["schema_id"] != schema_id
            or value["change_id"] != change_id
            or value["revision"] != value["sequence"]
            or snapshot["revision"] != value["revision"]
            or (snapshot["tenant_id"], snapshot["project_id"], snapshot["schema_id"])
            != (tenant_id, project_id, schema_id)
        ):
            raise ValueError("receipt identity mismatch")
        return value
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        raise RuntimeError("corrupt stored schema receipt") from error


def history_page_json(
    *,
    schema_id: str,
    after_revision: int,
    upper_revision: int,
    receipts: list[str],
    max_bytes: int = MAX_TRANSPORT_BYTES,
) -> str:
    """Reserve the whole envelope and keep every accepted receipt's original JSON bytes."""

    def render(items: list[str], cursor: int, more: bool) -> str:
        prefix = json.dumps(
            {
                "schema_id": schema_id,
                "upper_revision": upper_revision,
                "next_after_revision": cursor,
                "has_more": more,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return prefix[:-1] + ',"receipts":[' + ",".join(items) + "]}"

    accepted: list[str] = []
    for raw in receipts:
        if len(render([*accepted, raw], upper_revision, False).encode("utf-8")) > max_bytes:
            break
        accepted.append(raw)
    if receipts and not accepted:
        raise RuntimeError("schema history receipt exceeds transport budget")
    cursor = after_revision + len(accepted)
    result = render(accepted, cursor, cursor < upper_revision)
    if len(result.encode("utf-8")) > max_bytes:
        raise RuntimeError("schema history envelope exceeds transport budget")
    return result
