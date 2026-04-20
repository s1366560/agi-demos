"""Materialize sensed workspace goal candidates into executable root tasks."""

from __future__ import annotations

from src.application.schemas.workspace_agent_autonomy import GoalCandidateRecordModel
from src.application.services.workspace_agent_autonomy import (
    build_inferred_goal_root_metadata,
    build_projected_objective_root_metadata,
)
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.domain.ports.repositories.workspace.cyber_objective_repository import (
    CyberObjectiveRepository,
)
from src.domain.ports.repositories.workspace.workspace_task_repository import (
    WorkspaceTaskRepository,
)


class WorkspaceGoalMaterializationService:
    """Turn ranked goal candidates into authoritative root tasks when allowed."""

    def __init__(
        self,
        *,
        objective_repo: CyberObjectiveRepository,
        task_repo: WorkspaceTaskRepository,
        task_service: WorkspaceTaskService,
        task_command_service: WorkspaceTaskCommandService,
    ) -> None:
        self._objective_repo = objective_repo
        self._task_repo = task_repo
        self._task_service = task_service
        self._task_command_service = task_command_service

    async def materialize_candidate(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        candidate: GoalCandidateRecordModel,
    ) -> WorkspaceTask | None:
        if candidate.decision == "reject_as_non_goal":
            return None

        if candidate.decision == "adopt_existing_goal":
            return await self._materialize_existing_goal(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                candidate=candidate,
            )

        if candidate.decision == "formalize_new_goal":
            return await self._task_command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=candidate.candidate_text,
                metadata=build_inferred_goal_root_metadata(candidate),
                actor_type="agent",
                reason="workspace_goal_candidate.formalize",
            )

        return None

    async def _materialize_existing_goal(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        candidate: GoalCandidateRecordModel,
    ) -> WorkspaceTask | None:
        for source_ref in candidate.source_refs:
            if source_ref.startswith("task:"):
                task_id = source_ref.split(":", 1)[1]
                return await self._task_service.get_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                )
            if source_ref.startswith("objective:"):
                objective_id = source_ref.split(":", 1)[1]
                existing = await self._task_repo.find_root_by_objective_id(
                    workspace_id, objective_id
                )
                if existing is not None:
                    return existing

                objective = await self._objective_repo.find_by_id(objective_id)
                if objective is None or objective.workspace_id != workspace_id:
                    continue
                return await self._task_command_service.create_task(
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                    title=objective.title,
                    description=objective.description,
                    metadata=build_projected_objective_root_metadata(objective),
                    actor_type="agent",
                    reason="workspace_goal_candidate.project_objective",
                )
        return None
