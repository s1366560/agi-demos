"""Workspace lifecycle, member, and agent binding API routes."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_agent_autonomy import AutonomyProfileModel
from src.application.services.workspace_autonomy_profiles import (
    evaluate_workspace_code_context,
    normalize_sandbox_code_root,
)
from src.application.services.workspace_layout_limits import MAX_WORKSPACE_HEX_COORDINATE
from src.application.services.workspace_service import WorkspaceService
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    tags=["workspaces"],
)
logger = logging.getLogger(__name__)


def get_workspace_service(request: Request, db: AsyncSession = Depends(get_db)) -> WorkspaceService:
    """Resolve workspace service from request-scoped DI container."""
    container = request.app.state.container.with_db(db)
    redis_client = container.redis_client

    async def _publish_event(workspace_id: str, event_name: str, payload: dict[str, Any]) -> None:
        from src.domain.events.types import AgentEventType
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event_with_retry,
        )

        event_type = AgentEventType(event_name)
        await publish_workspace_event_with_retry(
            redis_client,
            workspace_id=workspace_id,
            event_type=event_type,
            payload=payload,
        )

    return WorkspaceService(
        workspace_repo=container.workspace_repository(),
        workspace_member_repo=container.workspace_member_repository(),
        workspace_agent_repo=container.workspace_agent_repository(),
        topology_repo=container.topology_repository(),
        workspace_event_publisher=_publish_event if redis_client is not None else None,
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        message = str(exc)
        if "not found" in message.lower():
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


def _ensure_workspace_scope(workspace: Workspace, tenant_id: str, project_id: str) -> None:
    if workspace.tenant_id != tenant_id or workspace.project_id != project_id:
        raise ValueError("Workspace not found")


WorkspaceUseCase = Literal["general", "programming", "conversation", "research", "operations"]
WorkspaceType = Literal["general", "software_development", "research", "operations"]
WorkspaceCollaborationMode = Literal[
    "single_agent",
    "multi_agent_shared",
    "multi_agent_isolated",
    "autonomous",
]

_DEFAULT_WORKSPACE_USE_CASE: WorkspaceUseCase = "general"
_DEFAULT_COLLABORATION_MODE: WorkspaceCollaborationMode = "single_agent"
_USE_CASE_TO_WORKSPACE_TYPE: dict[WorkspaceUseCase, WorkspaceType] = {
    "general": "general",
    "programming": "software_development",
    "conversation": "general",
    "research": "research",
    "operations": "operations",
}
_VALID_USE_CASES = set(_USE_CASE_TO_WORKSPACE_TYPE)
_VALID_COLLABORATION_MODES = {
    "single_agent",
    "multi_agent_shared",
    "multi_agent_isolated",
    "autonomous",
}


def _as_mapping(value: Any) -> Mapping[str, Any]:  # noqa: ANN401
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _coerce_use_case(value: Any) -> WorkspaceUseCase | None:  # noqa: ANN401
    if value == "software_development":
        return "programming"
    if isinstance(value, str) and value in _VALID_USE_CASES:
        return value
    return None


def _coerce_workspace_type(value: Any) -> WorkspaceType | None:  # noqa: ANN401
    if value == "software_development":
        return "software_development"
    if value == "research":
        return "research"
    if value == "operations":
        return "operations"
    if value == "general":
        return "general"
    return None


def _coerce_collaboration_mode(value: Any) -> WorkspaceCollaborationMode | None:  # noqa: ANN401
    if isinstance(value, str) and value in _VALID_COLLABORATION_MODES:
        return cast(WorkspaceCollaborationMode, value)
    return None


def _resolve_use_case(
    explicit: WorkspaceUseCase | None,
    metadata: Mapping[str, Any],
) -> WorkspaceUseCase:
    if explicit is not None:
        return explicit
    profile = _as_mapping(metadata.get("autonomy_profile"))
    for value in (
        metadata.get("workspace_use_case"),
        metadata.get("use_case"),
        metadata.get("workspace_type"),
        profile.get("workspace_type"),
    ):
        use_case = _coerce_use_case(value)
        if use_case is not None:
            return use_case
        workspace_type = _coerce_workspace_type(value)
        if workspace_type == "software_development":
            return "programming"
        if workspace_type in {"research", "operations", "general"}:
            return cast(WorkspaceUseCase, workspace_type)
    return _DEFAULT_WORKSPACE_USE_CASE


def _resolve_collaboration_mode(
    explicit: WorkspaceCollaborationMode | None,
    metadata: Mapping[str, Any],
) -> WorkspaceCollaborationMode:
    if explicit is not None:
        return explicit
    for value in (
        metadata.get("collaboration_mode"),
        metadata.get("agent_conversation_mode"),
    ):
        mode = _coerce_collaboration_mode(value)
        if mode is not None:
            return mode
    return _DEFAULT_COLLABORATION_MODE


def _workspace_type_for_use_case(use_case: WorkspaceUseCase) -> WorkspaceType:
    return _USE_CASE_TO_WORKSPACE_TYPE[use_case]


def _compose_workspace_metadata(payload: WorkspaceCreateRequest) -> dict[str, Any]:
    metadata = dict(payload.metadata or {})
    use_case = _resolve_use_case(payload.use_case, metadata)
    workspace_type = _workspace_type_for_use_case(use_case)
    collaboration_mode = _resolve_collaboration_mode(payload.collaboration_mode, metadata)

    profile = dict(_as_mapping(metadata.get("autonomy_profile")))
    if payload.autonomy_profile is not None:
        profile.update(payload.autonomy_profile.model_dump(exclude_none=True))
    profile["workspace_type"] = workspace_type

    metadata.update(
        {
            "workspace_use_case": use_case,
            "workspace_type": workspace_type,
            "collaboration_mode": collaboration_mode,
            "agent_conversation_mode": collaboration_mode,
            "autonomy_profile": profile,
        }
    )

    sandbox_code_root = normalize_sandbox_code_root(
        payload.sandbox_code_root or metadata.get("sandbox_code_root")
    )
    if sandbox_code_root:
        code_context = dict(_as_mapping(metadata.get("code_context")))
        code_context["sandbox_code_root"] = sandbox_code_root
        metadata["sandbox_code_root"] = sandbox_code_root
        metadata["code_context"] = code_context

    code_context_eval = evaluate_workspace_code_context(
        root_metadata=None,
        workspace_metadata=metadata,
    )
    if not code_context_eval.allowed:
        raise ValueError(code_context_eval.reason or "Invalid workspace code context")

    return metadata


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


def _to_workspace_response(workspace: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        tenant_id=workspace.tenant_id,
        project_id=workspace.project_id,
        name=workspace.name,
        created_by=workspace.created_by,
        description=workspace.description,
        is_archived=workspace.is_archived,
        metadata=workspace.metadata,
        office_status=workspace.office_status,
        hex_layout_config=workspace.hex_layout_config,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _to_member_response(
    member: WorkspaceMember, user_email: str | None = None
) -> WorkspaceMemberResponse:
    return WorkspaceMemberResponse(
        id=member.id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        user_email=user_email,
        role=member.role,
        invited_by=member.invited_by,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def _to_agent_response(agent: WorkspaceAgent) -> WorkspaceAgentResponse:
    return WorkspaceAgentResponse(
        id=agent.id,
        workspace_id=agent.workspace_id,
        agent_id=agent.agent_id,
        display_name=agent.display_name,
        description=agent.description,
        config=agent.config,
        is_active=agent.is_active,
        hex_q=agent.hex_q,
        hex_r=agent.hex_r,
        theme_color=agent.theme_color,
        label=agent.label,
        status=agent.status,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    tenant_id: str,
    project_id: str,
    payload: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    try:
        workspace = await workspace_service.create_workspace(
            tenant_id=tenant_id,
            project_id=project_id,
            name=payload.name,
            created_by=current_user.id,
            description=payload.description,
            metadata=_compose_workspace_metadata(payload),
        )
        await db.commit()
        return _to_workspace_response(workspace)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    tenant_id: str,
    project_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceResponse]:
    try:
        workspaces = await workspace_service.list_workspaces(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        return [_to_workspace_response(workspace) for workspace in workspaces]
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        return _to_workspace_response(workspace)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        updated = await workspace_service.update_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            is_archived=payload.is_archived,
            metadata=payload.metadata,
        )
        await db.commit()
        return _to_workspace_response(updated)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        _ = await workspace_service.delete_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
async def list_workspace_members(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceMemberResponse]:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        members = await workspace_service.list_members(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        # Batch-resolve user emails
        from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
            SqlUserRepository,
        )

        user_repo = SqlUserRepository(db)
        email_map: dict[str, str] = {}
        for member in members:
            user = await user_repo.find_by_id(member.user_id)
            if user:
                email_map[member.user_id] = user.email
        return [
            _to_member_response(member, user_email=email_map.get(member.user_id))
            for member in members
        ]
    except Exception as exc:
        raise _map_error(exc) from exc


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceMemberResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        member = await workspace_service.add_member(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            target_user_id=payload.user_id,
            role=payload.role,
        )
        await db.commit()
        return _to_member_response(member)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberResponse)
async def update_workspace_member(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    user_id: str,
    payload: WorkspaceMemberUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceMemberResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        member = await workspace_service.update_member_role(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            target_user_id=user_id,
            new_role=payload.role,
        )
        await db.commit()
        return _to_member_response(member)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workspace_member(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        _ = await workspace_service.remove_member(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            target_user_id=user_id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.get("/{workspace_id}/agents", response_model=list[WorkspaceAgentResponse])
async def list_workspace_agents(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    active_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceAgentResponse]:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        bindings = await workspace_service.list_workspace_agents(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        return [_to_agent_response(binding) for binding in bindings]
    except Exception as exc:
        raise _map_error(exc) from exc


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceAgentResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        binding = await workspace_service.bind_agent(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            agent_id=payload.agent_id,
            display_name=payload.display_name,
            description=payload.description,
            config=payload.config,
            is_active=payload.is_active,
            hex_q=payload.hex_q,
            hex_r=payload.hex_r,
            theme_color=payload.theme_color,
            label=payload.label,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    try:
        await workspace_service.publish_pending_events()
    except Exception:
        logger.exception("Failed to publish workspace agent bind event", extra={"workspace_id": workspace_id})
    return _to_agent_response(binding)


@router.patch("/{workspace_id}/agents/{workspace_agent_id}", response_model=WorkspaceAgentResponse)
async def update_workspace_agent(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    workspace_agent_id: str,
    payload: WorkspaceAgentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceAgentResponse:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        binding = await workspace_service.update_agent_binding(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            workspace_agent_id=workspace_agent_id,
            display_name=payload.display_name,
            description=payload.description,
            config=payload.config,
            is_active=payload.is_active,
            hex_q=payload.hex_q,
            hex_r=payload.hex_r,
            theme_color=payload.theme_color,
            label=payload.label,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    try:
        await workspace_service.publish_pending_events()
    except Exception:
        logger.exception(
            "Failed to publish workspace agent update event",
            extra={"workspace_id": workspace_id, "workspace_agent_id": workspace_agent_id},
        )
    return _to_agent_response(binding)


@router.delete(
    "/{workspace_id}/agents/{workspace_agent_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_workspace_agent(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    workspace_agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    try:
        workspace = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        _ensure_workspace_scope(workspace, tenant_id=tenant_id, project_id=project_id)
        _ = await workspace_service.unbind_agent(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            workspace_agent_id=workspace_agent_id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
    try:
        await workspace_service.publish_pending_events()
    except Exception:
        logger.exception(
            "Failed to publish workspace agent unbind event",
            extra={"workspace_id": workspace_id, "workspace_agent_id": workspace_agent_id},
        )
