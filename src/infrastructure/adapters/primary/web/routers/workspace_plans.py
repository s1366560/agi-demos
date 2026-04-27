"""Workspace plan snapshot API routes."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_service import WorkspaceService
from src.configuration.di_container import DIContainer
from src.domain.events.types import AgentEventType
from src.domain.model.workspace_plan import Plan, PlanNode, PlanNodeId, Progress
from src.domain.model.workspace_plan.plan_node import TaskExecution, TaskIntent
from src.domain.model.workspace_plan.state_machine import transition_execution, transition_intent
from src.domain.ports.services.blackboard_port import BlackboardEntry
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_events import publish_workspace_event
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    User,
    WorkspacePlanEventModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_blackboard import (
    SqlWorkspacePlanBlackboard,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_events import (
    SqlWorkspacePlanEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import ROOT_GOAL_TASK_ID, TASK_ROLE
from src.infrastructure.agent.workspace_plan.outbox_handlers import SUPERVISOR_TICK_EVENT

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/plan", tags=["workspace-plans"])
logger = logging.getLogger(__name__)


class WorkspacePlanActionCapabilityResponse(BaseModel):
    enabled: bool
    label: str
    reason: str | None = None
    requires_confirmation: bool = False


class WorkspacePlanNodeResponse(BaseModel):
    id: str
    parent_id: str | None
    kind: str
    title: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[dict[str, Any]] = Field(default_factory=list)
    feature_checkpoint: dict[str, Any] | None = None
    handoff_package: dict[str, Any] | None = None
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
    actions: dict[str, WorkspacePlanActionCapabilityResponse] = Field(default_factory=dict)


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
    plan_id: str | None
    workspace_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
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
    actions: dict[str, WorkspacePlanActionCapabilityResponse] = Field(default_factory=dict)


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


class WorkspacePlanRootGoalResponse(BaseModel):
    id: str
    title: str
    status: str
    blocker_reason: str | None = None
    goal_health: str | None = None
    remediation_status: str | None = None
    remediation_summary: str | None = None
    evidence_grade: str | None = None
    completion_blocker_reason: str | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class WorkspacePlanSnapshotResponse(BaseModel):
    workspace_id: str
    plan: WorkspacePlanResponse | None = None
    root_goal: WorkspacePlanRootGoalResponse | None = None
    blackboard: list[WorkspacePlanBlackboardEntryResponse] = Field(default_factory=list)
    outbox: list[WorkspacePlanOutboxItemResponse] = Field(default_factory=list)
    events: list[WorkspacePlanEventResponse] = Field(default_factory=list)


class WorkspacePlanActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class WorkspacePlanActionResultResponse(BaseModel):
    ok: bool
    message: str
    plan_id: str
    node_id: str | None = None
    outbox_id: str | None = None


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


async def _ensure_workspace_access(
    *,
    workspace_id: str,
    request: Request,
    db: AsyncSession,
    current_user: User,
) -> None:
    workspace_service = _get_workspace_service(request, db)
    _ = await workspace_service.get_workspace(
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
    )


def _action(
    *,
    enabled: bool,
    label: str,
    reason: str | None = None,
    requires_confirmation: bool = False,
) -> WorkspacePlanActionCapabilityResponse:
    return WorkspacePlanActionCapabilityResponse(
        enabled=enabled,
        label=label,
        reason=reason,
        requires_confirmation=requires_confirmation,
    )


def _node_actions(node: PlanNode) -> dict[str, WorkspacePlanActionCapabilityResponse]:
    executable = node.kind.value in {"task", "verify"}
    done = node.intent is TaskIntent.DONE
    blocked = node.intent is TaskIntent.BLOCKED
    has_attempt = bool(node.current_attempt_id or node.workspace_task_id)
    return {
        "open_attempt": _action(
            enabled=has_attempt,
            label="Open attempt",
            reason=None if has_attempt else "No worker attempt has been linked yet.",
        ),
        "request_replan": _action(
            enabled=executable and not done,
            label="Request replan",
            reason=(
                None
                if executable and not done
                else "Only active task or verification nodes can be replanned."
            ),
            requires_confirmation=True,
        ),
        "reopen_blocked": _action(
            enabled=blocked,
            label="Reopen blocked node",
            reason=None if blocked else "Only blocked nodes can be reopened.",
        ),
    }


def _outbox_actions(
    item: WorkspacePlanOutboxModel,
) -> dict[str, WorkspacePlanActionCapabilityResponse]:
    retryable = item.status in {"failed", "dead_letter"}
    return {
        "retry_outbox": _action(
            enabled=retryable,
            label="Retry now",
            reason=None if retryable else "Only failed or dead-letter jobs can be retried.",
        )
    }


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
            feature_checkpoint=(
                node.feature_checkpoint.to_json() if node.feature_checkpoint is not None else None
            ),
            handoff_package=(
                node.handoff_package.to_json() if node.handoff_package is not None else None
            ),
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
            actions=_node_actions(node),
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
        payload=dict(item.payload_json or {}),
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
        actions=_outbox_actions(item),
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


async def _load_root_goal_response(
    db: AsyncSession,
    *,
    workspace_id: str,
    plan: Plan,
) -> WorkspacePlanRootGoalResponse | None:
    root_goal_id = await _resolve_root_goal_task_id(db, workspace_id=workspace_id, plan=plan)
    row: WorkspaceTaskModel | None = None
    if root_goal_id:
        candidate = await db.get(WorkspaceTaskModel, root_goal_id)
        if candidate is not None and candidate.workspace_id == workspace_id:
            row = candidate
    if row is None:
        result = await db.execute(
            refresh_select_statement(
                select(WorkspaceTaskModel)
                .where(WorkspaceTaskModel.workspace_id == workspace_id)
                .where(WorkspaceTaskModel.metadata_json[TASK_ROLE].as_string() == "goal_root")
                .where(WorkspaceTaskModel.archived_at.is_(None))
                .order_by(
                    WorkspaceTaskModel.completed_at.is_(None).desc(),
                    WorkspaceTaskModel.updated_at.desc(),
                    WorkspaceTaskModel.created_at.desc(),
                )
                .limit(1)
            )
        )
        row = result.scalar_one_or_none()
    if row is None:
        return None
    return _to_root_goal_response(row)


async def _resolve_root_goal_task_id(
    db: AsyncSession,
    *,
    workspace_id: str,
    plan: Plan,
) -> str | None:
    workspace_task_ids = [
        node.workspace_task_id
        for node in plan.nodes.values()
        if isinstance(node.workspace_task_id, str) and node.workspace_task_id
    ]
    if not workspace_task_ids:
        return None
    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceTaskModel)
            .where(WorkspaceTaskModel.workspace_id == workspace_id)
            .where(WorkspaceTaskModel.id.in_(workspace_task_ids))
        )
    )
    for task in result.scalars().all():
        metadata = dict(task.metadata_json or {})
        root_goal_id = metadata.get(ROOT_GOAL_TASK_ID)
        if isinstance(root_goal_id, str) and root_goal_id:
            return root_goal_id
    return None


def _to_root_goal_response(row: WorkspaceTaskModel) -> WorkspacePlanRootGoalResponse:
    metadata = dict(row.metadata_json or {})
    evidence = metadata.get("goal_evidence")
    evidence_grade = (
        evidence.get("verification_grade")
        if isinstance(evidence, dict) and isinstance(evidence.get("verification_grade"), str)
        else None
    )
    return WorkspacePlanRootGoalResponse(
        id=row.id,
        title=row.title,
        status=row.status,
        blocker_reason=row.blocker_reason,
        goal_health=_metadata_text(metadata, "goal_health"),
        remediation_status=_metadata_text(metadata, "remediation_status"),
        remediation_summary=_metadata_text(metadata, "remediation_summary"),
        evidence_grade=evidence_grade,
        completion_blocker_reason=_root_completion_blocker_reason(
            status=row.status,
            blocker_reason=row.blocker_reason,
            metadata=metadata,
            evidence_grade=evidence_grade,
        ),
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _root_completion_blocker_reason(
    *,
    status: str,
    blocker_reason: str | None,
    metadata: dict[str, Any],
    evidence_grade: str | None,
) -> str | None:
    if status == "done":
        return None
    if blocker_reason:
        return blocker_reason
    if evidence_grade == "fail":
        return (
            _metadata_text(metadata, "remediation_summary")
            or "Root goal evidence failed completion policy checks."
        )
    if metadata.get("remediation_status") == "ready_for_completion":
        return (
            _metadata_text(metadata, "remediation_summary")
            or "Root goal is ready for completion but has not closed yet."
        )
    return None


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        message = str(exc)
        if "not found" in message.lower():
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


async def _load_plan_for_workspace(db: AsyncSession, workspace_id: str) -> Plan:
    plan = await SqlPlanRepository(db).get_by_workspace(workspace_id)
    if plan is None:
        raise ValueError(f"workspace plan not found for workspace {workspace_id}")
    return plan


def _load_plan_node(plan: Plan, node_id: str) -> PlanNode:
    node = plan.nodes.get(PlanNodeId(value=node_id))
    if node is None:
        raise ValueError(f"plan node {node_id} not found")
    return node


def _reset_node_for_operator(
    *,
    node: PlanNode,
    actor_id: str,
    action: str,
    reason: str | None,
) -> PlanNode:
    target_intent = TaskIntent.TODO
    if node.intent is TaskIntent.DONE:
        raise ValueError("done nodes cannot be reopened or replanned")
    if node.intent is not target_intent:
        _ = transition_intent(node.intent, target_intent)
    if node.execution is not TaskExecution.IDLE:
        _ = transition_execution(node.execution, TaskExecution.IDLE)

    current_time = datetime.now(UTC)
    action_label = "reopened" if action == "operator_node_reopened" else "sent back for replan"
    return replace(
        node,
        intent=target_intent,
        execution=TaskExecution.IDLE,
        progress=Progress(
            percent=0,
            confidence=node.progress.confidence,
            note=f"Operator {action_label}.",
        ),
        metadata={
            **dict(node.metadata or {}),
            "operator_action": {
                "action": action,
                "actor_id": actor_id,
                "reason": reason,
                "created_at": current_time.isoformat(),
            },
        },
        completed_at=None,
        updated_at=current_time,
    )


async def _enqueue_operator_tick(
    *,
    db: AsyncSession,
    plan: Plan,
    workspace_id: str,
    node_id: str,
    actor_id: str,
    reason: str | None,
    action: str,
) -> None:
    _ = await SqlWorkspacePlanOutboxRepository(db).enqueue(
        plan_id=plan.id,
        workspace_id=workspace_id,
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": workspace_id,
            "plan_id": plan.id,
            "node_id": node_id,
            "actor_user_id": actor_id,
            "operator_action": action,
            "reason": reason,
        },
        metadata={"source": "operator_action"},
    )


async def _publish_plan_updated_event(
    *,
    request: Request,
    workspace_id: str,
    plan_id: str,
    action: str,
    node_id: str | None = None,
    outbox_id: str | None = None,
    reason: str | None = None,
) -> None:
    state = getattr(getattr(request, "app", None), "state", None)
    container = getattr(state, "container", None)
    redis_client = getattr(container, "redis_client", None)
    if redis_client is None:
        return

    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "plan_id": plan_id,
        "action": action,
    }
    if node_id is not None:
        payload["node_id"] = node_id
    if outbox_id is not None:
        payload["outbox_id"] = outbox_id
    if reason:
        payload["reason"] = reason

    try:
        await publish_workspace_event(
            redis_client,
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_PLAN_UPDATED,
            payload=payload,
            metadata={"source": "workspace_plan_api", "action": action},
            correlation_id=plan_id,
        )
    except Exception:
        logger.warning(
            "workspace_plan.update_event_publish_failed",
            exc_info=True,
            extra={
                "event": "workspace_plan.update_event_publish_failed",
                "workspace_id": workspace_id,
                "plan_id": plan_id,
                "action": action,
            },
        )


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
        await _ensure_workspace_access(
            workspace_id=workspace_id,
            request=request,
            db=db,
            current_user=current_user,
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
            root_goal=await _load_root_goal_response(db, workspace_id=workspace_id, plan=plan),
            blackboard=[_to_blackboard_response(entry) for entry in blackboard_entries],
            outbox=[_to_outbox_response(item) for item in outbox_items],
            events=[_to_event_response(item) for item in event_items],
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/outbox/{outbox_id}/retry", response_model=WorkspacePlanActionResultResponse)
async def retry_workspace_plan_outbox_item(
    workspace_id: str,
    outbox_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    """Retry a failed/dead-letter durable plan job immediately."""
    try:
        await _ensure_workspace_access(
            workspace_id=workspace_id,
            request=request,
            db=db,
            current_user=current_user,
        )
        repo = SqlWorkspacePlanOutboxRepository(db)
        item = await repo.retry_now(
            outbox_id,
            workspace_id=workspace_id,
            actor_id=current_user.id,
            reason=body.reason,
        )
        if item is None:
            raise ValueError(f"outbox item {outbox_id} not found")
        if item.plan_id is None:
            raise ValueError(f"outbox item {outbox_id} is not associated with a workspace plan")
        plan_id = item.plan_id
        _ = await SqlWorkspacePlanEventRepository(db).append(
            plan_id=plan_id,
            workspace_id=workspace_id,
            event_type="operator_retry_outbox",
            source="operator",
            actor_id=current_user.id,
            payload={
                "outbox_id": outbox_id,
                "event_type": item.event_type,
                "reason": body.reason,
            },
        )
        await db.commit()
        await _publish_plan_updated_event(
            request=request,
            workspace_id=workspace_id,
            plan_id=plan_id,
            action="operator_retry_outbox",
            outbox_id=outbox_id,
            reason=body.reason,
        )
        return WorkspacePlanActionResultResponse(
            ok=True,
            message="Outbox job queued for retry.",
            plan_id=plan_id,
            outbox_id=outbox_id,
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/nodes/{node_id}/request-replan", response_model=WorkspacePlanActionResultResponse)
async def request_workspace_plan_node_replan(
    workspace_id: str,
    node_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    """Return an active plan node to TODO and schedule supervisor recovery."""
    try:
        await _ensure_workspace_access(
            workspace_id=workspace_id,
            request=request,
            db=db,
            current_user=current_user,
        )
        plan = await _load_plan_for_workspace(db, workspace_id)
        node = _load_plan_node(plan, node_id)
        updated = _reset_node_for_operator(
            node=node,
            actor_id=current_user.id,
            action="operator_replan_requested",
            reason=body.reason,
        )
        plan.replace_node(updated)
        await SqlPlanRepository(db).save(plan)
        _ = await SqlWorkspacePlanEventRepository(db).append(
            plan_id=plan.id,
            workspace_id=workspace_id,
            node_id=node_id,
            attempt_id=node.current_attempt_id,
            event_type="operator_replan_requested",
            source="operator",
            actor_id=current_user.id,
            payload={"reason": body.reason},
        )
        await _enqueue_operator_tick(
            db=db,
            plan=plan,
            workspace_id=workspace_id,
            node_id=node_id,
            actor_id=current_user.id,
            reason=body.reason,
            action="operator_replan_requested",
        )
        await db.commit()
        await _publish_plan_updated_event(
            request=request,
            workspace_id=workspace_id,
            plan_id=plan.id,
            action="operator_replan_requested",
            node_id=node_id,
            reason=body.reason,
        )
        return WorkspacePlanActionResultResponse(
            ok=True,
            message="Plan node sent back for supervisor recovery.",
            plan_id=plan.id,
            node_id=node_id,
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/nodes/{node_id}/reopen", response_model=WorkspacePlanActionResultResponse)
async def reopen_blocked_workspace_plan_node(
    workspace_id: str,
    node_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    """Reopen a blocked durable plan node and schedule supervisor recovery."""
    try:
        await _ensure_workspace_access(
            workspace_id=workspace_id,
            request=request,
            db=db,
            current_user=current_user,
        )
        plan = await _load_plan_for_workspace(db, workspace_id)
        node = _load_plan_node(plan, node_id)
        if node.intent is not TaskIntent.BLOCKED:
            raise ValueError("only blocked nodes can be reopened")
        updated = _reset_node_for_operator(
            node=node,
            actor_id=current_user.id,
            action="operator_node_reopened",
            reason=body.reason,
        )
        plan.replace_node(updated)
        await SqlPlanRepository(db).save(plan)
        _ = await SqlWorkspacePlanEventRepository(db).append(
            plan_id=plan.id,
            workspace_id=workspace_id,
            node_id=node_id,
            attempt_id=node.current_attempt_id,
            event_type="operator_node_reopened",
            source="operator",
            actor_id=current_user.id,
            payload={"reason": body.reason},
        )
        await _enqueue_operator_tick(
            db=db,
            plan=plan,
            workspace_id=workspace_id,
            node_id=node_id,
            actor_id=current_user.id,
            reason=body.reason,
            action="operator_node_reopened",
        )
        await db.commit()
        await _publish_plan_updated_event(
            request=request,
            workspace_id=workspace_id,
            plan_id=plan.id,
            action="operator_node_reopened",
            node_id=node_id,
            reason=body.reason,
        )
        return WorkspacePlanActionResultResponse(
            ok=True,
            message="Blocked plan node reopened.",
            plan_id=plan.id,
            node_id=node_id,
        )
    except Exception as exc:
        raise _map_error(exc) from exc


__all__ = [
    "WorkspacePlanSnapshotResponse",
    "router",
]
