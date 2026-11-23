"""Sandbox image staleness is reported, and live containers are not rebuilt."""

from __future__ import annotations

import pytest

from plugins.business.environments.backend.sandbox.sandbox_image_lifecycle import (
    IMAGE_DIGEST_SCOPE,
    SOURCE_DIGEST_LABEL,
    automatic_rebuild_allowed,
    container_marks_active_run,
    fingerprint_sources,
    image_status,
    plan_explicit_migration,
)

pytestmark = pytest.mark.unit


def test_fingerprint_changes_when_source_bytes_change() -> None:
    first = fingerprint_sources({"Dockerfile": b"FROM python:3.12\n"})
    second = fingerprint_sources({"Dockerfile": b"FROM python:3.13\n"})
    same = fingerprint_sources({"Dockerfile": b"FROM python:3.12\n"})
    assert first == same
    assert first != second


def test_missing_digest_is_unknown_rather_than_fresh() -> None:
    status = image_status({}, None)
    assert status.stale is False
    assert status.reason == "unknown"


def test_image_digest_does_not_attest_the_loaded_tool_server() -> None:
    assert "container image source bytes" in IMAGE_DIGEST_SCOPE
    assert "tool server process" in IMAGE_DIGEST_SCOPE
    assert "/opt/sandbox-mcp-venv" in IMAGE_DIGEST_SCOPE
    assert "mtime" in IMAGE_DIGEST_SCOPE
    assert "outside the container" not in IMAGE_DIGEST_SCOPE


def test_different_recorded_digest_is_stale() -> None:
    status = image_status({SOURCE_DIGEST_LABEL: "aaa"}, "bbb")
    assert status.stale is True
    assert status.reason == "stale"
    assert status.recorded_digest == "aaa"
    assert status.current_digest == "bbb"


def test_production_startup_and_run_lifecycle_call_the_guard() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[5]
    execution = (root / "src/infrastructure/agent/actor/execution.py").read_text(encoding="utf-8")
    main = (root / "src/infrastructure/adapters/primary/web/main.py").read_text(encoding="utf-8")
    adapter = (
        root / "src/infrastructure/adapters/secondary/sandbox/mcp_sandbox_adapter.py"
    ).read_text(encoding="utf-8")
    assert "note_project_run" in execution
    assert "_mark_root_run_authority_running" in execution
    assert "_settle_root_run_authority" in execution
    assert "_run_state_session_factory = async_session_factory" in main
    assert "project_run_state" in adapter


def test_run_lifecycle_mark_is_visible_without_a_container_label() -> None:
    from plugins.business.environments.backend.sandbox.sandbox_image_lifecycle import (
        note_project_run,
        project_run_mark,
    )

    note_project_run("project-live", active=True)
    assert project_run_mark("project-live") is True
    note_project_run("project-live", active=False)
    assert project_run_mark("project-live") is False


def test_automatic_rebuild_refuses_an_active_or_unknown_run() -> None:
    assert automatic_rebuild_allowed(run_state="idle") is True
    assert automatic_rebuild_allowed(run_state="active") is False
    assert automatic_rebuild_allowed(run_state="unknown") is False
    assert container_marks_active_run({"org.memstack.sandbox.active_run": "true"}) is True


def test_explicit_migration_keeps_workspace_and_refuses_a_live_run() -> None:
    refused = plan_explicit_migration(
        sandbox_id="sb-1",
        project_id="project-1",
        workspace_path="/data/project-1",
        permission_mode="read_only",
        target_digest="abc",
        active_run=True,
        human_requested=True,
    )
    assert refused.allowed is False
    assert refused.refusal == "active_run"
    assert refused.workspace_path == "/data/project-1"
    assert refused.permission_mode == "read_only"
    assert refused.recreate_live_container is False

    silent = plan_explicit_migration(
        sandbox_id="sb-1",
        project_id="project-1",
        workspace_path="/data/project-1",
        permission_mode="read_only",
        target_digest="abc",
        active_run=False,
        human_requested=False,
    )
    assert silent.allowed is False
    assert silent.refusal == "human_request_required"

    planned = plan_explicit_migration(
        sandbox_id="sb-1",
        project_id="project-1",
        workspace_path="/data/project-1",
        permission_mode="read_only",
        target_digest="abc",
        active_run=False,
        human_requested=True,
    )
    assert planned.allowed is True
    assert planned.preserve_workspace is True
    assert planned.permission_mode == "read_only"
    assert planned.recreate_live_container is False
    assert planned.upgrade_performed is False
    assert planned.stage == "plan_only"
