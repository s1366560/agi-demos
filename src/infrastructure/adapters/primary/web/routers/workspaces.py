"""Workspace Core-owned lifecycle, member, and agent binding HTTP contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_agent_autonomy import AutonomyProfileModel
from src.application.schemas.workspace_collaboration_capabilities import (
    WorkspaceCollaborationCapabilitiesResponse,
)
from src.application.services.workspace_layout_limits import MAX_WORKSPACE_HEX_COORDINATE
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db as _get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    tags=["workspaces"],
)

WorkspaceUseCase = Literal["general", "programming", "conversation", "research", "operations"]
WorkspaceCollaborationMode = Literal[
    "single_agent",
    "multi_agent_shared",
    "multi_agent_isolated",
    "autonomous",
]


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    use_case: WorkspaceUseCase | None = None
    collaboration_mode: WorkspaceCollaborationMode | None = None
    autonomy_profile: AutonomyProfileModel | None = None
    sandbox_code_root: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    is_archived: bool | None = None
    metadata: dict[str, Any] | None = None


class WorkspaceResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    name: str
    created_by: str
    description: str | None
    is_archived: bool
    metadata: dict[str, Any]
    office_status: str
    hex_layout_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None


class WorkspaceMemberCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: WorkspaceRole = WorkspaceRole.VIEWER


class WorkspaceMemberUpdateRequest(BaseModel):
    role: WorkspaceRole


class WorkspaceMemberResponse(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    user_email: str | None = None
    role: WorkspaceRole
    invited_by: str | None
    created_at: datetime
    updated_at: datetime | None


class WorkspaceAgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    display_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    hex_q: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    hex_r: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    theme_color: str | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=64)


class WorkspaceAgentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    config: dict[str, Any] | None = None
    is_active: bool | None = None
    hex_q: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    hex_r: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    theme_color: str | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=64)


class WorkspaceAgentResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    display_name: str | None
    description: str | None
    config: dict[str, Any]
    is_active: bool
    hex_q: int | None
    hex_r: int | None
    theme_color: str | None
    label: str | None
    status: str | None
    created_at: datetime
    updated_at: datetime | None


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    tenant_id: str,
    project_id: str,
    payload: WorkspaceCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceResponse:
    raise workspace_core_unavailable_error()


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    tenant_id: str,
    project_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> list[WorkspaceResponse]:
    raise workspace_core_unavailable_error()


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> WorkspaceResponse:
    raise workspace_core_unavailable_error()


@router.get(
    "/{workspace_id}/collaboration/capabilities",
    response_model=WorkspaceCollaborationCapabilitiesResponse,
)
async def get_workspace_collaboration_capabilities(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> WorkspaceCollaborationCapabilitiesResponse:
    raise workspace_core_unavailable_error()


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceResponse:
    raise workspace_core_unavailable_error()


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> None:
    raise workspace_core_unavailable_error()


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
async def list_workspace_members(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> list[WorkspaceMemberResponse]:
    raise workspace_core_unavailable_error()


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_member(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: WorkspaceMemberCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceMemberResponse:
    raise workspace_core_unavailable_error()


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberResponse)
async def update_workspace_member(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    user_id: str,
    payload: WorkspaceMemberUpdateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceMemberResponse:
    raise workspace_core_unavailable_error()


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workspace_member(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    user_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> None:
    raise workspace_core_unavailable_error()


@router.get("/{workspace_id}/agents", response_model=list[WorkspaceAgentResponse])
async def list_workspace_agents(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    active_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> list[WorkspaceAgentResponse]:
    raise workspace_core_unavailable_error()


@router.post(
    "/{workspace_id}/agents",
    response_model=WorkspaceAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bind_workspace_agent(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: WorkspaceAgentCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceAgentResponse:
    raise workspace_core_unavailable_error()


@router.patch(
    "/{workspace_id}/agents/{workspace_agent_id}",
    response_model=WorkspaceAgentResponse,
)
async def update_workspace_agent(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    workspace_agent_id: str,
    payload: WorkspaceAgentUpdateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceAgentResponse:
    raise workspace_core_unavailable_error()


@router.delete(
    "/{workspace_id}/agents/{workspace_agent_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_workspace_agent(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    workspace_agent_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> None:
    raise workspace_core_unavailable_error()


from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_mutations import (  # noqa: E402
    router as workspace_collaboration_mutation_router,
)

router.include_router(workspace_collaboration_mutation_router)
