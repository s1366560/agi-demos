"""Workspace goal candidate sensing and materialization API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_agent_autonomy import GoalCandidateRecordModel
from src.application.services.workspace_goal_materialization_service import (
    WorkspaceGoalMaterializationService,
)
from src.application.services.workspace_goal_sensing_service import WorkspaceGoalSensingService
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_tasks import (
    WorkspaceTaskResponse,
    _to_response as _task_to_response,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_workspace_message_repository import (
    SqlWorkspaceMessageRepository,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/goal-candidates",
    tags=["workspace-goal-candidates"],
)


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    return request.app.state.container.with_db(db)


def _get_workspace_task_service(request: Request, db: AsyncSession) -> WorkspaceTaskService:
    container = get_container_with_db(request, db)
    return WorkspaceTaskService(
        workspace_repo=container.workspace_repository(),
        workspace_member_repo=container.workspace_member_repository(),
        workspace_agent_repo=container.workspace_agent_repository(),
        workspace_task_repo=container.workspace_task_repository(),
    )


def _get_workspace_task_command_service(
    request: Request, db: AsyncSession
) -> WorkspaceTaskCommandService:
    return WorkspaceTaskCommandService(_get_workspace_task_service(request, db))


@router.get("", response_model=list[GoalCandidateRecordModel])
async def list_workspace_goal_candidates(
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GoalCandidateRecordModel]:
    container = get_container_with_db(request, db)
    task_service = _get_workspace_task_service(request, db)

    try:
        tasks = await task_service.list_tasks(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            limit=100,
            offset=0,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    objective_repo = container.cyber_objective_repository()
    blackboard_repo = container.blackboard_repository()
    message_repo = SqlWorkspaceMessageRepository(db)

    objectives = await objective_repo.find_by_workspace(workspace_id, limit=50)
    posts = await blackboard_repo.list_posts_by_workspace(workspace_id, limit=20)
    messages = await message_repo.find_by_workspace(workspace_id, limit=50)

    return WorkspaceGoalSensingService().sense_candidates(
        tasks=tasks,
        objectives=objectives,
        posts=posts,
        messages=messages,
    )


@router.post("/materialize", response_model=WorkspaceTaskResponse, status_code=status.HTTP_201_CREATED)
async def materialize_workspace_goal_candidate(
    workspace_id: str,
    candidate: GoalCandidateRecordModel,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    container = get_container_with_db(request, db)
    task_service = _get_workspace_task_service(request, db)
    materialization_service = WorkspaceGoalMaterializationService(
        objective_repo=container.cyber_objective_repository(),
        task_repo=container.workspace_task_repository(),
        task_service=task_service,
        task_command_service=_get_workspace_task_command_service(request, db),
    )

    try:
        task = await materialization_service.materialize_candidate(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            candidate=candidate,
        )
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Candidate cannot be materialized",
            )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _task_to_response(task)
