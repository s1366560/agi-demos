"""Workspace Core-owned task HTTP contract declarations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.task_execution_session_monitor import TaskRecoveryAction
from src.domain.model.workspace.workspace_task import (
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db as _get_db
from src.infrastructure.adapters.secondary.persistence.models import User

PreferredLanguage = Literal["en-US", "zh-CN"]

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/tasks", tags=["workspace-tasks"])


class WorkspaceTaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    assignee_user_id: str | None = None
    metadata: dict[str, Any] | None = None
    preferred_language: PreferredLanguage | None = None
    priority: WorkspaceTaskPriority | None = None
    estimated_effort: str | None = None
    blocker_reason: str | None = None


class WorkspaceTaskUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    assignee_user_id: str | None = None
    status: WorkspaceTaskStatus | None = None
    metadata: dict[str, Any] | None = None
    priority: WorkspaceTaskPriority | None = None
    estimated_effort: str | None = None
    blocker_reason: str | None = None


class AssignAgentRequest(BaseModel):
    workspace_agent_id: str
    preferred_language: PreferredLanguage | None = None


class WorkspaceTaskResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str | None
    created_by: str
    assignee_user_id: str | None
    assignee_agent_id: str | None
    workspace_agent_id: str | None = None
    current_attempt_id: str | None = None
    current_attempt_number: int | None = None
    current_attempt_conversation_id: str | None = None
    current_attempt_worker_binding_id: str | None = None
    current_attempt_worker_agent_id: str | None = None
    last_attempt_status: str | None = None
    pending_leader_adjudication: bool = False
    last_worker_report_type: str | None = None
    last_worker_report_summary: str | None = None
    last_worker_report_artifacts: list[str] = Field(default_factory=list)
    last_worker_report_verifications: list[str] = Field(default_factory=list)
    status: WorkspaceTaskStatus
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None
    priority: WorkspaceTaskPriority | None = None
    estimated_effort: str | None = None
    blocker_reason: str | None = None
    completed_at: datetime | None = None
    archived_at: datetime | None = None


class WorkspaceTaskExperienceResponse(BaseModel):
    task_id: str
    workspace_id: str
    readiness: dict[str, Any]
    execution: dict[str, Any]
    evidence: dict[str, Any]
    diagnostics: dict[str, Any]
    activity: list[dict[str, Any]] = Field(default_factory=list)


class TaskExecutionIncidentResponse(BaseModel):
    type: str
    severity: str
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    opened_at: str | None = None


class TaskExecutionSessionResponse(BaseModel):
    workspace_id: str
    task_id: str
    task_status: str
    health: str
    session_status: str
    conversation_id: str | None = None
    attempt_id: str | None = None
    attempt_status: str | None = None
    execution_status: str | None = None
    last_event_at: str | None = None
    last_assistant_event_at: str | None = None
    last_error: str | None = None
    has_user_input: bool = False
    has_assistant_output: bool = False
    incidents: list[TaskExecutionIncidentResponse] = Field(default_factory=list)
    recommended_recovery_action: str | None = None
    available_interventions: list[str] = Field(default_factory=list)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    recovery_actions: list[dict[str, Any]] = Field(default_factory=list)


class TaskRecoveryActionRequest(BaseModel):
    action: TaskRecoveryAction
    reason: str | None = Field(default=None, max_length=500)
    workspace_agent_id: str | None = None


class TaskRecoveryActionResponse(BaseModel):
    workspace_id: str
    task_id: str
    action: str
    status: str
    message: str
    conversation_id: str | None = None
    attempt_id: str | None = None
    outbox_id: str | None = None
    session: TaskExecutionSessionResponse | None = None


@router.post("", response_model=WorkspaceTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_task(
    workspace_id: str,
    body: WorkspaceTaskCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()


@router.get("", response_model=list[WorkspaceTaskResponse])
async def list_workspace_tasks(
    workspace_id: str,
    request: Request,
    status_filter: WorkspaceTaskStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> list[WorkspaceTaskResponse]:
    raise workspace_core_unavailable_error()


@router.get("/{task_id}", response_model=WorkspaceTaskResponse)
async def get_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()


@router.get("/{task_id}/experience", response_model=WorkspaceTaskExperienceResponse)
async def get_workspace_task_experience(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskExperienceResponse:
    raise workspace_core_unavailable_error()


@router.get("/{task_id}/execution-session", response_model=TaskExecutionSessionResponse)
async def get_workspace_task_execution_session(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> TaskExecutionSessionResponse:
    raise workspace_core_unavailable_error()


@router.post("/{task_id}/recovery-actions", response_model=TaskRecoveryActionResponse)
async def apply_workspace_task_recovery_action(
    workspace_id: str,
    task_id: str,
    body: TaskRecoveryActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> TaskRecoveryActionResponse:
    raise workspace_core_unavailable_error()


@router.patch("/{task_id}", response_model=WorkspaceTaskResponse)
async def update_workspace_task(
    workspace_id: str,
    task_id: str,
    body: WorkspaceTaskUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> None:
    raise workspace_core_unavailable_error()


@router.post("/{task_id}/assign-agent", response_model=WorkspaceTaskResponse)
async def assign_workspace_task_to_agent(
    workspace_id: str,
    task_id: str,
    body: AssignAgentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()


@router.post("/{task_id}/unassign-agent", response_model=WorkspaceTaskResponse)
async def unassign_workspace_task_from_agent(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()


@router.post("/{task_id}/claim", response_model=WorkspaceTaskResponse)
async def claim_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()


@router.post("/{task_id}/start", response_model=WorkspaceTaskResponse)
async def start_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()


@router.post("/{task_id}/block", response_model=WorkspaceTaskResponse)
async def block_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()


@router.post("/{task_id}/complete", response_model=WorkspaceTaskResponse)
async def complete_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
) -> WorkspaceTaskResponse:
    raise workspace_core_unavailable_error()
