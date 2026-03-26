"""Application service for workspace task lifecycle and delegation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository
from src.domain.ports.repositories.workspace.workspace_task_repository import (
    WorkspaceTaskRepository,
)


class WorkspaceTaskService:
    """Orchestrates workspace task CRUD, assignment, and state transitions."""

    def __init__(
        self,
        workspace_repo: WorkspaceRepository,
        workspace_member_repo: WorkspaceMemberRepository,
        workspace_agent_repo: WorkspaceAgentRepository,
        workspace_task_repo: WorkspaceTaskRepository,
    ) -> None:
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo
        self._workspace_agent_repo = workspace_agent_repo
        self._workspace_task_repo = workspace_task_repo

    async def create_task(
        self,
        workspace_id: str,
        actor_user_id: str,
        title: str,
        description: str | None = None,
        assignee_user_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to create workspace task",
        )

        now = datetime.now(UTC)
        task = WorkspaceTask(
            id=WorkspaceTask.generate_id(),
            workspace_id=workspace.id,
            title=title,
            description=description,
            created_by=actor_user_id,
            assignee_user_id=assignee_user_id,
            status=WorkspaceTaskStatus.TODO,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        return await self._workspace_task_repo.save(task)

    async def list_tasks(
        self,
        workspace_id: str,
        actor_user_id: str,
        status: WorkspaceTaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceTask]:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._workspace_task_repo.find_by_workspace(
            workspace_id=workspace.id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def get_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._require_task(workspace_id=workspace.id, task_id=task_id)

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
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to update workspace task",
        )
        task = await self._require_task(workspace_id=workspace.id, task_id=task_id)

        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if assignee_user_id is not None:
            task.assignee_user_id = assignee_user_id
            task.assignee_agent_id = None
        if metadata is not None:
            task.metadata = dict(metadata)
        if status is not None and status != task.status:
            self._validate_transition(task.status, status)
            task.status = status

        task.updated_at = datetime.now(UTC)
        return await self._workspace_task_repo.save(task)

    async def delete_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> bool:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to delete workspace task",
        )
        task = await self._require_task(workspace_id=workspace.id, task_id=task_id)
        return await self._workspace_task_repo.delete(task.id)

    async def assign_task_to_agent(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        workspace_agent_id: str,
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to assign workspace task",
        )
        task = await self._require_task(workspace.id, task_id)
        relation = await self._workspace_agent_repo.find_by_id(workspace_agent_id)
        if relation is None:
            raise ValueError(f"Workspace agent binding {workspace_agent_id} not found")
        if relation.workspace_id != workspace.id:
            raise ValueError("Workspace agent binding does not belong to workspace")
        if not relation.is_active:
            raise ValueError("Workspace agent binding must be active for assignment")

        task.assignee_agent_id = relation.agent_id
        task.assignee_user_id = None
        task.updated_at = datetime.now(UTC)
        return await self._workspace_task_repo.save(task)

    async def unassign_task_from_agent(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to unassign workspace task",
        )
        task = await self._require_task(workspace.id, task_id)
        task.assignee_agent_id = None
        task.updated_at = datetime.now(UTC)
        return await self._workspace_task_repo.save(task)

    async def claim_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        task = await self._require_task(workspace.id, task_id)
        if task.status == WorkspaceTaskStatus.DONE:
            raise ValueError("Cannot claim a completed task")
        if task.assignee_user_id and task.assignee_user_id != actor_user_id:
            raise ValueError("Task is already claimed by another user")

        task.assignee_user_id = actor_user_id
        task.assignee_agent_id = None
        task.updated_at = datetime.now(UTC)
        return await self._workspace_task_repo.save(task)

    async def start_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        task = await self._require_task(workspace.id, task_id)
        self._apply_transition(task, WorkspaceTaskStatus.IN_PROGRESS)
        return await self._workspace_task_repo.save(task)

    async def block_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        task = await self._require_task(workspace.id, task_id)
        self._apply_transition(task, WorkspaceTaskStatus.BLOCKED)
        return await self._workspace_task_repo.save(task)

    async def complete_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> WorkspaceTask:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        task = await self._require_task(workspace.id, task_id)
        self._apply_transition(task, WorkspaceTaskStatus.DONE)
        return await self._workspace_task_repo.save(task)

    async def _require_workspace(self, workspace_id: str) -> Workspace:
        workspace = await self._workspace_repo.find_by_id(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id} not found")
        return workspace

    async def _require_membership(self, workspace_id: str, user_id: str) -> WorkspaceMember:
        member = await self._workspace_member_repo.find_by_workspace_and_user(
            workspace_id=workspace_id, user_id=user_id
        )
        if member is None:
            raise PermissionError("User must be a workspace member")
        return member

    async def _require_minimum_role(
        self,
        workspace_id: str,
        user_id: str,
        minimum: WorkspaceRole,
        error_message: str,
    ) -> None:
        member = await self._require_membership(workspace_id=workspace_id, user_id=user_id)
        if self._role_weight(member.role) < self._role_weight(minimum):
            raise PermissionError(error_message)

    async def _require_task(self, workspace_id: str, task_id: str) -> WorkspaceTask:
        task = await self._workspace_task_repo.find_by_id(task_id)
        if task is None:
            raise ValueError(f"Workspace task {task_id} not found")
        if task.workspace_id != workspace_id:
            raise ValueError("Workspace task does not belong to workspace")
        return task

    @staticmethod
    def _role_weight(role: WorkspaceRole) -> int:
        if role == WorkspaceRole.OWNER:
            return 300
        if role == WorkspaceRole.EDITOR:
            return 200
        return 100

    @staticmethod
    def _validate_transition(from_status: WorkspaceTaskStatus, to_status: WorkspaceTaskStatus) -> None:
        allowed: dict[WorkspaceTaskStatus, set[WorkspaceTaskStatus]] = {
            WorkspaceTaskStatus.TODO: {WorkspaceTaskStatus.IN_PROGRESS, WorkspaceTaskStatus.BLOCKED},
            WorkspaceTaskStatus.IN_PROGRESS: {WorkspaceTaskStatus.BLOCKED, WorkspaceTaskStatus.DONE},
            WorkspaceTaskStatus.BLOCKED: {WorkspaceTaskStatus.IN_PROGRESS, WorkspaceTaskStatus.DONE},
            WorkspaceTaskStatus.DONE: set(),
        }
        if to_status not in allowed[from_status]:
            raise ValueError(f"Cannot transition task status from {from_status.value} to {to_status.value}")

    def _apply_transition(self, task: WorkspaceTask, target: WorkspaceTaskStatus) -> None:
        self._validate_transition(task.status, target)
        task.status = target
        task.updated_at = datetime.now(UTC)
