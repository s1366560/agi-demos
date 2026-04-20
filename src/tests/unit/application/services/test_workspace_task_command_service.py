"""Unit tests for WorkspaceTaskCommandService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus


def _make_task(
    *,
    task_id: str = "wt-1",
    status: WorkspaceTaskStatus = WorkspaceTaskStatus.TODO,
    assignee_user_id: str | None = None,
    assignee_agent_id: str | None = None,
) -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id="ws-1",
        title="Investigate integration issue",
        description="details",
        created_by="owner-1",
        assignee_user_id=assignee_user_id,
        assignee_agent_id=assignee_agent_id,
        status=status,
        metadata={"source": "test"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.unit
class TestWorkspaceTaskCommandService:
    @pytest.mark.asyncio
    async def test_create_task_queues_assigned_then_created_events(self) -> None:
        task_service = AsyncMock()
        task_service.create_task.return_value = _make_task(assignee_user_id="user-2")
        command_service = WorkspaceTaskCommandService(task_service)

        task = await command_service.create_task(
            workspace_id="ws-1",
            actor_user_id="user-1",
            title="Task",
            assignee_user_id="user-2",
        )

        events = command_service.consume_pending_events()

        assert task.assignee_user_id == "user-2"
        assert [event.event_type for event in events] == [
            AgentEventType.WORKSPACE_TASK_ASSIGNED,
            AgentEventType.WORKSPACE_TASK_CREATED,
        ]
        assert events[0].payload["task_id"] == task.id
        assert events[1].payload["task"]["id"] == task.id
        assert command_service.consume_pending_events() == []

    @pytest.mark.asyncio
    async def test_start_task_queues_status_changed_event(self) -> None:
        task_service = AsyncMock()
        task_service.start_task.return_value = _make_task(status=WorkspaceTaskStatus.IN_PROGRESS)
        command_service = WorkspaceTaskCommandService(task_service)

        task = await command_service.start_task(
            workspace_id="ws-1",
            task_id="wt-1",
            actor_user_id="user-1",
        )

        events = command_service.consume_pending_events()

        assert task.status == WorkspaceTaskStatus.IN_PROGRESS
        assert len(events) == 1
        assert events[0].event_type == AgentEventType.WORKSPACE_TASK_STATUS_CHANGED
        assert events[0].payload["new_status"] == WorkspaceTaskStatus.IN_PROGRESS.value



    @pytest.mark.asyncio
    async def test_update_task_queues_child_and_root_snapshot_events(self) -> None:
        task_service = AsyncMock()
        child_task = _make_task(task_id="child-1", status=WorkspaceTaskStatus.IN_PROGRESS)
        child_task.metadata = {"root_goal_task_id": "root-1", "source": "test"}
        root_task = _make_task(task_id="root-1", status=WorkspaceTaskStatus.IN_PROGRESS)
        root_task.metadata = {"task_role": "goal_root"}
        task_service.update_task.return_value = child_task
        task_service.get_task.return_value = root_task
        command_service = WorkspaceTaskCommandService(task_service)

        task = await command_service.update_task(
            workspace_id="ws-1",
            task_id="child-1",
            actor_user_id="user-1",
            metadata={"pending_leader_adjudication": True},
        )

        events = command_service.consume_pending_events()

        assert task is child_task
        assert [event.event_type for event in events] == [
            AgentEventType.WORKSPACE_TASK_UPDATED,
            AgentEventType.WORKSPACE_TASK_UPDATED,
        ]
        assert events[0].payload["task"]["id"] == "child-1"
        assert events[1].payload["task"]["id"] == "root-1"
        task_service.get_task.assert_awaited_once_with(
            workspace_id="ws-1",
            task_id="root-1",
            actor_user_id="user-1",
        )

    @pytest.mark.asyncio
    async def test_complete_task_queues_status_change_then_root_snapshot(self) -> None:
        task_service = AsyncMock()
        child_task = _make_task(task_id="child-2", status=WorkspaceTaskStatus.DONE)
        child_task.metadata = {"root_goal_task_id": "root-2", "source": "test"}
        root_task = _make_task(task_id="root-2", status=WorkspaceTaskStatus.IN_PROGRESS)
        root_task.metadata = {"task_role": "goal_root"}
        task_service.complete_task.return_value = child_task
        task_service.get_task.return_value = root_task
        command_service = WorkspaceTaskCommandService(task_service)

        task = await command_service.complete_task(
            workspace_id="ws-1",
            task_id="child-2",
            actor_user_id="user-1",
        )

        events = command_service.consume_pending_events()

        assert task is child_task
        assert [event.event_type for event in events] == [
            AgentEventType.WORKSPACE_TASK_STATUS_CHANGED,
            AgentEventType.WORKSPACE_TASK_UPDATED,
        ]
        assert events[0].payload["task"]["id"] == "child-2"
        assert events[0].payload["new_status"] == WorkspaceTaskStatus.DONE.value
        assert events[1].payload["task"]["id"] == "root-2"

    @pytest.mark.asyncio
    async def test_create_goal_root_queues_autonomy_tick(self) -> None:
        """Creating a goal_root task enqueues an autonomy tick for post-commit drain.

        Without this, newly-materialized root goals never get their first
        decomposition pass (worker-report ticks require existing children, and
        the idle waker is opt-in).
        """
        task_service = AsyncMock()
        root_task = _make_task(task_id="root-99", status=WorkspaceTaskStatus.TODO)
        root_task.metadata = {"task_role": "goal_root", "source": "candidate"}
        task_service.create_task.return_value = root_task
        command_service = WorkspaceTaskCommandService(task_service)

        await command_service.create_task(
            workspace_id="ws-1",
            actor_user_id="user-1",
            title="Root goal",
            metadata={"task_role": "goal_root"},
        )

        ticks = command_service.consume_pending_autonomy_ticks()
        assert ticks == [("ws-1", "user-1")]
        # draining clears the queue
        assert command_service.consume_pending_autonomy_ticks() == []

    @pytest.mark.asyncio
    async def test_create_non_goal_root_does_not_queue_tick(self) -> None:
        """Only goal_root creation should enqueue a tick; execution tasks use worker launch."""
        task_service = AsyncMock()
        exec_task = _make_task(task_id="exec-1", status=WorkspaceTaskStatus.TODO)
        exec_task.metadata = {"task_role": "execution_task"}
        task_service.create_task.return_value = exec_task
        command_service = WorkspaceTaskCommandService(task_service)

        await command_service.create_task(
            workspace_id="ws-1",
            actor_user_id="user-1",
            title="Sub task",
            metadata={"task_role": "execution_task"},
        )

        assert command_service.consume_pending_autonomy_ticks() == []

    @pytest.mark.asyncio
    async def test_create_without_metadata_does_not_queue_tick(self) -> None:
        """Tasks without task_role metadata must not trigger autonomy ticks."""
        task_service = AsyncMock()
        task_service.create_task.return_value = _make_task()
        command_service = WorkspaceTaskCommandService(task_service)

        await command_service.create_task(
            workspace_id="ws-1",
            actor_user_id="user-1",
            title="Ad-hoc task",
        )

        assert command_service.consume_pending_autonomy_ticks() == []


@pytest.mark.unit
class TestMaybeScheduleWorkerSession:
    """Regression tests for _maybe_schedule_worker_session task_role guard."""

    @pytest.mark.parametrize(
        "task_role",
        ["execution", "execution_task"],
        ids=["legacy_execution", "canonical_execution_task"],
    )
    def test_accepts_both_execution_role_variants(
        self, monkeypatch: pytest.MonkeyPatch, task_role: str
    ) -> None:
        """Both 'execution' and 'execution_task' must trigger worker launch.

        Production code writes 'execution_task' (todowrite + bootstrap paths);
        only legacy tests used 'execution'. Before the P5a fix, the guard
        `task_role != "execution"` silently skipped worker launch in production.
        """
        task = _make_task(
            task_id="wt-role",
            status=WorkspaceTaskStatus.TODO,
            assignee_agent_id="agent-x",
        )
        task.metadata = {"task_role": task_role}

        launch_calls: list[dict] = []

        def _fake_schedule(**kwargs: object) -> None:
            launch_calls.append(dict(kwargs))

        import src.infrastructure.agent.workspace.worker_launch as worker_launch_mod

        monkeypatch.setattr(worker_launch_mod, "schedule_worker_session", _fake_schedule)

        command_service = WorkspaceTaskCommandService(AsyncMock())
        command_service._maybe_schedule_worker_session(
            task=task,
            actor_user_id="user-1",
            actor_agent_id="leader-1",
        )

        assert len(launch_calls) == 1
        assert launch_calls[0]["worker_agent_id"] == "agent-x"

    def test_skips_goal_root_role(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """goal_root role must NOT trigger worker launch (root has its own path)."""
        task = _make_task(
            task_id="wt-root",
            status=WorkspaceTaskStatus.TODO,
            assignee_agent_id="agent-x",
        )
        task.metadata = {"task_role": "goal_root"}

        launch_calls: list[dict] = []

        def _fake_schedule(**kwargs: object) -> None:
            launch_calls.append(dict(kwargs))

        import src.infrastructure.agent.workspace.worker_launch as worker_launch_mod

        monkeypatch.setattr(worker_launch_mod, "schedule_worker_session", _fake_schedule)

        command_service = WorkspaceTaskCommandService(AsyncMock())
        command_service._maybe_schedule_worker_session(
            task=task,
            actor_user_id="user-1",
            actor_agent_id="leader-1",
        )

        assert launch_calls == []
