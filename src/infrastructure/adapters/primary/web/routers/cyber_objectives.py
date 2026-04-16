from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_cyber_schemas import (
    CyberObjectiveCreate,
    CyberObjectiveListResponse,
    CyberObjectiveResponse,
    CyberObjectiveUpdate,
)
from src.application.services.workspace_agent_autonomy import (
    build_projected_objective_root_metadata,
)
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_event_publisher import WorkspaceTaskEventPublisher
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.domain.model.workspace.cyber_objective import (
    CyberObjective,
    CyberObjectiveType,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.utils import (
    get_container_with_db,
)
from src.infrastructure.adapters.primary.web.routers.workspace_tasks import (
    WorkspaceTaskResponse,
    _to_response as _task_to_response,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix=(
        "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives"
    ),
    tags=["cyber-objectives"],
)


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


def _get_workspace_task_event_publisher(request: Request) -> WorkspaceTaskEventPublisher:
    return WorkspaceTaskEventPublisher(request.app.state.container.redis())


def _to_response(obj: CyberObjective) -> CyberObjectiveResponse:
    return CyberObjectiveResponse(
        id=obj.id,
        workspace_id=obj.workspace_id,
        title=obj.title,
        description=obj.description,
        obj_type=obj.obj_type,
        parent_id=obj.parent_id,
        progress=obj.progress,
        created_by=obj.created_by,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


@router.post(
    "",
    response_model=CyberObjectiveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_objective(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: CyberObjectiveCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CyberObjectiveResponse:
    container = get_container_with_db(request, db)
    repo = container.cyber_objective_repository()
    objective = CyberObjective(
        workspace_id=workspace_id,
        title=payload.title,
        description=payload.description,
        obj_type=payload.obj_type,
        parent_id=payload.parent_id,
        progress=payload.progress,
        created_by=current_user.id,
    )
    saved = await repo.save(objective)
    await db.commit()
    return _to_response(saved)


@router.get("", response_model=CyberObjectiveListResponse)
async def list_objectives(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    obj_type: CyberObjectiveType | None = None,
    parent_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CyberObjectiveListResponse:
    container = get_container_with_db(request, db)
    repo = container.cyber_objective_repository()
    obj_type_str = obj_type.value if obj_type is not None else None
    items = await repo.find_by_workspace(
        workspace_id=workspace_id,
        obj_type=obj_type_str,
        parent_id=parent_id,
        limit=limit,
        offset=offset,
    )
    return CyberObjectiveListResponse(
        items=[_to_response(item) for item in items],
        total=len(items),
    )


@router.get("/{objective_id}", response_model=CyberObjectiveResponse)
async def get_objective(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    objective_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CyberObjectiveResponse:
    container = get_container_with_db(request, db)
    repo = container.cyber_objective_repository()
    obj = await repo.find_by_id(objective_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objective not found",
        )
    return _to_response(obj)


@router.patch("/{objective_id}", response_model=CyberObjectiveResponse)
async def update_objective(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    objective_id: str,
    payload: CyberObjectiveUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CyberObjectiveResponse:
    container = get_container_with_db(request, db)
    repo = container.cyber_objective_repository()
    obj = await repo.find_by_id(objective_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objective not found",
        )
    if payload.title is not None:
        obj.title = payload.title
    if payload.description is not None:
        obj.description = payload.description
    if payload.obj_type is not None:
        obj.obj_type = payload.obj_type
    if payload.parent_id is not None:
        obj.parent_id = payload.parent_id
    if payload.progress is not None:
        obj.progress = payload.progress
    obj.updated_at = datetime.now(UTC)
    saved = await repo.save(obj)
    await db.commit()
    return _to_response(saved)


@router.delete(
    "/{objective_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_objective(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    objective_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    container = get_container_with_db(request, db)
    repo = container.cyber_objective_repository()
    obj = await repo.find_by_id(objective_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objective not found",
        )
    await repo.delete(objective_id)
    await db.commit()


@router.post(
    "/{objective_id}/project-to-task",
    response_model=WorkspaceTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def project_objective_to_task(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    objective_id: str,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    del tenant_id, project_id
    container = get_container_with_db(request, db)
    objective_repo = container.cyber_objective_repository()
    task_repo = container.workspace_task_repository()
    task_service = _get_workspace_task_service(request, db)
    objective = await objective_repo.find_by_id(objective_id)
    if objective is None or objective.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Objective not found",
        )

    try:
        await task_service.list_tasks(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            limit=1,
            offset=0,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    existing_task = await task_repo.find_root_by_objective_id(workspace_id, objective_id)
    if existing_task is not None:
        response.status_code = status.HTTP_200_OK
        return _task_to_response(existing_task)

    command_service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        task = await command_service.create_task(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            title=objective.title,
            description=objective.description,
            metadata=build_projected_objective_root_metadata(objective),
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    try:
        await event_publisher.publish_pending_events(command_service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish projected objective workspace task events",
            extra={"workspace_id": workspace_id, "objective_id": objective_id},
        )
    return _task_to_response(task)
