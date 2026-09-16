"""Session-scope baseline anchoring for the run changes authority endpoint."""

from typing import Any

import pytest

from src.infrastructure.adapters.primary.web.routers.agent.run_authority_common import (
    SessionBaseline,
    resolve_session_baseline,
)
from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel

pytestmark = pytest.mark.unit


def _run(run_id: str, environment: dict[str, Any] | None = None) -> AgentRunAuthorityModel:
    snapshot: dict[str, Any] = {"environment": environment} if environment is not None else {}
    return AgentRunAuthorityModel(
        id=run_id,
        tenant_id="tenant-1",
        project_id="project-1",
        conversation_id="conversation-1",
        run_kind="chat",
        idempotency_key=f"key-{run_id}",
        message_id=f"message-{run_id}",
        request_message="Run",
        status="running",
        revision=1,
        permission_profile="read_only",
        authorization_snapshot=snapshot,
    )


def _environment(**overrides: Any) -> dict[str, Any]:
    environment: dict[str, Any] = {
        "id": "environment-1",
        "kind": "sandbox",
        "label": "Workspace",
        "workspace_path": "/workspace",
        "repository_root": "/repo",
        "branch": "main",
        "base_commit": "base-1",
        "created_at": "2026-01-01T00:00:00Z",
    }
    environment.update(overrides)
    return environment


def test_first_workspace_run_anchors_the_session_baseline() -> None:
    runs = [
        _run("run-without-environment"),
        _run("run-first-workspace", _environment()),
        _run("run-later", _environment(id="environment-2", base_commit="base-2")),
    ]

    baseline = resolve_session_baseline(runs)

    assert isinstance(baseline, SessionBaseline)
    assert baseline.base_revision == "base-1"
    assert baseline.environment_id == "environment-1"
    assert baseline.repository_root == "/repo"
    assert baseline.workspace_path == "/workspace"
    assert baseline.branch == "main"


def test_later_runs_with_new_base_commit_do_not_move_the_anchor() -> None:
    runs = [
        _run("run-first-workspace", _environment()),
        _run("run-later", _environment(id="environment-2", base_commit="base-2")),
    ]

    baseline = resolve_session_baseline(runs)

    assert isinstance(baseline, SessionBaseline)
    assert baseline.base_revision == "base-1"


def test_missing_environment_on_every_run_fails_closed() -> None:
    assert resolve_session_baseline([_run("run-a"), _run("run-b")]) == (
        "session_baseline_unavailable"
    )
    assert resolve_session_baseline([]) == "session_baseline_unavailable"


def test_first_workspace_run_without_base_commit_fails_closed() -> None:
    runs = [
        _run("run-first-workspace", _environment(base_commit=None)),
        _run("run-later", _environment(id="environment-2", base_commit="base-2")),
    ]

    assert resolve_session_baseline(runs) == "session_baseline_unavailable"


def test_blank_base_commit_fails_closed() -> None:
    runs = [_run("run-first-workspace", _environment(base_commit="  "))]

    assert resolve_session_baseline(runs) == "session_baseline_unavailable"


def test_repository_root_drift_fails_closed() -> None:
    runs = [
        _run("run-first-workspace", _environment()),
        _run("run-later", _environment(repository_root="/other-repo")),
    ]

    assert resolve_session_baseline(runs) == "session_baseline_environment_mismatch"


def test_workspace_path_drift_fails_closed() -> None:
    runs = [
        _run("run-first-workspace", _environment()),
        _run("run-later", _environment(workspace_path="/other-workspace")),
    ]

    assert resolve_session_baseline(runs) == "session_baseline_environment_mismatch"


def test_undeclared_workspace_keys_on_either_side_do_not_conflict() -> None:
    runs = [
        _run("run-first-workspace", _environment(repository_root=None)),
        _run("run-later", _environment(repository_root="/repo")),
        _run("run-last", _environment(repository_root=None)),
    ]

    baseline = resolve_session_baseline(runs)

    assert isinstance(baseline, SessionBaseline)
    assert baseline.repository_root is None


def test_runs_without_environment_are_skipped_for_drift_checks() -> None:
    runs = [
        _run("run-first-workspace", _environment()),
        _run("run-without-environment"),
        _run("run-later", _environment(id="environment-2", base_commit="base-2")),
    ]

    baseline = resolve_session_baseline(runs)

    assert isinstance(baseline, SessionBaseline)
    assert baseline.base_revision == "base-1"


def test_non_mapping_environment_is_treated_as_unrecorded() -> None:
    run = _run("run-a")
    run.authorization_snapshot = {"environment": "not-a-mapping"}

    assert resolve_session_baseline([run]) == "session_baseline_unavailable"
