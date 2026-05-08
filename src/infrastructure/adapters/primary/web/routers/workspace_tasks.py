"""Workspace task API endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.task_execution_session_monitor import (
    TaskExecutionSessionMonitor,
    TaskExecutionSessionState,
    TaskRecoveryAction,
    TaskRecoveryActionResult,
)
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_event_publisher import WorkspaceTaskEventPublisher
from src.application.services.workspace_task_experience_service import (
    WorkspaceTaskExperienceService,
)
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.configuration.di_container import DIContainer
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_events import (
    publish_workspace_event_with_retry,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.agent.workspace.workspace_metadata_keys import PREFERRED_LANGUAGE

logger = logging.getLogger(__name__)

PreferredLanguage = Literal["en-US", "zh-CN"]


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get a request-scoped container with DB session."""
    return cast(DIContainer, request.app.state.container.with_db(db))


def _with_preferred_language_metadata(
    metadata: dict[str, Any] | None,
    preferred_language: PreferredLanguage | None,
) -> dict[str, Any] | None:
    if preferred_language is None:
        return metadata
    return {**dict(metadata or {}), PREFERRED_LANGUAGE: preferred_language}


def _get_workspace_task_service(request: Request, db: AsyncSession) -> WorkspaceTaskService:
    """Build WorkspaceTaskService from repositories in DI container."""
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


def _get_workspace_task_experience_service(
    request: Request,
    db: AsyncSession,
) -> WorkspaceTaskExperienceService:
    container = get_container_with_db(request, db)
    return WorkspaceTaskExperienceService(
        task_service=_get_workspace_task_service(request, db),
        attempt_repo=container.workspace_task_session_attempt_repository(),
    )


def _get_task_execution_session_monitor(
    request: Request,
    db: AsyncSession,
) -> tuple[TaskExecutionSessionMonitor, WorkspaceTaskCommandService]:
    container = get_container_with_db(request, db)
    task_service = _get_workspace_task_service(request, db)
    command_service = WorkspaceTaskCommandService(task_service)
    return (
        TaskExecutionSessionMonitor(
            db=db,
            task_service=task_service,
            command_service=command_service,
            attempt_repo=container.workspace_task_session_attempt_repository(),
        ),
        command_service,
    )


def _get_workspace_task_event_publisher(request: Request) -> WorkspaceTaskEventPublisher:
    return WorkspaceTaskEventPublisher(request.app.state.container.redis())


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/tasks", tags=["workspace-tasks"])

_INTERNAL_TO_PUBLIC_PRIORITY: dict[int, str] = {
    0: "",
    1: "P1",
    2: "P2",
    3: "P3",
    4: "P4",
}


class WorkspaceTaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    assignee_user_id: str | None = None
    metadata: dict[str, Any] | None = None
    preferred_language: PreferredLanguage | None = None
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


