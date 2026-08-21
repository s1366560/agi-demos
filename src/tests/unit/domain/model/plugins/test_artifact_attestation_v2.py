"""Canonical artifact-byte contract tests for plugin protocol v2."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from src.domain.model.plugins.artifact_attestation_v2 import (
    artifact_digest_v2,
    python_artifact_path_v2,
    python_artifact_source_v2,
)


@pytest.mark.unit
def test_python_artifact_contract_uses_raw_entrypoint_module_bytes() -> None:
    entrypoint = "src.infrastructure.plugins.v2.agent_loop:_apply_builtin_agent_loop_v2"

    assert python_artifact_path_v2(entrypoint) == PurePosixPath(
        "src/infrastructure/plugins/v2/agent_loop.py"
    )
    assert python_artifact_source_v2(entrypoint) == (
        "repo+python://src/infrastructure/plugins/v2/agent_loop.py"
    )
    assert artifact_digest_v2(b"line-one\r\nline-two\n") == (
        "sha256:0cb361e714992cdb7f88c2556b644cda99fc254b499d427d097c1f003ea77c07"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "entrypoint",
    [
        "",
        "src.example.plugin",
        "src.example.plugin:",
        ":apply",
        "src.example..plugin:apply",
        "src.example.plugin:apply.member",
        "../src.example.plugin:apply",
    ],
)
def test_python_artifact_contract_rejects_noncanonical_entrypoints(entrypoint: str) -> None:
    with pytest.raises(ValueError, match="Python plugin entrypoint"):
        python_artifact_path_v2(entrypoint)
