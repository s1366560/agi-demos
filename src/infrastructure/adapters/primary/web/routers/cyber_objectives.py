"""Workspace Core-owned cyber-objective HTTP contract declarations."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from src.application.schemas.workspace_cyber_schemas import (
    CyberObjectiveCreate,
    CyberObjectiveListResponse,
    CyberObjectiveResponse,
    CyberObjectiveUpdate,
)
from src.domain.model.workspace.cyber_objective import CyberObjectiveType
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_tasks import WorkspaceTaskResponse
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.models import User

PreferredLanguage = Literal["en-US", "zh-CN"]


class ProjectObjectiveToTaskRequest(BaseModel):
    preferred_language: PreferredLanguage | None = None


router = APIRouter(
    prefix=(
        "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives"
    ),
    tags=["cyber-objectives"],
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
    current_user: User = Depends(get_current_user),
) -> CyberObjectiveResponse:
    raise workspace_core_unavailable_error()


@router.get("", response_model=CyberObjectiveListResponse)
async def list_objectives(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    obj_type: CyberObjectiveType | None = None,
    parent_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> CyberObjectiveListResponse:
    raise workspace_core_unavailable_error()


@router.get("/{objective_id}", response_model=CyberObjectiveResponse)
async def get_objective(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    objective_id: str,
    current_user: User = Depends(get_current_user),
) -> CyberObjectiveResponse:
    raise workspace_core_unavailable_error()


@router.patch("/{objective_id}", response_model=CyberObjectiveResponse)
async def update_objective(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    objective_id: str,
    payload: CyberObjectiveUpdate,
    current_user: User = Depends(get_current_user),
) -> CyberObjectiveResponse:
    raise workspace_core_unavailable_error()


@router.delete(
    "/{objective_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_objective(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    objective_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    raise workspace_core_unavailable_error()


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
    body: ProjectObjectiveToTaskRequest | None = None,
    current_user: User = Depends(get_current_user),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()
