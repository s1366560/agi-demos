"""Tests for worker report metadata builder (P2d M6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttemptStatus,
)
from src.infrastructure.agent.workspace.worker_report import (
    WorkerReportPatch,
    build_worker_report_patch,
)

FIXED_NOW = datetime(2026, 4, 20, 10, 0, 0, tzinfo=UTC)
FIXED_ISO = "2026-04-20T10:00:00Z"


def _base_kwargs(**overrides):
    kwargs = {
        "task_metadata": {},
        "report_type": "progress",
        "summary": "",
        "artifacts": [],
        "report_id": None,
        "resolved_attempt_id": "attempt-1",
        "resolved_attempt_number": 1,
        "effective_worker_agent_id": "worker-1",
        "now": FIXED_NOW,
    }
    kwargs.update(overrides)
    return kwargs


class TestInputValidation:
    def test_empty_report_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="report_type"):
            build_worker_report_patch(**_base_kwargs(report_type=""))

    def test_empty_attempt_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="resolved_attempt_id"):
            build_worker_report_patch(**_base_kwargs(resolved_attempt_id=""))

    def test_empty_worker_agent_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="effective_worker_agent_id"):
            build_worker_report_patch(**_base_kwargs(effective_worker_agent_id=""))


class TestProgressReport:
    def test_minimal_progress_report(self) -> None:
        result = build_worker_report_patch(**_base_kwargs(report_type="progress"))
        assert not result.duplicate
        assert result.normalized_summary == "worker_report:progress"
        assert result.merged_artifacts == []
        assert result.report_verifications == []
        assert result.merged_verifications == []
        patch = result.patch
        assert patch["last_worker_report_type"] == "progress"
        assert patch["pending_leader_adjudication"] is False
        assert patch["last_attempt_status"] == WorkspaceTaskSessionAttemptStatus.RUNNING.value
        assert patch["execution_state"]["phase"] == "in_progress"
        assert patch["execution_state"]["last_agent_action"] == "start"
        assert patch["execution_state"]["updated_by_actor_id"] == "worker-1"
        assert patch["last_worker_reported_at"] == FIXED_ISO
        assert patch["current_attempt_id"] == "attempt-1"
        assert patch["last_attempt_id"] == "attempt-1"
        assert patch["current_attempt_number"] == 1
        assert "last_worker_report_id" not in patch

    def test_preserves_workspace_binding_projection_when_present(self) -> None:
        result = build_worker_report_patch(
            **_base_kwargs(
                task_metadata={"workspace_agent_binding_id": "binding-1"},
                report_type="progress",
            )
        )
        assert result.patch["current_attempt_worker_binding_id"] == "binding-1"

    def test_keeps_existing_current_attempt_worker_binding_projection(self) -> None:
        result = build_worker_report_patch(
            **_base_kwargs(
                task_metadata={"current_attempt_worker_binding_id": "binding-existing"},
                report_type="progress",
            )
        )
        assert result.patch["current_attempt_worker_binding_id"] == "binding-existing"


class TestTerminalReport:
    def test_completed_marks_awaiting_leader(self) -> None:
        result = build_worker_report_patch(
            **_base_kwargs(report_type="completed", summary="shipped!")
        )
        assert not result.duplicate
        patch = result.patch
        assert patch["pending_leader_adjudication"] is True
        assert (
            patch["last_attempt_status"]
            == WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value
        )
        assert patch["execution_state"]["last_agent_action"] == "await_leader_adjudication"
        # default for completed with no explicit verification
        assert "worker_report:completed" in result.report_verifications
        assert "worker_report:completed" in patch["execution_verifications"]

    @pytest.mark.parametrize("report_type", ["failed", "blocked", "needs_replan"])
    def test_non_completed_terminals_also_await_leader(self, report_type: str) -> None:
        result = build_worker_report_patch(**_base_kwargs(report_type=report_type, summary="issue"))
        assert result.patch["pending_leader_adjudication"] is True
        assert (
            result.patch["last_attempt_status"]
            == WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value
        )
        # Only "completed" gets the automatic verification stamp.
        assert "worker_report:completed" not in result.report_verifications


class TestPriorMetadataMerging:
    def test_prior_artifacts_and_verifications_merged_and_deduped(self) -> None:
        result = build_worker_report_patch(
            **_base_kwargs(
                task_metadata={
                    "evidence_refs": ["a", "b", ""],
                    "execution_verifications": ["v1"],
                },
                report_type="progress",
                artifacts=["b", "c"],
            )
        )
        assert result.merged_artifacts == ["a", "b", "c"]
        assert result.patch["evidence_refs"] == ["a", "b", "c"]
        # prior verifications preserved in execution_verifications
        assert result.patch["execution_verifications"] == ["v1"]
        assert result.merged_verifications == ["v1"]

    def test_prior_non_list_metadata_ignored(self) -> None:
        result = build_worker_report_patch(
            **_base_kwargs(
                task_metadata={"evidence_refs": "not-a-list"},
                artifacts=["x"],
            )
        )
        assert result.merged_artifacts == ["x"]


class TestDuplicateFingerprint:
    def test_duplicate_returns_empty_patch(self) -> None:
        # First call: compute the fingerprint the task would persist.
        first = build_worker_report_patch(
            **_base_kwargs(
                report_type="completed",
                summary="done",
                artifacts=["a1"],
                report_id="rpt-1",
            )
        )
        assert not first.duplicate
        fingerprint = first.fingerprint

        # Second call with the same inputs + fingerprint stamped on task_metadata.
        second = build_worker_report_patch(
            **_base_kwargs(
                task_metadata={"last_worker_report_fingerprint": fingerprint},
                report_type="completed",
                summary="done",
                artifacts=["a1"],
                report_id="rpt-1",
            )
        )
        assert second.duplicate is True
        assert second.patch == {}
        assert second.fingerprint == fingerprint

    def test_different_report_id_is_not_duplicate(self) -> None:
        first = build_worker_report_patch(
            **_base_kwargs(report_type="completed", summary="done", report_id="rpt-1")
        )
        second = build_worker_report_patch(
            **_base_kwargs(
                task_metadata={"last_worker_report_fingerprint": first.fingerprint},
                report_type="completed",
                summary="done",
                report_id="rpt-2",
            )
        )
        assert second.duplicate is False
        assert second.fingerprint != first.fingerprint


class TestReportIdPatchKey:
    def test_report_id_stamped_when_present(self) -> None:
        result = build_worker_report_patch(
            **_base_kwargs(report_type="progress", report_id="rpt-42")
        )
        assert result.patch["last_worker_report_id"] == "rpt-42"


class TestDataclass:
    def test_is_frozen(self) -> None:
        result = WorkerReportPatch()
        with pytest.raises(Exception):
            result.fingerprint = "x"  # type: ignore[misc]

    def test_default_fields_are_independent(self) -> None:
        a = WorkerReportPatch()
        b = WorkerReportPatch()
        assert a.patch is not b.patch
        assert a.merged_artifacts is not b.merged_artifacts
