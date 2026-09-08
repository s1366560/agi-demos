"""The runtime validator is generated from the same authoritative DTO schema."""

from __future__ import annotations

import copy
import subprocess
import sys

import pytest

from scripts.generate_native_knowledge_contract import ROOT, TYPESCRIPT, load_definitions
from scripts.native_knowledge_runtime_schema import render_processing_schema


@pytest.mark.unit
def test_runtime_schema_matches_generated_file() -> None:
    assert TYPESCRIPT.with_name("nativeKnowledgeProcessingSchemaGenerated.ts").read_text() == (
        render_processing_schema(load_definitions())
    )


@pytest.mark.unit
@pytest.mark.parametrize("keyword", ["format", "dependentRequired", "not", "unevaluatedProperties"])
def test_new_validation_keywords_cannot_silently_weaken_runtime_contract(keyword: str) -> None:
    definitions = copy.deepcopy(load_definitions())
    definitions["NativeKnowledgeScope"]["properties"]["tenant_id"][keyword] = "unsupported"
    with pytest.raises(ValueError, match="unsupported processing schema keywords"):
        render_processing_schema(definitions)


@pytest.mark.unit
def test_generator_remains_executable_as_a_standalone_script() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_native_knowledge_contract.py"), "--check"],
        cwd="/tmp",
        check=True,
        capture_output=True,
        timeout=15,
    )
