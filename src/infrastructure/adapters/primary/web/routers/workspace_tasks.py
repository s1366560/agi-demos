"""Workspace task API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_task_service import WorkspaceTaskService
from src.configuration.di_container import DIContainer
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_events import publish_workspace_event
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get a request-scoped container with DB session."""
    return request.app.state.container.with_db(db)


def _get_workspace_task_service(request: Request, db: AsyncSession) -> WorkspaceTaskService:
    """Build WorkspaceTaskService from repositories in DI container."""
    container = get_container_with_db(request, db)
    return WorkspaceTaskService(
        workspace_repo=container.workspace_repository(),
        workspace_member_repo=container.workspace_member_repository(),
        workspace_agent_repo=container.workspace_agent_repository(),
        workspace_task_repo=container.workspace_task_repository(),
    )


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/tasks", tags=["workspace-tasks"])


class WorkspaceTaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    assignee_user_id: str | None = None
    metadata: dict[str, Any] | None = None


class WorkspaceTaskUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    assignee_user_id: str | None = None
    status: WorkspaceTaskStatus | None = None
    metadata: dict[str, Any] | None = None
    priority: str | None = None
    estimated_effort: str | None = None
    blocker_reason: str | None = None
    assignee_agent_id: str | None = None


class AssignAgentRequest(BaseModel):
    workspace_agent_id: str


class WorkspaceTaskResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str | None
    created_by: str
    assignee_user_id: str | None
    assignee_agent_id: str | None
    status: WorkspaceTaskStatus
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None
    priority: str | None = None
    estimated_effort: str | None = None
    blocker_reason: str | None = None
    completed_at: datetime | None = None
    archived_at: datetime | None = None


def _to_response(task: WorkspaceTask) -> WorkspaceTaskResponse:
    return WorkspaceTaskResponse(
        id=task.id,
        workspace_id=task.workspace_id,
        title=task.title,
        description=task.description,
        created_by=task.created_by,
        assignee_user_id=task.assignee_user_id,
        assignee_agent_id=task.assignee_agent_id,
        status=task.status,
        metadata=task.metadata,
        created_at=task.created_at,
        updated_at=task.updated_at,
        priority=str(task.priority) if task.priority else None,
        estimated_effort=task.estimated_effort,
        blocker_reason=task.blocker_reason,
        completed_at=task.completed_at,
        archived_at=task.archived_at,
    )


def _to_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        message = str(exc)
        if "not found" in message.lower():
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error"
    )


async def _publish_task_assigned_event(request: Request, task: WorkspaceTask) -> None:
    if not task.assignee_user_id and not task.assignee_agent_id:
        return
    await publish_workspace_event(
        request.app.state.container.redis(),
        workspace_id=task.workspace_id,
        event_type=AgentEventType.WORKSPACE_TASK_ASSIGNED,
        payload={
            "workspace_id": task.workspace_id,
            "task_id": task.id,
            "assignee_user_id": task.assignee_user_id,
            "assignee_agent_id": task.assignee_agent_id,
            "status": task.status.value,
        },
    )


@router.post("", response_model=WorkspaceTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_task(
    workspace_id: str,
    body: WorkspaceTaskCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.create_task(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            title=body.title,
            description=body.description,
            assignee_user_id=body.assignee_user_id,
            metadata=body.metadata,
        )
        await db.commit()
        if task.assignee_user_id:
            await _publish_task_assigned_event(request, task)
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_TASK_CREATED,
            payload={
                "task": _to_response(task).model_dump(mode="json"),
            },
        )
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    return _to_response(task)


@router.get("", response_model=list[WorkspaceTaskResponse])
async def list_workspace_tasks(
    workspace_id: str,
    request: Request,
    status_filter: WorkspaceTaskStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceTaskResponse]:
    service = _get_workspace_task_service(request, db)
    try:
        tasks = await service.list_tasks(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise _to_http_error(exc) from exc
    return [_to_response(task) for task in tasks]


@router.get("/{task_id}", response_model=WorkspaceTaskResponse)
async def get_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.get_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
    except Exception as exc:
        raise _to_http_error(exc) from exc
    return _to_response(task)


@router.patch("/{task_id}", response_model=WorkspaceTaskResponse)
async def update_workspace_task(
    workspace_id: str,
    task_id: str,
    body: WorkspaceTaskUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.update_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
            title=body.title,
            description=body.description,
            assignee_user_id=body.assignee_user_id,
            status=body.status,
            metadata=body.metadata,
        )
        await db.commit()
        if body.assignee_user_id is not None:
            await _publish_task_assigned_event(request, task)
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_TASK_UPDATED,
            payload={
                "task": _to_response(task).model_dump(mode="json"),
            },
        )
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    return _to_response(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = _get_workspace_task_service(request, db)
    try:
        await service.delete_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_TASK_DELETED,
            payload={"task_id": task_id},
        )
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc


@router.post("/{task_id}/assign-agent", response_model=WorkspaceTaskResponse)
async def assign_workspace_task_to_agent(
    workspace_id: str,
    task_id: str,
    body: AssignAgentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.assign_task_to_agent(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
            workspace_agent_id=body.workspace_agent_id,
        )
        await db.commit()
        await _publish_task_assigned_event(request, task)
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    return _to_response(task)


@router.post("/{task_id}/unassign-agent", response_model=WorkspaceTaskResponse)
async def unassign_workspace_task_from_agent(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.unassign_task_from_agent(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_TASK_UPDATED,
            payload={
                "task": _to_response(task).model_dump(mode="json"),
            },
        )
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    return _to_response(task)


@router.post("/{task_id}/claim", response_model=WorkspaceTaskResponse)
async def claim_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.claim_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_TASK_UPDATED,
            payload={
                "task": _to_response(task).model_dump(mode="json"),
            },
        )
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    return _to_response(task)


@router.post("/{task_id}/start", response_model=WorkspaceTaskResponse)
async def start_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.start_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_TASK_STATUS_CHANGED,
            payload={
                "task": _to_response(task).model_dump(mode="json"),
                "new_status": "in_progress",
            },
        )
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    return _to_response(task)


@router.post("/{task_id}/block", response_model=WorkspaceTaskResponse)
async def block_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.block_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_TASK_STATUS_CHANGED,
            payload={
                "task": _to_response(task).model_dump(mode="json"),
                "new_status": "blocked",
            },
        )
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    return _to_response(task)


@router.post("/{task_id}/complete", response_model=WorkspaceTaskResponse)
async def complete_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_service(request, db)
    try:
        task = await service.complete_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_TASK_STATUS_CHANGED,
            payload={
                "task": _to_response(task).model_dump(mode="json"),
                "new_status": "done",
            },
        )
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    return _to_response(task)
