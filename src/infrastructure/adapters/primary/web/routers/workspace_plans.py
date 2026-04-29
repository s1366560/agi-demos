"""Workspace plan snapshot API routes."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
from src.infrastructure.adapters.primary.web.startup.workspace_plan_outbox import (
    initialize_workspace_plan_outbox_worker,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    User,
    WorkspacePlanEventModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
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
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    HANDOFF_RESUME_EVENT,
    SUPERVISOR_TICK_EVENT,
    WORKER_LAUNCH_EVENT,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/plan", tags=["workspace-plans"])
logger = logging.getLogger(__name__)
_SNAPSHOT_RECOVERY_DISPATCH_STALE_SECONDS = 180
_SNAPSHOT_RECOVERY_RUNNING_STALE_SECONDS = 900
_ITERATION_PHASE_ORDER = ("research", "plan", "implement", "test", "deploy", "review")
_ITERATION_PHASE_LABELS = {
    "research": "Research",
    "plan": "Plan",
    "implement": "Implement",
    "test": "Test",
    "deploy": "Deploy",
    "review": "Review",
}


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


class WorkspacePlanIterationPhaseResponse(BaseModel):
    id: str
    label: str
    total: int = 0
    done: int = 0
    running: int = 0
    blocked: int = 0
    progress: int = 0


class WorkspacePlanIterationSummaryResponse(BaseModel):
    current_iteration: int = 1
    loop_label: str = "Scrum feedback loop"
    cadence: str = "research -> plan -> implement -> test -> deploy -> review"
    active_phase: str = "research"
    active_phase_label: str = "Research"
    next_action: str = ""
    task_count: int = 0
    task_budget: int = 6
    phases: list[WorkspacePlanIterationPhaseResponse] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    feedback_items: list[str] = Field(default_factory=list)


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
    iteration: WorkspacePlanIterationSummaryResponse | None = None
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


def _to_iteration_summary(
    *,
    plan: Plan,
    root_goal: WorkspacePlanRootGoalResponse | None,
    blackboard_entries: list[BlackboardEntry],
    outbox_items: list[WorkspacePlanOutboxModel],
    event_items: list[WorkspacePlanEventModel],
) -> WorkspacePlanIterationSummaryResponse:
    runnable_nodes = [node for node in plan.nodes.values() if node.kind.value in {"task", "verify"}]
    current_iteration = _current_iteration(runnable_nodes)
    iteration_nodes = [
        node for node in runnable_nodes if _node_iteration_index(node) == current_iteration
    ]
    phases = [_phase_response(phase_id, iteration_nodes) for phase_id in _ITERATION_PHASE_ORDER]
    active_phase = _active_iteration_phase(iteration_nodes)
    return WorkspacePlanIterationSummaryResponse(
        current_iteration=current_iteration,
        active_phase=active_phase,
        active_phase_label=_ITERATION_PHASE_LABELS[active_phase],
        next_action=_iteration_next_action(
            phase_id=active_phase,
            nodes=iteration_nodes,
            root_goal=root_goal,
            outbox_items=outbox_items,
        ),
        task_count=len(iteration_nodes),
        task_budget=len(_ITERATION_PHASE_ORDER),
        phases=phases,
        deliverables=_iteration_deliverables(iteration_nodes, blackboard_entries),
        feedback_items=_iteration_feedback_items(root_goal, outbox_items, event_items),
    )


def _current_iteration(nodes: list[PlanNode]) -> int:
    if not nodes:
        return 1
    active = [
        index
        for node in nodes
        if node.intent is not TaskIntent.DONE
        for index in [_node_iteration_index(node)]
    ]
    if active:
        return min(active)
    return max(_node_iteration_index(node) for node in nodes)


def _node_iteration_index(node: PlanNode) -> int:
    value = dict(node.metadata or {}).get("iteration_index")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return max(1, int(value))
    return 1


def _node_iteration_phase(node: PlanNode) -> str:
    phase = dict(node.metadata or {}).get("iteration_phase")
    if isinstance(phase, str) and phase in _ITERATION_PHASE_ORDER:
        return phase
    sequence = node.feature_checkpoint.sequence if node.feature_checkpoint is not None else 0
    if sequence > 0:
        return _ITERATION_PHASE_ORDER[(sequence - 1) % len(_ITERATION_PHASE_ORDER)]
    return "plan"


def _phase_response(
    phase_id: str,
    nodes: list[PlanNode],
) -> WorkspacePlanIterationPhaseResponse:
    phase_nodes = [node for node in nodes if _node_iteration_phase(node) == phase_id]
    done = sum(1 for node in phase_nodes if node.intent is TaskIntent.DONE)
    blocked = sum(1 for node in phase_nodes if node.intent is TaskIntent.BLOCKED)
    running = sum(
        1
        for node in phase_nodes
        if node.execution
        in {
            TaskExecution.DISPATCHED,
            TaskExecution.RUNNING,
            TaskExecution.REPORTED,
            TaskExecution.VERIFYING,
        }
        or node.intent is TaskIntent.IN_PROGRESS
    )
    progress = 0
    if phase_nodes:
        progress = round(
            sum(
                100 if node.intent is TaskIntent.DONE else node.progress.percent
                for node in phase_nodes
            )
            / len(phase_nodes)
        )
    return WorkspacePlanIterationPhaseResponse(
        id=phase_id,
        label=_ITERATION_PHASE_LABELS[phase_id],
        total=len(phase_nodes),
        done=done,
        running=running,
        blocked=blocked,
        progress=max(0, min(progress, 100)),
    )


def _active_iteration_phase(nodes: list[PlanNode]) -> str:
    if not nodes:
        return "research"
    for phase_id in _ITERATION_PHASE_ORDER:
        if any(
            _node_iteration_phase(node) == phase_id and node.intent is TaskIntent.BLOCKED
            for node in nodes
        ):
            return phase_id
    for phase_id in _ITERATION_PHASE_ORDER:
        if any(
            _node_iteration_phase(node) == phase_id
            and (
                node.intent is TaskIntent.IN_PROGRESS
                or node.execution
                in {
                    TaskExecution.DISPATCHED,
                    TaskExecution.RUNNING,
                    TaskExecution.REPORTED,
                    TaskExecution.VERIFYING,
                }
            )
            for node in nodes
        ):
            return phase_id
    for phase_id in _ITERATION_PHASE_ORDER:
        if any(
            _node_iteration_phase(node) == phase_id and node.intent is TaskIntent.TODO
            for node in nodes
        ):
            return phase_id
    return "review"


def _iteration_next_action(
    *,
    phase_id: str,
    nodes: list[PlanNode],
    root_goal: WorkspacePlanRootGoalResponse | None,
    outbox_items: list[WorkspacePlanOutboxModel],
) -> str:
    phase_label = _ITERATION_PHASE_LABELS[phase_id].lower()
    if any(item.status in {"failed", "dead_letter"} for item in outbox_items):
        return "Recover failed queue work before advancing the sprint."
    if any(node.intent is TaskIntent.BLOCKED for node in nodes):
        return f"Resolve blockers in {phase_label}, then re-run the supervisor tick."
    if root_goal and root_goal.completion_blocker_reason:
        return "Close root-goal evidence gaps before starting the next iteration."
    if any(
        node.execution
        in {
            TaskExecution.DISPATCHED,
            TaskExecution.RUNNING,
            TaskExecution.REPORTED,
            TaskExecution.VERIFYING,
        }
        for node in nodes
    ):
        return f"Let active {phase_label} work finish and collect verification evidence."
    if any(node.intent is TaskIntent.TODO for node in nodes):
        return f"Dispatch the next {phase_label} task in the current sprint."
    return "Review feedback and create the next bounded sprint if the goal is not done."


def _iteration_deliverables(
    nodes: list[PlanNode],
    blackboard_entries: list[BlackboardEntry],
) -> list[str]:
    values: list[str] = []
    for node in nodes:
        if node.feature_checkpoint is not None:
            values.extend(node.feature_checkpoint.expected_artifacts)
        write_set = dict(node.metadata or {}).get("write_set")
        if isinstance(write_set, list):
            values.extend(item for item in write_set if isinstance(item, str) and item)
    for entry in blackboard_entries:
        if entry.key.startswith("artifact."):
            values.append(entry.key)
    return list(dict.fromkeys(values))[:8]


def _iteration_feedback_items(
    root_goal: WorkspacePlanRootGoalResponse | None,
    outbox_items: list[WorkspacePlanOutboxModel],
    event_items: list[WorkspacePlanEventModel],
) -> list[str]:
    feedback: list[str] = []
    if root_goal and root_goal.completion_blocker_reason:
        feedback.append(root_goal.completion_blocker_reason)
    for item in outbox_items:
        if item.last_error and item.status in {"failed", "dead_letter"}:
            feedback.append(item.last_error)
    for event in event_items:
        payload = dict(event.payload_json or {})
        if event.event_type == "verification_completed" and payload.get("passed") is not True:
            summary = payload.get("summary") or payload.get("reason") or payload.get("error")
            if isinstance(summary, str) and summary:
                feedback.append(summary)
    return list(dict.fromkeys(feedback))[:5]


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


async def _ensure_plan_outbox_worker_running(request: Request) -> None:
    """Idempotently restart the durable plan outbox worker from plan traffic."""
    state = getattr(getattr(request, "app", None), "state", None)
    container = getattr(state, "container", None)
    if container is None:
        return
    redis_client = None
    try:
        redis_client = container.redis()
    except Exception:
        redis_client = None
    try:
        await initialize_workspace_plan_outbox_worker(redis_client=redis_client)
    except Exception:
        logger.warning(
            "workspace_plan.outbox_worker_ensure_failed",
            exc_info=True,
            extra={"event": "workspace_plan.outbox_worker_ensure_failed"},
        )


def _stale_running_nodes(plan: Plan) -> list[PlanNode]:
    now = datetime.now(UTC)
    stale_nodes: list[PlanNode] = []
    for node in plan.nodes.values():
        if node.execution not in {TaskExecution.DISPATCHED, TaskExecution.RUNNING}:
            continue
        threshold_seconds = (
            _SNAPSHOT_RECOVERY_DISPATCH_STALE_SECONDS
            if node.execution is TaskExecution.DISPATCHED
            else _SNAPSHOT_RECOVERY_RUNNING_STALE_SECONDS
        )
        threshold = timedelta(seconds=threshold_seconds)
        last_update = node.updated_at or node.created_at
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=UTC)
        if now - last_update > threshold:
            stale_nodes.append(node)
    return stale_nodes


async def _nodes_without_live_worker(
    *,
    session: AsyncSession,
    nodes: list[PlanNode],
) -> list[PlanNode]:
    """Return stale nodes that do not still have an active worker process.

    Plan node timestamps are updated by adjudication state transitions, not by
    the worker heartbeat loop. A long-running but healthy worker can therefore
    look stale from the plan row alone. Redis running/cooldown keys are the
    runtime-owned liveness signal for launched workers.
    """

    attempt_ids = [
        node.current_attempt_id
        for node in nodes
        if node.execution is TaskExecution.RUNNING and node.current_attempt_id
    ]
    if not attempt_ids:
        return nodes

    result = await session.execute(
        refresh_select_statement(
            select(
                WorkspaceTaskSessionAttemptModel.id,
                WorkspaceTaskSessionAttemptModel.conversation_id,
            ).where(WorkspaceTaskSessionAttemptModel.id.in_(attempt_ids))
        )
    )
    conversation_by_attempt = {
        attempt_id: conversation_id
        for attempt_id, conversation_id in result.all()
        if isinstance(conversation_id, str) and conversation_id
    }
    if not conversation_by_attempt:
        return nodes

    try:
        from src.infrastructure.agent.state.agent_worker_state import get_redis_client

        redis_client = await get_redis_client()
    except Exception:
        logger.debug(
            "workspace_plan.snapshot_liveness_lookup_failed",
            exc_info=True,
            extra={"event": "workspace_plan.snapshot_liveness_lookup_failed"},
        )
        return nodes

    live_attempt_ids: set[str] = set()
    for attempt_id, conversation_id in conversation_by_attempt.items():
        try:
            running_exists = await redis_client.exists(f"agent:running:{conversation_id}")
            cooldown_exists = await redis_client.exists(
                f"workspace:worker_launch:cooldown:{conversation_id}"
            )
        except Exception:
            logger.debug(
                "workspace_plan.snapshot_liveness_key_check_failed",
                exc_info=True,
                extra={
                    "event": "workspace_plan.snapshot_liveness_key_check_failed",
                    "attempt_id": attempt_id,
                    "conversation_id": conversation_id,
                },
            )
            continue
        if bool(running_exists) or bool(cooldown_exists):
            live_attempt_ids.add(attempt_id)

    if not live_attempt_ids:
        return nodes

    filtered = [
        node
        for node in nodes
        if not node.current_attempt_id or node.current_attempt_id not in live_attempt_ids
    ]
    suppressed = len(nodes) - len(filtered)
    if suppressed:
        logger.info(
            "workspace_plan.snapshot_stale_node_recovery_suppressed_live_worker",
            extra={
                "event": "workspace_plan.snapshot_stale_node_recovery_suppressed_live_worker",
                "suppressed": suppressed,
            },
        )
    return filtered


async def _has_pending_node_recovery_job(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan_id: str,
    node_id: str,
) -> bool:
    result = await session.execute(
        refresh_select_statement(
            select(WorkspacePlanOutboxModel.id)
            .where(WorkspacePlanOutboxModel.workspace_id == workspace_id)
            .where(WorkspacePlanOutboxModel.plan_id == plan_id)
            .where(
                WorkspacePlanOutboxModel.event_type.in_([HANDOFF_RESUME_EVENT, WORKER_LAUNCH_EVENT])
            )
            .where(WorkspacePlanOutboxModel.status.in_(["pending", "processing", "failed"]))
            .where(WorkspacePlanOutboxModel.payload_json["node_id"].as_string() == node_id)
            .limit(1)
        )
    )
    return result.scalar_one_or_none() is not None


async def _enqueue_stale_plan_node_recovery(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan: Plan,
    nodes: list[PlanNode],
    actor_id: str,
) -> int:
    root_goal_task_id = plan.goal_node.workspace_task_id or ""
    enqueued = 0
    repo = SqlWorkspacePlanOutboxRepository(session)
    for node in nodes[:1]:
        if not node.workspace_task_id or not node.assignee_agent_id:
            continue
        if await _has_pending_node_recovery_job(
            session=session,
            workspace_id=workspace_id,
            plan_id=plan.id,
            node_id=node.id,
        ):
            continue
        _ = await repo.enqueue(
            plan_id=plan.id,
            workspace_id=workspace_id,
            event_type=HANDOFF_RESUME_EVENT,
            payload={
                "workspace_id": workspace_id,
                "task_id": node.workspace_task_id,
                "node_id": node.id,
                "worker_agent_id": node.assignee_agent_id,
                "actor_user_id": actor_id,
                "previous_attempt_id": node.current_attempt_id,
                "root_goal_task_id": root_goal_task_id,
                "summary": "auto_recovery_stale_plan_node_no_terminal_worker_report",
                "reason": "retry",
                "force_schedule": True,
            },
            metadata={
                "source": "workspace_plan.snapshot_stale_node_recovery",
                "previous_attempt_id": node.current_attempt_id,
            },
        )
        _ = await SqlWorkspacePlanEventRepository(session).append(
            plan_id=plan.id,
            workspace_id=workspace_id,
            node_id=node.id,
            attempt_id=node.current_attempt_id,
            event_type="auto_stale_node_recovery_queued",
            source="workspace_plan_snapshot",
            actor_id=actor_id,
            payload={
                "reason": "stale_plan_node_without_recoverable_attempt",
                "execution": node.execution.value,
            },
        )
        enqueued += 1
    if enqueued:
        await session.commit()
        logger.warning(
            "workspace_plan.snapshot_stale_node_recovery_queued",
            extra={
                "event": "workspace_plan.snapshot_stale_node_recovery_queued",
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "enqueued": enqueued,
            },
        )
    return enqueued


async def _recover_stale_attempts_for_snapshot(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan: Plan,
    actor_id: str,
) -> bool:
    """Best-effort targeted recovery for stale plan nodes observed by the UI."""

    stale_nodes = await _nodes_without_live_worker(
        session=session,
        nodes=_stale_running_nodes(plan),
    )
    if not stale_nodes:
        return False
    try:
        from src.infrastructure.adapters.primary.web.startup.attempt_recovery import (
            recover_workspace_attempts_once,
        )

        recovered_attempts = await recover_workspace_attempts_once(workspace_id)
        if recovered_attempts > 0:
            return True
        return (
            await _enqueue_stale_plan_node_recovery(
                session=session,
                workspace_id=workspace_id,
                plan=plan,
                nodes=stale_nodes,
                actor_id=actor_id,
            )
            > 0
        )
    except Exception:
        logger.warning(
            "workspace_plan.snapshot_recovery_failed",
            exc_info=True,
            extra={
                "event": "workspace_plan.snapshot_recovery_failed",
                "workspace_id": workspace_id,
            },
        )
        return False


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
        await _ensure_plan_outbox_worker_running(request)
        plan_repo = SqlPlanRepository(db)
        plan = await plan_repo.get_by_workspace(workspace_id)
        if plan is None:
            return WorkspacePlanSnapshotResponse(workspace_id=workspace_id)
        if await _recover_stale_attempts_for_snapshot(
            session=db,
            workspace_id=workspace_id,
            plan=plan,
            actor_id=current_user.id,
        ):
            plan = await plan_repo.get_by_workspace(workspace_id)
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
        root_goal = await _load_root_goal_response(db, workspace_id=workspace_id, plan=plan)
        return WorkspacePlanSnapshotResponse(
            workspace_id=workspace_id,
            plan=_to_plan_response(plan),
            root_goal=root_goal,
            iteration=_to_iteration_summary(
                plan=plan,
                root_goal=root_goal,
                blackboard_entries=blackboard_entries,
                outbox_items=outbox_items,
                event_items=event_items,
            ),
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
