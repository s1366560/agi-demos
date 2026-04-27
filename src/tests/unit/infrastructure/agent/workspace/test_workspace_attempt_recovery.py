"""Unit tests for WorkspaceAttemptRecoveryService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.infrastructure.agent.workspace.workspace_attempt_recovery import (
    RECOVERY_SUMMARY_RESTART,
    RECOVERY_SUMMARY_STALE,
    WorkspaceAttemptRecoveryService,
)


def _make_attempt(
    *,
    attempt_id: str = "att-1",
    workspace_id: str = "ws-1",
    workspace_task_id: str = "task-1",
    root_goal_task_id: str = "root-1",
    conversation_id: str | None = "conv-1",
    worker_agent_id: str | None = "worker-agent",
    leader_agent_id: str | None = "leader-agent",
    status: WorkspaceTaskSessionAttemptStatus = WorkspaceTaskSessionAttemptStatus.RUNNING,
) -> WorkspaceTaskSessionAttempt:
    return WorkspaceTaskSessionAttempt(
        id=attempt_id,
        workspace_task_id=workspace_task_id,
        root_goal_task_id=root_goal_task_id,
        workspace_id=workspace_id,
        attempt_number=1,
        status=status,
        conversation_id=conversation_id,
        worker_agent_id=worker_agent_id,
        leader_agent_id=leader_agent_id,
        created_at=datetime.now(UTC) - timedelta(minutes=10),
        updated_at=datetime.now(UTC) - timedelta(minutes=10),
    )


class _SessionContext:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def __aenter__(self) -> Any:
        return self._session

    async def __aexit__(self, *_a: object) -> None:
        return None


def _make_service(
    *,
    stale_attempts: list[WorkspaceTaskSessionAttempt],
    apply_report: AsyncMock | None = None,
    schedule_tick: MagicMock | None = None,
    enqueue_resume: AsyncMock | None = None,
    liveness_lookup: Any = None,
    task_lookup: dict[str, str] | None = None,
    task_status_lookup: dict[str, Any] | None = None,
    attempt_lookup: dict[str, WorkspaceTaskSessionAttempt] | None = None,
    attempt_saves: list[WorkspaceTaskSessionAttempt] | None = None,
) -> tuple[WorkspaceAttemptRecoveryService, AsyncMock, MagicMock]:
    apply_report = apply_report or AsyncMock(return_value=MagicMock())
    schedule_tick = schedule_tick or MagicMock()
    enqueue_resume = enqueue_resume or AsyncMock()
    lookup = task_lookup if task_lookup is not None else {"task-1": "user-1"}
    from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus

    status_lookup = (
        task_status_lookup
        if task_status_lookup is not None
        else dict.fromkeys(lookup, WorkspaceTaskStatus.IN_PROGRESS)
    )
    attempts_by_id = (
        attempt_lookup if attempt_lookup is not None else {a.id: a for a in stale_attempts}
    )
    saves_sink = attempt_saves if attempt_saves is not None else []

    class _Session:
        async def commit(self) -> None:
            return None

    def _session_cm() -> Any:
        class _CM:
            async def __aenter__(self_inner) -> Any:
                return _Session()

            async def __aexit__(self_inner, *_a: object) -> None:
                return None

        return _CM()

    def session_factory() -> Any:
        return _session_cm()

    repo_instance = MagicMock()
    repo_instance.find_stale_non_terminal = AsyncMock(return_value=stale_attempts)

    async def _find_by_id_attempt(attempt_id: str) -> Any:
        return attempts_by_id.get(attempt_id)

    async def _save_attempt(attempt: WorkspaceTaskSessionAttempt) -> Any:
        saves_sink.append(attempt)
        return attempt

    repo_instance.find_by_id = AsyncMock(side_effect=_find_by_id_attempt)
    repo_instance.save = AsyncMock(side_effect=_save_attempt)

    def _task_repo(_session: Any) -> Any:
        task_repo = MagicMock()

        async def _find_by_id(task_id: str) -> Any:
            uid = lookup.get(task_id)
            if uid is None:
                return None
            task = MagicMock()
            task.created_by = uid
            task.status = status_lookup.get(task_id, WorkspaceTaskStatus.IN_PROGRESS)
            return task

        task_repo.find_by_id = AsyncMock(side_effect=_find_by_id)
        return task_repo

    service = WorkspaceAttemptRecoveryService(
        session_factory=session_factory,
        apply_report=apply_report,
        schedule_tick=schedule_tick,
        enqueue_resume=enqueue_resume,
        liveness_lookup=liveness_lookup or (list),
        stale_seconds=60,
        startup_grace_seconds=5,
        check_interval_seconds=30,
    )

    patch_attempt_repo = patch(
        "src.infrastructure.agent.workspace.workspace_attempt_recovery.SqlWorkspaceTaskSessionAttemptRepository",
        return_value=repo_instance,
    )
    patch_task_repo = patch(
        "src.infrastructure.agent.workspace.workspace_attempt_recovery.SqlWorkspaceTaskRepository",
        side_effect=_task_repo,
    )
    service._patches = (patch_attempt_repo, patch_task_repo)  # type: ignore[attr-defined]
    service._saves = saves_sink  # type: ignore[attr-defined]
    return service, apply_report, schedule_tick


class TestStartupSweep:
    @pytest.mark.asyncio
    async def test_recovers_all_non_terminal_and_schedules_tick_per_workspace(
        self,
    ) -> None:
        att_a = _make_attempt(attempt_id="a1", workspace_id="ws-1", workspace_task_id="task-1")
        att_b = _make_attempt(attempt_id="a2", workspace_id="ws-1", workspace_task_id="task-1")
        att_c = _make_attempt(attempt_id="a3", workspace_id="ws-2", workspace_task_id="task-2")

        service, apply_report, schedule_tick = _make_service(
            stale_attempts=[att_a, att_b, att_c],
            task_lookup={"task-1": "user-1", "task-2": "user-2"},
        )
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.startup_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        assert recovered == 3
        assert apply_report.await_count == 3
        for call in apply_report.await_args_list:
            kwargs = call.kwargs
            assert kwargs["report_type"] == "blocked"
            assert kwargs["summary"] == RECOVERY_SUMMARY_RESTART
        # One tick per unique (workspace_id, actor_user_id)
        assert schedule_tick.call_count == 2
        ticked = {call.args for call in schedule_tick.call_args_list}
        assert ticked == {("ws-1", "user-1"), ("ws-2", "user-2")}

    @pytest.mark.asyncio
    async def test_successful_recovery_enqueues_resume_job(self) -> None:
        enqueue_resume = AsyncMock()
        att = _make_attempt(attempt_id="att-resume", workspace_task_id="task-1")
        service, _apply_report, _schedule_tick = _make_service(
            stale_attempts=[att],
            enqueue_resume=enqueue_resume,
            task_lookup={"task-1": "user-1"},
        )
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.startup_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        assert recovered == 1
        enqueue_resume.assert_awaited_once_with(att, RECOVERY_SUMMARY_RESTART, "user-1")

    @pytest.mark.asyncio
    async def test_noop_when_no_stale_attempts(self) -> None:
        service, apply_report, schedule_tick = _make_service(stale_attempts=[])
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.startup_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        assert recovered == 0
        apply_report.assert_not_awaited()
        schedule_tick.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_attempt_when_parent_task_deleted(self) -> None:
        att = _make_attempt(workspace_task_id="ghost-task")
        service, apply_report, schedule_tick = _make_service(
            stale_attempts=[att],
            task_lookup={},  # task missing
        )
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.startup_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        assert recovered == 0
        apply_report.assert_not_awaited()
        schedule_tick.assert_not_called()
        # Orphan attempt must be flipped BLOCKED at the attempt-row level.
        assert len(service._saves) == 1  # type: ignore[attr-defined]
        saved = service._saves[0]  # type: ignore[attr-defined]
        assert saved.status == WorkspaceTaskSessionAttemptStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_skips_cascade_when_parent_task_already_done(self) -> None:
        from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus

        att = _make_attempt(workspace_task_id="task-1")
        service, apply_report, schedule_tick = _make_service(
            stale_attempts=[att],
            task_lookup={"task-1": "user-1"},
            task_status_lookup={"task-1": WorkspaceTaskStatus.DONE},
        )
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.startup_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        # Must NOT cascade (would raise done->blocked transition error)
        apply_report.assert_not_awaited()
        schedule_tick.assert_not_called()
        assert recovered == 0
        # Attempt itself flipped BLOCKED so next sweep ignores it.
        assert len(service._saves) == 1  # type: ignore[attr-defined]
        assert service._saves[0].status == WorkspaceTaskSessionAttemptStatus.BLOCKED  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_skips_cascade_when_parent_task_already_blocked(self) -> None:
        from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus

        att = _make_attempt(workspace_task_id="task-1")
        service, apply_report, schedule_tick = _make_service(
            stale_attempts=[att],
            task_lookup={"task-1": "user-1"},
            task_status_lookup={"task-1": WorkspaceTaskStatus.BLOCKED},
        )
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.startup_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        apply_report.assert_not_awaited()
        schedule_tick.assert_not_called()
        assert recovered == 0
        assert len(service._saves) == 1  # type: ignore[attr-defined]


class TestPeriodicSweep:
    @pytest.mark.asyncio
    async def test_skips_attempts_in_liveness_set(self) -> None:
        live = _make_attempt(attempt_id="live", workspace_task_id="task-1")
        dead = _make_attempt(attempt_id="dead", workspace_task_id="task-1")

        service, apply_report, schedule_tick = _make_service(
            stale_attempts=[live, dead],
            liveness_lookup=lambda: ["live"],
        )
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.periodic_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        assert recovered == 1
        assert apply_report.await_count == 1
        only_kwargs = apply_report.await_args_list[0].kwargs
        assert only_kwargs["attempt_id"] == "dead"
        assert only_kwargs["summary"] == RECOVERY_SUMMARY_STALE
        schedule_tick.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_live_is_noop(self) -> None:
        att = _make_attempt(attempt_id="only", workspace_task_id="task-1")
        service, apply_report, schedule_tick = _make_service(
            stale_attempts=[att],
            liveness_lookup=lambda: ["only"],
        )
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.periodic_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        assert recovered == 0
        apply_report.assert_not_awaited()
        schedule_tick.assert_not_called()


class TestApplyReportFailure:
    @pytest.mark.asyncio
    async def test_single_failure_does_not_abort_batch(self) -> None:
        att_ok = _make_attempt(attempt_id="ok", workspace_task_id="task-1")
        att_bad = _make_attempt(attempt_id="bad", workspace_task_id="task-1")

        calls = {"n": 0}

        async def _apply(**kwargs: Any) -> Any:
            calls["n"] += 1
            if kwargs["attempt_id"] == "bad":
                raise RuntimeError("boom")
            return MagicMock()

        apply_report = AsyncMock(side_effect=_apply)
        service, _, schedule_tick = _make_service(
            stale_attempts=[att_bad, att_ok],
            apply_report=apply_report,
        )
        for p in service._patches:  # type: ignore[attr-defined]
            p.start()
        try:
            recovered = await service.startup_sweep()
        finally:
            for p in service._patches:  # type: ignore[attr-defined]
                p.stop()

        assert calls["n"] == 2
        assert recovered == 1
        # tick still scheduled because one attempt recovered
        schedule_tick.assert_called_once()


class TestValidation:
    def test_stale_seconds_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            WorkspaceAttemptRecoveryService(
                session_factory=lambda: _SessionContext(MagicMock()),
                apply_report=AsyncMock(),
                schedule_tick=MagicMock(),
                stale_seconds=0,
            )

    def test_check_interval_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            WorkspaceAttemptRecoveryService(
                session_factory=lambda: _SessionContext(MagicMock()),
                apply_report=AsyncMock(),
                schedule_tick=MagicMock(),
                check_interval_seconds=0,
            )
