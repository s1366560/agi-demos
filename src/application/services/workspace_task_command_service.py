"""Shared workspace task mutation pipeline that queues post-commit events."""

from __future__ import annotations

from collections.abc import Mapping

from src.application.services.workspace_task_event_publisher import (
    PendingWorkspaceTaskEvent,
    serialize_workspace_task,
)
from src.application.services.workspace_task_service import (
    WorkspaceTaskAuthorityContext,
    WorkspaceTaskService,
)
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
)

_GOAL_ROOT_ROLE = "goal_root"


class WorkspaceTaskCommandService:
    """Runs workspace task mutations and queues canonical events for post-commit publish."""

    def __init__(self, task_service: WorkspaceTaskService) -> None:
        self._task_service = task_service
        self._pending_events: list[PendingWorkspaceTaskEvent] = []
        # (workspace_id, actor_user_id) pairs for goal_root tasks created in
        # this unit of work. Drained by callers AFTER db.commit() because
        # ``schedule_autonomy_tick`` opens its own session and must see the
        # persisted root — mirrors the pattern in ``apply_workspace_worker_report``.
        self._pending_autonomy_ticks: list[tuple[str, str]] = []

    def consume_pending_events(self) -> list[PendingWorkspaceTaskEvent]:
        pending_events = list(self._pending_events)
        self._pending_events.clear()
        return pending_events

    def consume_pending_autonomy_ticks(self) -> list[tuple[str, str]]:
        """Return and clear queued ``(workspace_id, actor_user_id)`` tick targets.

        Callers MUST drain this after ``await db.commit()`` and fire
        ``schedule_autonomy_tick`` for each entry. Failing to drain means
        newly-created root goals never get their first autonomy pass
        (the idle waker is opt-in and worker-report ticks require existing
        children).
        """
        pending = list(self._pending_autonomy_ticks)
        self._pending_autonomy_ticks.clear()
        return pending

    def _maybe_schedule_worker_session(
        self,
        *,
        task: WorkspaceTask,
        actor_user_id: str,
        actor_agent_id: str | None,
    ) -> None:
        """Fire a worker session launch when the task is an assigned execution step.

        Accepts both the canonical ``execution_task`` role and the legacy ``execution``
        alias. ``goal_root`` tasks are intentionally skipped — root tasks have their
        own leader-owned launch path (see ``_maybe_enqueue_root_autonomy_tick``).
        """
        from src.infrastructure.agent.workspace import worker_launch as worker_launch_mod

        metadata = dict(getattr(task, "metadata", {}) or {})
        task_role = metadata.get(TASK_ROLE)
        if task_role not in {"execution", "execution_task"}:
            return
        worker_agent_id = getattr(task, "assignee_agent_id", None)
        if not worker_agent_id:
            return
        worker_launch_mod.schedule_worker_session(
            workspace_id=task.workspace_id,
            task=task,
            worker_agent_id=worker_agent_id,
            actor_user_id=actor_user_id,
            leader_agent_id=actor_agent_id,
        )

    def _maybe_enqueue_root_autonomy_tick(
        self,
        *,
        task: WorkspaceTask,
        actor_user_id: str,
    ) -> None:
        """Queue an autonomy tick when a new ``goal_root`` task is created.

        Root goals otherwise have no "first activation" trigger: the idle waker
        is opt-in (``WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED``, default off) and
        ``apply_workspace_worker_report`` only fires on worker terminal reports,
        which requires the root to already have children. Without this enqueue,
        a freshly-created root goal sits at TODO indefinitely.
        """
        metadata = dict(getattr(task, "metadata", {}) or {})
        if metadata.get(TASK_ROLE) != _GOAL_ROOT_ROLE:
            return
        self._pending_autonomy_ticks.append((task.workspace_id, actor_user_id))

    async def create_task(  # noqa: PLR0913
        self,
        workspace_id: str,
        actor_user_id: str,
        title: str,
        description: str | None = None,
        assignee_user_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        priority: WorkspaceTaskPriority | None = None,
        estimated_effort: str | None = None,
        blocker_reason: str | None = None,
        actor_type: str = "human",
        actor_agent_id: str | None = None,
        workspace_agent_binding_id: str | None = None,
        reason: str | None = None,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.create_task(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            title=title,
            description=description,
            assignee_user_id=assignee_user_id,
            metadata=metadata,
            priority=priority,
            estimated_effort=estimated_effort,
            blocker_reason=blocker_reason,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
            authority=authority,
        )
        if task.assignee_user_id or task.assignee_agent_id:
            self._queue_assigned(task)
        self._queue_task_snapshot(task, AgentEventType.WORKSPACE_TASK_CREATED)
        self._maybe_enqueue_root_autonomy_tick(task=task, actor_user_id=actor_user_id)
        await self.queue_root_snapshot_async(
            workspace_id,
            actor_user_id,
            task.metadata.get(ROOT_GOAL_TASK_ID)
            if isinstance(task.metadata.get(ROOT_GOAL_TASK_ID), str)
            else None,
        )
        return task

    async def update_task(  # noqa: PLR0913
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
        estimated_effort: str | None = None,
        blocker_reason: str | None = None,
        actor_type: str = "human",
        actor_agent_id: str | None = None,
        workspace_agent_binding_id: str | None = None,
        reason: str | None = None,
        authority: WorkspaceTaskAuthorityContext | None = None,
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
            estimated_effort=estimated_effort,
            blocker_reason=blocker_reason,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
            authority=authority,
        )
        if assignee_user_id is not None:
            self._queue_assigned(task)
        self._queue_task_snapshot(task, AgentEventType.WORKSPACE_TASK_UPDATED)
        await self.queue_root_snapshot_async(
            workspace_id,
            actor_user_id,
            task.metadata.get(ROOT_GOAL_TASK_ID)
            if isinstance(task.metadata.get(ROOT_GOAL_TASK_ID), str)
            else None,
        )
        return task

    async def delete_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> bool:
        root_goal_task_id = await self._task_service.get_root_goal_task_id(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        deleted = await self._task_service.delete_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            authority=authority,
        )
        if deleted:
            self._pending_events.append(
                PendingWorkspaceTaskEvent(
                    workspace_id=workspace_id,
                    event_type=AgentEventType.WORKSPACE_TASK_DELETED,
                    payload={"task_id": task_id},
                )
            )
            await self.queue_root_snapshot_async(workspace_id, actor_user_id, root_goal_task_id)
        return deleted

    async def assign_task_to_agent(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        workspace_agent_id: str,
        actor_type: str = "human",
        actor_agent_id: str | None = None,
        reason: str | None = None,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.assign_task_to_agent(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            workspace_agent_id=workspace_agent_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            reason=reason,
            authority=authority,
        )
        self._queue_assigned(task, workspace_agent_id=workspace_agent_id)
        await self.queue_root_snapshot_async(
            workspace_id,
            actor_user_id,
            task.metadata.get(ROOT_GOAL_TASK_ID)
            if isinstance(task.metadata.get(ROOT_GOAL_TASK_ID), str)
            else None,
        )
        return task

    async def unassign_task_from_agent(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        actor_type: str = "human",
        actor_agent_id: str | None = None,
        workspace_agent_binding_id: str | None = None,
        reason: str | None = None,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.unassign_task_from_agent(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
            authority=authority,
        )
        self._queue_task_snapshot(task, AgentEventType.WORKSPACE_TASK_UPDATED)
        await self.queue_root_snapshot_async(
            workspace_id,
            actor_user_id,
            task.metadata.get(ROOT_GOAL_TASK_ID)
            if isinstance(task.metadata.get(ROOT_GOAL_TASK_ID), str)
            else None,
        )
        return task

    async def claim_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        actor_type: str = "human",
        actor_agent_id: str | None = None,
        workspace_agent_binding_id: str | None = None,
        reason: str | None = None,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.claim_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
            authority=authority,
        )
        self._queue_task_snapshot(task, AgentEventType.WORKSPACE_TASK_UPDATED)
        await self.queue_root_snapshot_async(
            workspace_id,
            actor_user_id,
            task.metadata.get(ROOT_GOAL_TASK_ID)
            if isinstance(task.metadata.get(ROOT_GOAL_TASK_ID), str)
            else None,
        )
        return task

    async def start_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        actor_type: str = "human",
        actor_agent_id: str | None = None,
        workspace_agent_binding_id: str | None = None,
        reason: str | None = None,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.start_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
            authority=authority,
        )
        self._queue_status_changed(task)
        await self.queue_root_snapshot_async(
            workspace_id,
            actor_user_id,
            task.metadata.get(ROOT_GOAL_TASK_ID)
            if isinstance(task.metadata.get(ROOT_GOAL_TASK_ID), str)
            else None,
        )
        return task

    async def block_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        actor_type: str = "human",
        actor_agent_id: str | None = None,
        workspace_agent_binding_id: str | None = None,
        reason: str | None = None,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.block_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
            authority=authority,
        )
        self._queue_status_changed(task)
        await self.queue_root_snapshot_async(
            workspace_id,
            actor_user_id,
            task.metadata.get(ROOT_GOAL_TASK_ID)
            if isinstance(task.metadata.get(ROOT_GOAL_TASK_ID), str)
            else None,
        )
        return task

    async def complete_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        actor_type: str = "human",
        actor_agent_id: str | None = None,
        workspace_agent_binding_id: str | None = None,
        reason: str | None = None,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> WorkspaceTask:
        task = await self._task_service.complete_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
            authority=authority,
        )
        self._queue_status_changed(task)
        await self.queue_root_snapshot_async(
            workspace_id,
            actor_user_id,
            task.metadata.get(ROOT_GOAL_TASK_ID)
            if isinstance(task.metadata.get(ROOT_GOAL_TASK_ID), str)
            else None,
        )
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

    def _queue_assigned(
        self, task: WorkspaceTask, *, workspace_agent_id: str | None = None
    ) -> None:
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

    async def queue_root_snapshot_async(
        self,
        workspace_id: str,
        actor_user_id: str,
        root_goal_task_id: str | None,
    ) -> None:
        if not root_goal_task_id:
            return
        try:
            root_task = await self._task_service.get_task(
                workspace_id=workspace_id,
                task_id=root_goal_task_id,
                actor_user_id=actor_user_id,
            )
        except Exception:
            return
        self._queue_task_snapshot(root_task, AgentEventType.WORKSPACE_TASK_UPDATED)
