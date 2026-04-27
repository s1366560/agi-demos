"""Unit tests for status_handlers dispatch (P2d M4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.infrastructure.agent.workspace.adjudicator import (
    AttemptAdjudicationContext,
    AttemptAdjudicationOutcome,
    LeaderVerdict,
    dispatch_attempt_adjudication,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _attempt(
    attempt_id: str,
    *,
    status: WorkspaceTaskSessionAttemptStatus = WorkspaceTaskSessionAttemptStatus.PENDING,
    number: int = 1,
) -> WorkspaceTaskSessionAttempt:
    return WorkspaceTaskSessionAttempt(
        id=attempt_id,
        workspace_task_id="task-1",
        root_goal_task_id="root-1",
        workspace_id="ws-1",
        attempt_number=number,
        status=status,
    )


def _context(
    *,
    current_attempt_id: str = "attempt-1",
    worker_agent_id: str | None = "worker-1",
    task_title: str = "Do X",
) -> AttemptAdjudicationContext:
    return AttemptAdjudicationContext(
        workspace_id="ws-1",
        task_id="task-1",
        task_title=task_title,
        root_goal_task_id="root-1",
        worker_agent_id=worker_agent_id,
        current_attempt_id=current_attempt_id,
    )


def _verdict(
    status: WorkspaceTaskStatus,
    *,
    summary: str = "",
    leader_agent_id: str | None = "leader-1",
) -> LeaderVerdict:
    return LeaderVerdict(
        status=status,
        summary=summary,
        actor_user_id="user-1",
        leader_agent_id=leader_agent_id,
    )


def _fake_service() -> MagicMock:
    svc = MagicMock()
    svc.accept = AsyncMock()
    svc.block = AsyncMock()
    svc.reject = AsyncMock()
    svc.create_attempt = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# Context / Outcome construction
# ---------------------------------------------------------------------------


class TestAttemptAdjudicationContext:
    def test_requires_workspace_id(self) -> None:
        with pytest.raises(ValueError, match="workspace_id"):
            AttemptAdjudicationContext(
                workspace_id="",
                task_id="t",
                task_title="",
                root_goal_task_id="",
                worker_agent_id=None,
                current_attempt_id="a",
            )

    def test_requires_task_id(self) -> None:
        with pytest.raises(ValueError, match="task_id"):
            AttemptAdjudicationContext(
                workspace_id="ws",
                task_id="",
                task_title="",
                root_goal_task_id="",
                worker_agent_id=None,
                current_attempt_id="a",
            )

    def test_requires_current_attempt_id(self) -> None:
        with pytest.raises(ValueError, match="current_attempt_id"):
            AttemptAdjudicationContext(
                workspace_id="ws",
                task_id="t",
                task_title="",
                root_goal_task_id="",
                worker_agent_id=None,
                current_attempt_id="",
            )

    def test_frozen(self) -> None:
        ctx = _context()
        with pytest.raises(Exception):
            ctx.workspace_id = "other"  # type: ignore[misc]


class TestAttemptAdjudicationOutcome:
    def test_default_empty(self) -> None:
        out = AttemptAdjudicationOutcome()
        assert out.metadata_updates == {}
        assert out.retry_launch_request is None


# ---------------------------------------------------------------------------
# DONE handler
# ---------------------------------------------------------------------------


class TestDoneHandler:
    @pytest.mark.asyncio
    async def test_calls_accept_and_stamps_metadata(self) -> None:
        svc = _fake_service()
        accepted = _attempt("a1", status=WorkspaceTaskSessionAttemptStatus.ACCEPTED)
        svc.accept.return_value = accepted

        outcome = await dispatch_attempt_adjudication(
            verdict=_verdict(WorkspaceTaskStatus.DONE, summary="shipped"),
            context=_context(),
            attempt_service=svc,
        )

        svc.accept.assert_awaited_once_with("attempt-1", leader_feedback="shipped")
        svc.block.assert_not_awaited()
        svc.reject.assert_not_awaited()
        svc.create_attempt.assert_not_awaited()
        assert outcome.metadata_updates == {
            "last_attempt_status": "accepted",
            "last_attempt_id": "a1",
            "current_attempt_id": "a1",
        }
        assert outcome.retry_launch_request is None

    @pytest.mark.asyncio
    async def test_empty_summary_passes_none(self) -> None:
        # Empty summary is stored as None.
        svc = _fake_service()
        svc.accept.return_value = _attempt("a1", status=WorkspaceTaskSessionAttemptStatus.ACCEPTED)
        await dispatch_attempt_adjudication(
            verdict=_verdict(WorkspaceTaskStatus.DONE, summary=""),
            context=_context(),
            attempt_service=svc,
        )
        svc.accept.assert_awaited_once_with("attempt-1", leader_feedback=None)


# ---------------------------------------------------------------------------
# BLOCKED handler
# ---------------------------------------------------------------------------


class TestBlockedHandler:
    @pytest.mark.asyncio
    async def test_calls_block_with_feedback(self) -> None:
        svc = _fake_service()
        blocked = _attempt("a2", status=WorkspaceTaskSessionAttemptStatus.BLOCKED)
        svc.block.return_value = blocked

        outcome = await dispatch_attempt_adjudication(
            verdict=_verdict(WorkspaceTaskStatus.BLOCKED, summary="waiting for env"),
            context=_context(),
            attempt_service=svc,
        )
        svc.block.assert_awaited_once_with(
            "attempt-1",
            leader_feedback="waiting for env",
            adjudication_reason="leader_blocked",
        )
        assert outcome.metadata_updates["last_attempt_status"] == "blocked"
        assert outcome.metadata_updates["last_attempt_id"] == "a2"
        assert outcome.metadata_updates["current_attempt_id"] == "a2"
        assert outcome.retry_launch_request is None

    @pytest.mark.asyncio
    async def test_empty_summary_falls_back_to_title(self) -> None:
        svc = _fake_service()
        svc.block.return_value = _attempt("a2", status=WorkspaceTaskSessionAttemptStatus.BLOCKED)
        await dispatch_attempt_adjudication(
            verdict=_verdict(WorkspaceTaskStatus.BLOCKED, summary=""),
            context=_context(task_title="Do X"),
            attempt_service=svc,
        )
        svc.block.assert_awaited_once_with(
            "attempt-1",
            leader_feedback="Do X",
            adjudication_reason="leader_blocked",
        )


# ---------------------------------------------------------------------------
# IN_PROGRESS handler
# ---------------------------------------------------------------------------


class TestInProgressHandler:
    @pytest.mark.asyncio
    async def test_rejects_and_creates_new_attempt(self) -> None:
        svc = _fake_service()
        rejected = _attempt("a3", status=WorkspaceTaskSessionAttemptStatus.REJECTED)
        new_attempt = _attempt("a4", status=WorkspaceTaskSessionAttemptStatus.PENDING, number=2)
        svc.reject.return_value = rejected
        svc.create_attempt.return_value = new_attempt

        outcome = await dispatch_attempt_adjudication(
            verdict=_verdict(WorkspaceTaskStatus.IN_PROGRESS, summary="rework needed"),
            context=_context(),
            attempt_service=svc,
        )

        svc.reject.assert_awaited_once_with(
            "attempt-1",
            leader_feedback="rework needed",
            adjudication_reason="leader_rework_required",
        )
        svc.create_attempt.assert_awaited_once_with(
            workspace_task_id="task-1",
            root_goal_task_id="root-1",
            workspace_id="ws-1",
            worker_agent_id="worker-1",
            leader_agent_id="leader-1",
        )
        assert outcome.metadata_updates == {
            "last_attempt_status": "rejected",
            "last_attempt_id": "a3",
            "current_attempt_id": "a4",
            "current_attempt_number": 2,
        }
        assert outcome.retry_launch_request == {
            "workspace_id": "ws-1",
            "root_goal_task_id": "root-1",
            "workspace_task_id": "task-1",
            "attempt_id": "a4",
            "actor_user_id": "user-1",
            "leader_agent_id": "leader-1",
            "retry_feedback": "rework needed",
        }

    @pytest.mark.asyncio
    async def test_no_retry_when_leader_missing(self) -> None:
        svc = _fake_service()
        svc.reject.return_value = _attempt("a3", status=WorkspaceTaskSessionAttemptStatus.REJECTED)
        svc.create_attempt.return_value = _attempt(
            "a4", status=WorkspaceTaskSessionAttemptStatus.PENDING, number=2
        )
        outcome = await dispatch_attempt_adjudication(
            verdict=_verdict(
                WorkspaceTaskStatus.IN_PROGRESS,
                summary="rework",
                leader_agent_id=None,
            ),
            context=_context(),
            attempt_service=svc,
        )
        # Still rejects + creates new attempt, but no retry request.
        svc.reject.assert_awaited_once()
        svc.create_attempt.assert_awaited_once()
        assert outcome.retry_launch_request is None
        assert outcome.metadata_updates["current_attempt_id"] == "a4"

    @pytest.mark.asyncio
    async def test_no_retry_when_assignee_missing(self) -> None:
        svc = _fake_service()
        svc.reject.return_value = _attempt("a3", status=WorkspaceTaskSessionAttemptStatus.REJECTED)
        svc.create_attempt.return_value = _attempt(
            "a4", status=WorkspaceTaskSessionAttemptStatus.PENDING, number=2
        )
        outcome = await dispatch_attempt_adjudication(
            verdict=_verdict(WorkspaceTaskStatus.IN_PROGRESS, summary="rework"),
            context=_context(worker_agent_id=None),
            attempt_service=svc,
        )
        assert outcome.retry_launch_request is None

    @pytest.mark.asyncio
    async def test_empty_summary_falls_back_to_title(self) -> None:
        svc = _fake_service()
        svc.reject.return_value = _attempt("a3", status=WorkspaceTaskSessionAttemptStatus.REJECTED)
        svc.create_attempt.return_value = _attempt(
            "a4", status=WorkspaceTaskSessionAttemptStatus.PENDING, number=2
        )
        outcome = await dispatch_attempt_adjudication(
            verdict=_verdict(WorkspaceTaskStatus.IN_PROGRESS, summary=""),
            context=_context(task_title="Do X"),
            attempt_service=svc,
        )
        svc.reject.assert_awaited_once_with(
            "attempt-1",
            leader_feedback="Do X",
            adjudication_reason="leader_rework_required",
        )
        assert outcome.retry_launch_request is not None
        assert outcome.retry_launch_request["retry_feedback"] == "Do X"


# ---------------------------------------------------------------------------
# TODO / fall-through
# ---------------------------------------------------------------------------


class TestTodoHandler:
    @pytest.mark.asyncio
    async def test_todo_is_noop(self) -> None:
        svc = _fake_service()
        outcome = await dispatch_attempt_adjudication(
            verdict=_verdict(WorkspaceTaskStatus.TODO, summary="replan"),
            context=_context(),
            attempt_service=svc,
        )
        svc.accept.assert_not_awaited()
        svc.block.assert_not_awaited()
        svc.reject.assert_not_awaited()
        svc.create_attempt.assert_not_awaited()
        assert outcome.metadata_updates == {}
        assert outcome.retry_launch_request is None
