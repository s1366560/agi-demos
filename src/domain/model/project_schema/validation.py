"""Structural constraints only; names and JSON-schema meaning are opaque."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

MAX_DOCUMENT_BYTES = 1_048_576
MAX_REVISION = 2**31 - 1
MAX_MEMBERS = 1_024
MAX_SCHEMA_NODES = 1_024
MAX_SCHEMA_TEXT_BYTES = 16_384
MAX_SCHEMA_DEPTH = 16
MAX_SAFE_NUMBER = 2**53 - 1
KINDS = {"entity_types": "entity_type", "edge_types": "edge_type", "mappings": "mapping"}


class ProjectSchemaError(ValueError):
    """A stable protocol failure, never a semantic judgment."""

    def __init__(self, code: str = "project_schema_document_invalid") -> None:
        self.code = code
        super().__init__(code)


def require(condition: bool) -> None:
    if not condition:
        raise ProjectSchemaError


def closed(value: object, keys: set[str]) -> None:
    require(type(value) is dict and set(value) == keys)


def text(value: object, maximum: int, *, nonempty: bool = True) -> None:
    require(type(value) is str)
    assert isinstance(value, str)
    require(
        (bool(value) or not nonempty)
        and len(value.encode("utf-8")) <= maximum
        and "\0" not in value
    )


def identifier(value: object) -> None:
    text(value, 512)
    assert isinstance(value, str)
    require(value == value.strip(" \t\r\n"))


def uuid(value: object) -> None:
    require(type(value) is str)
    assert isinstance(value, str)
    try:
        parsed = UUID(value)
        require(str(parsed) == value and parsed.int != 0)
    except (ValueError, AttributeError) as error:
        raise ProjectSchemaError from error


def revision(value: object) -> None:
    require(type(value) is int and 1 <= value <= MAX_REVISION)


def schema_object(value: object) -> None:
    require(type(value) is dict)
    nodes = 0
    text_bytes = 0

    def visit(item: object, depth: int) -> None:
        nonlocal nodes, text_bytes
        nodes += 1
        require(nodes <= MAX_SCHEMA_NODES and depth <= MAX_SCHEMA_DEPTH)
        if type(item) is dict:
            for key, child in item.items():
                require("\0" not in key)
                text_bytes += len(key.encode("utf-8"))
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            require("\0" not in item)
            text_bytes += len(item.encode("utf-8"))
        elif type(item) in {int, float}:
            assert isinstance(item, (int, float))
            require(math.isfinite(item) and abs(item) <= MAX_SAFE_NUMBER)
        else:
            require(item is None or type(item) is bool)
        require(text_bytes <= MAX_SCHEMA_TEXT_BYTES)

    visit(value, 0)


def document_weight(value: object) -> int:
    """Serialization upper bound, reserving 32 bytes per number on both runtimes."""
    if type(value) is dict:
        return (
            2
            + max(0, len(value) - 1)
            + sum(document_weight(key) + 1 + document_weight(child) for key, child in value.items())
        )
    if type(value) is list:
        return 2 + max(0, len(value) - 1) + sum(document_weight(child) for child in value)
    if type(value) is str:
        return 2 + sum(
            2 if byte in {8, 9, 10, 12, 13, 34, 92} else 6 if byte < 32 else 1
            for byte in value.encode("utf-8")
        )
    if type(value) in {int, float}:
        return 32
    return 5 if value is False else 4


def validate_document(value: dict[str, Any]) -> None:
    closed(
        value,
        {
            "format_version",
            "tenant_id",
            "project_id",
            "schema_id",
            "revision",
            "deleted",
            "entity_types",
            "edge_types",
            "mappings",
            "tombstones",
        },
    )
    require(type(value["format_version"]) is int and value["format_version"] == 1)
    identifier(value["tenant_id"])
    identifier(value["project_id"])
    uuid(value["schema_id"])
    revision(value["revision"])
    require(type(value["deleted"]) is bool)
    for key in (*KINDS, "tombstones"):
        require(type(value[key]) is list)
    require(sum(len(value[key]) for key in (*KINDS, "tombstones")) <= MAX_MEMBERS)
    require(not value["deleted"] or all(not value[key] for key in KINDS))
    used = {value["schema_id"]}
    for key in KINDS:
        for member in value[key]:
            common = {"id", "status", "source"}
            fields = (
                {"source_type_id", "target_type_id", "edge_type_id"}
                if key == "mappings"
                else {"name", "description", "schema"}
            )
            closed(member, common | fields)
            uuid(member["id"])
            require(member["id"] not in used)
            used.add(member["id"])
            require(type(member["status"]) is str and member["status"] in {"ENABLED", "DISABLED"})
            text(member["source"], 128)
            if key != "mappings":
                text(member["name"], 512)
                text(member["description"], 4_096, nonempty=False)
                schema_object(member["schema"])
    entities = {member["id"] for member in value["entity_types"]}
    edges = {member["id"] for member in value["edge_types"]}
    for member in value["mappings"]:
        for key, allowed in (
            ("source_type_id", entities),
            ("target_type_id", entities),
            ("edge_type_id", edges),
        ):
            uuid(member[key])
            require(member[key] in allowed)
    for tombstone in value["tombstones"]:
        closed(tombstone, {"id", "kind", "deleted_revision"})
        uuid(tombstone["id"])
        require(tombstone["id"] not in used)
        used.add(tombstone["id"])
        require(type(tombstone["kind"]) is str and tombstone["kind"] in KINDS.values())
        revision(tombstone["deleted_revision"])
        require(tombstone["deleted_revision"] <= value["revision"])
    require(document_weight(value) <= MAX_DOCUMENT_BYTES)
