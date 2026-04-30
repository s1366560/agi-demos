"""Default-wiring factory for :class:`WorkspaceOrchestrator`.

Returns an orchestrator configured either with side-effect-free in-memory
adapters for tests/CLI callers or SQL-backed repositories for request-scoped
workspace execution. Production call sites should prefer ``build_sql_orchestrator``
so durable plans, verifier events, and workspace-task projections stay in one
transactional path.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.model.workspace_plan import PlanNode
from src.domain.ports.services.iteration_review_port import IterationReviewPort
from src.domain.ports.services.task_allocator_port import Allocation, WorkspaceAgent
from src.domain.ports.services.verifier_port import VerificationContext
from src.infrastructure.adapters.secondary.persistence.models import (
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
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    LAST_LEADER_ADJUDICATION_STATUS,
    LAST_WORKER_REPORT_SUMMARY,
    PENDING_LEADER_ADJUDICATION,
    ROOT_GOAL_TASK_ID,
)
from src.infrastructure.agent.workspace_plan.allocator import CapabilityAllocator
from src.infrastructure.agent.workspace_plan.blackboard import InMemoryBlackboard
from src.infrastructure.agent.workspace_plan.orchestrator import (
    OrchestratorConfig,
    WorkspaceOrchestrator,
)
from src.infrastructure.agent.workspace_plan.planner import LLMGoalPlanner, TaskDecomposerProtocol
from src.infrastructure.agent.workspace_plan.progress import ProgressProjector
from src.infrastructure.agent.workspace_plan.repository import InMemoryPlanRepository
from src.infrastructure.agent.workspace_plan.supervisor import (
    AgentPoolProvider,
    AttemptContextProvider,
    Dispatcher,
    PlanEventSink,
    ProgressSink,
    WorkspaceSupervisor,
)
from src.infrastructure.agent.workspace_plan.verifier import AcceptanceCriterionVerifier

logger = logging.getLogger(__name__)


async def _empty_agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
    return []


async def _noop_dispatcher(workspace_id: str, allocation: Allocation, node: PlanNode) -> str | None:
    logger.info(
        "workspace_plan.dispatcher.noop workspace=%s node=%s agent=%s",
        workspace_id,
        node.id,
        getattr(allocation, "agent_id", None),
    )
    return None


async def _default_attempt_context(workspace_id: str, node: PlanNode) -> VerificationContext:
    return VerificationContext(workspace_id=workspace_id, node=node)


def _make_sql_plan_event_sink(db: AsyncSession) -> PlanEventSink:
    async def _sink(
        workspace_id: str,
        node: PlanNode,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        _ = await SqlWorkspacePlanEventRepository(db).append(
            plan_id=node.plan_id,
            workspace_id=workspace_id,
            node_id=node.id,
            attempt_id=_payload_string(payload, "attempt_id") or node.current_attempt_id,
            event_type=event_type,
            source="workspace_plan_verifier",
            payload=payload,
        )
        if event_type == "verification_completed":
            await _project_verification_to_workspace_task(db, node, payload)
        if event_type == "verification_retry_scheduled":
            await SqlWorkspacePlanOutboxRepository(db).enqueue(
                plan_id=node.plan_id,
                workspace_id=workspace_id,
                event_type="supervisor_tick",
                payload={
                    "workspace_id": workspace_id,
                    "retry_node_id": node.id,
                    "retry_attempt_id": _payload_string(payload, "attempt_id"),
                    "retry_reason": "verification_retry_scheduled",
                },
                metadata={
                    "source_event_type": event_type,
                    "node_id": node.id,
                    "attempt_id": _payload_string(payload, "attempt_id"),
                },
                next_attempt_at=_payload_datetime(payload, "retry_not_before"),
            )
        if event_type == "iteration_next_sprint_planned":
            await SqlWorkspacePlanOutboxRepository(db).enqueue(
                plan_id=node.plan_id,
                workspace_id=workspace_id,
                event_type="supervisor_tick",
                payload={
                    "workspace_id": workspace_id,
                    "plan_id": node.plan_id,
                    "iteration_followup": "next_sprint_dispatch",
                    "reviewed_iteration": payload.get("iteration_index"),
                    "next_iteration": payload.get("next_iteration"),
                },
                metadata={
                    "source_event_type": event_type,
                    "node_id": node.id,
                    "iteration_index": payload.get("iteration_index"),
                    "next_iteration": payload.get("next_iteration"),
                },
            )
        if event_type == "pipeline_run_requested":
            await SqlWorkspacePlanOutboxRepository(db).enqueue(
                plan_id=node.plan_id,
                workspace_id=workspace_id,
                event_type="pipeline_run_requested",
                payload={
                    "workspace_id": workspace_id,
                    "plan_id": node.plan_id,
                    "node_id": node.id,
                    "attempt_id": _payload_string(payload, "attempt_id")
                    or node.current_attempt_id,
                    "reason": payload.get("reason") or "pipeline_gate_required",
                },
                metadata={
                    "source_event_type": event_type,
                    "node_id": node.id,
                    "attempt_id": _payload_string(payload, "attempt_id")
                    or node.current_attempt_id,
                },
            )
        if event_type == "dispatch_deferred_concurrency_limit":
            await SqlWorkspacePlanOutboxRepository(db).enqueue(
                plan_id=node.plan_id,
                workspace_id=workspace_id,
                event_type="supervisor_tick",
                payload={
                    "workspace_id": workspace_id,
                    "plan_id": node.plan_id,
                    "deferred_node_id": node.id,
                    "deferred_reason": "dispatch_concurrency_limit",
                },
                metadata={
                    "source_event_type": event_type,
                    "node_id": node.id,
                    "max_dispatches_per_tick": payload.get("max_dispatches_per_tick"),
                },
            )

    return _sink


async def _project_verification_to_workspace_task(
    db: AsyncSession,
    node: PlanNode,
    payload: dict[str, Any],
) -> None:
    """Keep workspace task/session projections in sync with V2 verifier authority."""
    attempt_id = _payload_string(payload, "attempt_id") or node.current_attempt_id
    passed = bool(payload.get("passed"))
    hard_fail = bool(payload.get("hard_fail"))
    summary = str(payload.get("summary") or "")
    now = datetime.now(UTC)
    evidence_refs = _verification_payload_evidence_refs(payload)
    commit_ref = _first_prefixed_evidence_value(evidence_refs, "commit_ref:")
    git_diff_summary = _first_prefixed_evidence_value(evidence_refs, "git_diff_summary:")
    test_commands = [
        ref.removeprefix("test_run:") for ref in evidence_refs if ref.startswith("test_run:")
    ]

    if attempt_id:
        await _project_verification_to_attempt(
            db=db,
            attempt_id=attempt_id,
            passed=passed,
            hard_fail=hard_fail,
            summary=summary,
            now=now,
        )

    if node.workspace_task_id:
        task = await db.get(WorkspaceTaskModel, node.workspace_task_id)
        if task is not None:
            await _project_verification_to_task(
                db=db,
                task=task,
                attempt_id=attempt_id,
                passed=passed,
                hard_fail=hard_fail,
                summary=summary,
                evidence_refs=evidence_refs,
                commit_ref=commit_ref,
                git_diff_summary=git_diff_summary,
                test_commands=test_commands,
                now=now,
            )


async def _project_verification_to_attempt(
    *,
    db: AsyncSession,
    attempt_id: str,
    passed: bool,
    hard_fail: bool,
    summary: str,
    now: datetime,
) -> None:
    attempt = await db.get(WorkspaceTaskSessionAttemptModel, attempt_id)
    if attempt is None:
        return
    if passed:
        attempt.status = WorkspaceTaskSessionAttemptStatus.ACCEPTED.value
        attempt.leader_feedback = summary or "accepted by durable plan verifier"
    elif hard_fail:
        attempt.status = WorkspaceTaskSessionAttemptStatus.BLOCKED.value
        attempt.leader_feedback = summary or "blocked by durable plan verifier"
    else:
        attempt.status = WorkspaceTaskSessionAttemptStatus.REJECTED.value
        attempt.leader_feedback = summary or "replan requested by durable plan verifier"
    attempt.completed_at = now
    attempt.updated_at = now


async def _project_verification_to_task(
    *,
    db: AsyncSession,
    task: WorkspaceTaskModel,
    attempt_id: str | None,
    passed: bool,
    hard_fail: bool,
    summary: str,
    evidence_refs: list[str],
    commit_ref: str | None,
    git_diff_summary: str | None,
    test_commands: list[str],
    now: datetime,
) -> None:
    metadata = dict(task.metadata_json or {})
    metadata[PENDING_LEADER_ADJUDICATION] = False
    metadata["durable_plan_verdict"] = (
        "accepted" if passed else "blocked" if hard_fail else "replan_requested"
    )
    metadata["durable_plan_verification_summary"] = summary
    metadata["durable_plan_verified_at"] = now.isoformat().replace("+00:00", "Z")
    if passed:
        _apply_verification_checkpoint_metadata(
            metadata=metadata,
            summary=summary,
            evidence_refs=evidence_refs,
            commit_ref=commit_ref,
            git_diff_summary=git_diff_summary,
            test_commands=test_commands,
            created_at=now,
        )
    metadata["last_attempt_status"] = _verification_attempt_status(
        passed=passed,
        hard_fail=hard_fail,
    )
    if attempt_id:
        metadata["last_attempt_id"] = attempt_id
        metadata[CURRENT_ATTEMPT_ID] = attempt_id
    if passed:
        metadata["last_worker_report_type"] = "completed"
        metadata[LAST_WORKER_REPORT_SUMMARY] = summary or str(
            metadata.get(LAST_WORKER_REPORT_SUMMARY) or "Accepted by durable plan verifier."
        )
        metadata[LAST_LEADER_ADJUDICATION_STATUS] = "accepted"
    task.metadata_json = metadata
    if passed:
        task.status = "done"
        task.blocker_reason = None
        task.completed_at = now
    elif hard_fail:
        task.status = "blocked"
        task.blocker_reason = summary or "durable plan verification failed"
    task.updated_at = now
    await _reconcile_root_goal_if_present(db, task, metadata)


def _verification_attempt_status(*, passed: bool, hard_fail: bool) -> str:
    if passed:
        return WorkspaceTaskSessionAttemptStatus.ACCEPTED.value
    if hard_fail:
        return WorkspaceTaskSessionAttemptStatus.BLOCKED.value
    return WorkspaceTaskSessionAttemptStatus.REJECTED.value


async def _reconcile_root_goal_if_present(
    db: AsyncSession,
    task: WorkspaceTaskModel,
    metadata: dict[str, Any],
) -> None:
    root_goal_task_id = metadata.get(ROOT_GOAL_TASK_ID)
    if not isinstance(root_goal_task_id, str) or not root_goal_task_id:
        return
    from src.application.services.workspace_agent_autonomy import (
        reconcile_root_goal_progress,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
        SqlWorkspaceTaskRepository,
    )

    _ = await reconcile_root_goal_progress(
        task_repo=SqlWorkspaceTaskRepository(db),
        workspace_id=task.workspace_id,
        root_goal_task_id=root_goal_task_id,
    )


def _payload_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _payload_datetime(payload: dict[str, Any], key: str) -> datetime | None:
    value = _payload_string(payload, key)
    if value is None:
        return None
    if value.endswith("Z"):
        value = value.removesuffix("Z") + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _verification_payload_evidence_refs(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    results = payload.get("results")
    if not isinstance(results, list):
        return refs
    for result in results:
        if not isinstance(result, dict):
            continue
        evidence = result.get("evidence")
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if isinstance(item, dict) and isinstance(item.get("ref"), str):
                refs.append(item["ref"])
    return list(dict.fromkeys(refs))


def _first_prefixed_evidence_value(refs: list[str], prefix: str) -> str | None:
    for ref in refs:
        if ref.startswith(prefix):
            return ref.removeprefix(prefix)
    return None


def _apply_verification_checkpoint_metadata(
    *,
    metadata: dict[str, Any],
    summary: str,
    evidence_refs: list[str],
    commit_ref: str | None,
    git_diff_summary: str | None,
    test_commands: list[str],
    created_at: datetime,
) -> None:
    if commit_ref or git_diff_summary or test_commands:
        feature_checkpoint = metadata.get("feature_checkpoint")
        if isinstance(feature_checkpoint, dict):
            if commit_ref:
                feature_checkpoint["commit_ref"] = commit_ref
            metadata["feature_checkpoint"] = feature_checkpoint
        handoff = metadata.get("handoff_package")
        if not isinstance(handoff, dict):
            handoff = {
                "reason": "planned",
                "summary": "Accepted by durable plan verifier.",
                "next_steps": [],
                "completed_steps": [],
                "changed_files": [],
                "git_head": None,
                "git_diff_summary": "",
                "test_commands": [],
                "verification_notes": "",
                "created_at": created_at.isoformat(),
            }
        if commit_ref:
            handoff["git_head"] = commit_ref
        if git_diff_summary:
            handoff["git_diff_summary"] = git_diff_summary
        if test_commands:
            handoff["test_commands"] = test_commands
        handoff["verification_notes"] = summary
        metadata["handoff_package"] = handoff

    progress_events = metadata.get("progress_events")
    if not isinstance(progress_events, list):
        progress_events = []
    progress_events.append(
        {
            "event_id": f"verification:{created_at.isoformat()}",
            "event_type": "verification_accepted",
            "summary": summary or "Accepted by durable plan verifier.",
            "evidence_refs": evidence_refs,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
        }
    )
    metadata["progress_events"] = progress_events[-25:]
    metadata["next_session_briefing"] = _build_next_session_briefing(
        summary=summary,
        evidence_refs=evidence_refs,
        commit_ref=commit_ref,
        git_diff_summary=git_diff_summary,
        test_commands=test_commands,
    )


def _build_next_session_briefing(
    *,
    summary: str,
    evidence_refs: list[str],
    commit_ref: str | None,
    git_diff_summary: str | None,
    test_commands: list[str],
) -> str:
    lines = [
        "Last durable verification passed.",
        f"Summary: {summary or 'accepted by durable plan verifier'}",
    ]
    if commit_ref:
        lines.append(f"Commit: {commit_ref}")
    if git_diff_summary:
        lines.append(f"Git diff: {git_diff_summary}")
    if test_commands:
        lines.append("Tests: " + "; ".join(test_commands))
    browser_refs = [ref for ref in evidence_refs if ref.startswith(("browser_e2e:", "screenshot:"))]
    if browser_refs:
        lines.append("Browser evidence: " + "; ".join(browser_refs))
    lines.append("Next session: inspect git status, feature checkpoint, and latest progress event.")
    return "\n".join(lines)


def build_default_orchestrator(
    *,
    config: OrchestratorConfig | None = None,
    decomposer: TaskDecomposerProtocol | None = None,
    iteration_reviewer: IterationReviewPort | None = None,
) -> WorkspaceOrchestrator:
    """Wire a default, side-effect-free :class:`WorkspaceOrchestrator`.

    Suitable for unit tests, CLI tools, and the initial DI singleton. Real
    production wiring will replace the stub callables with the worker-launch
    dispatcher and SQL-backed repositories.
    """
    cfg = config or OrchestratorConfig.from_env()
    plan_repo = InMemoryPlanRepository()
    planner = LLMGoalPlanner(decomposer=decomposer)
    allocator = CapabilityAllocator()
    verifier = AcceptanceCriterionVerifier()
    projector = ProgressProjector()
    blackboard = InMemoryBlackboard()
    supervisor = WorkspaceSupervisor(
        plan_repo=plan_repo,
        allocator=allocator,
        verifier=verifier,
        projector=projector,
        planner=planner,
        agent_pool=_empty_agent_pool,
        dispatcher=_noop_dispatcher,
        attempt_context=_default_attempt_context,
        iteration_reviewer=iteration_reviewer,
        heartbeat_seconds=cfg.heartbeat_seconds,
        max_dispatches_per_tick=cfg.max_dispatches_per_tick,
    )
    return WorkspaceOrchestrator(
        planner=planner,
        allocator=allocator,
        verifier=verifier,
        projector=projector,
        supervisor=supervisor,
        plan_repo=plan_repo,
        blackboard=blackboard,
        config=cfg,
    )


def build_sql_orchestrator(
    db: AsyncSession,
    *,
    config: OrchestratorConfig | None = None,
    decomposer: TaskDecomposerProtocol | None = None,
    agent_pool: AgentPoolProvider | None = None,
    dispatcher: Dispatcher | None = None,
    attempt_context: AttemptContextProvider | None = None,
    progress_sink: ProgressSink | None = None,
    event_sink: PlanEventSink | None = None,
    iteration_reviewer: IterationReviewPort | None = None,
) -> WorkspaceOrchestrator:
    """Wire a SQL-backed Workspace V2 orchestrator.

    This is an explicit boundary for request-scoped or job-scoped callers. The
    caller owns the provided ``AsyncSession`` lifetime and commit. Long-lived
    production supervisors should use a future session-factory/outbox wrapper
    rather than retaining a request session indefinitely.
    """
    cfg = config or OrchestratorConfig.from_env()
    plan_repo = SqlPlanRepository(db)
    planner = LLMGoalPlanner(decomposer=decomposer)
    allocator = CapabilityAllocator()
    verifier = AcceptanceCriterionVerifier()
    projector = ProgressProjector()
    blackboard = SqlWorkspacePlanBlackboard(db)
    supervisor = WorkspaceSupervisor(
        plan_repo=plan_repo,
        allocator=allocator,
        verifier=verifier,
        projector=projector,
        planner=planner,
        agent_pool=agent_pool or _empty_agent_pool,
        dispatcher=dispatcher or _noop_dispatcher,
        attempt_context=attempt_context or _default_attempt_context,
        progress_sink=progress_sink,
        event_sink=event_sink or _make_sql_plan_event_sink(db),
        iteration_reviewer=iteration_reviewer,
        heartbeat_seconds=cfg.heartbeat_seconds,
        max_dispatches_per_tick=cfg.max_dispatches_per_tick,
    )
    return WorkspaceOrchestrator(
        planner=planner,
        allocator=allocator,
        verifier=verifier,
        projector=projector,
        supervisor=supervisor,
        plan_repo=plan_repo,
        blackboard=blackboard,
        config=cfg,
    )


__all__ = ["build_default_orchestrator", "build_sql_orchestrator"]
