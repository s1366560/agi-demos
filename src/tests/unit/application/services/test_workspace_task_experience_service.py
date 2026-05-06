"""Unit tests for WorkspaceTaskExperienceService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.application.services.workspace_task_experience_service import (
    WorkspaceTaskExperienceService,
    build_workspace_task_experience_summary,
)
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)

_NOW = datetime(2026, 4, 30, 8, 0, tzinfo=UTC)


def _task(
    *,
    status: WorkspaceTaskStatus = WorkspaceTaskStatus.IN_PROGRESS,
    metadata: dict[str, object] | None = None,
    blocker_reason: str | None = None,
) -> WorkspaceTask:
    return WorkspaceTask(
        id="task-1",
        workspace_id="ws-1",
        title="Ship workspace task detail",
        description="Expose execution evidence in the workspace board",
        created_by="user-1",
        status=status,
        metadata=metadata or {},
        blocker_reason=blocker_reason,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _attempt() -> WorkspaceTaskSessionAttempt:
    return WorkspaceTaskSessionAttempt(
        id="attempt-1",
        workspace_task_id="task-1",
        root_goal_task_id="root-1",
        workspace_id="ws-1",
        attempt_number=2,
        status=WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION,
        conversation_id="conv-1",
        worker_agent_id="worker-1",
        candidate_summary="Implemented the detail panel",
        candidate_artifacts=["artifact:panel"],
        candidate_verifications=["vitest TaskBoard"],
        leader_feedback="Needs one more verification",
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.unit
class TestBuildWorkspaceTaskExperienceSummary:
    def test_marks_missing_evidence_without_artifacts_or_verifications(self) -> None:
        summary = build_workspace_task_experience_summary(_task())

        assert summary["task_id"] == "task-1"
        assert summary["readiness"]["missing_evidence"] == ["evidence"]
        assert summary["readiness"]["transition_gates"]["done"]["would_block"] is True
        assert summary["diagnostics"]["missing_conversation"] is False
        assert summary["evidence"]["artifacts"] == []

    def test_merges_worker_report_and_attempt_evidence(self) -> None:
        task = _task(
            metadata={
                "current_attempt_id": "attempt-1",
                "current_attempt_number": 2,
                "current_attempt_conversation_id": "conv-1",
                "last_worker_report_type": "completed",
                "last_worker_report_summary": "Panel implemented",
                "last_worker_report_artifacts": ["artifact:summary"],
                "last_worker_report_verifications": ["pytest passed"],
                "goal_evidence": {"verification_grade": "warn"},
                "pending_leader_adjudication": True,
            }
        )

        summary = build_workspace_task_experience_summary(task, attempts=[_attempt()])

        assert summary["execution"]["active_attempt"]["id"] == "attempt-1"
        assert summary["execution"]["current_attempt_number"] == 2
        assert summary["evidence"]["artifacts"] == ["artifact:summary", "artifact:panel"]
        assert summary["evidence"]["verification_summaries"] == [
            "pytest passed",
            "vitest TaskBoard",
        ]
        assert summary["evidence"]["worker_report"]["summary"] == "Panel implemented"
        assert summary["diagnostics"]["pending_leader_adjudication"] is True
        assert summary["readiness"]["transition_gates"]["done"]["missing"] == [
            "leader_adjudication"
        ]
        assert any(item["type"] == "attempt" for item in summary["activity"])


@pytest.mark.unit
class TestWorkspaceTaskExperienceService:
    async def test_get_summary_checks_task_authority_and_loads_attempts(self) -> None:
        task = _task(metadata={"current_attempt_id": "attempt-1"})
        task_service = AsyncMock()
        task_service.get_task.return_value = task
        attempt_repo = AsyncMock()
        attempt_repo.find_by_workspace_task_id.return_value = [_attempt()]
        service = WorkspaceTaskExperienceService(
            task_service=task_service,
            attempt_repo=attempt_repo,
        )

        summary = await service.get_summary(
            workspace_id="ws-1",
            task_id="task-1",
            actor_user_id="user-1",
        )

        task_service.get_task.assert_awaited_once_with(
            workspace_id="ws-1",
            task_id="task-1",
            actor_user_id="user-1",
        )
        attempt_repo.find_by_workspace_task_id.assert_awaited_once_with("task-1", limit=5)
        assert summary["execution"]["active_attempt"]["id"] == "attempt-1"
