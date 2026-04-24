"""Workspace plan snapshot API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_service import WorkspaceService
from src.configuration.di_container import DIContainer
from src.domain.model.workspace_plan import Plan
from src.domain.ports.services.blackboard_port import BlackboardEntry
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    User,
    WorkspacePlanEventModel,
    WorkspacePlanOutboxModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_blackboard import (
    SqlWorkspacePlanBlackboard,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/plan", tags=["workspace-plans"])


class WorkspacePlanNodeResponse(BaseModel):
    id: str
    parent_id: str | None
    kind: str
    title: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[dict[str, Any]] = Field(default_factory=list)
    recommended_capabilities: list[dict[str, Any]] = Field(default_factory=list)
    intent: str
    execution: str
    progress: dict[str, Any] = Field(default_factory=dict)
    assignee_agent_id: str | None
    current_attempt_id: str | None
    workspace_task_id: str | None
    priority: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None
    completed_at: datetime | None


class WorkspacePlanResponse(BaseModel):
    id: str
    workspace_id: str
    goal_id: str
    status: str
    created_at: datetime
    updated_at: datetime | None
    nodes: list[WorkspacePlanNodeResponse] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class WorkspacePlanBlackboardEntryResponse(BaseModel):
    plan_id: str
    key: str
    value: Any
    published_by: str
    version: int
    schema_ref: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspacePlanOutboxItemResponse(BaseModel):
    id: str
    plan_id: str
    workspace_id: str
    event_type: str
    status: str
    attempt_count: int
    max_attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    last_error: str | None
    next_attempt_at: datetime | None
    processed_at: datetime | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None


class WorkspacePlanEventResponse(BaseModel):
    id: str
    plan_id: str
    workspace_id: str
    node_id: str | None
    attempt_id: str | None
    event_type: str
    source: str
    actor_id: str | None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WorkspacePlanSnapshotResponse(BaseModel):
    workspace_id: str
    plan: WorkspacePlanResponse | None = None
    blackboard: list[WorkspacePlanBlackboardEntryResponse] = Field(default_factory=list)
    outbox: list[WorkspacePlanOutboxItemResponse] = Field(default_factory=list)
    events: list[WorkspacePlanEventResponse] = Field(default_factory=list)


def _get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    return cast(DIContainer, request.app.state.container.with_db(db))


def _get_workspace_service(request: Request, db: AsyncSession) -> WorkspaceService:
    container = _get_container_with_db(request, db)
    return WorkspaceService(
        workspace_repo=container.workspace_repository(),
        workspace_member_repo=container.workspace_member_repository(),
        workspace_agent_repo=container.workspace_agent_repository(),
        topology_repo=container.topology_repository(),
    )


def _to_node_response(plan: Plan) -> list[WorkspacePlanNodeResponse]:
    nodes = sorted(plan.nodes.values(), key=lambda node: (node.kind.value, node.priority, node.id))
    return [
        WorkspacePlanNodeResponse(
            id=node.id,
            parent_id=node.parent_id.value if node.parent_id else None,
            kind=node.kind.value,
            title=node.title,
            description=node.description,
            depends_on=sorted(dep.value for dep in node.depends_on),
            acceptance_criteria=[
                {
                    "kind": criterion.kind.value,
                    "spec": criterion.spec,
                    "required": criterion.required,
                    "description": criterion.description,
                }
                for criterion in node.acceptance_criteria
            ],
            recommended_capabilities=[
                {"name": capability.name, "weight": capability.weight}
                for capability in node.recommended_capabilities
            ],
            intent=node.intent.value,
            execution=node.execution.value,
            progress={
                "percent": node.progress.percent,
                "confidence": node.progress.confidence,
                "note": node.progress.note,
            },
            assignee_agent_id=node.assignee_agent_id,
            current_attempt_id=node.current_attempt_id,
            workspace_task_id=node.workspace_task_id,
            priority=node.priority,
            metadata=dict(node.metadata),
            created_at=node.created_at,
            updated_at=node.updated_at,
            completed_at=node.completed_at,
        )
        for node in nodes
    ]


def _to_plan_response(plan: Plan) -> WorkspacePlanResponse:
    counts: dict[str, int] = {}
    for node in plan.nodes.values():
        counts[f"intent:{node.intent.value}"] = counts.get(f"intent:{node.intent.value}", 0) + 1
        counts[f"execution:{node.execution.value}"] = (
            counts.get(f"execution:{node.execution.value}", 0) + 1
        )
    return WorkspacePlanResponse(
        id=plan.id,
        workspace_id=plan.workspace_id,
        goal_id=plan.goal_id.value,
        status=plan.status.value,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        nodes=_to_node_response(plan),
        counts=counts,
    )


def _to_blackboard_response(entry: BlackboardEntry) -> WorkspacePlanBlackboardEntryResponse:
    return WorkspacePlanBlackboardEntryResponse(
        plan_id=entry.plan_id,
        key=entry.key,
        value=entry.value,
        published_by=entry.published_by,
        version=entry.version,
        schema_ref=entry.schema_ref,
        metadata=dict(entry.metadata),
    )


def _to_outbox_response(item: WorkspacePlanOutboxModel) -> WorkspacePlanOutboxItemResponse:
    return WorkspacePlanOutboxItemResponse(
        id=item.id,
        plan_id=item.plan_id,
        workspace_id=item.workspace_id,
        event_type=item.event_type,
        status=item.status,
        attempt_count=item.attempt_count,
        max_attempts=item.max_attempts,
        lease_owner=item.lease_owner,
        lease_expires_at=item.lease_expires_at,
        last_error=item.last_error,
        next_attempt_at=item.next_attempt_at,
        processed_at=item.processed_at,
        metadata=dict(item.metadata_json or {}),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _to_event_response(item: WorkspacePlanEventModel) -> WorkspacePlanEventResponse:
    return WorkspacePlanEventResponse(
        id=item.id,
        plan_id=item.plan_id,
        workspace_id=item.workspace_id,
        node_id=item.node_id,
        attempt_id=item.attempt_id,
        event_type=item.event_type,
        source=item.source,
        actor_id=item.actor_id,
        payload=dict(item.payload_json or {}),
        created_at=item.created_at,
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


@router.get("", response_model=WorkspacePlanSnapshotResponse)
async def get_workspace_plan_snapshot(
    workspace_id: str,
    request: Request,
    outbox_limit: int = Query(20, ge=0, le=100),
    event_limit: int = Query(50, ge=0, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanSnapshotResponse:
    """Return durable plan state for the central blackboard dashboard."""
    try:
        workspace_service = _get_workspace_service(request, db)
        _ = await workspace_service.get_workspace(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
        )
        plan = await SqlPlanRepository(db).get_by_workspace(workspace_id)
        if plan is None:
            return WorkspacePlanSnapshotResponse(workspace_id=workspace_id)

        blackboard_entries = await SqlWorkspacePlanBlackboard(db).list(plan.id)
        result = await db.execute(
            refresh_select_statement(
                select(WorkspacePlanOutboxModel)
                .where(WorkspacePlanOutboxModel.plan_id == plan.id)
                .order_by(WorkspacePlanOutboxModel.created_at.desc())
                .limit(outbox_limit)
            )
        )
        outbox_items = list(result.scalars().all())
        event_result = await db.execute(
            refresh_select_statement(
                select(WorkspacePlanEventModel)
                .where(WorkspacePlanEventModel.plan_id == plan.id)
                .order_by(
                    WorkspacePlanEventModel.created_at.desc(),
                    WorkspacePlanEventModel.id.desc(),
                )
                .limit(event_limit)
            )
        )
        event_items = list(event_result.scalars().all())
        return WorkspacePlanSnapshotResponse(
            workspace_id=workspace_id,
            plan=_to_plan_response(plan),
            blackboard=[_to_blackboard_response(entry) for entry in blackboard_entries],
            outbox=[_to_outbox_response(item) for item in outbox_items],
            events=[_to_event_response(item) for item in event_items],
        )
    except Exception as exc:
        raise _map_error(exc) from exc


__all__ = [
    "WorkspacePlanSnapshotResponse",
    "router",
]
