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

