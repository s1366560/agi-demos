"""Application service for workspace task lifecycle and delegation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Literal

from src.application.services.workspace_agent_autonomy import (
    ensure_goal_completion_allowed_for_workspace,
    ensure_root_goal_mutation_allowed,
    is_autonomy_task,
    is_goal_root_task,
    merge_validated_metadata,
    reconcile_root_goal_progress,
    record_task_actor,
    validate_autonomy_metadata,
)
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
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
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    EXECUTION_STATE,
    LAST_WORKER_REPORT_SUMMARY,
    PENDING_LEADER_ADJUDICATION,
    ROOT_GOAL_TASK_ID,
    WORKSPACE_AGENT_BINDING_ID,
)


@dataclass(frozen=True)
class WorkspaceTaskAuthorityContext:
    role: Literal["default", "leader", "worker"] = "default"
    actor_agent_id: str | None = None

    @classmethod
    def leader(cls, actor_agent_id: str | None) -> WorkspaceTaskAuthorityContext:
        return cls(role="leader", actor_agent_id=actor_agent_id)

    @classmethod
    def worker(cls, actor_agent_id: str | None) -> WorkspaceTaskAuthorityContext:
        return cls(role="worker", actor_agent_id=actor_agent_id)


class WorkspaceTaskService:
    """Orchestrates workspace task CRUD, assignment, and state transitions."""

    _PUBLIC_PRIORITY_TO_INTERNAL: ClassVar[dict[str, int]] = {
        "": 0,
        "P1": 1,
        "P2": 2,
        "P3": 3,
        "P4": 4,
    }
    _WORKER_ALLOWED_METADATA_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            EXECUTION_STATE,
            "evidence_refs",
            "execution_verifications",
            "last_worker_report_type",
            LAST_WORKER_REPORT_SUMMARY,
            "last_worker_report_artifacts",
            "last_worker_report_verifications",
            "last_worker_reported_at",
            "last_worker_report_fingerprint",
            "last_worker_report_id",
            PENDING_LEADER_ADJUDICATION,
            CURRENT_ATTEMPT_ID,
            "last_attempt_id",
            "current_attempt_number",
            "last_attempt_status",
            "last_mutation_actor",
        }
    )

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
            priority=priority or WorkspaceTaskPriority.NONE,
            estimated_effort=estimated_effort,
            blocker_reason=blocker_reason,
            metadata=merge_validated_metadata({}, metadata),
            created_at=now,
            updated_at=now,
        )
        record_task_actor(
            task,
            action="create",
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
        )
        saved = await self._workspace_task_repo.save(task)
        await self._reconcile_root_goal_if_needed(saved)
        return saved

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

    async def get_root_goal_task_id(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> str | None:
        task = await self.get_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        value = task.metadata.get(ROOT_GOAL_TASK_ID)
        return value if isinstance(value, str) and value else None

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
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to update workspace task",
        )
        task = await self._require_task(workspace_id=workspace.id, task_id=task_id)
        authority_ctx = authority or WorkspaceTaskAuthorityContext()
        self._ensure_update_allowed(
            task=task,
            authority=authority_ctx,
            title=title,
            description=description,
            assignee_user_id=assignee_user_id,
            status=status,
            metadata=metadata,
            priority=priority,
            estimated_effort=estimated_effort,
            blocker_reason=blocker_reason,
        )
        ensure_root_goal_mutation_allowed(
            task,
            title=title,
            description=description,
            metadata=metadata,
        )

        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if assignee_user_id is not None:
            task.assignee_user_id = assignee_user_id
            task.assignee_agent_id = None
        if metadata is not None:
            task.metadata = merge_validated_metadata(task.metadata, metadata)
        if priority is not None:
            task.priority = priority
        if estimated_effort is not None:
            task.estimated_effort = estimated_effort
        if blocker_reason is not None:
            task.blocker_reason = blocker_reason
        record_task_actor(
            task,
            action="update",
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
        )
        if status is not None and status != task.status:
            if status == WorkspaceTaskStatus.DONE:
                ensure_goal_completion_allowed_for_workspace(
                    task,
                    workspace_metadata=workspace.metadata,
                )
            await self._ensure_transition_allowed(
                workspace_id=workspace.id,
                task=task,
                target=status,
                authority=authority_ctx,
            )
            self._apply_transition(task, status)
            if status is not WorkspaceTaskStatus.BLOCKED:
                task.blocker_reason = None
            saved = await self._workspace_task_repo.save(task)
            await self._reconcile_root_goal_if_needed(saved)
            return saved

        task.updated_at = datetime.now(UTC)
        saved = await self._workspace_task_repo.save(task)
        await self._reconcile_root_goal_if_needed(saved)
        return saved

    async def delete_task(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        authority: WorkspaceTaskAuthorityContext | None = None,
    ) -> bool:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to delete workspace task",
        )
        task = await self._require_task(workspace_id=workspace.id, task_id=task_id)
        self._ensure_structural_mutation_allowed(
            task=task,
            authority=authority or WorkspaceTaskAuthorityContext(),
            action="delete",
        )
        root_goal_task_id = self._root_goal_task_id(task)
        deleted = await self._workspace_task_repo.delete(task.id)
        if deleted and root_goal_task_id:
            await reconcile_root_goal_progress(
                task_repo=self._workspace_task_repo,
                workspace_id=workspace.id,
                root_goal_task_id=root_goal_task_id,
            )
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
        self._ensure_structural_mutation_allowed(
            task=task,
            authority=authority or WorkspaceTaskAuthorityContext(),
            action="assign_agent",
        )

        task.assignee_agent_id = relation.agent_id
        task.assignee_user_id = None
        self._set_workspace_agent_binding_id(task, workspace_agent_id)
        task.updated_at = datetime.now(UTC)
        record_task_actor(
            task,
            action="assign_agent",
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id or relation.agent_id,
            workspace_agent_binding_id=workspace_agent_id,
            reason=reason,
        )
        saved = await self._workspace_task_repo.save(task)
        await self._reconcile_root_goal_if_needed(saved)
        return saved

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
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to unassign workspace task",
        )
        task = await self._require_task(workspace.id, task_id)
        self._ensure_structural_mutation_allowed(
            task=task,
            authority=authority or WorkspaceTaskAuthorityContext(),
            action="unassign_agent",
        )
        task.assignee_agent_id = None
        self._clear_workspace_agent_binding_id(task)
        task.updated_at = datetime.now(UTC)
        record_task_actor(
            task,
            action="unassign_agent",
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
        )
        saved = await self._workspace_task_repo.save(task)
        await self._reconcile_root_goal_if_needed(saved)
        return saved

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
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        task = await self._require_task(workspace.id, task_id)
        self._ensure_structural_mutation_allowed(
            task=task,
            authority=authority or WorkspaceTaskAuthorityContext(),
            action="claim",
        )
        if task.status == WorkspaceTaskStatus.DONE:
            raise ValueError("Cannot claim a completed task")
        if task.assignee_user_id and task.assignee_user_id != actor_user_id:
            raise ValueError("Task is already claimed by another user")

        task.assignee_user_id = actor_user_id
        task.assignee_agent_id = None
        self._clear_workspace_agent_binding_id(task)
        task.updated_at = datetime.now(UTC)
        record_task_actor(
            task,
            action="claim",
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
        )
        saved = await self._workspace_task_repo.save(task)
        await self._reconcile_root_goal_if_needed(saved)
        return saved

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
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        task = await self._require_task(workspace.id, task_id)
        await self._ensure_transition_allowed(
            workspace_id=workspace.id,
            task=task,
            target=WorkspaceTaskStatus.IN_PROGRESS,
            authority=authority or WorkspaceTaskAuthorityContext(),
        )
        self._apply_transition(task, WorkspaceTaskStatus.IN_PROGRESS)
        record_task_actor(
            task,
            action="start",
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
        )
        saved = await self._workspace_task_repo.save(task)
        await self._reconcile_root_goal_if_needed(saved)
        return saved

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
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        task = await self._require_task(workspace.id, task_id)
        await self._ensure_transition_allowed(
            workspace_id=workspace.id,
            task=task,
            target=WorkspaceTaskStatus.BLOCKED,
            authority=authority or WorkspaceTaskAuthorityContext(),
        )
        self._apply_transition(task, WorkspaceTaskStatus.BLOCKED)
        record_task_actor(
            task,
            action="block",
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
        )
        saved = await self._workspace_task_repo.save(task)
        await self._reconcile_root_goal_if_needed(saved)
        return saved

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
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        task = await self._require_task(workspace.id, task_id)
        await self._ensure_transition_allowed(
            workspace_id=workspace.id,
            task=task,
            target=WorkspaceTaskStatus.DONE,
            authority=authority or WorkspaceTaskAuthorityContext(),
        )
        ensure_goal_completion_allowed_for_workspace(
            task,
            workspace_metadata=workspace.metadata,
        )
        self._apply_transition(task, WorkspaceTaskStatus.DONE)
        record_task_actor(
            task,
            action="complete",
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            actor_agent_id=actor_agent_id,
            workspace_agent_binding_id=workspace_agent_binding_id,
            reason=reason,
        )
        saved = await self._workspace_task_repo.save(task)
        await self._reconcile_root_goal_if_needed(saved)
        return saved

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
    def _validate_transition(
        from_status: WorkspaceTaskStatus, to_status: WorkspaceTaskStatus
    ) -> None:
        allowed: dict[WorkspaceTaskStatus, set[WorkspaceTaskStatus]] = {
            WorkspaceTaskStatus.TODO: {
                WorkspaceTaskStatus.IN_PROGRESS,
                WorkspaceTaskStatus.BLOCKED,
            },
            WorkspaceTaskStatus.IN_PROGRESS: {
                WorkspaceTaskStatus.BLOCKED,
                WorkspaceTaskStatus.DONE,
            },
            WorkspaceTaskStatus.BLOCKED: {
                WorkspaceTaskStatus.IN_PROGRESS,
                WorkspaceTaskStatus.DONE,
            },
            WorkspaceTaskStatus.DONE: set(),
        }
        if to_status not in allowed[from_status]:
            raise ValueError(
                f"Cannot transition task status from {from_status.value} to {to_status.value}"
            )

    def _apply_transition(self, task: WorkspaceTask, target: WorkspaceTaskStatus) -> None:
        self._validate_transition(task.status, target)
        task.status = target
        now = datetime.now(UTC)
        task.updated_at = now
        task.completed_at = now if target == WorkspaceTaskStatus.DONE else None

    async def _reconcile_root_goal_if_needed(self, task: WorkspaceTask) -> None:
        root_goal_task_id = self._root_goal_task_id(task)
        if root_goal_task_id:
            await reconcile_root_goal_progress(
                task_repo=self._workspace_task_repo,
                workspace_id=task.workspace_id,
                root_goal_task_id=root_goal_task_id,
            )

    def _ensure_update_allowed(
        self,
        *,
        task: WorkspaceTask,
        authority: WorkspaceTaskAuthorityContext,
        title: str | None,
        description: str | None,
        assignee_user_id: str | None,
        status: WorkspaceTaskStatus | None,
        metadata: Mapping[str, object] | None,
        priority: WorkspaceTaskPriority | None,
        estimated_effort: str | None,
        blocker_reason: str | None,
    ) -> None:
        if not is_autonomy_task(task):
            return
        if is_goal_root_task(task):
            self._require_leader_authority(authority, "mutate root goal task")
            return
        if authority.role == "leader":
            if status in {WorkspaceTaskStatus.DONE, WorkspaceTaskStatus.BLOCKED}:
                current_attempt_id = task.metadata.get(CURRENT_ATTEMPT_ID)
                if not isinstance(current_attempt_id, str) or not current_attempt_id:
                    raise PermissionError(
                        "Leader must adjudicate a concrete execution attempt before finalizing an execution task"
                    )
            return
        if authority.role != "worker":
            raise PermissionError(
                "Autonomy execution tasks require leader or assigned worker authority"
            )
        self._require_worker_ownership(task, authority)
        if title is not None or description is not None:
            raise PermissionError("Worker cannot rewrite execution task content")
        if assignee_user_id is not None or priority is not None or estimated_effort is not None:
            raise PermissionError(
                "Worker cannot structurally modify execution task ownership or priority"
            )
        if metadata is not None:
            disallowed = set(metadata) - self._WORKER_ALLOWED_METADATA_KEYS
            if disallowed:
                ordered = ", ".join(sorted(disallowed))
                raise PermissionError(
                    f"Worker cannot mutate execution task metadata fields: {ordered}"
                )
        if status is not None and status == WorkspaceTaskStatus.TODO:
            raise PermissionError("Worker cannot reset execution task to todo")
        _ = blocker_reason

    def _ensure_structural_mutation_allowed(
        self,
        *,
        task: WorkspaceTask,
        authority: WorkspaceTaskAuthorityContext,
        action: str,
    ) -> None:
        if not is_autonomy_task(task):
            return
        self._require_leader_authority(authority, f"{action} autonomy task")

    async def _ensure_transition_allowed(
        self,
        *,
        workspace_id: str,
        task: WorkspaceTask,
        target: WorkspaceTaskStatus,
        authority: WorkspaceTaskAuthorityContext,
    ) -> None:
        if not is_autonomy_task(task):
            return
        if is_goal_root_task(task):
            self._require_leader_authority(authority, f"transition root goal to {target.value}")
            return
        if target == WorkspaceTaskStatus.IN_PROGRESS:
            await self._ensure_root_not_todo_for_child_start(workspace_id=workspace_id, task=task)
        if authority.role == "leader":
            if target in {WorkspaceTaskStatus.DONE, WorkspaceTaskStatus.BLOCKED}:
                current_attempt_id = task.metadata.get(CURRENT_ATTEMPT_ID)
                if not isinstance(current_attempt_id, str) or not current_attempt_id:
                    raise PermissionError(
                        "Leader must adjudicate a concrete execution attempt before finalizing an execution task"
                    )
            return
        if authority.role != "worker":
            raise PermissionError(
                "Autonomy execution task transitions require leader or assigned worker authority"
            )
        self._require_worker_ownership(task, authority)
        if target != WorkspaceTaskStatus.IN_PROGRESS:
            raise PermissionError(
                "Only workspace plan leader authority may finalize or block execution tasks"
            )

    async def _ensure_root_not_todo_for_child_start(
        self,
        *,
        workspace_id: str,
        task: WorkspaceTask,
    ) -> None:
        root_goal_task_id = self._root_goal_task_id(task)
        if root_goal_task_id is None:
            return
        root_task = await self._workspace_task_repo.find_by_id(root_goal_task_id)
        if root_task is None or root_task.workspace_id != workspace_id:
            return
        root_status = getattr(root_task.status, "value", root_task.status)
        if root_status == WorkspaceTaskStatus.TODO.value:
            raise PermissionError(
                "Root goal must leave todo before a child task enters in_progress"
            )

    @staticmethod
    def _require_leader_authority(
        authority: WorkspaceTaskAuthorityContext,
        action: str,
    ) -> None:
        if authority.role != "leader":
            raise PermissionError(f"Only workspace plan leader authority may {action}")

    @staticmethod
    def _require_worker_ownership(
        task: WorkspaceTask,
        authority: WorkspaceTaskAuthorityContext,
    ) -> None:
        if not authority.actor_agent_id or task.assignee_agent_id != authority.actor_agent_id:
            raise PermissionError("Only the assigned worker may mutate this execution task")

    @staticmethod
    def _set_workspace_agent_binding_id(
        task: WorkspaceTask, workspace_agent_binding_id: str
    ) -> None:
        metadata = dict(task.metadata)
        metadata[WORKSPACE_AGENT_BINDING_ID] = workspace_agent_binding_id
        task.metadata = validate_autonomy_metadata(metadata)

    @staticmethod
    def _clear_workspace_agent_binding_id(task: WorkspaceTask) -> None:
        metadata = dict(task.metadata)
        metadata.pop(WORKSPACE_AGENT_BINDING_ID, None)
        task.metadata = validate_autonomy_metadata(metadata)

    @staticmethod
    def _root_goal_task_id(task: WorkspaceTask) -> str | None:
        value = task.metadata.get(ROOT_GOAL_TASK_ID)
        return value if isinstance(value, str) and value else None

    @classmethod
    def _parse_public_priority(cls, priority: str) -> int:
        normalized = priority.strip().upper()
        if normalized not in cls._PUBLIC_PRIORITY_TO_INTERNAL:
            allowed = ", ".join(repr(value) for value in cls._PUBLIC_PRIORITY_TO_INTERNAL)
            raise ValueError(f"Unsupported priority {priority!r}. Expected one of: {allowed}")
        return cls._PUBLIC_PRIORITY_TO_INTERNAL[normalized]
