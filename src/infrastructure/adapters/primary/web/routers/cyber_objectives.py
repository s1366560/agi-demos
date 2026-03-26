from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_cyber_schemas import (
    CyberObjectiveCreate,
    CyberObjectiveListResponse,
    CyberObjectiveResponse,
    CyberObjectiveUpdate,
)
from src.domain.model.workspace.cyber_objective import (
    CyberObjective,
    CyberObjectiveType,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.utils import (
    get_container_with_db,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(
    prefix=(
        "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives"
    ),
    tags=["cyber-objectives"],
)


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
