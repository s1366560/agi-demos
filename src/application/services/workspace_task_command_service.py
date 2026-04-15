"""Shared workspace task mutation pipeline that queues post-commit events."""

from __future__ import annotations

from collections.abc import Mapping

from src.application.services.workspace_task_event_publisher import (
    PendingWorkspaceTaskEvent,
    serialize_workspace_task,
)
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)


class WorkspaceTaskCommandService:
    """Runs workspace task mutations and queues canonical events for post-commit publish."""

    def __init__(self, task_service: WorkspaceTaskService) -> None:
        self._task_service = task_service
        self._pending_events: list[PendingWorkspaceTaskEvent] = []

    def consume_pending_events(self) -> list[PendingWorkspaceTaskEvent]:
        pending_events = list(self._pending_events)
        self._pending_events.clear()
        return pending_events

    async def create_task(
        self,
        workspace_id: str,
        actor_user_id: str,
        title: str,
        description: str | None = None,
        assignee_user_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.create_task(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            title=title,
            description=description,
            assignee_user_id=assignee_user_id,
            metadata=metadata,
        )
        if task.assignee_user_id or task.assignee_agent_id:
            self._queue_assigned(task)
        self._queue_task_snapshot(task, AgentEventType.WORKSPACE_TASK_CREATED)
        return task

    async def update_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        title: str | None = None,
        description: str | None = None,
        assignee_user_id: str | None = None,
        status: WorkspaceTaskStatus | None = None,
        metadata: Mapping[str, object] | None = None,
        priority: WorkspaceTaskPriority | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.update_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            title=title,
            description=description,
            assignee_user_id=assignee_user_id,
            status=status,
            metadata=metadata,
            priority=priority,
        )
        if assignee_user_id is not None:
            self._queue_assigned(task)
        self._queue_task_snapshot(task, AgentEventType.WORKSPACE_TASK_UPDATED)
        return task

    async def delete_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> bool:
        deleted = await self._task_service.delete_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        if deleted:
            self._pending_events.append(
                PendingWorkspaceTaskEvent(
                    workspace_id=workspace_id,
                    event_type=AgentEventType.WORKSPACE_TASK_DELETED,
                    payload={"task_id": task_id},
                )
            )
        return deleted

    async def assign_task_to_agent(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        workspace_agent_id: str,
    ) -> WorkspaceTask:
        task = await self._task_service.assign_task_to_agent(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            workspace_agent_id=workspace_agent_id,
        )
        self._queue_assigned(task, workspace_agent_id=workspace_agent_id)
        return task

    async def unassign_task_from_agent(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        task = await self._task_service.unassign_task_from_agent(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        self._queue_task_snapshot(task, AgentEventType.WORKSPACE_TASK_UPDATED)
        return task

    async def claim_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        task = await self._task_service.claim_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        self._queue_task_snapshot(task, AgentEventType.WORKSPACE_TASK_UPDATED)
        return task

    async def start_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        task = await self._task_service.start_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        self._queue_status_changed(task)
        return task

    async def block_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        task = await self._task_service.block_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        self._queue_status_changed(task)
        return task

    async def complete_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        task = await self._task_service.complete_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        self._queue_status_changed(task)
        return task

    def _queue_task_snapshot(self, task: WorkspaceTask, event_type: AgentEventType) -> None:
        self._pending_events.append(
            PendingWorkspaceTaskEvent(
                workspace_id=task.workspace_id,
                event_type=event_type,
                payload={"task": serialize_workspace_task(task)},
            )
        )

    def _queue_status_changed(self, task: WorkspaceTask) -> None:
        self._pending_events.append(
            PendingWorkspaceTaskEvent(
                workspace_id=task.workspace_id,
                event_type=AgentEventType.WORKSPACE_TASK_STATUS_CHANGED,
                payload={
                    "task": serialize_workspace_task(task),
                    "new_status": task.status.value,
                },
            )
        )

    def _queue_assigned(self, task: WorkspaceTask, *, workspace_agent_id: str | None = None) -> None:
        self._pending_events.append(
            PendingWorkspaceTaskEvent(
                workspace_id=task.workspace_id,
                event_type=AgentEventType.WORKSPACE_TASK_ASSIGNED,
                payload={
                    "workspace_id": task.workspace_id,
                    "task_id": task.id,
                    "task": serialize_workspace_task(task),
                    "assignee_user_id": task.assignee_user_id,
                    "assignee_agent_id": task.assignee_agent_id,
                    "workspace_agent_id": workspace_agent_id,
                    "status": task.status.value,
                },
            )
        )
