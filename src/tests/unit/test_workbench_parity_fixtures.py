from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "shared" / "fixtures"
_FIXTURE_NAMES = (
    "hitl-authority.v1.json",
    "workspace-surface.v1.json",
    "artifact-content.v1.json",
    "sandbox-runtime.v1.json",
    "automation-run-receipt.v1.json",
)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURE_ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name", _FIXTURE_NAMES)
def test_workbench_authority_fixture_is_cross_client_canonical(fixture_name: str) -> None:
    fixture = _load_fixture(fixture_name)

    assert fixture["schema_version"] == "1.0.0"
    assert fixture["web_expected_view_model"] == fixture["desktop_expected_view_model"]


@pytest.mark.unit
def test_hitl_fixture_never_replays_response_values() -> None:
    fixture = _load_fixture("hitl-authority.v1.json")
    request = fixture["input"]["request"]
    expected = fixture["web_expected_view_model"]

    assert request["status"] in {"answered", "expired"}
    assert expected["editable"] is False
    assert expected["authority_revision"] >= 1
    assert {"response_data", "response_data_encrypted", "env_value"}.isdisjoint(expected)


@pytest.mark.unit
def test_workspace_fixture_requires_canonical_refetch_after_cursor_gap() -> None:
    fixture = _load_fixture("workspace-surface.v1.json")
    surface = fixture["input"]["surface"]
    expected = fixture["web_expected_view_model"]

    assert surface["status"] == "stale"
    assert expected["requires_canonical_refetch"] is True
    assert expected["revision"] == surface["revision"]
    assert expected["cursor"] == surface["cursor"]


@pytest.mark.unit
def test_artifact_fixture_is_revision_and_idempotency_guarded() -> None:
    fixture = _load_fixture("artifact-content.v1.json")
    artifact = fixture["input"]["artifact"]
    expected = fixture["web_expected_view_model"]

    assert artifact["content_hash"].startswith("sha256:")
    assert len(artifact["content_hash"]) == len("sha256:") + 64
    assert artifact["expected_revision"] == artifact["revision"]
    assert expected["conflict_safe"] is True
    assert expected["has_idempotency_key"] is True
    assert "idempotency_key" not in expected


@pytest.mark.unit
def test_sandbox_fixture_fails_closed_per_capability() -> None:
    fixture = _load_fixture("sandbox-runtime.v1.json")
    runtime = fixture["input"]["runtime"]
    features = fixture["web_expected_view_model"]["features"]

    for name in ("terminal_interactive", "terminal_resume", "files", "kasm_vnc"):
        capability = runtime[name]
        expected_available = capability["availability"] in {"available", "degraded"}
        assert features[name]["available"] is expected_available
        if not expected_available:
            assert capability["reason_code"]


@pytest.mark.unit
def test_automation_fixture_is_v2_replay_safe_without_exposing_key() -> None:
    fixture = _load_fixture("automation-run-receipt.v1.json")
    receipt = fixture["input"]["receipt"]
    expected = fixture["web_expected_view_model"]

    assert receipt["contract_version"] == 2
    assert receipt["idempotency_key"]
    assert expected["replay_safe"] is True
    assert expected["duplicate"] is True
    assert "idempotency_key" not in expected
