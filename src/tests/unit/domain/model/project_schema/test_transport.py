"""Strict cloud envelopes and byte-exact complete history pages."""

import json

import pytest

from src.domain.model.project_schema.transport import (
    MAX_TRANSPORT_BYTES,
    SchemaHistoryQuery,
    SchemaReceiptQuery,
    history_page_json,
    parse_transport,
    validate_stored_receipt,
)
from src.domain.model.project_schema.validation import ProjectSchemaError

SCHEMA = "00000000-0000-4000-8000-000000000001"
CHANGE = "00000000-0000-4000-8000-000000000002"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":"\\ud800"}',
        b"[]",
        b"{} trailing",
        b"\xff",
        b" " * (MAX_TRANSPORT_BYTES + 1),
    ],
)
def test_raw_boundary_rejects_before_dispatch(raw):
    with pytest.raises(ProjectSchemaError, match="project_schema_transport_invalid"):
        parse_transport(raw)


def test_closed_queries_and_strict_integer_cursor():
    assert (
        SchemaReceiptQuery.from_value({"schema_id": SCHEMA, "change_id": CHANGE}).change_id
        == CHANGE
    )
    for value in [True, -1, 2**31, 1.0]:
        with pytest.raises(ProjectSchemaError):
            SchemaHistoryQuery.from_value(
                {"schema_id": SCHEMA, "after_revision": value, "limit": 1}
            )
    for value in [0, 101, True, 1.0]:
        with pytest.raises(ProjectSchemaError):
            SchemaHistoryQuery.from_value(
                {"schema_id": SCHEMA, "after_revision": 0, "limit": value}
            )
    with pytest.raises(ProjectSchemaError):
        SchemaReceiptQuery.from_value(
            {"schema_id": SCHEMA, "change_id": CHANGE, "actor_id": "other"}
        )


def test_entire_page_budget_reserves_cursor_digit_and_false_growth():
    receipts = [json.dumps({"revision": n}) for n in (9, 10)]
    full = history_page_json(
        schema_id=SCHEMA, after_revision=8, upper_revision=10, receipts=receipts
    )
    page = json.loads(full)
    assert page["next_after_revision"] == 10 and page["has_more"] is False
    bounded = history_page_json(
        schema_id=SCHEMA,
        after_revision=8,
        upper_revision=10,
        receipts=receipts,
        max_bytes=len(full.encode()) - 1,
    )
    value = json.loads(bounded)
    assert len(bounded.encode()) < len(full.encode())
    assert value["next_after_revision"] == 9 and value["has_more"] is True
    assert value["receipts"] == [{"revision": 9}]


def test_malformed_stored_receipt_is_internal_error():
    with pytest.raises(RuntimeError, match="corrupt stored schema receipt"):
        validate_stored_receipt(
            '{"revision":true}', tenant_id="t", project_id="p", schema_id=SCHEMA, change_id=CHANGE
        )


def test_published_cloud_rpc_fixtures_match_runtime_and_json_schema():
    from pathlib import Path

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from src.domain.model.project_schema.transport import parse_replace
    from src.domain.model.project_schema.validation import closed

    root = Path(__file__).resolve().parents[6] / "contracts/project-schema-v1"
    schema = json.loads((root / "cloud-rpc.schema.json").read_text())
    document = json.loads((root / "document.schema.json").read_text())
    registry = Registry().with_resources(
        [(value["$id"], Resource.from_contents(value)) for value in [schema, document]]
    )
    Draft202012Validator.check_schema(schema)
    parsers = {
        "readRequest": lambda value: closed(value, set()),
        "replaceRequest": parse_replace,
        "receiptRequest": SchemaReceiptQuery.from_value,
        "historyRequest": SchemaHistoryQuery.from_value,
    }
    for case in json.loads((root / "cloud-rpc-fixtures.json").read_text()):
        validator = Draft202012Validator(
            {"$ref": schema["$id"] + "#/$defs/" + case["definition"]}, registry=registry
        )
        assert validator.is_valid(case["value"]) is case["valid"], case["name"]
        try:
            parsers[case["definition"]](case["value"])
            accepted = True
        except ProjectSchemaError:
            accepted = False
        assert accepted is case["valid"], case["name"]


def test_negative_zero_token_is_strict_for_cursor_but_document_values_stay_opaque():
    from pathlib import Path

    from src.domain.model.project_schema.transport import parse_replace

    raw = ('{"schema_id":"' + SCHEMA + '","after_revision":-0,"limit":1}').encode()
    with pytest.raises(ProjectSchemaError, match="project_schema_cursor_invalid"):
        SchemaHistoryQuery.from_value(parse_transport(raw))
    root = Path(__file__).resolve().parents[6] / "contracts/project-schema-v1"
    document = json.loads((root / "fixtures.json").read_text())[0]["document"]
    document["revision"] = 2
    document["entity_types"][0]["schema"]["zero"] = 0
    envelope = {"document": document, "expected_revision": 1, "change_id": CHANGE}
    raw = json.dumps(envelope).replace('"zero": 0', '"zero": -0').encode()
    assert parse_replace(parse_transport(raw)).document.to_dict() == document
