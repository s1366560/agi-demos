"""Workspace plan compatibility routes owned by Avernet Workspace Core."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Never

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/plan", tags=["workspace-plans"])


class WorkspacePlanActionCapabilityResponse(BaseModel):
    enabled: bool
    label: str
    reason: str | None = None
    requires_confirmation: bool = False


class WorkspacePlanPhaseContractResponse(BaseModel):
    phase: str = "plan"
    title: str = "Plan"
    entry_gate: str = ""
    exit_gate: str = ""
    required_evidence: list[str] = Field(default_factory=list)
    allowed_routing: list[str] = Field(default_factory=list)
    blocked_semantics: str = (
        "Blocked is reserved for missing human permission, credentials, policy decisions, or "
        "irreversible operator choices. Test, pipeline, or evidence failures should route to "
        "recovery or replan."
    )


class WorkspacePlanGateStatusResponse(BaseModel):
    status: str = "pending"
    summary: str = ""
    missing: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    routing: str = "continue"


class WorkspacePlanEvidenceBundleResponse(BaseModel):
    artifacts: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    pipeline_refs: list[str] = Field(default_factory=list)
    verification_summary: str = ""
    review_summary: str = ""


class WorkspacePlanBlockerAnalysisResponse(BaseModel):
    blocker_type: str = "none"
    root_cause: str = ""
    resolution: str = ""
    routing_decision: str = "continue"
    human_intervention_required: bool = False


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
    phase_contract: WorkspacePlanPhaseContractResponse | None = None
    evidence_bundle: WorkspacePlanEvidenceBundleResponse = Field(
        default_factory=WorkspacePlanEvidenceBundleResponse
    )
    gate_status: WorkspacePlanGateStatusResponse = Field(default_factory=WorkspacePlanGateStatusResponse)
    blocker_analysis: WorkspacePlanBlockerAnalysisResponse | None = None
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
    gate_status: WorkspacePlanGateStatusResponse = Field(default_factory=WorkspacePlanGateStatusResponse)
    required_artifacts: list[str] = Field(default_factory=list)
    missing_artifacts: list[str] = Field(default_factory=list)
    summary: str = ""


class WorkspacePlanIterationHistoryResponse(BaseModel):
    iteration_index: int
    verdict: str
    summary: str
    confidence: float = 0.0
    next_sprint_goal: str = ""
    created_at: str = ""


class WorkspacePlanReviewFindingResponse(BaseModel):
    file: str
    line: int
    category: str
    severity: str
    raw_confidence: int
    validated_confidence: int
    description: str
    suggestion: str = ""
    concrete_evidence: bool = False
    verdict: str
    reasoning: str = ""


class WorkspacePlanIterationSummaryResponse(BaseModel):
    current_iteration: int = 1
    loop_label: str = "Scrum feedback loop"
    cadence: str = "research -> plan -> implement -> test -> deploy -> review"
    loop_status: str = "active"
    max_iterations: int = 8
    completed_iterations: list[int] = Field(default_factory=list)
    current_sprint_goal: str = ""
    review_summary: str = ""
    stop_reason: str = ""
    active_phase: str = "research"
    active_phase_label: str = "Research"
    next_action: str = ""
    task_count: int = 0
    task_budget: int = 6
    phases: list[WorkspacePlanIterationPhaseResponse] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    feedback_items: list[str] = Field(default_factory=list)
    history: list[WorkspacePlanIterationHistoryResponse] = Field(default_factory=list)
    actions: dict[str, WorkspacePlanActionCapabilityResponse] = Field(default_factory=dict)
    findings: list[WorkspacePlanReviewFindingResponse] = Field(default_factory=list)
    rejected_finding_count: int = 0


class WorkspacePipelineStageRunResponse(BaseModel):
    id: str
    run_id: str
    stage: str
    status: str
    service_id: str | None = None
    external_id: str | None = None
    external_url: str | None = None
    step_name: str | None = None
    command: str | None = None
    exit_code: int | None = None
    stdout_preview: str | None = None
    stderr_preview: str | None = None
    log_ref: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkspacePipelineRunResponse(BaseModel):
    id: str
    provider: str
    status: str
    reason: str | None = None
    external_id: str | None = None
    external_url: str | None = None
    node_id: str | None = None
    attempt_id: str | None = None
    commit_ref: str | None = None
    stages: list[WorkspacePipelineStageRunResponse] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class WorkspaceDeploymentResponse(BaseModel):
    id: str
    provider: str
    status: str
    service_id: str | None = None
    service_name: str | None = None
    node_id: str | None = None
    pipeline_run_id: str | None = None
    command: str | None = None
    pid: int | None = None
    port: int | None = None
    service_url: str | None = None
    preview_url: str | None = None
    ws_preview_url: str | None = None
    health_url: str | None = None
    required: bool = True
    restart_count: int = 0
    last_healthy_at: datetime | None = None
    rollback_ref: str | None = None
    log_ref: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class WorkspaceDeliveryServiceResponse(BaseModel):
    service_id: str
    name: str
    start_command: str | None = None
    internal_port: int | None = None
    internal_scheme: str = "http"
    path_prefix: str = "/"
    health_path: str | None = None
    health_command: str | None = None
    required: bool = True
    auto_open: bool = True
    preview_url: str | None = None
    status: str = "not_deployed"


class WorkspacePlanRunAssessmentResponse(BaseModel):
    status: str = "not_run"
    summary: str = "No pipeline run has been recorded."
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_services_total: int = 0
    required_services_healthy: int = 0
    failed_required_services: list[str] = Field(default_factory=list)


class WorkspaceDeliverySummaryResponse(BaseModel):
    provider: str = "sandbox_native"
    status: str = "not_configured"
    contract_source: str = "metadata"
    contract_confidence: float = 0.0
    agent_managed: bool = True
    code_root: str | None = None
    latest_run: WorkspacePipelineRunResponse | None = None
    recent_runs: list[WorkspacePipelineRunResponse] = Field(default_factory=list)
    services: list[WorkspaceDeliveryServiceResponse] = Field(default_factory=list)
    deployment: WorkspaceDeploymentResponse | None = None
    deployments: list[WorkspaceDeploymentResponse] = Field(default_factory=list)
    run_assessment: WorkspacePlanRunAssessmentResponse = Field(
        default_factory=WorkspacePlanRunAssessmentResponse
    )
    warnings: list[str] = Field(default_factory=list)
    actions: dict[str, WorkspacePlanActionCapabilityResponse] = Field(default_factory=dict)


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


class WorkspacePlanIterationRunResponse(BaseModel):
    iteration_index: int
    status: str
    sprint_goal: str = ""
    review_summary: str = ""
    next_sprint_goal: str = ""
    time_range: dict[str, str] = Field(default_factory=dict)
    task_counts: dict[str, int] = Field(default_factory=dict)
    attempt_counts: dict[str, int] = Field(default_factory=dict)
    interaction_counts: dict[str, int] = Field(default_factory=dict)
    feedback_counts: dict[str, int] = Field(default_factory=dict)
    deliverables: dict[str, list[str]] = Field(default_factory=dict)
    verification_summary: dict[str, int] = Field(default_factory=dict)
    repair_turns: list[dict[str, Any]] = Field(default_factory=list)
    carryover_node_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)


class WorkspacePlanRunHealthResponse(BaseModel):
    final_status: str = "unknown"
    attempt_success_rate: float = 0.0
    attempts: dict[str, int] = Field(default_factory=dict)
    interactions: dict[str, int] = Field(default_factory=dict)
    top_failure_reasons: list[dict[str, Any]] = Field(default_factory=list)
    recovery_events: int = 0
    provider_error_events: int = 0
    repair_turns: dict[str, int] = Field(default_factory=dict)
    feedback_counts: dict[str, int] = Field(default_factory=dict)
    stale_evidence_events: int = 0
    dirty_worktree_events: int = 0
    missing_report_events: int = 0


class WorkspacePlanArtifactIndexResponse(BaseModel):
    verified_outputs: list[dict[str, Any]] = Field(default_factory=list)
    claimed_outputs: list[dict[str, Any]] = Field(default_factory=list)
    final_deliverables: list[dict[str, Any]] = Field(default_factory=list)


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


class WorkspacePlanHistoryItemResponse(BaseModel):
    plan_id: str
    title: str
    status: str
    loop_status: str
    root_goal_id: str | None = None
    root_goal_status: str | None = None
    current_iteration: int = 1
    max_iterations: int = 8
    completed_iterations: list[int] = Field(default_factory=list)
    task_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None
    is_latest: bool = False
    is_selected: bool = False


class WorkspacePlanSnapshotResponse(BaseModel):
    workspace_id: str
    plan: WorkspacePlanResponse | None = None
    root_goal: WorkspacePlanRootGoalResponse | None = None
    iteration: WorkspacePlanIterationSummaryResponse | None = None
    delivery: WorkspaceDeliverySummaryResponse | None = None
    blackboard: list[WorkspacePlanBlackboardEntryResponse] = Field(default_factory=list)
    outbox: list[WorkspacePlanOutboxItemResponse] = Field(default_factory=list)
    events: list[WorkspacePlanEventResponse] = Field(default_factory=list)
    plan_history: list[WorkspacePlanHistoryItemResponse] = Field(default_factory=list)
    iteration_runs: list[WorkspacePlanIterationRunResponse] = Field(default_factory=list)
    run_health: WorkspacePlanRunHealthResponse | None = None
    artifact_index: WorkspacePlanArtifactIndexResponse | None = None


class WorkspacePlanActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class WorkspacePlanPipelineRunRequest(WorkspacePlanActionRequest):
    node_id: str | None = None


class WorkspacePlanActionResultResponse(BaseModel):
    ok: bool
    message: str
    plan_id: str
    node_id: str | None = None
    outbox_id: str | None = None


def _retired(*values: object) -> Never:
    del values
    raise workspace_core_unavailable_error()


@router.get("", response_model=WorkspacePlanSnapshotResponse)
async def get_workspace_plan_snapshot(
    workspace_id: str,
    request: Request,
    outbox_limit: int = Query(20, ge=0, le=100),
    event_limit: int = Query(50, ge=0, le=200),
    include_details: bool = Query(True),
    recover_stale_attempts: bool = Query(False),
    plan_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanSnapshotResponse:
    _retired(
        workspace_id,
        request,
        outbox_limit,
        event_limit,
        include_details,
        recover_stale_attempts,
        plan_id,
        current_user,
        db,
    )


@router.post("/recover-stale-attempts", response_model=WorkspacePlanActionResultResponse)
async def recover_workspace_plan_stale_attempts(
    workspace_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    _retired(workspace_id, body, request, current_user, db)


@router.post("/outbox/{outbox_id}/retry", response_model=WorkspacePlanActionResultResponse)
async def retry_workspace_plan_outbox_item(
    workspace_id: str,
    outbox_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    _retired(workspace_id, outbox_id, body, request, current_user, db)


async def _iteration_action(
    workspace_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> WorkspacePlanActionResultResponse:
    _retired(workspace_id, body, request, current_user, db)


@router.post("/iteration/pause", response_model=WorkspacePlanActionResultResponse)
async def pause_workspace_plan_iteration_loop(
    workspace_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    return await _iteration_action(workspace_id, body, request, current_user, db)


@router.post("/iteration/resume", response_model=WorkspacePlanActionResultResponse)
async def resume_workspace_plan_iteration_loop(
    workspace_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    return await _iteration_action(workspace_id, body, request, current_user, db)


@router.post("/iteration/trigger-next", response_model=WorkspacePlanActionResultResponse)
async def trigger_workspace_plan_next_iteration(
    workspace_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    return await _iteration_action(workspace_id, body, request, current_user, db)


@router.post("/delivery/run-pipeline", response_model=WorkspacePlanActionResultResponse)
async def request_workspace_plan_pipeline_run(
    workspace_id: str,
    body: WorkspacePlanPipelineRunRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    _retired(workspace_id, body, request, current_user, db)


@router.post("/delivery/regenerate-contract", response_model=WorkspacePlanActionResultResponse)
async def request_workspace_plan_delivery_contract_regeneration(
    workspace_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    _retired(workspace_id, body, request, current_user, db)


async def _node_action(
    workspace_id: str,
    node_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> WorkspacePlanActionResultResponse:
    _retired(workspace_id, node_id, body, request, current_user, db)


@router.post("/nodes/{node_id}/request-replan", response_model=WorkspacePlanActionResultResponse)
async def request_workspace_plan_node_replan(
    workspace_id: str,
    node_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    return await _node_action(workspace_id, node_id, body, request, current_user, db)


@router.post("/nodes/{node_id}/reopen", response_model=WorkspacePlanActionResultResponse)
async def reopen_blocked_workspace_plan_node(
    workspace_id: str,
    node_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    return await _node_action(workspace_id, node_id, body, request, current_user, db)


@router.post("/nodes/{node_id}/accept-review", response_model=WorkspacePlanActionResultResponse)
async def accept_review_workspace_plan_node(
    workspace_id: str,
    node_id: str,
    body: WorkspacePlanActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanActionResultResponse:
    return await _node_action(workspace_id, node_id, body, request, current_user, db)
