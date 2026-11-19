"""Sandbox image staleness is reported, and live containers are not rebuilt."""

from __future__ import annotations

import pytest

from src.application.services.sandbox_image_lifecycle import (
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


def test_different_recorded_digest_is_stale() -> None:
    status = image_status({SOURCE_DIGEST_LABEL: "aaa"}, "bbb")
    assert status.stale is True
    assert status.reason == "stale"
    assert status.recorded_digest == "aaa"
    assert status.current_digest == "bbb"


def test_automatic_rebuild_refuses_an_active_run() -> None:
    assert automatic_rebuild_allowed(active_run=False) is True
    assert automatic_rebuild_allowed(active_run=True) is False
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
