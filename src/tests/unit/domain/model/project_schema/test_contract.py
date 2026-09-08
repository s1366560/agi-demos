"""Shared acceptance cases and a direct Python/Rust contract comparison."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.domain.model.project_schema.document import ProjectSchemaDocument, ProjectSchemaError
from src.tests.unit.domain.model.project_schema.cases import boundary_cases

ROOT = Path(__file__).resolve().parents[6]
CASES = json.loads((ROOT / "contracts/project-schema-v1/fixtures.json").read_text())
CASES += boundary_cases(CASES[0]["document"])
BASE_RAW = json.dumps(CASES[0]["document"], ensure_ascii=False, separators=(",", ":"))
PADDED_RAW = BASE_RAW + " " * (1_048_576 - len(BASE_RAW.encode("utf-8")))
CASES += [
    {"name": "wire_byte_limit", "document": PADDED_RAW, "valid": True},
    {"name": "wire_byte_overflow", "document": PADDED_RAW + " ", "valid": False},
    {"name": "array_root", "document": "[]", "valid": False},
    {"name": "null_root", "document": "null", "valid": False},
    {
        "name": "integer_exponent_revision",
        "document": BASE_RAW.replace('"revision":1', '"revision":1e0'),
        "valid": False,
    },
]


def evaluate(case):
    try:
        raw = case["document"]
        document = ProjectSchemaDocument.from_json(
            raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=True)
        )
        if "previous" in case:
            previous = case["previous"]
            document.validate_successor(
                previous=(
                    None
                    if previous is None
                    else ProjectSchemaDocument.from_json(json.dumps(previous, ensure_ascii=False))
                ),
                expected_revision=case["expected_revision"],
            )
        return {"valid": True, "document": document.to_dict()}
    except ProjectSchemaError as error:
        return {"valid": False, "code": error.code}


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_contract_cases(case):
    assert evaluate(case)["valid"] == case["valid"]


@pytest.mark.unit
def test_validated_document_does_not_expose_mutable_state():
    document = ProjectSchemaDocument.from_json(json.dumps(CASES[0]["document"]))
    assert ProjectSchemaDocument.from_json(document.to_json()) == document
    external = document.to_dict()
    external["entity_types"][0]["schema"]["properties"].clear()
    assert document.to_dict() == CASES[0]["document"]


@pytest.mark.unit
def test_accepted_snapshots_match_published_json_schema():
    schema = json.loads((ROOT / "contracts/project-schema-v1/document.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for case in CASES:
        result = evaluate(case)
        if result["valid"]:
            validator.validate(result["document"])


@pytest.mark.unit
def test_python_rust_differential():
    executable = os.environ.get("PROJECT_SCHEMA_RUST_PROBE")
    if not executable:
        pytest.skip("set PROJECT_SCHEMA_RUST_PROBE to the built core contract example")
    result = subprocess.run(
        [executable],
        input="".join(
            json.dumps(
                {
                    **case,
                    "document": (
                        case["document"]
                        if isinstance(case["document"], str)
                        else json.dumps(case["document"], ensure_ascii=True)
                    ),
                },
                ensure_ascii=True,
            )
            + "\n"
            for case in CASES
        ),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert [json.loads(line) for line in result.stdout.splitlines()] == [
        evaluate(case) for case in CASES
    ]