def _to_response(task: WorkspaceTask) -> WorkspaceTaskResponse:
    current_attempt_id = task.metadata.get("current_attempt_id")
    current_attempt_number = task.metadata.get("current_attempt_number")
    current_attempt_conversation_id = task.metadata.get("current_attempt_conversation_id")
    current_attempt_worker_binding_id = task.metadata.get("current_attempt_worker_binding_id")
    current_attempt_worker_agent_id = task.metadata.get("current_attempt_worker_agent_id")
    last_attempt_status = task.metadata.get("last_attempt_status")
    pending_leader_adjudication = task.metadata.get("pending_leader_adjudication")
    last_worker_report_type = task.metadata.get("last_worker_report_type")
    last_worker_report_summary = task.metadata.get("last_worker_report_summary")
    last_worker_report_artifacts = task.metadata.get("last_worker_report_artifacts")
    last_worker_report_verifications = task.metadata.get("last_worker_report_verifications")
    return WorkspaceTaskResponse(
        id=task.id,
        workspace_id=task.workspace_id,
        title=task.title,
        description=task.description,
        created_by=task.created_by,
        assignee_user_id=task.assignee_user_id,
        assignee_agent_id=task.assignee_agent_id,
        workspace_agent_id=task.get_workspace_agent_binding_id(),
        current_attempt_id=current_attempt_id if isinstance(current_attempt_id, str) else None,
        current_attempt_number=(
            current_attempt_number if isinstance(current_attempt_number, int) else None
        ),
        current_attempt_conversation_id=(
            current_attempt_conversation_id
            if isinstance(current_attempt_conversation_id, str)
            else None
        ),
        current_attempt_worker_binding_id=(
            current_attempt_worker_binding_id
            if isinstance(current_attempt_worker_binding_id, str)
            else None
        ),
        current_attempt_worker_agent_id=(
            current_attempt_worker_agent_id
            if isinstance(current_attempt_worker_agent_id, str)
            else None
        ),
        last_attempt_status=last_attempt_status if isinstance(last_attempt_status, str) else None,
        pending_leader_adjudication=(pending_leader_adjudication is True),
        last_worker_report_type=(
            last_worker_report_type if isinstance(last_worker_report_type, str) else None
        ),
        last_worker_report_summary=(
            last_worker_report_summary if isinstance(last_worker_report_summary, str) else None
        ),
        last_worker_report_artifacts=(
            [
                item
                for item in last_worker_report_artifacts
                if isinstance(item, str) and len(item) > 0
            ][:3]
            if isinstance(last_worker_report_artifacts, list)
            else []
        ),
        last_worker_report_verifications=(
            [
                item
                for item in last_worker_report_verifications
                if isinstance(item, str) and len(item) > 0
            ][:3]
            if isinstance(last_worker_report_verifications, list)
            else []
        ),
        status=task.status,
        metadata=task.metadata,
        created_at=task.created_at,
        updated_at=task.updated_at,
        priority=task.priority if task.priority != WorkspaceTaskPriority.NONE else None,
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


def _execution_session_response(
    state: TaskExecutionSessionState,
) -> TaskExecutionSessionResponse:
    return TaskExecutionSessionResponse.model_validate(state.to_dict())


def _recovery_action_response(result: TaskRecoveryActionResult) -> TaskRecoveryActionResponse:
    return TaskRecoveryActionResponse.model_validate(result.to_dict())


async def _publish_task_execution_session_event(
    request: Request,
    *,
    workspace_id: str,
    event_type: AgentEventType,
    payload: dict[str, Any],
    task_id: str,
    source: str,
) -> None:
    await publish_workspace_event_with_retry(
        request.app.state.container.redis(),
        workspace_id=workspace_id,
        event_type=event_type,
        payload=payload,
        metadata={"source": source, "task_id": task_id},
        correlation_id=task_id,
    )


async def _publish_recovery_result_events(
    request: Request,
    *,
    result: TaskRecoveryActionResult,
) -> None:
    payload = result.to_dict()
    await _publish_task_execution_session_event(
        request,
        workspace_id=result.workspace_id,
        event_type=AgentEventType.TASK_RECOVERY_ACTION_STARTED,
        payload=payload,
        task_id=result.task_id,
        source="task_execution_session.recovery",
    )
    if result.session is not None:
        session_payload = result.session.to_dict()
        await _publish_task_execution_session_event(
            request,
            workspace_id=result.workspace_id,
            event_type=AgentEventType.TASK_EXECUTION_SESSION_UPDATED,
            payload=session_payload,
            task_id=result.task_id,
            source="task_execution_session.monitor",
        )
        for incident in result.session.incidents:
            await _publish_task_execution_session_event(
                request,
                workspace_id=result.workspace_id,
                event_type=AgentEventType.TASK_EXECUTION_INCIDENT_OPENED,
                payload={
                    "workspace_id": result.workspace_id,
                    "task_id": result.task_id,
                    "conversation_id": result.session.conversation_id,
                    "attempt_id": result.session.attempt_id,
                    "incident": incident.to_dict(),
                },
                task_id=result.task_id,
                source="task_execution_session.monitor",
            )
    await _publish_task_execution_session_event(
        request,
        workspace_id=result.workspace_id,
        event_type=AgentEventType.TASK_RECOVERY_ACTION_COMPLETED,
        payload=payload,
        task_id=result.task_id,
        source="task_execution_session.recovery",
    )


@router.post("", response_model=WorkspaceTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_task(
    workspace_id: str,
    body: WorkspaceTaskCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        task = await service.create_task(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            title=body.title,
            description=body.description,
            assignee_user_id=body.assignee_user_id,
            metadata=_with_preferred_language_metadata(body.metadata, body.preferred_language),
            estimated_effort=body.estimated_effort,
            blocker_reason=body.blocker_reason,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events", extra={"workspace_id": workspace_id}
        )
    for tick_workspace_id, tick_actor_user_id in service.consume_pending_autonomy_ticks():
        try:
            # Lazy import: ``workspace_leader_bootstrap`` imports from this module.
            from src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap import (
                schedule_autonomy_tick,
            )

            schedule_autonomy_tick(tick_workspace_id, tick_actor_user_id)
        except Exception:
            logger.warning(
                "schedule_autonomy_tick failed after direct workspace task creation",
                exc_info=True,
                extra={"workspace_id": tick_workspace_id},
            )
    try:
        from src.infrastructure.agent.workspace.worker_launch_drain import (
            drain_pending_worker_launches_to_outbox,
        )

        _ = await drain_pending_worker_launches_to_outbox(service, db)
    except Exception:
        logger.warning(
            "worker_launch drain failed after direct workspace task creation",
            exc_info=True,
            extra={"workspace_id": workspace_id},
        )
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


@router.get("/{task_id}/experience", response_model=WorkspaceTaskExperienceResponse)
async def get_workspace_task_experience(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskExperienceResponse:
    service = _get_workspace_task_experience_service(request, db)
    try:
        summary = await service.get_summary(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
    except Exception as exc:
        raise _to_http_error(exc) from exc
    return WorkspaceTaskExperienceResponse.model_validate(summary)


@router.get("/{task_id}/execution-session", response_model=TaskExecutionSessionResponse)
async def get_workspace_task_execution_session(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskExecutionSessionResponse:
    monitor, _command_service = _get_task_execution_session_monitor(request, db)
    try:
        state = await monitor.get_state(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
    except Exception as exc:
        raise _to_http_error(exc) from exc
    return _execution_session_response(state)


@router.post("/{task_id}/recovery-actions", response_model=TaskRecoveryActionResponse)
async def apply_workspace_task_recovery_action(
    workspace_id: str,
    task_id: str,
    body: TaskRecoveryActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskRecoveryActionResponse:
    monitor, command_service = _get_task_execution_session_monitor(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        result = await monitor.apply_recovery_action(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
            action=body.action,
            reason=body.reason,
            workspace_agent_id=body.workspace_agent_id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(command_service.consume_pending_events())
        await _publish_recovery_result_events(request, result=result)
    except Exception:
        logger.exception(
            "Failed to publish task execution recovery events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    return _recovery_action_response(result)


@router.patch("/{task_id}", response_model=WorkspaceTaskResponse)
async def update_workspace_task(
    workspace_id: str,
    task_id: str,
    body: WorkspaceTaskUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
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
            priority=body.priority,
            estimated_effort=body.estimated_effort,
            blocker_reason=body.blocker_reason,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    return _to_response(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        await service.delete_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )


@router.post("/{task_id}/assign-agent", response_model=WorkspaceTaskResponse)
async def assign_workspace_task_to_agent(
    workspace_id: str,
    task_id: str,
    body: AssignAgentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        task = await service.assign_task_to_agent(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
            workspace_agent_id=body.workspace_agent_id,
            metadata=_with_preferred_language_metadata(None, body.preferred_language),
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    try:
        from src.infrastructure.agent.workspace.worker_launch_drain import (
            drain_pending_worker_launches_to_outbox,
        )

        _ = await drain_pending_worker_launches_to_outbox(service, db)
    except Exception:
        logger.warning(
            "worker_launch drain failed after direct workspace task assign",
            exc_info=True,
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    return _to_response(task)


@router.post("/{task_id}/unassign-agent", response_model=WorkspaceTaskResponse)
async def unassign_workspace_task_from_agent(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        task = await service.unassign_task_from_agent(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    return _to_response(task)


@router.post("/{task_id}/claim", response_model=WorkspaceTaskResponse)
async def claim_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        task = await service.claim_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    return _to_response(task)


@router.post("/{task_id}/start", response_model=WorkspaceTaskResponse)
async def start_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        task = await service.start_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    return _to_response(task)


@router.post("/{task_id}/block", response_model=WorkspaceTaskResponse)
async def block_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        task = await service.block_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    return _to_response(task)


@router.post("/{task_id}/complete", response_model=WorkspaceTaskResponse)
async def complete_workspace_task(
    workspace_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceTaskResponse:
    service = _get_workspace_task_command_service(request, db)
    event_publisher = _get_workspace_task_event_publisher(request)
    try:
        task = await service.complete_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _to_http_error(exc) from exc
    try:
        await event_publisher.publish_pending_events(service.consume_pending_events())
    except Exception:
        logger.exception(
            "Failed to publish workspace task events",
            extra={"workspace_id": workspace_id, "task_id": task_id},
        )
    return _to_response(task)
