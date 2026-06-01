"""Handlers for durable workspace plan outbox jobs."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import posixpath
import re
import shlex
import shutil
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis
from dotenv import dotenv_values
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_agent_autonomy import AUTONOMY_SCHEMA_VERSION
from src.application.services.workspace_autonomy_profiles import resolve_workspace_type
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import (
    WorkspaceTaskAuthorityContext,
    WorkspaceTaskService,
)
from src.application.services.workspace_task_session_attempt_service import (
    WorkspaceTaskSessionAttemptService,
)
from src.domain.model.agent.agent_definition import Agent
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.model.workspace_plan import (
    FeatureCheckpoint,
    HandoffPackage,
    HandoffReason,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanStatus,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.services.iteration_review_port import IterationReviewPort
from src.domain.ports.services.task_allocator_port import (
    Allocation,
    WorkspaceAgent as AllocatorAgent,
)
from src.domain.ports.services.verifier_port import VerificationContext
from src.domain.ports.services.workspace_supervisor_decision_port import (
    WorkspaceSupervisorDecisionPort,
)
from src.domain.ports.services.workspace_supervisor_port import TickReport
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgePort,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspacePipelineRunModel,
    WorkspacePlanEventModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
    SqlAgentRegistryRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
    SqlWorkspaceAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
    SqlWorkspaceMemberRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_pipeline import (
    SqlWorkspacePipelineRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_events import (
    SqlWorkspacePlanEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    SqlWorkspaceRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_session_attempt_repository import (
    SqlWorkspaceTaskSessionAttemptRepository,
)
from src.infrastructure.agent.tools.workspace_planning_contract import PLANNING_CONTRACT_SOURCE
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    DERIVED_FROM_INTERNAL_PLAN_STEP,
    EXECUTION_STATE,
    LAST_WORKER_REPORT_ATTEMPT_ID,
    LAST_WORKER_REPORT_SUMMARY,
    LINEAGE_SOURCE,
    PREFERRED_LANGUAGE,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
    WORKSPACE_AGENT_BINDING_ID,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)
from src.infrastructure.agent.workspace_plan.factory import (
    _project_supervisor_disposition_to_workspace_task,
    _project_verification_to_task,
    build_sql_orchestrator,
)
from src.infrastructure.agent.workspace_plan.iteration_review import (
    UnavailableIterationReviewProvider,
    WorkspaceIterationReviewAgentProvider,
)
from src.infrastructure.agent.workspace_plan.orchestrator import OrchestratorConfig
from src.infrastructure.agent.workspace_plan.outbox_worker import WorkspacePlanOutboxHandler
from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_DOCKER_DEPLOY_VALIDATION,
    DRONE_PROVIDER,
    SANDBOX_NATIVE_PROVIDER,
    PipelineContractSpec,
    PipelineRunResult,
    PipelineServiceSpec,
    PipelineStageResult,
    SandboxNativePipelineProvider,
    build_pipeline_contract_from_metadata,
)
from src.infrastructure.agent.workspace_plan.pipeline_provider_registry import (
    PipelineProviderUnavailableError,
    require_pipeline_provider,
)
from src.infrastructure.agent.workspace_plan.run_controller import WorkspaceRunController
from src.infrastructure.agent.workspace_plan.supervisor import (
    AgentPoolProvider,
    AttemptContextProvider,
    Dispatcher,
    ProgressSink,
)
from src.infrastructure.agent.workspace_plan.supervisor_decision import (
    UnavailableWorkspaceSupervisorDecisionProvider,
    WorkspaceSupervisorAgentDecisionProvider,
)
from src.infrastructure.agent.workspace_plan.system_actor import (
    LEGACY_SISYPHUS_AGENT_ID,
    WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
    persisted_attempt_leader_agent_id,
)
from src.infrastructure.agent.workspace_plan.verification_judge import (
    UnavailableWorkspaceVerificationJudge,
    WorkspaceVerifierAgentJudge,
)
from src.infrastructure.agent.workspace_plan.worktree_agent import WorkspaceWorktreeAgentPreparer
from src.infrastructure.agent.workspace_plan.worktree_manager import (
    AttemptWorktreeContext,
    WorkspaceWorktreeManager,
    compact_command_output as _manager_compact_command_output,
    default_attempt_worktree_path as _manager_default_attempt_worktree_path,
    safe_git_token as _manager_safe_git_token,
    worktree_branch_name as _manager_worktree_branch_name,
    worktree_dirty_signature_command as _manager_worktree_dirty_signature_command,
    worktree_integration_command as _manager_worktree_integration_command,
    worktree_setup_command as _manager_worktree_setup_command,
    worktree_setup_note as _manager_worktree_setup_note,
)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

SUPERVISOR_TICK_EVENT = "supervisor_tick"
WORKER_LAUNCH_EVENT = "worker_launch"
HANDOFF_RESUME_EVENT = "handoff_resume"
ATTEMPT_RETRY_EVENT = "attempt_retry"
PIPELINE_RUN_REQUESTED_EVENT = "pipeline_run_requested"
PIPELINE_STAGE_EXECUTE_EVENT = "pipeline_stage_execute"
DEPLOYMENT_REQUESTED_EVENT = "deployment_requested"
DEPLOYMENT_HEALTH_CHECK_EVENT = "deployment_health_check"
PIPELINE_LOGS_SYNC_EVENT = "pipeline_logs_sync"
logger = logging.getLogger(__name__)
_WORKER_LAUNCH_MAX_ACTIVE_ENV = "WORKSPACE_WORKER_LAUNCH_MAX_ACTIVE"
_WORKER_LAUNCH_DEFER_SECONDS_ENV = "WORKSPACE_WORKER_LAUNCH_DEFER_SECONDS"
_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV = "WORKSPACE_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES"
_REPAIR_TURN_REUSE_ENABLED_ENV = "WORKSPACE_REPAIR_TURN_REUSE_ENABLED"
_REPAIR_TURN_REUSE_MAX_ENV = "WORKSPACE_REPAIR_TURN_REUSE_MAX"
_DEFAULT_SOFTWARE_WORKSPACE_MAX_SUBTASKS = 6
_MAX_WORKSPACE_DECOMPOSER_MAX_SUBTASKS = 12
_DEFAULT_WORKER_LAUNCH_MAX_ACTIVE = 4
_DEFAULT_WORKER_LAUNCH_DEFER_SECONDS = 20
_DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES = 3
_DEFAULT_REPAIR_TURN_REUSE_MAX = 2
_REPAIR_TURN_METADATA_KEY = "current_repair_turn"
_TERMINAL_ATTEMPT_STATUS_VALUES = frozenset(
    {
        "accepted",
        "rejected",
        "blocked",
        "cancelled",
    }
)
_WORKER_LAUNCHABLE_ATTEMPT_STATUS_VALUES = frozenset({"pending", "running"})
_NO_OUTPUT_SENTINELS = frozenset(
    {
        "(no output)",
        "tool executed successfully (no output)",
        "tool executed successfully. (no output)",
    }
)

WorktreePreparer = Callable[
    [AsyncSession, str, WorkspaceTask, str | None, str | None],
    Awaitable[str | AttemptWorktreeContext | None],
]

_AUTO_TEAM_AGENT_TOOLS = [
    "*",
]
_AUTO_TEAM_TOOL_NAMES = [
    "Read",
    "Write",
    "Edit",
    "Grep",
    "Glob",
    "Bash",
    "workspace_report_progress",
    "workspace_report_complete",
]
_AUTO_TEAM_MAX_ITERATIONS = 80
_AUTO_TEAM_ROLES = (
    {
        "key": "architect",
        "display_name": "Workspace Architect",
        "label": "Architect",
        "description": "Researches requirements and produces architecture or implementation plans.",
        "capabilities": [
            "architecture",
            "research",
            "planning",
            "web_search",
        ],
    },
    {
        "key": "builder",
        "display_name": "Workspace Builder",
        "label": "Builder",
        "description": "Implements backend, frontend, tests, and project artifacts.",
        "capabilities": [
            "software_development",
            "backend",
            "frontend",
            "codegen",
            "file_edit",
            "shell",
            "testing",
        ],
    },
    {
        "key": "verifier",
        "display_name": "Workspace Verifier",
        "label": "Verifier",
        "description": "Runs verification, browser checks, and evidence synthesis.",
        "capabilities": [
            "verification",
            "browser_e2e",
            "testing",
            "evidence",
            "shell",
        ],
    },
)


def _build_dispatch_execution_state(*, actor_id: str) -> dict[str, str]:
    return {
        "phase": "in_progress",
        "last_agent_reason": "workspace_plan.dispatch.project_attempt",
        "last_agent_action": "start",
        "updated_by_actor_type": "agent",
        "updated_by_actor_id": actor_id,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _persisted_attempt_leader_agent_id(leader_agent_id: str | None) -> str | None:
    """Return the agent-definition-backed leader id persisted on attempts.

    ``workspace-plan:system`` is a durable-plan actor marker, not an
    ``agent_definitions`` row. Keep using it for authority metadata and events,
    but do not put it into ``workspace_task_session_attempts.leader_agent_id``,
    which intentionally has an agent-definition foreign key.
    """
    return persisted_attempt_leader_agent_id(leader_agent_id)


def make_supervisor_tick_handler(
    *,
    config: OrchestratorConfig | None = None,
    agent_pool: AgentPoolProvider | None = None,
    dispatcher: Dispatcher | None = None,
    attempt_context: AttemptContextProvider | None = None,
    progress_sink: ProgressSink | None = None,
) -> WorkspacePlanOutboxHandler:
    """Build an outbox handler that runs one SQL-backed supervisor tick."""

    async def _handle(item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        workspace_id = str(item.payload_json.get("workspace_id") or item.workspace_id)
        payload = dict(item.payload_json or {})
        leader_agent_id = (
            _payload_string(payload, "leader_agent_id") or WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        )

        async def _run_existing_tick() -> TickReport:
            if item.plan_id:
                reconciled_terminal_attempt = await _reconcile_plan_nodes_with_terminal_attempts(
                    session=session,
                    plan_id=item.plan_id,
                    workspace_id=workspace_id,
                )
                reconciled_reported_attempt = await _reconcile_plan_nodes_with_reported_attempts(
                    session=session,
                    plan_id=item.plan_id,
                    workspace_id=workspace_id,
                )
                if reconciled_terminal_attempt or reconciled_reported_attempt:
                    await session.commit()
                reconciled_supervisor_disposed_nodes = (
                    await _reconcile_supervisor_disposed_nodes_before_tick(
                        session=session,
                        plan_id=item.plan_id,
                        workspace_id=workspace_id,
                    )
                )
                if reconciled_supervisor_disposed_nodes:
                    await session.commit()
                recovered_pipeline_requests = (
                    await _recover_orphaned_running_pipeline_requests_after_tick(
                        session=session,
                        plan_id=item.plan_id,
                        workspace_id=workspace_id,
                    )
                )
                if recovered_pipeline_requests:
                    await session.commit()
            resolved_agent_pool = agent_pool
            if resolved_agent_pool is None:
                await _ensure_leader_execution_team(
                    session=session,
                    workspace_id=workspace_id,
                    leader_agent_id=leader_agent_id,
                )
                resolved_agent_pool = _make_sql_agent_pool(
                    session,
                    leader_agent_id=leader_agent_id,
                )
            orchestrator = build_sql_orchestrator(
                session,
                config=config,
                agent_pool=resolved_agent_pool,
                dispatcher=dispatcher or _make_sql_dispatcher(session, item, payload),
                attempt_context=attempt_context or _make_sql_attempt_context(session),
                progress_sink=progress_sink,
                iteration_reviewer=await _make_sql_iteration_reviewer(
                    session=session,
                    workspace_id=workspace_id,
                    root_task_id=_payload_string(payload, "root_task_id"),
                ),
                verification_judge=await _make_sql_verification_judge(
                    session=session,
                    workspace_id=workspace_id,
                    root_task_id=_payload_string(payload, "root_task_id"),
                ),
                supervisor_decision_provider=await _make_sql_supervisor_decision_provider(
                    session=session,
                    workspace_id=workspace_id,
                    root_task_id=_payload_string(payload, "root_task_id"),
                ),
            )
            report = await orchestrator.tick_once(workspace_id)
            if report.errors:
                raise RuntimeError("; ".join(report.errors))
            projected_done_nodes = False
            if item.plan_id:
                projected_done_nodes = await _project_done_idle_accepted_attempts_after_tick(
                    session=session,
                    plan_id=item.plan_id,
                    workspace_id=workspace_id,
                )
                projected_done_nodes = (
                    await _project_done_idle_disposition_nodes_after_tick(
                        session=session,
                        plan_id=item.plan_id,
                        workspace_id=workspace_id,
                    )
                    or projected_done_nodes
                )
            if projected_done_nodes:
                await _enqueue_followup_supervisor_tick_after_terminal_reconcile(
                    session=session,
                    item=item,
                    workspace_id=workspace_id,
                    payload=payload,
                )
            return report

        _ = await WorkspaceRunController(session).tick(
            plan_id=item.plan_id,
            workspace_id=workspace_id,
            reason=_payload_string(payload, "controller_reason") or item.event_type,
            actor_id=leader_agent_id,
            runner=_run_existing_tick,
            current_outbox_id=item.id,
        )

    return _handle


async def _project_done_idle_accepted_attempts_after_tick(
    *,
    session: AsyncSession,
    plan_id: str,
    workspace_id: str,
) -> bool:
    """Project freshly verified terminal attempts without touching new dispatches."""

    repo = SqlPlanRepository(session)
    plan = await repo.get(plan_id)
    if plan is None or plan.workspace_id != workspace_id:
        return False

    now = datetime.now(UTC)
    changed = False
    for node in list(plan.nodes.values()):
        if not _node_is_done_idle_with_attempt(node) or not node.current_attempt_id:
            continue
        attempt = await _load_plan_attempt(session, node.current_attempt_id)
        if attempt is None:
            continue
        status = _attempt_status_value(attempt)
        if status != "accepted":
            if not _done_idle_node_has_accepted_supervisor_judge(node):
                continue
            summary = _accepted_supervisor_judge_summary(node, attempt)
            attempt.status = WorkspaceTaskSessionAttemptStatus.ACCEPTED.value
            attempt.leader_feedback = summary
            attempt.adjudication_reason = "supervisor_decision_accept_node_reconciled"
            attempt.completed_at = now
            attempt.updated_at = now
        if not _accepted_attempt_matches_node_expected_commit(node, attempt):
            continue
        if (
            node.metadata.get("terminal_attempt_status") == "accepted"
            and node.metadata.get("last_verification_attempt_id") == attempt.id
            and await _accepted_attempt_projection_complete_for_node(
                session=session,
                workspace_id=workspace_id,
                node=node,
                attempt=attempt,
            )
        ):
            continue
        summary = str(
            attempt.leader_feedback or attempt.candidate_summary or "accepted terminal attempt"
        )
        integration_metadata = await _project_accepted_terminal_attempt_to_task(
            session=session,
            workspace_id=workspace_id,
            node=node,
            attempt=attempt,
            summary=summary,
            now=now,
        )
        plan.replace_node(
            replace(
                node,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                current_attempt_id=attempt.id,
                feature_checkpoint=_accepted_attempt_projection_feature_checkpoint(
                    node,
                    attempt,
                ),
                metadata={
                    **_accepted_attempt_projection_base_metadata(node, attempt),
                    "terminal_attempt_status": "accepted",
                    "terminal_attempt_reconciled_at": now.isoformat().replace("+00:00", "Z"),
                    "last_verification_summary": summary,
                    "last_verification_passed": True,
                    "last_verification_hard_fail": False,
                    "last_verification_attempt_id": attempt.id,
                    "last_verification_ran_at": now.isoformat().replace("+00:00", "Z"),
                    **_accepted_attempt_evidence_metadata(attempt),
                    **integration_metadata,
                },
                updated_at=now,
            )
        )
        changed = True

    if changed:
        await repo.save(plan)
    return changed


def _done_idle_node_has_accepted_supervisor_judge(node: PlanNode) -> bool:
    metadata = dict(node.metadata or {})
    return str(metadata.get("last_verification_judge_verdict") or "").lower() == "accepted"


def _accepted_supervisor_judge_summary(
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttemptModel,
) -> str:
    metadata = dict(node.metadata or {})
    return str(
        metadata.get("last_verification_summary")
        or attempt.leader_feedback
        or attempt.candidate_summary
        or "accepted terminal attempt"
    )


_PROJECTABLE_DONE_DISPOSITIONS = frozenset(
    {
        "accepted_via_repair_alternative",
        "superseded_by_completed_repair_alternative",
    }
)


async def _reconcile_supervisor_disposed_nodes_before_tick(
    *,
    session: AsyncSession,
    plan_id: str,
    workspace_id: str,
) -> bool:
    """Restore terminal supervisor disposition before the next scheduling pass."""

    repo = SqlPlanRepository(session)
    plan = await repo.get(plan_id)
    if plan is None or plan.workspace_id != workspace_id:
        return False

    result = await session.execute(
        refresh_select_statement(
            select(
                WorkspacePlanEventModel.node_id,
                WorkspacePlanEventModel.attempt_id,
                WorkspacePlanEventModel.payload_json,
            )
            .where(WorkspacePlanEventModel.workspace_id == workspace_id)
            .where(WorkspacePlanEventModel.plan_id == plan_id)
            .where(WorkspacePlanEventModel.event_type == "supervisor_decision_completed")
            .where(WorkspacePlanEventModel.payload_json["action"].as_string() == "dispose_node")
            .order_by(WorkspacePlanEventModel.created_at.desc())
        )
    )
    events_by_node_id: dict[str, tuple[str | None, dict[str, Any]]] = {}
    for node_id, attempt_id, payload in result.all():
        if not node_id or node_id in events_by_node_id:
            continue
        events_by_node_id[str(node_id)] = (
            str(attempt_id) if attempt_id else None,
            dict(payload or {}),
        )
    if not events_by_node_id:
        return False

    now = datetime.now(UTC)
    changed = False
    for node in list(plan.nodes.values()):
        event = events_by_node_id.get(node.id)
        if event is None:
            continue
        if _node_has_projectable_supervisor_disposition(node):
            continue
        attempt_id, event_payload = event
        metadata = dict(node.metadata or {})
        metadata.update(
            {
                "verification_feedback_disposition": "supervisor_agent_disposed_node",
                "last_supervisor_decision_action": "dispose_node",
                "last_supervisor_decision_rationale": _metadata_string(
                    event_payload.get("rationale")
                ),
                "last_supervisor_decision_confidence": event_payload.get("confidence"),
                "last_supervisor_decision_feedback_items": event_payload.get(
                    "feedback_items",
                    [],
                ),
                "last_supervisor_decision_event_payload": event_payload,
                "supervisor_disposition_reconciled_at": now.isoformat().replace(
                    "+00:00",
                    "Z",
                ),
            }
        )
        plan.replace_node(
            replace(
                node,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                current_attempt_id=attempt_id or node.current_attempt_id,
                metadata=metadata,
                updated_at=now,
                completed_at=node.completed_at or now,
            )
        )
        changed = True

    if changed:
        await repo.save(plan)
    return changed


async def _project_done_idle_disposition_nodes_after_tick(
    *,
    session: AsyncSession,
    plan_id: str,
    workspace_id: str,
) -> bool:
    """Project verifier-disposed DONE nodes that do not have their own accepted attempt.

    Repair-alternative acceptance can close the original plan node without
    accepting a new attempt for that original node. The blackboard reads the
    linked workspace task row, so keep that row in sync with the plan verdict.
    """

    repo = SqlPlanRepository(session)
    plan = await repo.get(plan_id)
    if plan is None or plan.workspace_id != workspace_id:
        return False

    now = datetime.now(UTC)
    changed = False
    for node in list(plan.nodes.values()):
        if _node_has_projectable_supervisor_disposition(node):
            if await _project_supervisor_disposition_node_after_tick(
                session=session,
                workspace_id=workspace_id,
                plan=plan,
                node=node,
                now=now,
            ):
                changed = True
            continue
        if not _node_has_projectable_done_disposition(plan, node):
            continue
        task = await session.get(WorkspaceTaskModel, node.workspace_task_id)
        if task is None or task.workspace_id != workspace_id or task.status == "done":
            continue

        metadata = dict(node.metadata or {})
        evidence_refs = _done_disposition_evidence_refs(plan, node)
        summary = (
            _metadata_string(metadata.get("last_verification_summary"))
            or "accepted by durable plan disposition"
        )
        await _project_verification_to_task(
            db=session,
            task=task,
            attempt_id=_done_disposition_attempt_id(plan, node),
            passed=True,
            hard_fail=False,
            summary=summary,
            evidence_refs=evidence_refs,
            commit_ref=_done_disposition_commit_ref(plan, node, evidence_refs),
            git_diff_summary=_first_prefixed_ref(evidence_refs, "git_diff_summary:"),
            test_commands=[
                ref.removeprefix("test_run:")
                for ref in evidence_refs
                if ref.startswith("test_run:")
            ],
            now=now,
        )
        metadata["workspace_task_projection_status"] = "done"
        metadata["workspace_task_projected_at"] = now.isoformat().replace("+00:00", "Z")
        plan.replace_node(replace(node, metadata=metadata, updated_at=now))
        changed = True

    if changed:
        await repo.save(plan)
    return changed


async def _project_supervisor_disposition_node_after_tick(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan: Plan,
    node: PlanNode,
    now: datetime,
) -> bool:
    if not node.workspace_task_id:
        return False
    task = await session.get(WorkspaceTaskModel, node.workspace_task_id)
    if task is None or task.workspace_id != workspace_id:
        return False
    metadata = dict(node.metadata or {})
    if (
        task.status == "done"
        and dict(task.metadata_json or {}).get("durable_plan_verdict") == "disposed"
        and metadata.get("workspace_task_projection_status") == "done"
    ):
        return False
    event_payload = metadata.get("last_supervisor_decision_event_payload")
    payload: dict[str, Any] = {
        "action": "dispose_node",
        "attempt_id": node.current_attempt_id,
        "rationale": _metadata_string(metadata.get("last_supervisor_decision_rationale"))
        or _metadata_string(metadata.get("last_verification_summary"))
        or "disposed by workspace supervisor",
        "event_payload": event_payload if isinstance(event_payload, Mapping) else {},
    }
    _ = await _project_supervisor_disposition_to_workspace_task(
        db=session,
        node=node,
        payload=payload,
    )
    metadata["workspace_task_projection_status"] = "done"
    metadata["workspace_task_projected_at"] = now.isoformat().replace("+00:00", "Z")
    metadata["last_supervisor_decision_action"] = "dispose_node"
    plan.replace_node(replace(node, metadata=metadata, updated_at=now))
    return True


def _node_has_projectable_supervisor_disposition(node: PlanNode) -> bool:
    metadata = dict(node.metadata or {})
    return (
        node.intent is TaskIntent.DONE
        and node.execution is TaskExecution.IDLE
        and bool(node.workspace_task_id)
        and metadata.get("verification_feedback_disposition") == "supervisor_agent_disposed_node"
    )


def _node_has_projectable_done_disposition(plan: Plan, node: PlanNode) -> bool:
    metadata = dict(node.metadata or {})
    if not (
        node.intent is TaskIntent.DONE
        and node.execution is TaskExecution.IDLE
        and bool(node.workspace_task_id)
        and metadata.get("last_verification_passed") is True
        and metadata.get("verification_feedback_disposition") in _PROJECTABLE_DONE_DISPOSITIONS
        and bool(metadata.get("accepted_repair_node_id"))
    ):
        return False
    repair_node = _accepted_repair_node(plan, node)
    repair_metadata = dict(repair_node.metadata or {}) if repair_node is not None else {}
    return (
        repair_node is not None
        and repair_node.intent is TaskIntent.DONE
        and repair_node.execution is TaskExecution.IDLE
        and repair_metadata.get("last_verification_passed") is True
    )


def _done_disposition_evidence_refs(plan: Plan, node: PlanNode) -> list[str]:
    metadata = dict(node.metadata or {})
    refs = _merge_string_values(metadata.get("verification_evidence_refs"), [])
    refs = _merge_string_values(metadata.get("accepted_repair_evidence_refs"), refs)
    refs = _merge_string_values(metadata.get("evidence_refs"), refs)
    refs = _merge_string_values(metadata.get("execution_verifications"), refs)
    refs = _merge_string_values(metadata.get("last_worker_report_verifications"), refs)
    repair_node = _accepted_repair_node(plan, node)
    if repair_node is not None:
        repair_metadata = dict(repair_node.metadata or {})
        refs = _merge_string_values(repair_metadata.get("verification_evidence_refs"), refs)
        refs = _merge_string_values(repair_metadata.get("evidence_refs"), refs)
        refs = _merge_string_values(repair_metadata.get("execution_verifications"), refs)
        refs = _merge_string_values(repair_metadata.get("last_worker_report_verifications"), refs)
    return refs


def _done_disposition_attempt_id(plan: Plan, node: PlanNode) -> str | None:
    if node.current_attempt_id:
        return node.current_attempt_id
    metadata = dict(node.metadata or {})
    attempt_id = _metadata_string(metadata.get("last_verification_attempt_id"))
    if attempt_id:
        return attempt_id
    repair_node = _accepted_repair_node(plan, node)
    if repair_node is not None and repair_node.current_attempt_id:
        return repair_node.current_attempt_id
    if repair_node is None:
        return None
    repair_metadata = dict(repair_node.metadata or {})
    return _metadata_string(repair_metadata.get("last_verification_attempt_id"))


def _done_disposition_commit_ref(
    plan: Plan,
    node: PlanNode,
    evidence_refs: list[str],
) -> str | None:
    metadata = dict(node.metadata or {})
    commit_ref = (
        _first_prefixed_ref(evidence_refs, "commit_ref:")
        or _metadata_string(metadata.get("worktree_integration_commit_ref"))
        or _metadata_string(metadata.get("verified_commit_ref"))
        or _feature_checkpoint_commit_ref(node)
    )
    if commit_ref:
        return commit_ref
    repair_node = _accepted_repair_node(plan, node)
    if repair_node is None:
        return None
    repair_metadata = dict(repair_node.metadata or {})
    return (
        _metadata_string(repair_metadata.get("worktree_integration_commit_ref"))
        or _metadata_string(repair_metadata.get("verified_commit_ref"))
        or _feature_checkpoint_commit_ref(repair_node)
    )


def _accepted_repair_node(plan: Plan, node: PlanNode) -> PlanNode | None:
    repair_node_id = dict(node.metadata or {}).get("accepted_repair_node_id")
    if not isinstance(repair_node_id, str) or not repair_node_id.strip():
        return None
    return plan.nodes.get(PlanNodeId(repair_node_id.strip()))


async def _enqueue_followup_supervisor_tick_after_terminal_reconcile(
    *,
    session: AsyncSession,
    item: WorkspacePlanOutboxModel,
    workspace_id: str,
    payload: Mapping[str, Any],
) -> None:
    if not item.plan_id:
        return
    existing = await session.execute(
        select(WorkspacePlanOutboxModel.id)
        .where(WorkspacePlanOutboxModel.workspace_id == workspace_id)
        .where(WorkspacePlanOutboxModel.plan_id == item.plan_id)
        .where(WorkspacePlanOutboxModel.event_type == SUPERVISOR_TICK_EVENT)
        .where(WorkspacePlanOutboxModel.status.in_(["pending", "processing", "failed"]))
        .where(WorkspacePlanOutboxModel.id != item.id)
        .limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return

    followup_payload: dict[str, Any] = {"workspace_id": workspace_id}
    for key in ("leader_agent_id", "root_task_id"):
        value = _payload_string(payload, key)
        if value:
            followup_payload[key] = value
    if _payload_string(payload, "controller_reason"):
        followup_payload["controller_reason"] = "post_terminal_attempt_reconcile"

    _ = await SqlWorkspacePlanOutboxRepository(session).enqueue(
        plan_id=item.plan_id,
        workspace_id=workspace_id,
        event_type=SUPERVISOR_TICK_EVENT,
        payload=followup_payload,
        metadata={
            "source": "supervisor_tick",
            "reason": "post_terminal_attempt_reconcile",
            "previous_outbox_id": item.id,
        },
    )


async def _recover_orphaned_running_pipeline_requests_after_tick(
    *,
    session: AsyncSession,
    plan_id: str,
    workspace_id: str,
) -> bool:
    plan = await SqlPlanRepository(session).get(plan_id)
    if plan is None or plan.workspace_id != workspace_id:
        return False

    pipeline_repo = SqlWorkspacePipelineRepository(session)
    outbox_repo = SqlWorkspacePlanOutboxRepository(session)
    event_repo = SqlWorkspacePlanEventRepository(session)
    changed = False
    for node in plan.nodes.values():
        if not _node_has_running_pipeline_gate(node) or not node.current_attempt_id:
            continue
        node_id = str(node.id)
        attempt_id = str(node.current_attempt_id)
        latest = await pipeline_repo.latest_run_for_node(
            plan_id=plan_id,
            node_id=node_id,
            attempt_id=attempt_id,
        )
        if latest is None or latest.status != "running":
            continue
        if await _has_active_pipeline_request_outbox(
            session=session,
            workspace_id=workspace_id,
            plan_id=plan_id,
            node_id=node_id,
            attempt_id=attempt_id,
        ):
            continue
        _ = await outbox_repo.enqueue(
            plan_id=plan_id,
            workspace_id=workspace_id,
            event_type=PIPELINE_RUN_REQUESTED_EVENT,
            payload={
                "workspace_id": workspace_id,
                "plan_id": plan_id,
                "node_id": node_id,
                "attempt_id": attempt_id,
                "pipeline_run_id": latest.id,
                "reason": "recover_orphaned_running_pipeline",
            },
            metadata={
                "source": "workspace_plan.supervisor_tick.pipeline_running_recovery",
                "pipeline_run_id": latest.id,
            },
        )
        _ = await event_repo.append(
            plan_id=plan_id,
            workspace_id=workspace_id,
            node_id=node_id,
            attempt_id=attempt_id,
            event_type="pipeline_run_poll_recovery_queued",
            source="workspace_plan_supervisor_tick",
            actor_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
            payload={
                "reason": "running pipeline had no active outbox poller",
                "pipeline_run_id": latest.id,
            },
        )
        changed = True
    return changed


def _node_has_running_pipeline_gate(node: PlanNode) -> bool:
    metadata = dict(node.metadata or {})
    statuses = {
        (_metadata_string(metadata.get("pipeline_status")) or "").lower(),
        (_metadata_string(metadata.get("pipeline_gate_status")) or "").lower(),
    }
    return "running" in statuses


async def _has_active_pipeline_request_outbox(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan_id: str,
    node_id: str,
    attempt_id: str,
) -> bool:
    result = await session.execute(
        select(WorkspacePlanOutboxModel)
        .where(WorkspacePlanOutboxModel.workspace_id == workspace_id)
        .where(WorkspacePlanOutboxModel.plan_id == plan_id)
        .where(WorkspacePlanOutboxModel.event_type == PIPELINE_RUN_REQUESTED_EVENT)
        .where(WorkspacePlanOutboxModel.status.in_(("pending", "processing", "failed")))
        .order_by(WorkspacePlanOutboxModel.created_at.desc())
        .limit(50)
    )
    for item in result.scalars().all():
        payload = dict(item.payload_json or {})
        if (
            _payload_string(payload, "node_id") == node_id
            and _payload_string(payload, "attempt_id") == attempt_id
        ):
            return True
    return False


async def _run_controller_action(
    *,
    session: AsyncSession,
    item: WorkspacePlanOutboxModel,
    workspace_id: str,
    actor_id: str | None,
    reason: str,
    action: Callable[[], Awaitable[None]],
) -> None:
    async def _runner() -> TickReport:
        await action()
        return TickReport(workspace_id=workspace_id)

    _ = await WorkspaceRunController(session).tick(
        plan_id=item.plan_id,
        workspace_id=workspace_id,
        reason=reason,
        actor_id=actor_id,
        runner=_runner,
        current_outbox_id=item.id,
    )


async def _make_sql_iteration_reviewer(
    *,
    session: AsyncSession,
    workspace_id: str,
    root_task_id: str | None,
) -> IterationReviewPort | None:
    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        return None
    root_metadata: Mapping[str, Any] | None = None
    if root_task_id:
        root_task = await SqlWorkspaceTaskRepository(session).find_by_id(root_task_id)
        if root_task is not None and root_task.workspace_id == workspace_id:
            root_metadata = root_task.metadata
    if resolve_workspace_type(root_metadata, workspace.metadata) != "software_development":
        return None
    try:
        return WorkspaceIterationReviewAgentProvider(
            tenant_id=workspace.tenant_id,
            project_id=workspace.project_id,
            linked_workspace_task_id=root_task_id,
            max_next_tasks=_software_iteration_task_budget(),
        )
    except Exception:
        logger.warning(
            "workspace_plan.iteration_reviewer_unavailable",
            exc_info=True,
            extra={"workspace_id": workspace_id},
        )
        return UnavailableIterationReviewProvider("iteration review agent is unavailable")


async def _make_sql_verification_judge(
    *,
    session: AsyncSession,
    workspace_id: str,
    root_task_id: str | None,
) -> WorkspaceVerificationJudgePort | None:
    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        return None
    root_metadata: Mapping[str, Any] | None = None
    if root_task_id:
        root_task = await SqlWorkspaceTaskRepository(session).find_by_id(root_task_id)
        if root_task is not None and root_task.workspace_id == workspace_id:
            root_metadata = root_task.metadata
    if resolve_workspace_type(root_metadata, workspace.metadata) != "software_development":
        return None
    try:
        return WorkspaceVerifierAgentJudge(
            tenant_id=workspace.tenant_id,
            project_id=workspace.project_id,
            linked_workspace_task_id=root_task_id,
        )
    except Exception:
        logger.warning(
            "workspace_plan.verification_judge_unavailable",
            exc_info=True,
            extra={"workspace_id": workspace_id},
        )
        return UnavailableWorkspaceVerificationJudge("workspace verification judge is unavailable")


async def _make_sql_supervisor_decision_provider(
    *,
    session: AsyncSession,
    workspace_id: str,
    root_task_id: str | None,
) -> WorkspaceSupervisorDecisionPort | None:
    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        return None
    root_metadata: Mapping[str, Any] | None = None
    if root_task_id:
        root_task = await SqlWorkspaceTaskRepository(session).find_by_id(root_task_id)
        if root_task is not None and root_task.workspace_id == workspace_id:
            root_metadata = root_task.metadata
    if resolve_workspace_type(root_metadata, workspace.metadata) != "software_development":
        return None
    try:
        return WorkspaceSupervisorAgentDecisionProvider(
            tenant_id=workspace.tenant_id,
            project_id=workspace.project_id,
            linked_workspace_task_id=root_task_id,
        )
    except Exception:
        logger.warning(
            "workspace_plan.supervisor_decision_provider_unavailable",
            exc_info=True,
            extra={"workspace_id": workspace_id},
        )
        return UnavailableWorkspaceSupervisorDecisionProvider(
            "workspace supervisor decision agent is unavailable"
        )


def _software_iteration_task_budget() -> int:
    raw_value = os.getenv("WORKSPACE_V2_SOFTWARE_MAX_SUBTASKS")
    if raw_value is None:
        return _DEFAULT_SOFTWARE_WORKSPACE_MAX_SUBTASKS
    try:
        value = int(raw_value)
    except ValueError:
        return _DEFAULT_SOFTWARE_WORKSPACE_MAX_SUBTASKS
    return max(1, min(value, _MAX_WORKSPACE_DECOMPOSER_MAX_SUBTASKS))


def _node_recoverable_attempt_id(node: PlanNode) -> str | None:
    if not node.current_attempt_id:
        metadata = dict(node.metadata or {})
        verified_attempt_id = metadata.get("last_verification_attempt_id")
        if (
            isinstance(verified_attempt_id, str)
            and verified_attempt_id
            and metadata.get("last_verification_passed") is True
            and node.execution is TaskExecution.IDLE
            and node.intent in {TaskIntent.BLOCKED, TaskIntent.DONE}
        ):
            return verified_attempt_id
        return None
    if node.execution in {
        TaskExecution.DISPATCHED,
        TaskExecution.RUNNING,
        TaskExecution.REPORTED,
        TaskExecution.VERIFYING,
    }:
        return node.current_attempt_id
    if node.execution is TaskExecution.IDLE and node.intent in {
        TaskIntent.IN_PROGRESS,
        TaskIntent.BLOCKED,
        TaskIntent.DONE,
    }:
        return node.current_attempt_id
    return None


def _node_is_done_idle_with_attempt(node: PlanNode) -> bool:
    return (
        node.intent is TaskIntent.DONE
        and node.execution is TaskExecution.IDLE
        and bool(node.current_attempt_id)
    )


def _terminal_retry_metadata_cleared(metadata: Mapping[str, object]) -> dict[str, object]:
    cleaned = dict(metadata or {})
    cleaned.pop("terminal_attempt_retry_count", None)
    cleaned.pop("terminal_attempt_retry_reason", None)
    cleaned.pop("retry_not_before", None)
    return cleaned


_NO_COMMIT_ACCEPTED_ATTEMPT_STALE_METADATA_KEYS = frozenset(
    {
        "candidate_artifacts",
        "candidate_verifications",
        "execution_verifications",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "pipeline_evidence_refs",
        "pipeline_gate_status",
        "pipeline_last_summary",
        "pipeline_run_id",
        "pipeline_status",
        "source_publish_branch",
        "source_publish_commit_ref",
        "source_publish_provider",
        "source_publish_reason",
        "source_publish_source_commit_ref",
        "source_publish_status",
        "verification_evidence_refs",
        "verified_commit_ref",
        "verified_git_diff_summary",
        "verified_test_commands",
        "worktree_integration_attempt_id",
        "worktree_integration_commit_ref",
        "worktree_integration_dirty_signature",
        "worktree_integration_ran_at",
        "worktree_integration_status",
        "worktree_integration_summary",
        "worktree_integration_worktree_path",
    }
)


def _accepted_attempt_projection_base_metadata(
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> dict[str, object]:
    metadata = _terminal_retry_metadata_cleared(node.metadata)
    if _attempt_commit_refs(attempt):
        return metadata
    for key in _NO_COMMIT_ACCEPTED_ATTEMPT_STALE_METADATA_KEYS:
        metadata.pop(key, None)
    return metadata


def _accepted_attempt_projection_feature_checkpoint(
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> FeatureCheckpoint | None:
    if _attempt_commit_refs(attempt) or node.feature_checkpoint is None:
        return node.feature_checkpoint
    return replace(
        node.feature_checkpoint,
        worktree_path=None,
        branch_name=None,
        base_ref="HEAD",
        commit_ref=None,
    )


async def _reconcile_plan_nodes_with_terminal_attempts(
    *,
    session: AsyncSession,
    plan_id: str,
    workspace_id: str,
) -> bool:
    """Release V2 plan nodes that still point at terminal or missing attempts."""

    repo = SqlPlanRepository(session)
    plan = await repo.get(plan_id)
    if plan is None or plan.workspace_id != workspace_id:
        return False

    now = datetime.now(UTC)
    changed = False
    for node in list(plan.nodes.values()):
        attempt_id = _node_recoverable_attempt_id(node)
        if attempt_id is None:
            continue
        recoverable_done_idle = _node_is_done_idle_with_attempt(node)
        attempt = await _load_plan_attempt(session, attempt_id)
        if attempt is None:
            plan.replace_node(
                _plan_node_released_for_retry(
                    node,
                    reason="missing_attempt",
                    now=now,
                )
            )
            changed = True
            continue
        status = _attempt_status_value(attempt)
        if _reported_node_has_pipeline_result_pending_verification(node, status):
            continue
        if status == "accepted":
            stale_parent_done_output = (
                await _accepted_projection_was_superseded_by_parent_done_output_attempt(
                    session=session,
                    node=node,
                )
            )
            if stale_parent_done_output or not _accepted_attempt_matches_node_expected_commit(
                node,
                attempt,
            ):
                reason = (
                    "superseded_parent_done_attempt_has_output"
                    if stale_parent_done_output
                    else "accepted_attempt_commit_mismatch"
                )
                plan.replace_node(
                    _plan_node_released_for_retry(
                        node,
                        reason=reason,
                        now=now,
                    )
                )
                changed = True
                continue
            if (
                recoverable_done_idle
                and node.metadata.get("terminal_attempt_status") == "accepted"
                and node.metadata.get("last_verification_attempt_id") == attempt.id
                and await _accepted_attempt_projection_complete_for_node(
                    session=session,
                    workspace_id=workspace_id,
                    node=node,
                    attempt=attempt,
                )
            ):
                continue
            summary = str(
                attempt.leader_feedback or attempt.candidate_summary or "accepted terminal attempt"
            )
            integration_metadata = await _project_accepted_terminal_attempt_to_task(
                session=session,
                node=node,
                workspace_id=workspace_id,
                attempt=attempt,
                summary=summary,
                now=now,
            )
            plan.replace_node(
                replace(
                    node,
                    intent=TaskIntent.DONE,
                    execution=TaskExecution.IDLE,
                    current_attempt_id=attempt.id,
                    feature_checkpoint=_accepted_attempt_projection_feature_checkpoint(
                        node,
                        attempt,
                    ),
                    metadata={
                        **_accepted_attempt_projection_base_metadata(node, attempt),
                        "terminal_attempt_status": status,
                        "terminal_attempt_reconciled_at": now.isoformat().replace("+00:00", "Z"),
                        "last_verification_summary": summary,
                        "last_verification_passed": True,
                        "last_verification_hard_fail": False,
                        "last_verification_attempt_id": attempt.id,
                        "last_verification_ran_at": now.isoformat().replace("+00:00", "Z"),
                        **_accepted_attempt_evidence_metadata(attempt),
                        **integration_metadata,
                    },
                    updated_at=now,
                )
            )
            changed = True
            continue
        if status in _TERMINAL_ATTEMPT_STATUS_VALUES:
            accepted_attempt = await _load_reconciling_accepted_attempt_for_task(
                session=session,
                workspace_id=workspace_id,
                node=node,
                terminal_attempt=attempt,
            )
            if accepted_attempt is not None:
                summary = str(
                    accepted_attempt.leader_feedback
                    or accepted_attempt.candidate_summary
                    or "accepted terminal attempt"
                )
                integration_metadata = await _project_accepted_terminal_attempt_to_task(
                    session=session,
                    workspace_id=workspace_id,
                    node=node,
                    attempt=accepted_attempt,
                    summary=summary,
                    now=now,
                )
                plan.replace_node(
                    replace(
                        node,
                        intent=TaskIntent.DONE,
                        execution=TaskExecution.IDLE,
                        current_attempt_id=accepted_attempt.id,
                        feature_checkpoint=_accepted_attempt_projection_feature_checkpoint(
                            node,
                            accepted_attempt,
                        ),
                        metadata={
                            **_accepted_attempt_projection_base_metadata(
                                node,
                                accepted_attempt,
                            ),
                            "terminal_attempt_status": "accepted",
                            "terminal_attempt_reconciled_at": now.isoformat().replace(
                                "+00:00",
                                "Z",
                            ),
                            "terminal_attempt_superseded_attempt_id": attempt.id,
                            "terminal_attempt_superseded_status": status,
                            "terminal_attempt_superseded_reason": (
                                attempt.adjudication_reason or attempt.leader_feedback
                            ),
                            "last_verification_summary": summary,
                            "last_verification_passed": True,
                            "last_verification_hard_fail": False,
                            "last_verification_attempt_id": accepted_attempt.id,
                            "last_verification_ran_at": now.isoformat().replace(
                                "+00:00",
                                "Z",
                            ),
                            **_accepted_attempt_evidence_metadata(accepted_attempt),
                            **integration_metadata,
                        },
                        updated_at=now,
                    )
                )
                changed = True
                continue
            plan.replace_node(
                _plan_node_released_for_retry(
                    node,
                    reason=f"terminal_attempt_{status}",
                    now=now,
                )
            )
            changed = True

    if changed:
        await repo.save(plan)
    return changed


def _node_waiting_for_verification_retry(node: PlanNode) -> bool:
    return (
        node.execution is TaskExecution.REPORTED
        and dict(node.metadata or {}).get("retry_verification_only") is True
    )


def _reported_node_has_pipeline_result_pending_verification(node: PlanNode, status: str) -> bool:
    if _node_waiting_for_verification_retry(node):
        return True
    if _node_has_pipeline_gate_in_flight(node, status):
        return True
    if node.execution is not TaskExecution.REPORTED:
        return False
    if status == WorkspaceTaskSessionAttemptStatus.ACCEPTED.value:
        return False
    metadata = node.metadata or {}
    pipeline_status = (_metadata_string(metadata.get("pipeline_status")) or "").lower()
    if pipeline_status not in {"failed", "failure", "error", "success"}:
        return False
    return bool(
        _metadata_string(metadata.get("pipeline_run_id"))
        or _metadata_string(metadata.get("external_id"))
    )


def _node_has_pipeline_gate_in_flight(node: PlanNode, status: str) -> bool:
    if status == WorkspaceTaskSessionAttemptStatus.ACCEPTED.value:
        return False
    if node.intent is not TaskIntent.IN_PROGRESS:
        return False
    metadata = node.metadata or {}
    pipeline_status = (_metadata_string(metadata.get("pipeline_status")) or "").lower()
    gate_status = (_metadata_string(metadata.get("pipeline_gate_status")) or "").lower()
    return pipeline_status in {"requested", "running", "processing"} or gate_status in {
        "requested",
        "running",
        "processing",
    }


async def _reconcile_plan_nodes_with_reported_attempts(
    *,
    session: AsyncSession,
    plan_id: str,
    workspace_id: str,
) -> bool:
    """Move active plan nodes whose current attempts already produced reports."""

    repo = SqlPlanRepository(session)
    plan = await repo.get(plan_id)
    if plan is None or plan.workspace_id != workspace_id:
        return False

    now = datetime.now(UTC)
    changed_nodes: list[PlanNode] = []
    for node in list(plan.nodes.values()):
        recoverable_execution = node.execution in {
            TaskExecution.DISPATCHED,
            TaskExecution.RUNNING,
        }
        recoverable_in_progress_idle = (
            node.intent is TaskIntent.IN_PROGRESS
            and node.execution is TaskExecution.IDLE
            and bool(node.current_attempt_id)
        )
        if not (recoverable_execution or recoverable_in_progress_idle):
            continue
        if not node.current_attempt_id:
            continue
        attempt = await _load_plan_attempt(session, node.current_attempt_id)
        if attempt is None:
            continue
        if (
            _attempt_status_value(attempt)
            != WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value
        ):
            continue
        if not _attempt_has_candidate_output(attempt):
            continue
        metadata = {
            **dict(node.metadata or {}),
            "reported_attempt_reconciled_at": now.isoformat().replace("+00:00", "Z"),
            "reported_attempt_status": (
                WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value
            ),
        }
        repaired = replace(
            node,
            execution=TaskExecution.REPORTED,
            metadata=metadata,
            updated_at=now,
        )
        plan.replace_node(repaired)
        changed_nodes.append(repaired)

    if not changed_nodes:
        return False

    await repo.save(plan)
    _ = await SqlWorkspacePlanEventRepository(session).append(
        plan_id=plan.id,
        workspace_id=workspace_id,
        node_id=changed_nodes[0].id,
        attempt_id=changed_nodes[0].current_attempt_id,
        event_type="auto_reported_attempt_reconciled",
        source="workspace_plan_supervisor_tick",
        actor_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        payload={
            "reason": "active_plan_node_points_to_reported_attempt",
            "node_ids": [node.id for node in changed_nodes],
        },
    )
    logger.warning(
        "workspace_plan.supervisor_tick_reported_attempt_reconciled",
        extra={
            "event": "workspace_plan.supervisor_tick_reported_attempt_reconciled",
            "workspace_id": workspace_id,
            "plan_id": plan.id,
            "node_count": len(changed_nodes),
        },
    )
    return True


async def _project_accepted_terminal_attempt_to_task(
    *,
    session: AsyncSession,
    workspace_id: str,
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttemptModel,
    summary: str,
    now: datetime,
) -> dict[str, object]:
    task_id = node.workspace_task_id or attempt.workspace_task_id
    if not task_id:
        return {}
    task = await session.get(WorkspaceTaskModel, task_id)
    if task is None or task.workspace_id != workspace_id:
        return {}
    evidence_refs = _accepted_attempt_evidence_refs(attempt)
    commit_ref = _first_prefixed_ref(evidence_refs, "commit_ref:")
    if not commit_ref and not _accepted_attempt_has_same_verified_no_output_projection(
        node, attempt
    ):
        commit_ref = _feature_checkpoint_commit_ref(node)
    git_diff_summary = _first_prefixed_ref(evidence_refs, "git_diff_summary:")
    test_commands = [
        ref.removeprefix("test_run:") for ref in evidence_refs if ref.startswith("test_run:")
    ]
    await _project_verification_to_task(
        db=session,
        task=task,
        attempt_id=attempt.id,
        passed=True,
        hard_fail=False,
        summary=summary,
        evidence_refs=evidence_refs,
        commit_ref=commit_ref,
        git_diff_summary=git_diff_summary,
        test_commands=test_commands,
        now=now,
    )
    return await _integrate_accepted_attempt_worktree(
        session=session,
        workspace_id=workspace_id,
        node=node,
        task=task,
        attempt=attempt,
        commit_ref=commit_ref,
        now=now,
    )


def _accepted_attempt_evidence_refs(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> list[str]:
    refs: list[str] = []
    refs.extend(
        f"artifact:{artifact}" if not artifact.startswith("artifact:") else artifact
        for artifact in _attempt_list_field(
            attempt,
            domain_field="candidate_artifacts",
            model_field="candidate_artifacts_json",
        )
    )
    refs.extend(
        _attempt_list_field(
            attempt,
            domain_field="candidate_verifications",
            model_field="candidate_verifications_json",
        )
    )
    return list(dict.fromkeys(ref for ref in refs if ref))


def _first_prefixed_ref(refs: Iterable[str], prefix: str) -> str | None:
    for ref in refs:
        if ref.startswith(prefix):
            return ref.removeprefix(prefix)
        artifact_prefix = f"artifact:{prefix}"
        if ref.startswith(artifact_prefix):
            return ref.removeprefix(artifact_prefix)
    return None


def _accepted_attempt_evidence_metadata(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    candidate_artifacts = _attempt_list_field(
        attempt,
        domain_field="candidate_artifacts",
        model_field="candidate_artifacts_json",
    )
    candidate_verifications = _attempt_list_field(
        attempt,
        domain_field="candidate_verifications",
        model_field="candidate_verifications_json",
    )
    if candidate_artifacts:
        metadata["candidate_artifacts"] = candidate_artifacts
    if candidate_verifications:
        metadata["candidate_verifications"] = candidate_verifications
    return metadata


_WORKTREE_INTEGRATION_DONE_STATUSES = frozenset(
    {"merged", "already_merged", "skipped", "blocked_dirty_main", "failed"}
)


def _accepted_attempt_projection_complete(metadata: Mapping[str, object]) -> bool:
    commit_ref = _integration_commit_ref_from_metadata(metadata)
    if not commit_ref:
        return True
    status = str(metadata.get("worktree_integration_status") or "")
    return status in _WORKTREE_INTEGRATION_DONE_STATUSES


async def _accepted_attempt_projection_complete_for_node(
    *,
    session: AsyncSession,
    workspace_id: str,
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttemptModel,
) -> bool:
    metadata = dict(node.metadata or {})
    if not _accepted_attempt_projection_complete(metadata):
        return False
    checkpoint_commit_ref = _feature_checkpoint_commit_ref(node)
    if checkpoint_commit_ref:
        status = str(metadata.get("worktree_integration_status") or "")
        if status not in _WORKTREE_INTEGRATION_DONE_STATUSES:
            return False
    attempt_commit_ref = _first_prefixed_ref(
        _accepted_attempt_evidence_refs(attempt),
        "commit_ref:",
    )
    if attempt_commit_ref:
        status = str(metadata.get("worktree_integration_status") or "")
        if status not in _WORKTREE_INTEGRATION_DONE_STATUSES:
            return False
    if metadata.get("worktree_integration_status") != "blocked_dirty_main":
        return True
    return await _blocked_dirty_main_projection_still_current(
        session=session,
        workspace_id=workspace_id,
        node=node,
        attempt=attempt,
        metadata=metadata,
    )


async def _blocked_dirty_main_projection_still_current(
    *,
    session: AsyncSession,
    workspace_id: str,
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttemptModel,
    metadata: Mapping[str, object],
) -> bool:
    stored_signature = _metadata_string(metadata.get("worktree_integration_dirty_signature"))
    task_id = node.workspace_task_id or attempt.workspace_task_id
    task = await session.get(WorkspaceTaskModel, task_id) if task_id else None
    if task is None or task.workspace_id != workspace_id:
        return False
    if stored_signature is None:
        stored_signature = _metadata_string(
            dict(task.metadata_json or {}).get("worktree_integration_dirty_signature")
        )
    if stored_signature is None:
        return False
    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        return False
    code_context = await _load_workspace_code_context_for_task(
        session=session,
        workspace_id=workspace_id,
        task=task,
        workspace=workspace,
    )
    sandbox_code_root = getattr(code_context, "sandbox_code_root", None)
    if not sandbox_code_root:
        return False

    command = _worktree_dirty_signature_command(sandbox_code_root=str(sandbox_code_root))
    signature_status = await _run_worktree_dirty_signature_command(
        project_id=workspace.project_id,
        tenant_id=workspace.tenant_id,
        command=command,
    )
    if signature_status is None:
        return False
    status, current_signature, dirty_generated_only = signature_status
    return bool(
        not dirty_generated_only and status == "dirty" and current_signature == stored_signature
    )


async def _run_worktree_dirty_signature_command(
    *,
    project_id: str,
    tenant_id: str,
    command: str,
) -> tuple[str, str, bool] | None:
    try:
        result = await _WorkspaceSandboxCommandRunner(
            project_id=project_id,
            tenant_id=tenant_id,
        ).run_command(command, timeout=30)
    except Exception:
        return None

    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    status = _integration_output_field("status", stdout, stderr)
    dirty_signature = _integration_output_field("dirty_signature", stdout, stderr)
    dirty_generated_only = (
        _integration_output_field("dirty_generated_only", stdout, stderr).lower() == "true"
    )
    return status, dirty_signature, dirty_generated_only


def _integration_commit_ref_from_metadata(metadata: Mapping[str, object]) -> str | None:
    raw = metadata.get("verified_commit_ref")
    commit_ref = _commit_ref_token(raw)
    if commit_ref:
        return commit_ref
    feature = metadata.get("feature_checkpoint")
    if isinstance(feature, Mapping):
        return _commit_ref_token(feature.get("commit_ref"))
    return None


def _feature_checkpoint_commit_ref(node: PlanNode) -> str | None:
    feature = node.feature_checkpoint
    if feature is None:
        return None
    return _commit_ref_token(feature.commit_ref)


async def _integrate_accepted_attempt_worktree(  # noqa: PLR0911
    *,
    session: AsyncSession,
    workspace_id: str,
    node: PlanNode,
    task: WorkspaceTaskModel,
    attempt: WorkspaceTaskSessionAttemptModel,
    commit_ref: str | None,
    now: datetime,
) -> dict[str, object]:
    commit_token = _commit_ref_token(commit_ref)
    if not commit_token:
        return {}

    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        return _worktree_integration_metadata(
            status="skipped",
            summary="workspace not found",
            attempt_id=attempt.id,
            commit_ref=commit_token,
            worktree_path=None,
            now=now,
        )

    code_context = await _load_workspace_code_context_for_task(
        session=session,
        workspace_id=workspace_id,
        task=task,
        workspace=workspace,
    )
    sandbox_code_root = getattr(code_context, "sandbox_code_root", None)
    if not sandbox_code_root:
        return _worktree_integration_metadata(
            status="skipped",
            summary="sandbox_code_root is not available for accepted worktree integration",
            attempt_id=attempt.id,
            commit_ref=commit_token,
            worktree_path=None,
            now=now,
        )

    worktree_path = _accepted_attempt_worktree_path(
        node=node,
        task=task,
        sandbox_code_root=str(sandbox_code_root),
        attempt_id=attempt.id,
    )
    if not worktree_path:
        return _worktree_integration_metadata(
            status="skipped",
            summary="accepted attempt has no worktree_path",
            attempt_id=attempt.id,
            commit_ref=commit_token,
            worktree_path=None,
            now=now,
        )
    if _normalize_posix_path(worktree_path) == _normalize_posix_path(str(sandbox_code_root)):
        return await _record_worktree_integration_result(
            session=session,
            workspace_id=workspace_id,
            node=node,
            task=task,
            attempt=attempt,
            status="already_merged",
            summary="accepted attempt already ran in sandbox_code_root",
            commit_ref=commit_token,
            worktree_path=worktree_path,
            now=now,
        )

    command = _worktree_integration_command(
        sandbox_code_root=str(sandbox_code_root),
        worktree_path=worktree_path,
        commit_ref=commit_token,
    )
    try:
        result = await _WorkspaceSandboxCommandRunner(
            project_id=workspace.project_id,
            tenant_id=workspace.tenant_id,
        ).run_command(command, timeout=120)
    except Exception as exc:
        return await _record_worktree_integration_result(
            session=session,
            workspace_id=workspace_id,
            node=node,
            task=task,
            attempt=attempt,
            status="failed",
            summary=f"accepted worktree integration raised: {exc}",
            commit_ref=commit_token,
            worktree_path=worktree_path,
            now=now,
        )

    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    output = _compact_command_output(stdout or stderr)
    command_status = _integration_status_from_output(stdout, stderr)
    dirty_signature = _integration_output_field("dirty_signature", stdout, stderr) or None
    exit_code = int(result.get("exit_code") or 0)
    if exit_code == 0 and command_status in {"merged", "already_merged"}:
        status = command_status
    elif command_status == "blocked_dirty_main":
        status = "blocked_dirty_main"
    else:
        status = "failed"
    summary = output or f"accepted worktree integration {status}"
    return await _record_worktree_integration_result(
        session=session,
        workspace_id=workspace_id,
        node=node,
        task=task,
        attempt=attempt,
        status=status,
        summary=summary,
        commit_ref=commit_token,
        worktree_path=worktree_path,
        dirty_signature=dirty_signature,
        now=now,
    )


async def _load_workspace_code_context_for_task(
    *,
    session: AsyncSession,
    workspace_id: str,
    task: WorkspaceTaskModel,
    workspace: Workspace,
) -> object:
    root_metadata: Mapping[str, Any] = {}
    task_metadata = dict(task.metadata_json or {})
    root_task_id = _mapping_string(task_metadata, ROOT_GOAL_TASK_ID)
    if root_task_id:
        root_task = await SqlWorkspaceTaskRepository(session).find_by_id(root_task_id)
        if root_task is not None and root_task.workspace_id == workspace_id:
            root_metadata = dict(root_task.metadata or {})

    from src.infrastructure.agent.workspace.code_context import (
        load_workspace_code_context,
    )

    workspace_metadata = dict(getattr(workspace, "metadata", {}) or {})
    return load_workspace_code_context(
        project_id=str(workspace.project_id),
        root_metadata=root_metadata,
        workspace_metadata=workspace_metadata,
    )


def _accepted_attempt_worktree_path(
    *,
    node: PlanNode,
    task: WorkspaceTaskModel,
    sandbox_code_root: str,
    attempt_id: str,
) -> str | None:
    feature = node.feature_checkpoint
    raw_path = feature.worktree_path if feature is not None else None
    if not raw_path:
        task_metadata = dict(task.metadata_json or {})
        raw_feature = task_metadata.get("feature_checkpoint")
        if isinstance(raw_feature, Mapping):
            raw_path = _mapping_string(raw_feature, "worktree_path")
    if not raw_path:
        raw_path = _default_attempt_worktree_path(
            sandbox_code_root=sandbox_code_root,
            attempt_id=attempt_id,
        )
    path = raw_path.replace("${sandbox_code_root}", sandbox_code_root)
    if "${sandbox_code_root}" in path:
        return None
    return posixpath.normpath(path)


async def _record_worktree_integration_result(
    *,
    session: AsyncSession,
    workspace_id: str,
    node: PlanNode,
    task: WorkspaceTaskModel,
    attempt: WorkspaceTaskSessionAttemptModel,
    status: str,
    summary: str,
    commit_ref: str | None,
    worktree_path: str | None,
    now: datetime,
    dirty_signature: str | None = None,
) -> dict[str, object]:
    metadata = dict(task.metadata_json or {})
    event_type = {
        "merged": "accepted_worktree_integrated",
        "already_merged": "accepted_worktree_integration_skipped",
        "skipped": "accepted_worktree_integration_skipped",
        "blocked_dirty_main": "accepted_worktree_integration_blocked",
        "failed": "accepted_worktree_integration_failed",
    }.get(status, "accepted_worktree_integration_failed")
    integration_metadata = _worktree_integration_metadata(
        status=status,
        summary=summary,
        attempt_id=attempt.id,
        commit_ref=commit_ref,
        worktree_path=worktree_path,
        dirty_signature=dirty_signature,
        now=now,
    )
    metadata.update(integration_metadata)
    task.metadata_json = metadata
    task.updated_at = now
    await SqlWorkspacePlanEventRepository(session).append(
        plan_id=node.plan_id,
        workspace_id=workspace_id,
        node_id=node.id,
        attempt_id=attempt.id,
        event_type=event_type,
        source="workspace_plan.accepted_worktree_integration",
        actor_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        payload={
            "status": status,
            "summary": summary,
            "commit_ref": commit_ref,
            "worktree_path": worktree_path,
            "workspace_task_id": task.id,
            "dirty_signature": dirty_signature,
        },
    )
    return integration_metadata


def _worktree_integration_metadata(
    *,
    status: str,
    summary: str,
    attempt_id: str,
    commit_ref: str | None,
    worktree_path: str | None,
    now: datetime,
    dirty_signature: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "worktree_integration_status": status,
        "worktree_integration_summary": summary,
        "worktree_integration_attempt_id": attempt_id,
        "worktree_integration_ran_at": now.isoformat().replace("+00:00", "Z"),
    }
    if commit_ref:
        metadata["worktree_integration_commit_ref"] = commit_ref
    if worktree_path:
        metadata["worktree_integration_worktree_path"] = worktree_path
    metadata["worktree_integration_dirty_signature"] = dirty_signature
    return metadata


def _worktree_integration_command(
    *,
    sandbox_code_root: str,
    worktree_path: str,
    commit_ref: str,
) -> str:
    return _manager_worktree_integration_command(
        sandbox_code_root=sandbox_code_root,
        worktree_path=worktree_path,
        commit_ref=commit_ref,
    )


def _worktree_dirty_signature_command(*, sandbox_code_root: str) -> str:
    return _manager_worktree_dirty_signature_command(sandbox_code_root=sandbox_code_root)


def _integration_status_from_output(*outputs: str) -> str:
    return _integration_output_field("status", *outputs)


def _integration_output_field(field: str, *outputs: str) -> str:
    prefix = f"{field}="
    for output in outputs:
        for line in output.splitlines():
            if line.startswith(prefix):
                return line.removeprefix(prefix).strip()
    return ""


def _commit_ref_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().split(maxsplit=1)[0] if value.strip() else ""
    if re.fullmatch(r"[0-9A-Fa-f]{7,40}", token):
        return token
    return None


def _normalize_posix_path(value: str) -> str:
    return posixpath.normpath(value.rstrip("/") or "/")


def _attempt_status_value(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> str:
    status = attempt.status
    return (
        status.value if isinstance(status, WorkspaceTaskSessionAttemptStatus) else str(status or "")
    )


def _attempt_list_field(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
    *,
    domain_field: str,
    model_field: str,
) -> list[str]:
    value = getattr(attempt, domain_field, None)
    if value is None:
        value = getattr(attempt, model_field, None)
    if isinstance(value, list | tuple):
        return list(dict.fromkeys(str(item) for item in value if item))
    return []


def _attempt_has_candidate_output(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> bool:
    if str(getattr(attempt, "candidate_summary", None) or "").strip():
        return True
    if _attempt_list_field(
        attempt,
        domain_field="candidate_artifacts",
        model_field="candidate_artifacts_json",
    ):
        return True
    return bool(
        _attempt_list_field(
            attempt,
            domain_field="candidate_verifications",
            model_field="candidate_verifications_json",
        )
    )


async def _load_plan_attempt(
    session: AsyncSession,
    attempt_id: str,
) -> WorkspaceTaskSessionAttemptModel | None:
    return await session.get(WorkspaceTaskSessionAttemptModel, attempt_id)


async def _load_reconciling_accepted_attempt_for_task(
    *,
    session: AsyncSession,
    workspace_id: str,
    node: PlanNode,
    terminal_attempt: WorkspaceTaskSessionAttemptModel,
) -> WorkspaceTaskSessionAttemptModel | None:
    workspace_task_id = terminal_attempt.workspace_task_id
    if not workspace_task_id:
        return None
    result = await session.execute(
        select(WorkspaceTaskSessionAttemptModel)
        .where(WorkspaceTaskSessionAttemptModel.workspace_id == workspace_id)
        .where(WorkspaceTaskSessionAttemptModel.workspace_task_id == workspace_task_id)
        .where(WorkspaceTaskSessionAttemptModel.status == "accepted")
        .order_by(WorkspaceTaskSessionAttemptModel.attempt_number.desc())
        .limit(1)
    )
    accepted_attempt = result.scalar_one_or_none()
    if (
        accepted_attempt is not None
        and accepted_attempt.id != terminal_attempt.id
        and _accepted_attempt_matches_node_expected_commit(node, accepted_attempt)
        and (
            accepted_attempt.attempt_number > terminal_attempt.attempt_number
            or _attempt_cancelled_because_parent_done_without_output(terminal_attempt)
        )
    ):
        return accepted_attempt
    return None


async def _accepted_projection_was_superseded_by_parent_done_output_attempt(
    *,
    session: AsyncSession,
    node: PlanNode,
) -> bool:
    if not _node_is_done_idle_with_attempt(node):
        return False
    metadata = dict(node.metadata or {})
    if metadata.get("terminal_attempt_status") != "accepted":
        return False
    if metadata.get("terminal_attempt_superseded_status") != "cancelled":
        return False
    superseded_reason = str(metadata.get("terminal_attempt_superseded_reason") or "")
    if superseded_reason != "recovery:parent_done":
        return False
    superseded_attempt_id = str(metadata.get("terminal_attempt_superseded_attempt_id") or "")
    if not superseded_attempt_id:
        return False
    superseded_attempt = await _load_plan_attempt(session, superseded_attempt_id)
    return (
        superseded_attempt is not None
        and _attempt_cancelled_because_parent_done(superseded_attempt)
        and _attempt_has_candidate_output(superseded_attempt)
    )


def _attempt_cancelled_because_parent_done(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> bool:
    if _attempt_status_value(attempt) != "cancelled":
        return False
    reason = str(getattr(attempt, "adjudication_reason", None) or "")
    feedback = str(getattr(attempt, "leader_feedback", None) or "")
    return "recovery:parent_done" in {reason, feedback}


def _attempt_cancelled_because_parent_done_without_output(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> bool:
    return _attempt_cancelled_because_parent_done(attempt) and not _attempt_has_candidate_output(
        attempt
    )


def _accepted_attempt_matches_node_expected_commit(
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> bool:
    expected = _node_expected_commit_ref(node)
    if not expected:
        return True
    actual_refs = _attempt_commit_refs(attempt)
    if not actual_refs:
        return _last_verified_attempt_matches_expected_commit(
            node=node,
            attempt=attempt,
            expected=expected,
        )
    if any(_git_commit_refs_match(expected, actual) for actual in actual_refs):
        return True
    return _last_verified_attempt_contains_attempt_commit(
        node=node,
        attempt=attempt,
        actual_refs=actual_refs,
    )


def _accepted_attempt_has_same_verified_no_output_projection(
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> bool:
    metadata = dict(node.metadata or {})
    return (
        not _attempt_commit_refs(attempt)
        and metadata.get("last_verification_passed") is True
        and metadata.get("last_verification_attempt_id") == getattr(attempt, "id", None)
    )


def _last_verified_attempt_matches_expected_commit(
    *,
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
    expected: str,
) -> bool:
    metadata = dict(node.metadata or {})
    if metadata.get("last_verification_passed") is not True:
        return False
    if metadata.get("last_verification_attempt_id") != getattr(attempt, "id", None):
        return False
    metadata_refs = _node_metadata_commit_refs(metadata)
    direct_refs = [
        _commit_ref_token(metadata.get(key))
        for key in (
            "source_publish_source_commit_ref",
            "source_publish_commit_ref",
            "verified_commit_ref",
            "worktree_integration_commit_ref",
        )
    ]
    return any(
        _git_commit_refs_match(expected, metadata_ref)
        for metadata_ref in (*metadata_refs, *(ref for ref in direct_refs if ref))
    )


def _attempt_commit_refs(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> tuple[str, ...]:
    refs: list[str] = []
    for ref in _accepted_attempt_evidence_refs(attempt):
        value = _prefixed_ref(ref, "commit_ref:")
        if value:
            refs.append(value)
    return tuple(dict.fromkeys(refs))


def _last_verified_attempt_contains_attempt_commit(
    *,
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
    actual_refs: tuple[str, ...],
) -> bool:
    metadata = dict(node.metadata or {})
    if metadata.get("last_verification_passed") is not True:
        return False
    if metadata.get("last_verification_attempt_id") != getattr(attempt, "id", None):
        return False
    metadata_refs = _node_metadata_commit_refs(metadata)
    return any(
        _git_commit_refs_match(metadata_ref, actual_ref)
        for metadata_ref in metadata_refs
        for actual_ref in actual_refs
    )


def _node_metadata_commit_refs(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for key in (
        "verification_evidence_refs",
        "candidate_artifacts",
        "candidate_verifications",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "execution_verifications",
    ):
        for ref in _metadata_string_values(metadata, key):
            value = _prefixed_ref(ref, "commit_ref:")
            if value:
                refs.append(value)
    return tuple(dict.fromkeys(refs))


def _prefixed_ref(ref: str, prefix: str) -> str | None:
    if ref.startswith(prefix):
        return ref.removeprefix(prefix)
    artifact_prefix = f"artifact:{prefix}"
    if ref.startswith(artifact_prefix):
        return ref.removeprefix(artifact_prefix)
    return None


def _node_expected_commit_ref(node: PlanNode) -> str | None:
    if node.feature_checkpoint is not None:
        commit_ref = _commit_ref_token(node.feature_checkpoint.commit_ref)
        if commit_ref:
            return commit_ref
    metadata = dict(node.metadata or {})
    for key in (
        "source_publish_source_commit_ref",
        "verified_commit_ref",
        "worktree_integration_commit_ref",
    ):
        commit_ref = _commit_ref_token(metadata.get(key))
        if commit_ref:
            return commit_ref
    return None


def _git_commit_refs_match(left: str, right: str) -> bool:
    left = left.strip()
    right = right.strip()
    if not left or not right:
        return False
    if left == right:
        return True
    return (len(left) >= 7 and right.startswith(left)) or (
        len(right) >= 7 and left.startswith(right)
    )


def _plan_node_released_for_retry(
    node: PlanNode,
    *,
    reason: str,
    now: datetime,
) -> PlanNode:
    metadata = dict(node.metadata or {})
    retry_count = int(metadata.get("terminal_attempt_retry_count") or 0) + 1
    metadata.update(
        {
            "terminal_attempt_retry_count": retry_count,
            "terminal_attempt_retry_reason": reason,
            "terminal_attempt_reconciled_at": now.isoformat().replace("+00:00", "Z"),
        }
    )
    if retry_count > _plan_terminal_attempt_max_retries():
        return replace(
            node,
            intent=TaskIntent.BLOCKED,
            execution=TaskExecution.IDLE,
            current_attempt_id=None,
            metadata=metadata,
            updated_at=now,
        )
    metadata.pop("retry_not_before", None)
    return replace(
        node,
        intent=TaskIntent.TODO,
        execution=TaskExecution.IDLE,
        current_attempt_id=None,
        metadata=metadata,
        updated_at=now,
    )


def _make_sql_agent_pool(
    session: AsyncSession,
    *,
    leader_agent_id: str | None = None,
) -> AgentPoolProvider:
    async def _agent_pool(workspace_id: str) -> list[AllocatorAgent]:
        binding_repo = SqlWorkspaceAgentRepository(session)
        task_repo = SqlWorkspaceTaskRepository(session)
        bindings = await binding_repo.find_by_workspace(workspace_id, active_only=True, limit=500)
        tasks = await task_repo.find_by_workspace(workspace_id, limit=1000)
        active_counts: dict[str, int] = {}
        for task in tasks:
            if task.assignee_agent_id and getattr(task.status, "value", task.status) in {
                "todo",
                "in_progress",
                "dispatched",
                "executing",
                "reported",
                "adjudicating",
            }:
                active_counts[task.assignee_agent_id] = (
                    active_counts.get(task.assignee_agent_id, 0) + 1
                )

        pool: list[AllocatorAgent] = []
        for binding in bindings:
            config = dict(binding.config or {})
            tags = _string_set(
                [
                    binding.label,
                    binding.display_name,
                    binding.agent_id,
                    *_iter_config_strings(config.get("affinity_tags")),
                ]
            )
            pool.append(
                AllocatorAgent(
                    agent_id=binding.agent_id,
                    display_name=binding.display_name or binding.label or binding.agent_id,
                    capabilities=_string_set(
                        [
                            *_iter_config_strings(config.get("capabilities")),
                            *_iter_config_strings(config.get("skills")),
                        ]
                    ),
                    tool_names=_string_set(
                        [
                            *_iter_config_strings(config.get("tool_names")),
                            *_iter_config_strings(config.get("tools")),
                            *_iter_config_strings(config.get("allowed_tools")),
                        ]
                    ),
                    active_task_count=active_counts.get(binding.agent_id, 0),
                    is_leader=(
                        binding.agent_id == LEGACY_SISYPHUS_AGENT_ID
                        or (leader_agent_id is not None and binding.agent_id == leader_agent_id)
                        or config.get("workspace_role") == "leader"
                    ),
                    is_available=binding.is_active and binding.status != "offline",
                    affinity_tags=tags,
                )
            )
        return pool

    return _agent_pool


async def _ensure_leader_execution_team(
    *,
    session: AsyncSession,
    workspace_id: str,
    leader_agent_id: str,
) -> None:
    """Materialize an execution team before dispatch stalls.

    This is intentionally idempotent: if any active non-leader worker exists,
    the existing team is respected. When no worker exists and the active plan has
    ready executable nodes, the runtime materializes a small bounded team using
    the workspace harness profile and records the composition on the bindings.
    """
    plan = await SqlPlanRepository(session).get_by_workspace(workspace_id)
    if plan is None or not plan.ready_nodes():
        return

    workspace_repo = SqlWorkspaceRepository(session)
    workspace = await workspace_repo.find_by_id(workspace_id)
    if workspace is None:
        return

    binding_repo = SqlWorkspaceAgentRepository(session)
    bindings = await binding_repo.find_by_workspace(workspace_id, active_only=True, limit=500)
    if any(_is_execution_worker_binding(binding, leader_agent_id) for binding in bindings):
        await _upgrade_existing_auto_team_agents(
            session=session,
            workspace_id=workspace_id,
            workspace=workspace,
        )
        return

    registry = SqlAgentRegistryRepository(session)
    composition_id = f"workspace-plan-team:{workspace_id}:v2"
    ready_capabilities = _capabilities_for_ready_nodes(plan.ready_nodes())
    for role in _AUTO_TEAM_ROLES:
        agent_name = _team_agent_name(workspace_id, str(role["key"]))
        agent = await registry.get_by_name(workspace.tenant_id, agent_name)
        if agent is None:
            agent = Agent.create(
                tenant_id=workspace.tenant_id,
                project_id=workspace.project_id,
                name=agent_name,
                display_name=str(role["display_name"]),
                system_prompt=_team_agent_prompt(
                    str(role["display_name"]), str(role["description"])
                ),
                trigger_description=(
                    "Execute tasks assigned by the durable workspace plan supervisor."
                ),
                allowed_tools=list(_AUTO_TEAM_AGENT_TOOLS),
                allowed_skills=[],
                allowed_mcp_servers=[],
                max_iterations=_AUTO_TEAM_MAX_ITERATIONS,
                agent_to_agent_enabled=True,
                agent_to_agent_allowlist=[leader_agent_id],
                discoverable=True,
                metadata={
                    "created_by": "workspace_plan_team_setup",
                    "workspace_id": workspace_id,
                    "workspace_role": "execution_worker",
                    "team_composition_id": composition_id,
                    "max_iterations_explicit": True,
                },
            )
            agent = await registry.create(agent)

        existing_binding = await binding_repo.find_by_workspace_and_agent_id(
            workspace_id=workspace_id,
            agent_id=agent.id,
        )
        capabilities = sorted(
            set(_iter_config_strings(role.get("capabilities"))) | ready_capabilities
        )
        config = {
            "auto_bound_by_leader": True,
            "workspace_role": "execution_worker",
            "team_composition_id": composition_id,
            "capabilities": capabilities,
            "tool_names": list(_AUTO_TEAM_TOOL_NAMES),
            "allowed_tools": list(_AUTO_TEAM_AGENT_TOOLS),
        }
        if existing_binding is None:
            await binding_repo.save(
                WorkspaceAgent(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    display_name=str(role["display_name"]),
                    description=str(role["description"]),
                    config=config,
                    is_active=True,
                    label=str(role["label"]),
                    status="idle",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        else:
            if _should_upgrade_auto_team_agent(agent, workspace_id):
                agent.max_iterations = max(agent.max_iterations, _AUTO_TEAM_MAX_ITERATIONS)
                agent.metadata = {
                    **dict(agent.metadata or {}),
                    "created_by": "workspace_plan_team_setup",
                    "workspace_id": workspace_id,
                    "max_iterations_explicit": True,
                }
                agent.updated_at = datetime.now(UTC)
                await registry.update(agent)
            existing_binding.is_active = True
            existing_binding.status = "idle"
            existing_binding.config = {
                **dict(existing_binding.config or {}),
                **config,
            }
            existing_binding.updated_at = datetime.now(UTC)
            await binding_repo.save(existing_binding)


async def _upgrade_existing_auto_team_agents(
    *,
    session: AsyncSession,
    workspace_id: str,
    workspace: object,
) -> None:
    tenant_id = getattr(workspace, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id:
        return
    registry = SqlAgentRegistryRepository(session)
    for role in _AUTO_TEAM_ROLES:
        agent = await registry.get_by_name(
            tenant_id,
            _team_agent_name(workspace_id, str(role["key"])),
        )
        if agent is None:
            continue
        if not _should_upgrade_auto_team_agent(agent, workspace_id):
            continue
        agent.max_iterations = max(agent.max_iterations, _AUTO_TEAM_MAX_ITERATIONS)
        agent.metadata = {
            **dict(agent.metadata or {}),
            "created_by": "workspace_plan_team_setup",
            "workspace_id": workspace_id,
            "max_iterations_explicit": True,
        }
        agent.updated_at = datetime.now(UTC)
        await registry.update(agent)


def _should_upgrade_auto_team_agent(agent: Agent, workspace_id: str) -> bool:
    metadata = dict(agent.metadata or {})
    if metadata.get("created_by") != "workspace_plan_team_setup":
        return False
    if metadata.get("workspace_id") != workspace_id:
        return False
    return int(agent.max_iterations or 0) < _AUTO_TEAM_MAX_ITERATIONS


def _is_execution_worker_binding(binding: WorkspaceAgent, leader_agent_id: str) -> bool:
    if not binding.is_active or binding.status == "offline":
        return False
    if binding.agent_id in {leader_agent_id, LEGACY_SISYPHUS_AGENT_ID}:
        return False
    return dict(binding.config or {}).get("workspace_role") != "leader"


def _capabilities_for_ready_nodes(nodes: Iterable[PlanNode]) -> set[str]:
    capabilities: set[str] = set()
    for node in nodes:
        capabilities.update(capability.name for capability in node.recommended_capabilities)
    return {cap for cap in capabilities if cap}


def _team_agent_name(workspace_id: str, role_key: str) -> str:
    compact_workspace_id = "".join(ch for ch in workspace_id.lower() if ch.isalnum())[:12]
    return f"workspace-{compact_workspace_id}-{role_key}"


def _team_agent_prompt(display_name: str, description: str) -> str:
    return (
        f"You are {display_name}, an execution worker in an autonomous workspace team. "
        f"{description} Follow the workspace task binding exactly, report progress through "
        "workspace reporting tools, provide concrete artifacts and verification evidence, "
        "and do not finalize the root goal yourself; the durable plan supervisor owns closeout."
    )


async def _build_child_task_metadata(
    *,
    task_repo: SqlWorkspaceTaskRepository,
    root_task_id: str,
    plan_id: str,
    node: PlanNode,
) -> dict[str, Any]:
    """Build metadata for a child execution task created from a plan node.

    Inherits ``preferred_language`` from the root goal task so worker
    conversations spawned from this child stay in the user's language.
    """
    metadata: dict[str, Any] = {
        AUTONOMY_SCHEMA_VERSION_KEY: AUTONOMY_SCHEMA_VERSION,
        TASK_ROLE: "execution_task",
        ROOT_GOAL_TASK_ID: root_task_id,
        LINEAGE_SOURCE: "agent",
        DERIVED_FROM_INTERNAL_PLAN_STEP: node.id,
        WORKSPACE_PLAN_ID: plan_id,
        WORKSPACE_PLAN_NODE_ID: node.id,
        **_execution_task_metadata_from_node(node),
    }
    root_task = await task_repo.find_by_id(root_task_id)
    if root_task is not None:
        inherited_pref = (root_task.metadata or {}).get(PREFERRED_LANGUAGE)
        if isinstance(inherited_pref, str) and inherited_pref in {"en-US", "zh-CN"}:
            metadata[PREFERRED_LANGUAGE] = inherited_pref
    return metadata


async def _supersede_stale_active_attempt_for_dispatch(
    *,
    session: AsyncSession,
    node: PlanNode,
    active_attempt: WorkspaceTaskSessionAttempt | None,
) -> WorkspaceTaskSessionAttempt | None:
    if active_attempt is None:
        return None
    if not _node_reset_supersedes_active_attempt(node):
        return active_attempt
    stored = await SqlWorkspaceTaskSessionAttemptRepository(session).find_by_id(active_attempt.id)
    if stored is None:
        return None
    if stored.status not in {
        WorkspaceTaskSessionAttemptStatus.PENDING,
        WorkspaceTaskSessionAttemptStatus.RUNNING,
        WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION,
    }:
        return None
    now = datetime.now(UTC)
    stored.status = WorkspaceTaskSessionAttemptStatus.CANCELLED
    stored.leader_feedback = stored.leader_feedback or (
        "Superseded by durable plan redispatch after node reset."
    )
    stored.adjudication_reason = stored.adjudication_reason or "plan_node_reset_superseded"
    stored.completed_at = stored.completed_at or now
    stored.updated_at = now
    await SqlWorkspaceTaskSessionAttemptRepository(session).save(stored)
    return None


def _node_reset_supersedes_active_attempt(node: PlanNode) -> bool:
    if node.current_attempt_id:
        return False
    metadata = dict(node.metadata or {})
    operator_action = metadata.get("operator_action")
    if isinstance(operator_action, Mapping):
        action = operator_action.get("action")
        if action in {"operator_replan_requested", "operator_node_reopened"}:
            return True
    return bool(metadata.get("dependency_invalidated_previous_attempt_id"))


def _make_sql_dispatcher(
    session: AsyncSession,
    item: WorkspacePlanOutboxModel,
    payload: Mapping[str, Any],
) -> Dispatcher:
    async def _dispatch(workspace_id: str, allocation: Allocation, node: PlanNode) -> str | None:
        plan_id = item.plan_id
        if plan_id is None:
            raise ValueError("workspace plan dispatch requires a plan_id")
        root_task_id = await _resolve_root_task_id(session, workspace_id, payload)
        if root_task_id is None:
            raise ValueError("workspace plan dispatch requires a root goal task")

        actor_user_id = await _resolve_actor_user_id(session, workspace_id, payload)
        leader_agent_id = (
            _payload_string(payload, "leader_agent_id") or WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        )
        binding = await SqlWorkspaceAgentRepository(session).find_by_workspace_and_agent_id(
            workspace_id=workspace_id,
            agent_id=str(allocation.agent_id),
        )
        if binding is None:
            raise ValueError(
                f"workspace agent binding not found for agent_id={allocation.agent_id}"
            )

        task_repo = SqlWorkspaceTaskRepository(session)
        existing_task = await _find_task_for_plan_node(
            session=session,
            workspace_id=workspace_id,
            plan_id=plan_id,
            node_id=node.id,
        )
        task_service = WorkspaceTaskService(
            workspace_repo=SqlWorkspaceRepository(session),
            workspace_member_repo=SqlWorkspaceMemberRepository(session),
            workspace_agent_repo=SqlWorkspaceAgentRepository(session),
            workspace_task_repo=task_repo,
        )
        command_service = WorkspaceTaskCommandService(task_service)
        if existing_task is None:
            child_metadata = await _build_child_task_metadata(
                task_repo=task_repo,
                root_task_id=root_task_id,
                plan_id=plan_id,
                node=node,
            )
            existing_task = await command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=node.title,
                description=node.description or None,
                metadata=child_metadata,
                priority=WorkspaceTaskPriority.from_rank(min(max(int(node.priority), 0), 4)),
                estimated_effort=(
                    f"{node.estimated_effort.minutes}m"
                    if node.estimated_effort.minutes > 0
                    else None
                ),
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason="workspace_plan.dispatch.create_projection_task",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )

        if existing_task.assignee_agent_id != binding.agent_id:
            existing_task = await command_service.assign_task_to_agent(
                workspace_id=workspace_id,
                task_id=existing_task.id,
                actor_user_id=actor_user_id,
                workspace_agent_id=binding.id,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason="workspace_plan.dispatch.assign_worker",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )

        attempt_service = WorkspaceTaskSessionAttemptService(
            SqlWorkspaceTaskSessionAttemptRepository(session)
        )
        attempt = await attempt_service.get_active_attempt(existing_task.id)
        attempt = await _supersede_stale_active_attempt_for_dispatch(
            session=session,
            node=node,
            active_attempt=attempt,
        )
        repair_context: dict[str, Any] | None = None
        should_schedule = False
        if attempt is None:
            repair_context = await _same_conversation_repair_context(
                session=session,
                task=existing_task,
                node=node,
                leader_agent_id=leader_agent_id,
            )
            attempt = await attempt_service.create_attempt(
                workspace_task_id=existing_task.id,
                root_goal_task_id=root_task_id,
                workspace_id=workspace_id,
                worker_agent_id=existing_task.assignee_agent_id,
                leader_agent_id=_persisted_attempt_leader_agent_id(leader_agent_id),
                conversation_id=_mapping_string(repair_context or {}, "conversation_id"),
            )
            attempt = await attempt_service.mark_running(attempt.id)
            should_schedule = True
        elif attempt.status is WorkspaceTaskSessionAttemptStatus.PENDING:
            attempt = await attempt_service.mark_running(attempt.id)
            should_schedule = True

        if repair_context is not None:
            repair_context["attempt_id"] = attempt.id
            repair_context["repair_turn_index"] = _repair_turn_index(repair_context)
            node.metadata = {
                **dict(node.metadata or {}),
                _REPAIR_TURN_METADATA_KEY: repair_context,
                "same_conversation_repair_turn_count": repair_context["repair_turn_index"],
            }
            await _append_plan_audit_event(
                session=session,
                plan_id=plan_id,
                workspace_id=workspace_id,
                node_id=node.id,
                attempt_id=attempt.id,
                event_type="worker_repair_turn_dispatched",
                payload=repair_context,
            )
        else:
            _apply_attempt_worktree_checkpoint(node, attempt.id)
        await _ensure_root_started_for_dispatch(
            task_service=task_service,
            command_service=command_service,
            workspace_id=workspace_id,
            root_task_id=root_task_id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
        )
        existing_task = await _project_dispatch_attempt_to_task(
            command_service=command_service,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            task=existing_task,
            attempt=attempt,
            worker_agent_id=binding.agent_id,
            worker_binding_id=binding.id,
            leader_agent_id=leader_agent_id,
            plan_metadata={
                **_execution_task_metadata_from_node(node),
                **(
                    {_REPAIR_TURN_METADATA_KEY: repair_context}
                    if repair_context is not None
                    else {}
                ),
            },
        )

        node.workspace_task_id = existing_task.id
        node.metadata = {
            **dict(node.metadata or {}),
            "workspace_task_id": existing_task.id,
            WORKSPACE_AGENT_BINDING_ID: binding.id,
        }

        await session.flush()
        if should_schedule and existing_task.assignee_agent_id:
            node_brief = _node_worker_brief(node)
            repair_brief_prompt = _repair_turn_prompt(repair_context) if repair_context else None
            _ = await SqlWorkspacePlanOutboxRepository(session).enqueue(
                plan_id=plan_id,
                workspace_id=workspace_id,
                event_type=WORKER_LAUNCH_EVENT,
                payload={
                    "workspace_id": workspace_id,
                    "node_id": node.id,
                    "task_id": existing_task.id,
                    "worker_agent_id": existing_task.assignee_agent_id,
                    "actor_user_id": actor_user_id,
                    "leader_agent_id": leader_agent_id,
                    "attempt_id": attempt.id,
                    "extra_instructions": node_brief,
                    "reuse_conversation_id": _mapping_string(
                        repair_context or {}, "conversation_id"
                    ),
                    "repair_brief_prompt": repair_brief_prompt,
                },
                metadata={
                    "source": (
                        "workspace_plan.dispatch.worker_repair_turn"
                        if repair_context is not None
                        else "workspace_plan.dispatch.worker_launch"
                    )
                },
            )

        return attempt.id

    return _dispatch


def make_worker_launch_handler(
    *,
    worktree_preparer: WorktreePreparer | None = None,
) -> WorkspacePlanOutboxHandler:
    """Build an outbox handler that durably schedules a worker conversation."""

    async def _handle(item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        payload = dict(item.payload_json or {})
        workspace_id = _payload_string(payload, "workspace_id") or item.workspace_id
        task_id = _required_payload_string(payload, "task_id")
        worker_agent_id = _payload_string(payload, "worker_agent_id")
        actor_user_id = _required_payload_string(payload, "actor_user_id")
        leader_agent_id = (
            _payload_string(payload, "leader_agent_id") or WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        )
        attempt_id = _payload_string(payload, "attempt_id")
        extra_instructions = _payload_string(payload, "extra_instructions")
        reuse_conversation_id = _payload_string(payload, "reuse_conversation_id")
        repair_brief_prompt = _payload_string(payload, "repair_brief_prompt")

        task = await SqlWorkspaceTaskRepository(session).find_by_id(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise ValueError(f"workspace task {task_id} not found for workspace {workspace_id}")
        resolved_worker_agent_id = worker_agent_id or task.assignee_agent_id
        if not resolved_worker_agent_id:
            raise ValueError(f"workspace task {task_id} has no worker agent")

        stale_reason = await _stale_worker_launch_reason(
            session=session,
            task=task,
            plan_id=item.plan_id,
            node_id=_payload_string(payload, "node_id"),
            attempt_id=attempt_id,
        )
        if stale_reason is not None:
            logger.info(
                "workspace_plan.worker_launch.skip_stale",
                extra={
                    "event": "workspace_plan.worker_launch.skip_stale",
                    "workspace_id": workspace_id,
                    "plan_id": item.plan_id,
                    "node_id": _payload_string(payload, "node_id"),
                    "task_id": task.id,
                    "attempt_id": attempt_id,
                    "reason": stale_reason,
                },
            )
            return

        if await _should_defer_worker_launch(
            session=session,
            workspace_id=workspace_id,
            attempt_id=attempt_id,
        ):
            await _defer_worker_launch(
                session=session,
                item=item,
                payload=payload,
                active_count=await _active_worker_conversation_count(session, workspace_id),
            )
            return

        worktree_context = await _worker_launch_worktree_context(
            worktree_preparer or _prepare_attempt_worktree_if_available,
            session=session,
            workspace_id=workspace_id,
            task=task,
            extra_instructions=extra_instructions,
            attempt_id=attempt_id,
        )
        await _persist_worker_launch_worktree_context(
            session=session,
            task=task,
            context=worktree_context,
        )
        if worktree_context is not None and worktree_context.setup_failed:
            await _block_task_for_worktree_setup_failure(
                session=session,
                task=task,
                context=worktree_context,
                attempt_id=attempt_id,
                plan_id=item.plan_id,
                node_id=_payload_string(payload, "node_id"),
            )
            return

        setup_note = worktree_context.setup_note() if worktree_context is not None else None
        extra_instructions = _append_launch_instruction_note(extra_instructions, setup_note)

        from src.infrastructure.agent.workspace.worker_launch import (
            schedule_worker_session,
        )

        schedule_worker_session(
            workspace_id=workspace_id,
            task=task,
            worker_agent_id=resolved_worker_agent_id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            attempt_id=attempt_id,
            extra_instructions=extra_instructions,
            reuse_conversation_id=reuse_conversation_id,
            repair_brief_prompt=repair_brief_prompt,
            attempt_worktree_context=(
                worktree_context.to_dict() if worktree_context is not None else None
            ),
        )
        await _mark_plan_node_running_after_launch_schedule(
            session=session,
            plan_id=item.plan_id,
            node_id=_payload_string(payload, "node_id"),
            attempt_id=attempt_id,
        )

    async def _wrapped(item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        payload = dict(item.payload_json or {})
        workspace_id = _payload_string(payload, "workspace_id") or item.workspace_id
        leader_agent_id = (
            _payload_string(payload, "leader_agent_id") or WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        )
        await _run_controller_action(
            session=session,
            item=item,
            workspace_id=workspace_id,
            actor_id=leader_agent_id,
            reason=item.event_type,
            action=lambda: _handle(item, session),
        )

    return _wrapped


async def _should_defer_worker_launch(
    *,
    session: AsyncSession,
    workspace_id: str,
    attempt_id: str | None,
) -> bool:
    max_active = _worker_launch_max_active()
    if max_active <= 0:
        return False
    if attempt_id and await _attempt_has_conversation(session, attempt_id):
        return False
    return await _active_worker_conversation_count(session, workspace_id) >= max_active


async def _active_worker_conversation_count(session: AsyncSession, workspace_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(WorkspaceTaskSessionAttemptModel)
        .where(WorkspaceTaskSessionAttemptModel.workspace_id == workspace_id)
        .where(WorkspaceTaskSessionAttemptModel.status == "running")
        .where(WorkspaceTaskSessionAttemptModel.conversation_id.is_not(None))
    )
    return int(result.scalar_one() or 0)


async def _attempt_has_conversation(session: AsyncSession, attempt_id: str) -> bool:
    result = await session.execute(
        select(WorkspaceTaskSessionAttemptModel.conversation_id).where(
            WorkspaceTaskSessionAttemptModel.id == attempt_id
        )
    )
    conversation_id = result.scalar_one_or_none()
    return isinstance(conversation_id, str) and bool(conversation_id)


async def _stale_worker_launch_reason(
    *,
    session: AsyncSession,
    task: WorkspaceTask,
    plan_id: str | None,
    node_id: str | None,
    attempt_id: str | None,
) -> str | None:
    """Return why a worker launch payload should no longer be scheduled."""

    if not attempt_id:
        return None
    reason: str | None = None
    result = await session.execute(
        select(
            WorkspaceTaskSessionAttemptModel.workspace_task_id,
            WorkspaceTaskSessionAttemptModel.workspace_id,
            WorkspaceTaskSessionAttemptModel.status,
        ).where(WorkspaceTaskSessionAttemptModel.id == attempt_id)
    )
    row = result.one_or_none()
    if row is None:
        reason = "attempt_missing"
    else:
        attempt_task_id, attempt_workspace_id, attempt_status = row
        if attempt_task_id != task.id or attempt_workspace_id != task.workspace_id:
            reason = "attempt_task_mismatch"
        elif str(attempt_status) not in _WORKER_LAUNCHABLE_ATTEMPT_STATUS_VALUES:
            reason = f"attempt_{attempt_status}"

    current_task_attempt_id = _mapping_string(dict(task.metadata or {}), CURRENT_ATTEMPT_ID)
    if reason is None and current_task_attempt_id and current_task_attempt_id != attempt_id:
        reason = "task_current_attempt_changed"

    if reason is None and plan_id and node_id:
        if await _has_supervisor_dispose_decision_for_node(
            session=session,
            workspace_id=task.workspace_id,
            plan_id=plan_id,
            node_id=node_id,
        ):
            return "supervisor_disposed_node"
        plan = await SqlPlanRepository(session).get(plan_id)
        node = plan.nodes.get(PlanNodeId(node_id)) if plan is not None else None
        if node is not None:
            if node.workspace_task_id and node.workspace_task_id != task.id:
                reason = "node_task_mismatch"
            elif node.current_attempt_id and node.current_attempt_id != attempt_id:
                reason = "node_current_attempt_changed"
            elif node.intent is TaskIntent.DONE or node.execution is TaskExecution.IDLE:
                reason = "node_not_launchable"
    return reason


async def _has_supervisor_dispose_decision_for_node(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan_id: str,
    node_id: str,
) -> bool:
    result = await session.execute(
        refresh_select_statement(
            select(WorkspacePlanEventModel.id)
            .where(WorkspacePlanEventModel.workspace_id == workspace_id)
            .where(WorkspacePlanEventModel.plan_id == plan_id)
            .where(WorkspacePlanEventModel.node_id == node_id)
            .where(WorkspacePlanEventModel.event_type == "supervisor_decision_completed")
            .where(WorkspacePlanEventModel.payload_json["action"].as_string() == "dispose_node")
            .limit(1)
        )
    )
    return result.scalar_one_or_none() is not None


async def _defer_worker_launch(
    *,
    session: AsyncSession,
    item: WorkspacePlanOutboxModel,
    payload: Mapping[str, Any],
    active_count: int,
) -> None:
    max_active = _worker_launch_max_active()
    delay_seconds = _worker_launch_defer_seconds()
    metadata = dict(item.metadata_json or {})
    defer_count = int(metadata.get("defer_count") or 0) + 1
    metadata.update(
        {
            "source": "workspace_plan.worker_launch.deferred_capacity",
            "deferred_from_outbox_id": item.id,
            "defer_count": defer_count,
            "active_worker_conversations": active_count,
            "max_active_worker_conversations": max_active,
        }
    )
    _ = await SqlWorkspacePlanOutboxRepository(session).enqueue(
        plan_id=item.plan_id,
        workspace_id=item.workspace_id,
        event_type=WORKER_LAUNCH_EVENT,
        payload=dict(payload),
        metadata=metadata,
        max_attempts=item.max_attempts,
        next_attempt_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
    )
    logger.info(
        "workspace worker launch deferred by active-worker capacity",
        extra={
            "event": "workspace_plan.worker_launch.deferred_capacity",
            "workspace_id": item.workspace_id,
            "outbox_id": item.id,
            "active_worker_conversations": active_count,
            "max_active_worker_conversations": max_active,
            "delay_seconds": delay_seconds,
            "defer_count": defer_count,
        },
    )


def _worker_launch_max_active() -> int:
    return _positive_int_env(_WORKER_LAUNCH_MAX_ACTIVE_ENV, _DEFAULT_WORKER_LAUNCH_MAX_ACTIVE)


def _worker_launch_defer_seconds() -> int:
    return _positive_int_env(_WORKER_LAUNCH_DEFER_SECONDS_ENV, _DEFAULT_WORKER_LAUNCH_DEFER_SECONDS)


def _plan_terminal_attempt_max_retries() -> int:
    return _positive_int_env(
        _PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV,
        _DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES,
    )


def _repair_turn_reuse_enabled() -> bool:
    raw = os.getenv(_REPAIR_TURN_REUSE_ENABLED_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _repair_turn_reuse_max() -> int:
    return _positive_int_env(_REPAIR_TURN_REUSE_MAX_ENV, _DEFAULT_REPAIR_TURN_REUSE_MAX)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value >= 0 else default


async def _same_conversation_repair_context(  # noqa: PLR0911
    *,
    session: AsyncSession,
    task: WorkspaceTask,
    node: PlanNode,
    leader_agent_id: str,
) -> dict[str, Any] | None:
    metadata = dict(node.metadata or {})
    if metadata.get("retry_verification_only") is True:
        return None
    next_action_kind = _mapping_string(metadata, "last_verification_judge_next_action_kind")
    if next_action_kind != "retry_same_node":
        return None
    previous_attempt_id = _mapping_string(metadata, "last_verification_attempt_id")
    if not previous_attempt_id:
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="missing_previous_attempt_id",
        )
        return None
    if not _repair_turn_reuse_enabled():
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="reuse_disabled",
            previous_attempt_id=previous_attempt_id,
        )
        return None
    repair_turn_count = _nonnegative_int(metadata.get("same_conversation_repair_turn_count"))
    if repair_turn_count >= _repair_turn_reuse_max():
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="max_repair_turns_reached",
            previous_attempt_id=previous_attempt_id,
        )
        return None
    previous_attempt = await session.get(WorkspaceTaskSessionAttemptModel, previous_attempt_id)
    if previous_attempt is None:
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="previous_attempt_missing",
            previous_attempt_id=previous_attempt_id,
        )
        return None
    if previous_attempt.workspace_task_id != task.id:
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="previous_attempt_task_mismatch",
            previous_attempt_id=previous_attempt_id,
        )
        return None
    previous_status = _attempt_status_value(previous_attempt)
    if previous_status != WorkspaceTaskSessionAttemptStatus.REJECTED.value:
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason=f"previous_attempt_status_{previous_status or 'unknown'}",
            previous_attempt_id=previous_attempt_id,
        )
        return None
    judge_verdict = _mapping_string(metadata, "last_verification_judge_verdict")
    if judge_verdict != "needs_rework":
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason=f"judge_verdict_{judge_verdict or 'missing'}",
            previous_attempt_id=previous_attempt_id,
        )
        return None
    conversation_id = _mapping_string(
        {"conversation_id": previous_attempt.conversation_id}, "conversation_id"
    )
    if not conversation_id:
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="missing_conversation",
            previous_attempt_id=previous_attempt_id,
        )
        return None
    if not _node_has_reusable_worktree(node):
        await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="missing_reusable_worktree",
            previous_attempt_id=previous_attempt_id,
        )
        return None

    repair_turn_index = repair_turn_count + 1
    return {
        "node_id": node.id,
        "workspace_task_id": task.id,
        "previous_attempt_id": previous_attempt_id,
        "previous_attempt_status": previous_status,
        "conversation_id": conversation_id,
        "reuse_conversation": True,
        "reuse_worktree": True,
        "repair_turn_index": repair_turn_index,
        "repair_turn_parent_attempt_id": previous_attempt_id,
        "repair_brief": _repair_brief_from_node(node, previous_attempt_id=previous_attempt_id),
    }


async def _repair_turn_ineligible(
    *,
    session: AsyncSession,
    task: WorkspaceTask,
    node: PlanNode,
    leader_agent_id: str,
    reason: str,
    previous_attempt_id: str | None = None,
) -> None:
    plan_id = node.plan_id
    payload = {
        "reason": reason,
        "node_id": node.id,
        "workspace_task_id": task.id,
        "previous_attempt_id": previous_attempt_id,
        "next_action_kind": node.metadata.get("last_verification_judge_next_action_kind"),
    }
    await _append_plan_audit_event(
        session=session,
        plan_id=plan_id,
        workspace_id=task.workspace_id,
        node_id=node.id,
        attempt_id=previous_attempt_id,
        event_type="worker_repair_turn_ineligible",
        payload=payload,
        actor_id=leader_agent_id,
    )
    logger.info(
        "workspace_plan.worker_repair_turn.ineligible",
        extra={
            "event": "workspace_plan.worker_repair_turn.ineligible",
            "workspace_id": task.workspace_id,
            "plan_id": plan_id,
            "node_id": node.id,
            "task_id": task.id,
            "attempt_id": previous_attempt_id,
            "reason": reason,
        },
    )
    return None


async def _append_plan_audit_event(
    *,
    session: AsyncSession,
    plan_id: str | None,
    workspace_id: str,
    node_id: str | None,
    attempt_id: str | None,
    event_type: str,
    payload: Mapping[str, Any],
    actor_id: str | None = None,
) -> None:
    if not plan_id:
        return
    await SqlWorkspacePlanEventRepository(session).append(
        plan_id=plan_id,
        workspace_id=workspace_id,
        node_id=node_id,
        attempt_id=attempt_id,
        event_type=event_type,
        actor_id=actor_id,
        source="workspace_plan.repair_turn",
        payload=dict(payload),
    )


def _node_has_reusable_worktree(node: PlanNode) -> bool:
    feature = node.feature_checkpoint
    return bool(feature and feature.worktree_path and feature.branch_name)


def _repair_turn_index(context: Mapping[str, Any]) -> int:
    value = context.get("repair_turn_index")
    if isinstance(value, int) and value > 0:
        return value
    return _nonnegative_int(context.get("repair_turn_index")) or 1


def _repair_brief_from_node(node: PlanNode, *, previous_attempt_id: str) -> dict[str, Any]:
    metadata = dict(node.metadata or {})
    provided = metadata.get("last_verification_judge_repair_brief")
    base: dict[str, Any] = {
        "node": {
            "id": node.id,
            "title": node.title,
            "description": node.description,
        },
        "attempt": {
            "previous_attempt_id": previous_attempt_id,
            "current_attempt_id": None,
        },
        "failed_items": list(
            _iter_config_strings(metadata.get("last_verification_judge_failed_criteria"))
        ),
        "evidence": list(_iter_config_strings(metadata.get("verification_evidence_refs"))),
        "required_next_action": metadata.get("last_verification_judge_required_next_action"),
        "allowed_write_scope": _repair_allowed_write_scope(node),
        "forbidden_actions": [
            "Do not weaken or rewrite tests only to make them pass.",
            (
                "Do not reuse prior worker reports, screenshots, commit refs, or "
                "stale dirty-tree text as current evidence."
            ),
            "Do not change unrelated files outside the repair brief scope.",
            (
                "Do not report completion without fresh git status, commit_ref, "
                "diff summary, and verification output."
            ),
        ],
        "minimum_verifications": _repair_minimum_verifications(node),
        "fresh_evidence_requirements": [
            "Run verification commands in the active attempt worktree.",
            "Commit any code changes and report the new commit_ref.",
            "Include git_diff_summary and git status --short after the commit.",
            "Report only evidence produced during this repair turn.",
        ],
    }
    if isinstance(provided, Mapping):
        base.update(dict(provided))
    worker_feedback = _worker_feedback_items(metadata, base.get("feedback_items"))
    if worker_feedback:
        base["feedback_items"] = worker_feedback
    else:
        base.pop("feedback_items", None)
    return base


def _worker_feedback_items(
    metadata: Mapping[str, Any],
    provided_items: object = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    raw_metadata_items = metadata.get("last_verification_feedback_items")
    if isinstance(raw_metadata_items, list):
        items.extend(dict(item) for item in raw_metadata_items if isinstance(item, Mapping))
    if isinstance(provided_items, list):
        items.extend(dict(item) for item in provided_items if isinstance(item, Mapping))
    worker_items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if item.get("target_layer") != "worker":
            continue
        key = (
            str(item.get("feedback_kind") or ""),
            str(item.get("recommended_action") or ""),
            str(item.get("failure_signature") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        worker_items.append(item)
    return worker_items


def _repair_allowed_write_scope(node: PlanNode) -> list[str]:
    metadata = dict(node.metadata or {})
    write_set = list(_iter_config_strings(metadata.get("write_set")))
    if write_set:
        return write_set
    feature = node.feature_checkpoint
    if feature is not None and feature.expected_artifacts:
        return list(feature.expected_artifacts)
    return []


def _repair_minimum_verifications(node: PlanNode) -> list[str]:
    metadata = dict(node.metadata or {})
    commands = list(_iter_config_strings(metadata.get("verification_commands")))
    feature = node.feature_checkpoint
    if feature is not None:
        commands.extend(feature.test_commands)
    commands.append("git status --short")
    return list(dict.fromkeys(command for command in commands if command))


def _repair_turn_prompt(context: Mapping[str, Any] | None) -> str | None:
    if not context:
        return None
    raw_brief = context.get("repair_brief")
    brief = dict(raw_brief) if isinstance(raw_brief, Mapping) else {}
    attempt = brief.get("attempt")
    if isinstance(attempt, Mapping):
        brief["attempt"] = {**dict(attempt), "current_attempt_id": context.get("attempt_id")}
    payload = {
        "repair_turn_parent_attempt_id": context.get("repair_turn_parent_attempt_id"),
        "current_attempt_id": context.get("attempt_id"),
        "repair_turn_index": context.get("repair_turn_index"),
        "reuse_conversation": True,
        "reuse_worktree": True,
        "repair_brief": brief,
    }
    repair_json = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return (
        "[repair-turn]\n"
        f"{repair_json}\n"
        "[/repair-turn]\n\n"
        "Repair turn rules:\n"
        "- Treat this as a new attempt with fresh evidence boundaries even though "
        "the conversation is reused.\n"
        "- Address only the failures in repair_brief.failed_items and required_next_action.\n"
        "- Re-run the minimum_verifications listed in the brief.\n"
        "- When complete, report using the current_attempt_id only; include fresh commit_ref, "
        "git_diff_summary, changed files, test_run evidence, and git status --short."
    )


def _nonnegative_int(value: object) -> int:
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return max(int(value.strip()), 0)
    return 0


async def _mark_plan_node_running_after_launch_schedule(
    *,
    session: AsyncSession,
    plan_id: str | None,
    node_id: str | None,
    attempt_id: str | None,
) -> None:
    """Mark a launched node RUNNING once the worker launch job has scheduled."""

    if not plan_id or not node_id:
        return
    plan = await SqlPlanRepository(session).get(plan_id)
    if plan is None:
        return
    node = plan.nodes.get(PlanNodeId(node_id))
    if node is None:
        return
    if attempt_id and node.current_attempt_id and node.current_attempt_id != attempt_id:
        return
    if node.execution not in {TaskExecution.DISPATCHED, TaskExecution.RUNNING}:
        return
    plan.replace_node(
        replace(
            node,
            execution=TaskExecution.RUNNING,
            current_attempt_id=attempt_id or node.current_attempt_id,
            updated_at=datetime.now(UTC),
        )
    )
    await SqlPlanRepository(session).save(plan)


def make_handoff_resume_handler() -> WorkspacePlanOutboxHandler:  # noqa: C901, PLR0915
    """Build a handler that turns recovery/retry jobs into fresh worker launches."""

    async def _handle(  # noqa: C901, PLR0912, PLR0915
        item: WorkspacePlanOutboxModel,
        session: AsyncSession,
    ) -> None:
        payload = dict(item.payload_json or {})
        workspace_id = _payload_string(payload, "workspace_id") or item.workspace_id
        task_id = _required_payload_string(payload, "task_id")

        task = await SqlWorkspaceTaskRepository(session).find_by_id(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise ValueError(f"workspace task {task_id} not found for workspace {workspace_id}")

        metadata = dict(task.metadata or {})
        actor_user_id = _payload_string(payload, "actor_user_id") or task.created_by
        leader_agent_id = (
            _payload_string(payload, "leader_agent_id") or WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        )
        worker_agent_id = _payload_string(payload, "worker_agent_id") or task.assignee_agent_id
        if not worker_agent_id:
            raise ValueError(f"workspace task {task_id} has no worker agent")

        root_task_id = (
            _payload_string(payload, ROOT_GOAL_TASK_ID)
            or _payload_string(payload, "root_goal_task_id")
            or _mapping_string(metadata, ROOT_GOAL_TASK_ID)
        )
        if not root_task_id:
            raise ValueError(f"workspace task {task_id} has no root goal task")

        plan_id = item.plan_id or _mapping_string(metadata, WORKSPACE_PLAN_ID)
        node_id = _payload_string(payload, "node_id") or _mapping_string(
            metadata, WORKSPACE_PLAN_NODE_ID
        )
        if plan_id and node_id:
            if await _has_supervisor_dispose_decision_for_node(
                session=session,
                workspace_id=workspace_id,
                plan_id=plan_id,
                node_id=node_id,
            ):
                logger.info(
                    "workspace_plan.handoff_resume.skip_supervisor_disposed_node",
                    extra={
                        "event": "workspace_plan.handoff_resume.skip_supervisor_disposed_node",
                        "workspace_id": workspace_id,
                        "plan_id": plan_id,
                        "node_id": node_id,
                        "task_id": task.id,
                    },
                )
                return
            missing_dependencies = await _defer_handoff_resume_for_unmet_dependencies(
                session=session,
                workspace_id=workspace_id,
                plan_id=plan_id,
                node_id=node_id,
                event_type=item.event_type,
            )
            if missing_dependencies:
                logger.info(
                    "workspace_plan.handoff_resume.deferred_unmet_dependencies",
                    extra={
                        "event": "workspace_plan.handoff_resume.deferred_unmet_dependencies",
                        "workspace_id": workspace_id,
                        "plan_id": plan_id,
                        "node_id": node_id,
                        "missing_dependency_ids": missing_dependencies,
                    },
                )
                return

        binding = await SqlWorkspaceAgentRepository(session).find_by_workspace_and_agent_id(
            workspace_id=workspace_id,
            agent_id=worker_agent_id,
        )
        if binding is None:
            raise ValueError(f"workspace agent binding not found for agent_id={worker_agent_id}")

        attempt_service = WorkspaceTaskSessionAttemptService(
            SqlWorkspaceTaskSessionAttemptRepository(session)
        )
        attempt = await attempt_service.get_active_attempt(task.id)
        should_schedule = _payload_bool(payload, "force_schedule")
        previous_attempt_id = _payload_string(payload, "previous_attempt_id")
        if (
            attempt is not None
            and not should_schedule
            and previous_attempt_id == attempt.id
            and attempt.status is WorkspaceTaskSessionAttemptStatus.RUNNING
            and attempt.conversation_id
        ):
            logger.info(
                "workspace_plan.handoff_resume.skip_running_current_attempt",
                extra={
                    "event": "workspace_plan.handoff_resume.skip_running_current_attempt",
                    "workspace_id": workspace_id,
                    "plan_id": plan_id,
                    "node_id": node_id,
                    "attempt_id": attempt.id,
                },
            )
            return
        if attempt is None:
            attempt = await attempt_service.create_attempt(
                workspace_task_id=task.id,
                root_goal_task_id=root_task_id,
                workspace_id=workspace_id,
                worker_agent_id=worker_agent_id,
                leader_agent_id=_persisted_attempt_leader_agent_id(leader_agent_id),
            )
            attempt = await attempt_service.mark_running(attempt.id)
            should_schedule = True
        elif attempt.status is WorkspaceTaskSessionAttemptStatus.PENDING:
            attempt = await attempt_service.mark_running(attempt.id)
            should_schedule = True
        elif not attempt.conversation_id:
            should_schedule = True

        handoff = _build_handoff_package(
            event_type=item.event_type,
            payload=payload,
            task=task,
            metadata=metadata,
        )

        node_brief: str | None = None
        plan_metadata: dict[str, object] = {"handoff_package": handoff.to_json()}
        if plan_id and node_id:
            node = await _attach_handoff_to_plan_node(
                session=session,
                plan_id=plan_id,
                node_id=node_id,
                task=task,
                attempt=attempt,
                worker_agent_id=worker_agent_id,
                worker_binding_id=binding.id,
                handoff=handoff,
            )
            if node is not None:
                node_brief = _node_worker_brief(node)
                plan_metadata.update(_execution_task_metadata_from_node(node))

        task_service = WorkspaceTaskService(
            workspace_repo=SqlWorkspaceRepository(session),
            workspace_member_repo=SqlWorkspaceMemberRepository(session),
            workspace_agent_repo=SqlWorkspaceAgentRepository(session),
            workspace_task_repo=SqlWorkspaceTaskRepository(session),
        )
        command_service = WorkspaceTaskCommandService(task_service)
        task = await _project_dispatch_attempt_to_task(
            command_service=command_service,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            task=task,
            attempt=attempt,
            worker_agent_id=worker_agent_id,
            worker_binding_id=binding.id,
            leader_agent_id=leader_agent_id,
            plan_metadata=plan_metadata,
        )

        await session.flush()
        if not should_schedule:
            return
        extra_instructions = _append_launch_instruction_note(
            _payload_string(payload, "extra_instructions"),
            node_brief or _handoff_only_brief(handoff),
        )
        _ = await SqlWorkspacePlanOutboxRepository(session).enqueue(
            plan_id=plan_id,
            workspace_id=workspace_id,
            event_type=WORKER_LAUNCH_EVENT,
            payload={
                "workspace_id": workspace_id,
                "node_id": node_id,
                "task_id": task.id,
                "worker_agent_id": worker_agent_id,
                "actor_user_id": actor_user_id,
                "leader_agent_id": leader_agent_id,
                "attempt_id": attempt.id,
                "extra_instructions": extra_instructions,
            },
            metadata={
                "source": f"workspace_plan.{item.event_type}",
                "previous_attempt_id": previous_attempt_id,
            },
        )

    async def _wrapped(item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        payload = dict(item.payload_json or {})
        workspace_id = _payload_string(payload, "workspace_id") or item.workspace_id
        leader_agent_id = (
            _payload_string(payload, "leader_agent_id") or WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        )
        await _run_controller_action(
            session=session,
            item=item,
            workspace_id=workspace_id,
            actor_id=leader_agent_id,
            reason=item.event_type,
            action=lambda: _handle(item, session),
        )

    return _wrapped


async def _defer_handoff_resume_for_unmet_dependencies(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan_id: str,
    node_id: str,
    event_type: str,
) -> list[str]:
    """Do not resume a stale downstream attempt before its DAG deps are done."""

    repo = SqlPlanRepository(session)
    plan = await repo.get(plan_id)
    if plan is None or plan.workspace_id != workspace_id:
        return []
    node = plan.nodes.get(PlanNodeId(node_id))
    if node is None or not node.depends_on:
        return []
    done_ids = frozenset(
        candidate.node_id
        for candidate in plan.nodes.values()
        if candidate.intent is TaskIntent.DONE
    )
    missing = sorted(dep.value for dep in node.depends_on if dep not in done_ids)
    if not missing:
        return []

    now = datetime.now(UTC)
    metadata = _clear_stale_attempt_metadata(node.metadata)
    metadata.update(
        {
            "handoff_resume_deferred_at": now.isoformat().replace("+00:00", "Z"),
            "handoff_resume_deferred_event_type": event_type,
            "handoff_resume_deferred_missing_dependency_ids": missing,
            "handoff_resume_deferred_previous_attempt_id": node.current_attempt_id,
            "handoff_resume_deferred_previous_intent": node.intent.value,
            "handoff_resume_deferred_previous_execution": node.execution.value,
        }
    )
    plan.replace_node(
        replace(
            node,
            intent=TaskIntent.TODO,
            execution=TaskExecution.IDLE,
            current_attempt_id=None,
            metadata=metadata,
            updated_at=now,
            completed_at=None,
        )
    )
    await repo.save(plan)
    return missing


def make_attempt_retry_handler() -> WorkspacePlanOutboxHandler:
    """Build a retry handler; retry and handoff resume share the same durable path."""

    return make_handoff_resume_handler()


def make_pipeline_run_requested_handler(  # noqa: C901, PLR0915
    *, redis_client: redis.Redis | None = None
) -> WorkspacePlanOutboxHandler:
    """Build a handler that runs harness-native CI/CD in the project sandbox."""

    async def _handle(  # noqa: C901, PLR0911, PLR0912, PLR0915
        item: WorkspacePlanOutboxModel,
        session: AsyncSession,
    ) -> None:
        payload = dict(item.payload_json or {})
        workspace_id = _payload_string(payload, "workspace_id") or item.workspace_id
        plan_id = _payload_string(payload, "plan_id") or item.plan_id
        node_id = _payload_string(payload, "node_id")
        attempt_id = _payload_string(payload, "attempt_id")
        if not plan_id or not node_id:
            raise ValueError("pipeline_run_requested requires plan_id and node_id")

        plan_repo = SqlPlanRepository(session)
        plan = await plan_repo.get(plan_id)
        if plan is None or plan.workspace_id != workspace_id:
            raise ValueError(f"workspace plan {plan_id} not found for workspace {workspace_id}")
        node = plan.nodes.get(PlanNodeId(node_id))
        if node is None:
            raise ValueError(f"workspace plan node {node_id} not found")
        current_attempt = (
            await _load_plan_attempt(session, node.current_attempt_id)
            if node.current_attempt_id
            else None
        )

        workspace_repo = SqlWorkspaceRepository(session)
        workspace = await workspace_repo.find_by_id(workspace_id)
        if workspace is None:
            raise ValueError(f"workspace {workspace_id} not found")

        root_metadata = await _pipeline_root_metadata(
            session=session,
            workspace_id=workspace_id,
            payload=payload,
        )
        workspace_metadata = dict(getattr(workspace, "metadata", {}) or {})
        if resolve_workspace_type(root_metadata, workspace_metadata) != "software_development":
            await _mark_pipeline_skipped(
                session=session,
                plan=plan,
                node=node,
                reason="workspace is not software_development",
            )
            return

        contract = _pipeline_contract_for_workspace(
            project_id=workspace.project_id,
            workspace_id=workspace_id,
            workspace_metadata=workspace_metadata,
            root_metadata=root_metadata,
        )
        contract = _pipeline_contract_for_node_phase(contract, node=node)
        if _needs_agent_managed_pipeline_proposal(contract):
            await _suspend_plan_for_pipeline(
                session=session,
                plan=plan,
                node=node,
                reason="planner agent did not submit delivery contract",
            )
            return
        if _requires_preview_deployment(contract) and not contract.services:
            await _suspend_plan_for_pipeline(
                session=session,
                plan=plan,
                node=node,
                reason=(
                    "planner agent did not submit delivery contract"
                    if contract.agent_managed
                    else "delivery contract requires preview deployment but has no services"
                ),
            )
            return
        if contract.provider not in {SANDBOX_NATIVE_PROVIDER, DRONE_PROVIDER}:
            await _suspend_plan_for_pipeline(
                session=session,
                plan=plan,
                node=node,
                reason=f"unsupported pipeline provider: {contract.provider}",
            )
            return

        requested_source_commit_ref = _pipeline_run_commit_ref(
            contract,
            node=node,
            current_attempt=current_attempt,
            attempt_id=attempt_id,
        )
        source_publish_result: PipelineRunResult | None = None
        source_publish_metadata: dict[str, Any] = {}
        if contract.provider == DRONE_PROVIDER:
            (
                contract,
                source_publish_metadata,
                source_publish_result,
            ) = await _prepare_drone_source_ref(
                workspace=workspace,
                workspace_metadata=workspace_metadata,
                root_metadata=root_metadata,
                node=node,
                attempt_id=attempt_id,
                current_attempt=current_attempt,
                contract=contract,
            )
            requested_source_commit_ref = (
                _commit_ref_token(source_publish_metadata.get("source_publish_source_commit_ref"))
                or requested_source_commit_ref
            )

        pipeline_repo = SqlWorkspacePipelineRepository(session)
        latest = await pipeline_repo.latest_run_for_node(
            plan_id=plan_id,
            node_id=node_id,
            attempt_id=attempt_id,
        )
        if latest is not None and latest.status == "running":
            if _pipeline_run_matches_requested_commit(
                latest,
                requested_source_commit_ref=requested_source_commit_ref,
            ):
                await _mark_pipeline_running(
                    session=session, plan=plan, node=node, run_id=latest.id
                )
                await session.commit()
                if contract.provider == DRONE_PROVIDER:
                    await _run_drone_pipeline(
                        session=session,
                        pipeline_repo=pipeline_repo,
                        plan=plan,
                        node=node,
                        run=latest,
                        contract=contract,
                        workspace_id=workspace_id,
                        plan_id=plan_id,
                        node_id=node_id,
                    )
                    return
            else:
                stale_source_commit_ref = _pipeline_run_source_commit_ref(latest)
                await pipeline_repo.finish_run(
                    latest,
                    status="failed",
                    reason=(
                        "stale pipeline run source commit "
                        f"{stale_source_commit_ref or 'unknown'} superseded by "
                        f"{requested_source_commit_ref or 'unknown'}"
                    ),
                    metadata={
                        "stale_pipeline_run": True,
                        "stale_source_commit_ref": stale_source_commit_ref,
                        "superseded_by_source_commit_ref": requested_source_commit_ref,
                    },
                )
        if latest is not None and _can_reflect_existing_pipeline_run(
            run=latest,
            contract=contract,
            node=node,
        ):
            await _reflect_existing_pipeline_run(
                session=session,
                plan=plan,
                node=node,
                run_id=latest.id,
                status=latest.status,
            )
            return

        contract_model = await pipeline_repo.ensure_contract(
            workspace_id=workspace_id,
            plan_id=plan_id,
            provider=contract.provider,
            code_root=contract.code_root,
            commands=contract.commands_json(),
            env=contract.env,
            trigger_policy={
                "trigger": "verification_gate",
                "node_id": node_id,
                "attempt_id": attempt_id,
            },
            timeout_seconds=contract.timeout_seconds,
            auto_deploy=contract.auto_deploy,
            preview_port=contract.preview_port,
            health_url=contract.health_url,
            metadata={
                "source": "workspace_plan.pipeline_run_requested",
                "agent_managed": contract.agent_managed,
                "contract_source": contract.contract_source,
                "contract_confidence": contract.contract_confidence,
                "services": contract.services_json(),
                "provider_config": contract.provider_config,
                **source_publish_metadata,
            },
        )
        run = await pipeline_repo.create_run(
            contract_id=contract_model.id,
            workspace_id=workspace_id,
            plan_id=plan_id,
            node_id=node_id,
            attempt_id=attempt_id,
            commit_ref=_pipeline_run_commit_ref(
                contract,
                node=node,
                current_attempt=current_attempt,
                attempt_id=attempt_id,
            ),
            provider=contract.provider,
            metadata={
                "reason": payload.get("reason") or "pipeline_gate_required",
                **source_publish_metadata,
            },
        )
        await _mark_pipeline_running(session=session, plan=plan, node=node, run_id=run.id)
        await session.commit()

        if contract.provider == DRONE_PROVIDER:
            if source_publish_result is not None:
                await _persist_external_pipeline_result(
                    session=session,
                    pipeline_repo=pipeline_repo,
                    plan=plan,
                    node=node,
                    run=run,
                    contract=contract,
                    result=source_publish_result,
                    workspace_id=workspace_id,
                    plan_id=plan_id,
                    node_id=node_id,
                )
            else:
                await _run_drone_pipeline(
                    session=session,
                    pipeline_repo=pipeline_repo,
                    plan=plan,
                    node=node,
                    run=run,
                    contract=contract,
                    workspace_id=workspace_id,
                    plan_id=plan_id,
                    node_id=node_id,
                )
            return

        runner = _WorkspaceSandboxCommandRunner(
            project_id=workspace.project_id,
            tenant_id=workspace.tenant_id,
        )
        provider = SandboxNativePipelineProvider(runner)
        stage_results = []
        evidence_refs: list[str] = []
        failure_reason: str | None = None
        service_status: dict[str, str] = {}
        service_pid: dict[str, int | None] = {}
        preview_urls: dict[str, str] = {}

        for stage in contract.stages:
            stage_row = await pipeline_repo.create_stage_run(
                run_id=run.id,
                workspace_id=workspace_id,
                stage=stage.stage,
                command=stage.command,
                metadata={"required": stage.required, "service_id": stage.service_id},
            )
            stage_result = await provider.run_stage(contract, stage)
            stage_results.append(stage_result)
            await pipeline_repo.finish_stage_run(
                stage_row,
                status=stage_result.status,
                exit_code=stage_result.exit_code,
                stdout_preview=stage_result.stdout_preview,
                stderr_preview=stage_result.stderr_preview,
                log_ref=stage_result.log_ref,
                artifact_refs=list(stage_result.artifact_refs),
                metadata={
                    "duration_ms_observed": stage_result.duration_ms,
                    "service_id": stage.service_id,
                },
            )
            service_suffix = f":{stage.service_id}" if stage.service_id else ""
            if stage_result.passed:
                evidence_refs.append(f"pipeline_stage:{stage.stage}:passed")
                if service_suffix:
                    evidence_refs.append(f"pipeline_stage:{stage.stage}:passed{service_suffix}")
            else:
                evidence_refs.append(f"pipeline_stage:{stage.stage}:failed")
                if service_suffix:
                    evidence_refs.append(f"pipeline_stage:{stage.stage}:failed{service_suffix}")
            if stage.service_id and stage.stage == "deploy":
                service_status[stage.service_id] = "running" if stage_result.passed else "failed"
                service_pid[stage.service_id] = (
                    _first_int(stage_result.stdout_preview) if stage_result.passed else None
                )
            if stage.stage == "health":
                health_status = "healthy" if stage_result.passed else "unhealthy"
                if stage.service_id:
                    service_status[stage.service_id] = health_status
                    health_ref_status = "passed" if stage_result.passed else "failed"
                    evidence_refs.append(
                        f"deployment_health:{health_ref_status}:{stage.service_id}"
                    )
                else:
                    evidence_refs.append(
                        "deployment_health:passed"
                        if stage_result.passed
                        else "deployment_health:failed"
                    )
            if not stage_result.passed and stage.required:
                failure_reason = f"stage {stage.stage} failed with exit {stage_result.exit_code}"
                break

        run_status = "success" if failure_reason is None else "failed"
        if contract.services:
            for service_spec in contract.services:
                status_value = service_status.get(service_spec.service_id)
                if status_value not in {"running", "healthy", "unhealthy"}:
                    continue
                preview_url, ws_preview_url, service_url = await _register_pipeline_service_preview(
                    project_id=workspace.project_id,
                    sandbox_runner=runner,
                    redis_client=redis_client,
                    service=service_spec,
                )
                preview_urls[service_spec.service_id] = preview_url
                evidence_refs.append(f"preview_url:{service_spec.service_id}:{preview_url}")
                evidence_refs.append(f"deployment:{service_spec.service_id}:{status_value}")
                await pipeline_repo.upsert_deployment(
                    workspace_id=workspace_id,
                    plan_id=plan_id,
                    node_id=node_id,
                    pipeline_run_id=run.id,
                    provider=contract.provider,
                    status=status_value,
                    command=service_spec.start_command,
                    pid=service_pid.get(service_spec.service_id),
                    port=service_spec.internal_port,
                    preview_url=preview_url,
                    health_url=service_spec.internal_health_url,
                    rollback_ref=_pipeline_commit_ref(node),
                    log_ref=None,
                    service_id=service_spec.service_id,
                    service_name=service_spec.name,
                    service_url=service_url,
                    ws_preview_url=ws_preview_url,
                    required=service_spec.required,
                    metadata={"pipeline_status": run_status},
                )

        if contract.services and _required_services_healthy(contract.services, service_status):
            evidence_refs.append("deployment_health:passed")
        evidence_refs.insert(
            0,
            f"ci_pipeline:{'passed' if run_status == 'success' else 'failed'}",
        )
        evidence_refs.append(f"pipeline_run:{run_status}:{run.id}")
        await pipeline_repo.finish_run(
            run,
            status=run_status,
            reason=failure_reason,
            metadata={
                "stage_count": len(stage_results),
                "service_count": len(contract.services),
                "preview_urls": preview_urls,
            },
        )
        primary_preview_url = next(iter(preview_urls.values()), None) or _pipeline_preview_url(
            contract.health_url,
            contract.preview_port,
        )
        if not contract.services and (contract.auto_deploy or contract.health_url):
            await pipeline_repo.upsert_deployment(
                workspace_id=workspace_id,
                plan_id=plan_id,
                node_id=node_id,
                pipeline_run_id=run.id,
                provider=contract.provider,
                status="skipped" if not contract.deploy_command else run_status,
                command=contract.deploy_command,
                port=contract.preview_port,
                preview_url=primary_preview_url,
                health_url=contract.health_url,
                rollback_ref=_pipeline_commit_ref(node),
                log_ref=None,
                metadata={"pipeline_status": run_status},
            )
        await _finish_pipeline_on_node(
            session=session,
            plan=plan,
            node=node,
            run_id=run.id,
            status=run_status,
            reason=failure_reason,
            evidence_refs=evidence_refs,
            preview_url=primary_preview_url,
            health_url=contract.health_url,
        )
        await SqlWorkspacePlanOutboxRepository(session).enqueue(
            plan_id=plan_id,
            workspace_id=workspace_id,
            event_type=SUPERVISOR_TICK_EVENT,
            payload={
                "workspace_id": workspace_id,
                "plan_id": plan_id,
                "node_id": node_id,
                "pipeline_run_id": run.id,
                "pipeline_status": run_status,
            },
            metadata={"source": "workspace_plan.pipeline_run_completed"},
        )

    return _handle


async def _prepare_drone_source_ref(
    *,
    workspace: Workspace,
    workspace_metadata: Mapping[str, Any],
    root_metadata: Mapping[str, Any],
    node: PlanNode,
    attempt_id: str | None,
    current_attempt: WorkspaceTaskSessionAttemptModel | None = None,
    contract: PipelineContractSpec,
) -> tuple[PipelineContractSpec, dict[str, Any], PipelineRunResult | None]:
    source_control = _drone_source_control_config(
        workspace_metadata=workspace_metadata,
        provider_config=contract.provider_config,
    )
    branch = _drone_source_branch(source_control, contract.provider_config)
    if not attempt_id:
        provider_config = dict(contract.provider_config)
        if branch and not _metadata_string(provider_config.get("branch")):
            provider_config["branch"] = branch
        metadata = _source_publish_metadata(
            status="skipped",
            reason="missing attempt_id; using remote branch head",
            commit_ref=_pipeline_contract_commit_ref(contract),
            branch=branch,
            source_commit_ref=None,
            token_env=_source_control_token_env(source_control),
        )
        return replace(contract, provider_config=provider_config), metadata, None

    commit_ref = _pipeline_commit_ref(node, current_attempt=current_attempt)
    if not commit_ref:
        return (
            contract,
            {
                "source_publish_status": "skipped",
                "source_publish_reason": "missing commit_ref",
            },
            None,
        )

    from src.infrastructure.agent.workspace.code_context import load_workspace_code_context

    code_context = load_workspace_code_context(
        project_id=str(workspace.project_id),
        root_metadata=root_metadata,
        workspace_metadata=workspace_metadata,
    )
    host_code_root = getattr(code_context, "host_code_root", None)
    if host_code_root is None:
        reason = "host_code_root is not available for Drone source publish"
        metadata = _source_publish_metadata(
            status="failed",
            reason=reason,
            commit_ref=commit_ref,
            branch=None,
            source_commit_ref=commit_ref,
        )
        return contract, metadata, _source_publish_failure_result(reason, metadata=metadata)

    if not branch:
        reason = "source_control.default_branch or delivery_cicd.drone.branch is required"
        metadata = _source_publish_metadata(
            status="failed",
            reason=reason,
            commit_ref=commit_ref,
            branch=None,
            source_commit_ref=commit_ref,
        )
        return contract, metadata, _source_publish_failure_result(reason, metadata=metadata)

    remote_url = _source_control_remote_url(source_control)
    token_env = _source_control_token_env(source_control)
    token = _source_control_token(token_env)
    publish = await _publish_git_ref_to_source_control(
        host_code_root=host_code_root,
        commit_ref=commit_ref,
        branch=branch,
        remote_url=remote_url,
        token=token,
        token_env=token_env,
    )
    publish_status = str(publish.get("status") or "failed")
    metadata = _source_publish_metadata(
        status=publish_status,
        reason=publish.get("reason"),
        commit_ref=publish.get("published_commit") or commit_ref,
        branch=branch,
        source_commit_ref=commit_ref,
        token_env=token_env,
    )
    if publish_status != "published":
        return (
            contract,
            metadata,
            _source_publish_failure_result(
                str(publish.get("reason") or "source publish failed"),
                metadata=metadata,
            ),
        )

    published_commit = str(publish.get("published_commit") or commit_ref)
    provider_config = dict(contract.provider_config)
    provider_config["branch"] = branch
    provider_config["commit"] = published_commit
    provider_config["source_publish"] = {
        "status": "published",
        "branch": branch,
        "commit_ref": published_commit,
        "source_commit_ref": commit_ref,
        "token_env": token_env,
    }
    return replace(contract, provider_config=provider_config), metadata, None


def _drone_source_control_config(
    *,
    workspace_metadata: Mapping[str, Any],
    provider_config: Mapping[str, Any],
) -> dict[str, Any]:
    source_control: dict[str, Any] = {}
    raw_source_control = provider_config.get("source_control")
    if isinstance(raw_source_control, Mapping):
        source_control.update(dict(raw_source_control))
    raw_workspace_source_control = workspace_metadata.get("source_control")
    if isinstance(raw_workspace_source_control, Mapping):
        source_control.update(dict(raw_workspace_source_control))
    if "repo" not in source_control and isinstance(provider_config.get("repo"), str):
        source_control["repo"] = provider_config["repo"]
    if "default_branch" not in source_control and isinstance(provider_config.get("branch"), str):
        source_control["default_branch"] = provider_config["branch"]
    return source_control


def _drone_source_branch(
    source_control: Mapping[str, Any],
    provider_config: Mapping[str, Any],
) -> str | None:
    branch = _metadata_string(provider_config.get("branch")) or _metadata_string(
        source_control.get("default_branch")
    )
    if not branch:
        return None
    return branch if _is_safe_git_branch(branch) else None


def _source_control_remote_url(source_control: Mapping[str, Any]) -> str | None:
    remote_url = _metadata_string(source_control.get("clone_url"))
    if remote_url:
        return remote_url
    repo = _metadata_string(source_control.get("repo"))
    if not repo:
        return None
    provider = str(source_control.get("provider") or "github").strip().lower()
    server_url = _metadata_string(source_control.get("server_url"))
    if provider == "gitlab":
        base_url = (server_url or "https://gitlab.com").rstrip("/")
    else:
        base_url = (server_url or "https://github.com").rstrip("/")
    suffix = "" if repo.endswith(".git") else ".git"
    return f"{base_url}/{repo}{suffix}"


def _source_control_token_env(source_control: Mapping[str, Any]) -> str | None:
    configured = _metadata_string(source_control.get("auth_token_env"))
    if configured:
        return configured
    provider = str(source_control.get("provider") or "github").strip().lower()
    if provider == "gitlab":
        return "GITLAB_TOKEN"
    return "GITHUB_TOKEN"


def _source_control_token(token_env: str | None) -> str | None:
    if not token_env:
        return None
    value = _metadata_string(os.getenv(token_env))
    if value:
        return value
    dotenv = _source_publish_dotenv_values(_source_publish_dotenv_path())
    return _metadata_string(dotenv.get(token_env))


def _source_publish_dotenv_path() -> str:
    return os.getenv("MEMSTACK_DRONE_DOTENV_PATH", ".env")


@lru_cache(maxsize=8)
def _source_publish_dotenv_values(path: str) -> Mapping[str, str | None]:
    dotenv_path = Path(path)
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return {}
    return dotenv_values(dotenv_path)


def _is_safe_git_branch(value: str) -> bool:
    if not value or value.startswith("-") or value.endswith("/") or ".." in value:
        return False
    if "@{" in value or "\\" in value or value.startswith("/") or "//" in value:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._/-]+", value))


async def _publish_git_ref_to_source_control(  # noqa: PLR0911
    *,
    host_code_root: Path,
    commit_ref: str,
    branch: str,
    remote_url: str | None,
    token: str | None,
    token_env: str | None,
) -> dict[str, str | None]:
    if not host_code_root.exists():
        return {
            "status": "failed",
            "reason": f"host_code_root does not exist: {host_code_root}",
            "published_commit": None,
        }
    if not _is_safe_git_branch(branch):
        return {"status": "failed", "reason": "unsafe git branch name", "published_commit": None}

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    askpass_path: str | None = None
    if token:
        fd, askpass_path = tempfile.mkstemp(prefix="memstack-git-askpass-", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                "#!/bin/sh\n"
                'case "$1" in\n'
                "*Username*) printf '%s\\n' \"${GIT_USERNAME:-x-access-token}\" ;;\n"
                "*) printf '%s\\n' \"$GIT_TOKEN\" ;;\n"
                "esac\n"
            )
        os.chmod(askpass_path, 0o700)
        env["GIT_ASKPASS"] = askpass_path
        env["GIT_TOKEN"] = token
        env["GIT_USERNAME"] = "oauth2" if token_env == "GITLAB_TOKEN" else "x-access-token"

    try:
        exists = await _run_git_command(
            host_code_root,
            ("cat-file", "-e", f"{commit_ref}^{{commit}}"),
            env=env,
        )
        if exists["exit_code"] != "0":
            return {
                "status": "failed",
                "reason": _compact_git_error(exists),
                "published_commit": None,
            }

        dirty = await _run_git_command(host_code_root, ("status", "--porcelain"), env=env)
        if str(dirty.get("stdout") or "").strip():
            return await _publish_git_ref_from_temporary_worktree(
                host_code_root=host_code_root,
                publish_ref=commit_ref,
                branch=branch,
                remote_url=remote_url,
                env=env,
            )

        already_ancestor = await _run_git_command(
            host_code_root,
            ("merge-base", "--is-ancestor", commit_ref, "HEAD"),
            env=env,
        )
        if already_ancestor["exit_code"] != "0":
            fast_forward = await _run_git_command(
                host_code_root,
                ("merge", "--ff-only", commit_ref),
                env=env,
                timeout=120,
            )
            if fast_forward["exit_code"] != "0":
                if _is_non_fast_forward_push_rejection(
                    fast_forward
                ) or _is_unrelated_history_merge_rejection(fast_forward):
                    return await _publish_git_ref_from_temporary_worktree(
                        host_code_root=host_code_root,
                        publish_ref=commit_ref,
                        branch=branch,
                        remote_url=remote_url,
                        env=env,
                        default_reason=(
                            "published from temporary worktree after local branch "
                            "could not fast-forward to candidate"
                        ),
                    )
                return {
                    "status": "failed",
                    "reason": _compact_git_error(fast_forward),
                    "published_commit": None,
                }

        head = await _run_git_command(host_code_root, ("rev-parse", "HEAD"), env=env)
        if head["exit_code"] != "0":
            return {
                "status": "failed",
                "reason": _compact_git_error(head),
                "published_commit": None,
            }
        published_commit = str(head.get("stdout") or "").strip()
        return await _push_git_head_to_source_branch(
            host_code_root=host_code_root,
            published_commit=published_commit,
            branch=branch,
            remote_url=remote_url,
            env=env,
        )
    finally:
        if askpass_path:
            with contextlib.suppress(OSError):
                os.unlink(askpass_path)


async def _push_git_head_to_source_branch(
    *,
    host_code_root: Path,
    published_commit: str,
    branch: str,
    remote_url: str | None,
    env: Mapping[str, str],
) -> dict[str, str | None]:
    remote = remote_url or "origin"
    push = await _run_git_command(
        host_code_root,
        ("push", remote, f"HEAD:refs/heads/{branch}"),
        env=env,
        timeout=180,
    )
    if push["exit_code"] == "0":
        return {
            "status": "published",
            "reason": None,
            "published_commit": published_commit,
        }
    if _is_non_fast_forward_push_rejection(push):
        return await _publish_git_ref_from_temporary_worktree(
            host_code_root=host_code_root,
            publish_ref=published_commit,
            branch=branch,
            remote_url=remote_url,
            env=env,
            default_reason="published from temporary worktree after remote branch advanced",
        )
    return {
        "status": "failed",
        "reason": _compact_git_error(push),
        "published_commit": published_commit,
    }


async def _publish_git_ref_from_temporary_worktree(
    *,
    host_code_root: Path,
    publish_ref: str,
    branch: str,
    remote_url: str | None,
    env: Mapping[str, str],
    default_reason: str = (
        "published from temporary worktree because main checkout has uncommitted changes"
    ),
) -> dict[str, str | None]:
    temp_parent = Path(tempfile.mkdtemp(prefix="memstack-source-publish-"))
    worktree_path = temp_parent / "worktree"
    added = False
    try:
        add = await _run_git_command(
            host_code_root,
            ("worktree", "add", "--detach", str(worktree_path), publish_ref),
            env=env,
            timeout=120,
        )
        if add["exit_code"] != "0":
            return {
                "status": "failed",
                "reason": _compact_git_error(add),
                "published_commit": None,
            }
        added = True

        remote = remote_url or "origin"
        remote_merge = await _merge_remote_branch_for_publish(
            worktree_path=worktree_path,
            candidate_ref=publish_ref,
            remote=remote,
            branch=branch,
            env=env,
        )
        if remote_merge.get("status") == "failed":
            return {
                "status": "failed",
                "reason": str(remote_merge.get("reason") or "remote branch merge failed"),
                "published_commit": None,
            }

        head = await _run_git_command(worktree_path, ("rev-parse", "HEAD"), env=env)
        if head["exit_code"] != "0":
            return {
                "status": "failed",
                "reason": _compact_git_error(head),
                "published_commit": None,
            }
        published_commit = str(head.get("stdout") or "").strip()
        push = await _run_git_command(
            worktree_path,
            ("push", remote, f"HEAD:refs/heads/{branch}"),
            env=env,
            timeout=180,
        )
        if push["exit_code"] != "0":
            if _is_non_fast_forward_push_rejection(push):
                retried = await _retry_temporary_worktree_push_after_non_fast_forward(
                    worktree_path=worktree_path,
                    candidate_ref=published_commit,
                    remote=remote,
                    branch=branch,
                    env=env,
                    default_reason=default_reason,
                )
                if retried is not None:
                    return retried
            return {
                "status": "failed",
                "reason": _compact_git_error(push),
                "published_commit": published_commit,
            }
        return {
            "status": "published",
            "reason": str(remote_merge.get("reason") or default_reason),
            "published_commit": published_commit,
        }
    finally:
        if added:
            remove = await _run_git_command(
                host_code_root,
                ("worktree", "remove", "--force", str(worktree_path)),
                env=env,
                timeout=120,
            )
            if remove["exit_code"] != "0":
                logger.warning("temporary source publish worktree cleanup failed: %s", remove)
        shutil.rmtree(temp_parent, ignore_errors=True)


async def _retry_temporary_worktree_push_after_non_fast_forward(
    *,
    worktree_path: Path,
    candidate_ref: str,
    remote: str,
    branch: str,
    env: Mapping[str, str],
    default_reason: str,
) -> dict[str, str | None] | None:
    retry_merge = await _merge_remote_branch_for_publish(
        worktree_path=worktree_path,
        candidate_ref=candidate_ref,
        remote=remote,
        branch=branch,
        env=env,
    )
    if retry_merge.get("status") == "failed":
        return {
            "status": "failed",
            "reason": str(
                retry_merge.get("reason") or "remote branch merge failed after push rejection"
            ),
            "published_commit": candidate_ref,
        }
    retry_head = await _run_git_command(worktree_path, ("rev-parse", "HEAD"), env=env)
    if retry_head["exit_code"] != "0":
        return {
            "status": "failed",
            "reason": _compact_git_error(retry_head),
            "published_commit": candidate_ref,
        }
    retried_commit = str(retry_head.get("stdout") or "").strip()
    retry_push = await _run_git_command(
        worktree_path,
        ("push", remote, f"HEAD:refs/heads/{branch}"),
        env=env,
        timeout=180,
    )
    if retry_push["exit_code"] == "0":
        retry_reason = str(retry_merge.get("reason") or default_reason)
        return {
            "status": "published",
            "reason": f"{retry_reason}; retried after non-fast-forward push",
            "published_commit": retried_commit,
        }
    return None


async def _merge_remote_branch_for_publish(  # noqa: PLR0911
    *,
    worktree_path: Path,
    candidate_ref: str,
    remote: str,
    branch: str,
    env: Mapping[str, str],
) -> dict[str, str | None]:
    remote_ref = f"refs/remotes/memstack-source-publish/{branch}"
    fetch = await _run_git_command(
        worktree_path,
        ("fetch", "--no-tags", remote, f"refs/heads/{branch}:{remote_ref}"),
        env=env,
        timeout=180,
    )
    if fetch["exit_code"] != "0":
        reason = _compact_git_error(fetch)
        if "couldn't find remote ref" in reason.lower():
            return {"status": "skipped", "reason": None}
        return {"status": "failed", "reason": reason}

    remote_ancestor = await _run_git_command(
        worktree_path,
        ("merge-base", "--is-ancestor", remote_ref, "HEAD"),
        env=env,
    )
    if remote_ancestor["exit_code"] == "0":
        return {"status": "skipped", "reason": None}

    local_ancestor = await _run_git_command(
        worktree_path,
        ("merge-base", "--is-ancestor", "HEAD", remote_ref),
        env=env,
    )
    if local_ancestor["exit_code"] == "0":
        return await _merge_remote_branch_preserving_local_tree(
            worktree_path=worktree_path,
            remote_ref=remote_ref,
            env=env,
        )

    merge = await _run_git_command(
        worktree_path,
        ("merge", "--no-edit", remote_ref),
        env=env,
        timeout=120,
    )
    if merge["exit_code"] == "0":
        return await _restore_candidate_publish_paths_after_merge(
            worktree_path=worktree_path,
            candidate_ref=candidate_ref,
            remote_ref=remote_ref,
            env=env,
            reason="merged remote branch before publish",
        )

    await _run_git_command(worktree_path, ("merge", "--abort"), env=env, timeout=60)
    merged = await _merge_remote_branch_with_local_preference(
        worktree_path=worktree_path,
        remote_ref=remote_ref,
        env=env,
    )
    if merged.get("status") == "failed":
        return merged
    return await _restore_candidate_publish_paths_after_merge(
        worktree_path=worktree_path,
        candidate_ref=candidate_ref,
        remote_ref=remote_ref,
        env=env,
        reason=str(merged.get("reason") or "merged remote branch before publish"),
    )


async def _merge_remote_branch_preserving_local_tree(
    *,
    worktree_path: Path,
    remote_ref: str,
    env: Mapping[str, str],
) -> dict[str, str | None]:
    merge_ours_strategy = await _run_git_command(
        worktree_path,
        ("merge", "--no-edit", "-s", "ours", remote_ref),
        env=env,
        timeout=120,
    )
    if merge_ours_strategy["exit_code"] == "0":
        return {
            "status": "merged",
            "reason": "merged remote branch history before publish preserving candidate tree",
        }
    return {"status": "failed", "reason": _compact_git_error(merge_ours_strategy)}


async def _restore_candidate_publish_paths_after_merge(  # noqa: PLR0911
    *,
    worktree_path: Path,
    candidate_ref: str,
    remote_ref: str,
    env: Mapping[str, str],
    reason: str,
) -> dict[str, str | None]:
    paths = await _candidate_publish_restore_path_states(
        worktree_path=worktree_path,
        candidate_ref=candidate_ref,
        remote_ref=remote_ref,
        env=env,
    )
    if not paths:
        return {"status": "merged", "reason": reason}

    present_paths = tuple(path for path, present in paths if present)
    removed_paths = tuple(path for path, present in paths if not present)
    if present_paths:
        checkout = await _run_git_command(
            worktree_path,
            ("checkout", candidate_ref, "--", *present_paths),
            env=env,
            timeout=120,
        )
        if checkout["exit_code"] != "0":
            return {"status": "failed", "reason": _compact_git_error(checkout)}
    if removed_paths:
        remove = await _run_git_command(
            worktree_path,
            ("rm", "-f", "--ignore-unmatch", "--", *removed_paths),
            env=env,
            timeout=120,
        )
        if remove["exit_code"] != "0":
            return {"status": "failed", "reason": _compact_git_error(remove)}

    changed = await _run_git_command(
        worktree_path,
        ("diff", "--cached", "--quiet", "--", *tuple(path for path, _ in paths)),
        env=env,
    )
    if changed["exit_code"] == "0":
        return {"status": "merged", "reason": reason}
    if changed["exit_code"] != "1":
        return {"status": "failed", "reason": _compact_git_error(changed)}

    commit = await _run_git_command(
        worktree_path,
        ("commit", "-m", "Preserve candidate source publish paths"),
        env=env,
        timeout=120,
    )
    if commit["exit_code"] != "0":
        return {"status": "failed", "reason": _compact_git_error(commit)}
    return {
        "status": "merged",
        "reason": f"{reason}; restored candidate tree paths after merge",
    }


async def _candidate_publish_restore_path_states(
    *,
    worktree_path: Path,
    candidate_ref: str,
    remote_ref: str,
    env: Mapping[str, str],
) -> tuple[tuple[str, bool], ...]:
    return await _candidate_publish_path_states(
        worktree_path=worktree_path,
        candidate_ref=candidate_ref,
        remote_ref=remote_ref,
        env=env,
    )


async def _candidate_publish_path_states(
    *,
    worktree_path: Path,
    candidate_ref: str,
    remote_ref: str,
    env: Mapping[str, str],
) -> tuple[tuple[str, bool], ...]:
    base = await _run_git_command(
        worktree_path,
        ("merge-base", candidate_ref, remote_ref),
        env=env,
    )
    if base["exit_code"] != "0":
        return ()
    base_ref = str(base.get("stdout") or "").strip()
    if not base_ref:
        return ()
    diff = await _run_git_command(
        worktree_path,
        ("diff", "--name-status", "-z", base_ref, candidate_ref),
        env=env,
    )
    if diff["exit_code"] != "0":
        return ()
    return _parse_git_name_status_path_states(str(diff.get("stdout") or ""))


def _parse_git_name_status_path_states(raw: str) -> tuple[tuple[str, bool], ...]:
    parts = [part for part in raw.split("\0") if part]
    paths: dict[str, bool] = {}
    index = 0
    while index < len(parts):
        status = parts[index]
        index += 1
        if not status:
            continue
        code = status[0]
        if code in {"R", "C"}:
            if index + 1 >= len(parts):
                break
            old_path = parts[index]
            new_path = parts[index + 1]
            index += 2
            if code == "R" and old_path:
                paths[old_path] = False
            if new_path:
                paths[new_path] = True
            continue
        if index >= len(parts):
            break
        path = parts[index]
        index += 1
        if path:
            paths[path] = code != "D"
    return tuple(paths.items())


async def _merge_remote_branch_with_local_preference(
    *,
    worktree_path: Path,
    remote_ref: str,
    env: Mapping[str, str],
) -> dict[str, str | None]:
    merge_ours = await _run_git_command(
        worktree_path,
        ("merge", "--no-edit", "-X", "ours", remote_ref),
        env=env,
        timeout=120,
    )
    if merge_ours["exit_code"] == "0":
        return {
            "status": "merged",
            "reason": "merged remote branch before publish using local conflict preference",
        }
    if _is_unrelated_history_merge_rejection(merge_ours):
        await _run_git_command(worktree_path, ("merge", "--abort"), env=env, timeout=60)
        merge_unrelated_ours = await _run_git_command(
            worktree_path,
            ("merge", "--no-edit", "--allow-unrelated-histories", "-X", "ours", remote_ref),
            env=env,
            timeout=120,
        )
        if merge_unrelated_ours["exit_code"] == "0":
            return {
                "status": "merged",
                "reason": (
                    "merged unrelated remote branch before publish using local conflict preference"
                ),
            }
        return {"status": "failed", "reason": _compact_git_error(merge_unrelated_ours)}
    return {"status": "failed", "reason": _compact_git_error(merge_ours)}


def _is_non_fast_forward_push_rejection(result: Mapping[str, object]) -> bool:
    text = "\n".join(str(result.get(key) or "") for key in ("stdout", "stderr", "reason")).lower()
    return (
        "non-fast-forward" in text
        or "fetch first" in text
        or "updates were rejected" in text
        or "tip of your current branch is behind" in text
        or "not possible to fast-forward" in text
    )


def _is_unrelated_history_merge_rejection(result: Mapping[str, object]) -> bool:
    text = "\n".join(str(result.get(key) or "") for key in ("stdout", "stderr", "reason"))
    normalized = text.lower()
    return "refusing to merge unrelated histories" in normalized or "拒绝合并无关的历史" in text


async def _run_git_command(
    cwd: Path,
    args: tuple[str, ...],
    *,
    env: Mapping[str, str],
    timeout: int = 60,
) -> dict[str, str]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        env=dict(env),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()
        return {
            "exit_code": "124",
            "stdout": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace") or "git command timed out",
        }
    return {
        "exit_code": str(process.returncode or 0),
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
    }


def _compact_git_error(result: Mapping[str, str], *, limit: int = 1200) -> str:
    text = str(result.get("stderr") or result.get("stdout") or "").strip()
    if not text:
        text = f"git exited with {result.get('exit_code')}"
    return _manager_compact_command_output(text, limit=limit)


def _source_publish_metadata(
    *,
    status: str,
    reason: str | None,
    commit_ref: str | None,
    branch: str | None,
    source_commit_ref: str | None = None,
    token_env: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_publish_status": status,
        "source_publish_provider": "git",
    }
    if reason:
        metadata["source_publish_reason"] = reason
    if commit_ref:
        metadata["source_publish_commit_ref"] = commit_ref
    if source_commit_ref:
        metadata["source_publish_source_commit_ref"] = source_commit_ref
    if branch:
        metadata["source_publish_branch"] = branch
    if token_env:
        metadata["source_publish_token_env"] = token_env
    return metadata


def _source_publish_failure_result(
    reason: str,
    *,
    metadata: Mapping[str, Any],
) -> PipelineRunResult:
    return PipelineRunResult(
        status="failed",
        reason=reason,
        stage_results=(
            PipelineStageResult(
                stage="source_publish",
                status="failed",
                command="git:publish",
                exit_code=1,
                stdout_preview="",
                stderr_preview=reason,
                metadata={
                    "external_provider": DRONE_PROVIDER,
                    **dict(metadata),
                },
            ),
        ),
        evidence_refs=("ci_pipeline:failed", "source_publish:failed"),
        metadata={"external_provider": DRONE_PROVIDER, **dict(metadata)},
    )


async def _run_drone_pipeline(
    *,
    session: AsyncSession,
    pipeline_repo: SqlWorkspacePipelineRepository,
    plan: Plan,
    node: PlanNode,
    run: WorkspacePipelineRunModel,
    contract: PipelineContractSpec,
    workspace_id: str,
    plan_id: str,
    node_id: str,
) -> None:
    try:
        provider = await require_pipeline_provider(contract.provider)
        result = await provider.run(contract)
    except PipelineProviderUnavailableError as exc:
        logger.warning("workspace drone pipeline provider unavailable: %s", exc)
        result = _drone_provider_unavailable_result(exc)
    except Exception as exc:
        logger.exception("workspace drone pipeline provider failed")
        result = _drone_provider_exception_result(exc)
    await _persist_external_pipeline_result(
        session=session,
        pipeline_repo=pipeline_repo,
        plan=plan,
        node=node,
        run=run,
        contract=contract,
        result=result,
        workspace_id=workspace_id,
        plan_id=plan_id,
        node_id=node_id,
    )


def _drone_provider_unavailable_result(exc: PipelineProviderUnavailableError) -> PipelineRunResult:
    message = str(exc).strip() or f"pipeline provider plugin is not enabled: {DRONE_PROVIDER}"
    metadata = {
        "external_provider": DRONE_PROVIDER,
        "plugin_unavailable": True,
        "provider": exc.provider,
    }
    return PipelineRunResult(
        status="failed",
        reason=message,
        stage_results=(
            PipelineStageResult(
                stage="drone_plugin",
                status="failed",
                command="plugin:resolve",
                exit_code=1,
                stdout_preview="",
                stderr_preview=message,
                metadata=metadata,
            ),
        ),
        evidence_refs=("ci_pipeline:failed", "drone:plugin_unavailable"),
        metadata={
            **metadata,
            "provider_error": message,
        },
    )


def _drone_provider_exception_result(exc: Exception) -> PipelineRunResult:
    message = str(exc).strip() or exc.__class__.__name__
    preview = _manager_compact_command_output(
        f"Drone pipeline provider failed: {message}",
        limit=1200,
    )
    metadata = {
        "external_provider": DRONE_PROVIDER,
        "provider_exception": exc.__class__.__name__,
    }
    return PipelineRunResult(
        status="failed",
        reason=preview,
        stage_results=(
            PipelineStageResult(
                stage="drone_api",
                status="failed",
                command="drone:api",
                exit_code=1,
                stdout_preview="",
                stderr_preview=preview,
                metadata=metadata,
            ),
        ),
        evidence_refs=("ci_pipeline:failed", "drone:api_failed"),
        metadata={
            **metadata,
            "provider_error": preview,
        },
    )


async def _persist_external_pipeline_result(
    *,
    session: AsyncSession,
    pipeline_repo: SqlWorkspacePipelineRepository,
    plan: Plan,
    node: PlanNode,
    run: WorkspacePipelineRunModel,
    contract: PipelineContractSpec,
    result: PipelineRunResult,
    workspace_id: str,
    plan_id: str,
    node_id: str,
) -> None:
    for stage_result in result.stage_results:
        stage_row = await pipeline_repo.create_stage_run(
            run_id=run.id,
            workspace_id=workspace_id,
            stage=stage_result.stage,
            command=stage_result.command,
            metadata={
                "provider": contract.provider,
                **dict(stage_result.metadata or {}),
            },
        )
        await pipeline_repo.finish_stage_run(
            stage_row,
            status=stage_result.status,
            exit_code=stage_result.exit_code,
            stdout_preview=stage_result.stdout_preview,
            stderr_preview=stage_result.stderr_preview,
            log_ref=stage_result.log_ref,
            artifact_refs=list(stage_result.artifact_refs),
            metadata={
                "duration_ms_observed": stage_result.duration_ms,
                **dict(stage_result.metadata or {}),
            },
        )

    result_summary = _pipeline_result_summary(result)
    evidence_refs = list(result.evidence_refs)
    evidence_refs.append(f"pipeline_run:{result.status}:{run.id}")
    if result.external_id:
        evidence_refs.append(f"pipeline_run_external:{contract.provider}:{result.external_id}")
    result_metadata = dict(result.metadata or {})
    if result_summary and result.status != "success":
        result_metadata["pipeline_failure_summary"] = result_summary
        result_metadata["pipeline_last_summary"] = result_summary
        failed_stage = _first_failed_pipeline_stage(result.stage_results)
        if failed_stage is not None:
            result_metadata["pipeline_failed_stage"] = failed_stage.stage
    await pipeline_repo.finish_run(
        run,
        status=result.status,
        reason=result_summary,
        metadata={
            "stage_count": len(result.stage_results),
            "service_count": len(contract.services),
            **result_metadata,
        },
    )
    evidence_refs.extend(
        await _persist_external_pipeline_deployments(
            pipeline_repo=pipeline_repo,
            contract=contract,
            node=node,
            run=run,
            result=result,
            workspace_id=workspace_id,
            plan_id=plan_id,
            node_id=node_id,
        )
    )
    await _finish_pipeline_on_node(
        session=session,
        plan=plan,
        node=node,
        run_id=run.id,
        status=result.status,
        reason=result_summary,
        evidence_refs=list(dict.fromkeys(evidence_refs)),
        preview_url=result.preview_url,
        health_url=result.health_url,
    )
    await SqlWorkspacePlanOutboxRepository(session).enqueue(
        plan_id=plan_id,
        workspace_id=workspace_id,
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": workspace_id,
            "plan_id": plan_id,
            "node_id": node_id,
            "pipeline_run_id": run.id,
            "pipeline_status": result.status,
            "pipeline_external_id": result.external_id,
        },
        metadata={"source": f"workspace_plan.{contract.provider}_pipeline_run_completed"},
    )


async def _persist_external_pipeline_deployments(
    *,
    pipeline_repo: SqlWorkspacePipelineRepository,
    contract: PipelineContractSpec,
    node: PlanNode,
    run: WorkspacePipelineRunModel,
    result: PipelineRunResult,
    workspace_id: str,
    plan_id: str,
    node_id: str,
) -> list[str]:
    status = _external_pipeline_deployment_status(result)
    if contract.deploy is None or not contract.deploy.enabled or status is None:
        return []

    specs = _external_pipeline_deployment_specs(contract, result)
    if not specs:
        return []

    evidence_refs: list[str] = []
    base_metadata = {
        "pipeline_status": result.status,
        "deployment_status": result.deployment_status,
        "external_provider": contract.provider,
        "external_id": result.external_id,
        "external_url": result.external_url,
        "deploy_mode": contract.deploy.mode,
        "deploy_stage": contract.deploy.stage,
        "deploy_service_count": len(specs),
    }
    for spec in specs:
        await pipeline_repo.upsert_deployment(
            workspace_id=workspace_id,
            plan_id=plan_id,
            node_id=node_id,
            pipeline_run_id=run.id,
            provider=contract.provider,
            status=status,
            command=_external_pipeline_deployment_command(contract),
            pid=result.deployment_pid,
            port=spec["port"],
            preview_url=spec["preview_url"],
            health_url=spec["health_url"],
            rollback_ref=_pipeline_commit_ref(node),
            log_ref=result.external_url,
            service_id=spec["service_id"],
            service_name=spec["service_name"],
            service_url=spec["service_url"],
            required=bool(spec["required"]),
            metadata={
                **base_metadata,
                "deploy_service_id": spec["service_id"],
                "deploy_service_name": spec["service_name"],
            },
        )
        service_id = spec["service_id"]
        if service_id:
            evidence_refs.append(f"deployment:{service_id}:{status}")
            if spec["preview_url"]:
                evidence_refs.append(f"preview_url:{service_id}:{spec['preview_url']}")
        else:
            evidence_refs.append(f"deployment:{status}")
            if spec["preview_url"]:
                evidence_refs.append(f"preview_url:{spec['preview_url']}")
    return evidence_refs


def _external_pipeline_deployment_status(result: PipelineRunResult) -> str | None:
    deployment_status = (result.deployment_status or "").strip().lower()
    if deployment_status == "deployed":
        return "running"
    if deployment_status in {"failed", "invalid", "missing"}:
        return "failed"
    return None


def _external_pipeline_deployment_specs(
    contract: PipelineContractSpec,
    result: PipelineRunResult,
) -> list[dict[str, Any]]:
    if contract.services:
        docker_services = _external_pipeline_docker_deploy_services(contract)
        return [
            _external_pipeline_deployment_spec_for_service(
                service,
                result=result,
                docker_services=docker_services,
            )
            for service in contract.services
        ]
    return [_external_pipeline_default_deployment_spec(contract, result)]


def _external_pipeline_docker_deploy_services(
    contract: PipelineContractSpec,
) -> list[Mapping[str, Any]]:
    deploy = contract.deploy
    if deploy is None:
        return []
    raw = deploy.docker.get("deploy_services")
    if not isinstance(raw, list):
        raw = deploy.docker.get("services")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _external_pipeline_deployment_spec_for_service(
    service: PipelineServiceSpec,
    *,
    result: PipelineRunResult,
    docker_services: list[Mapping[str, Any]],
) -> dict[str, Any]:
    docker_service = _external_pipeline_docker_service_for_pipeline_service(
        service,
        docker_services,
    )
    host_port = _metadata_optional_int(
        docker_service.get("deploy_host_port") or docker_service.get("host_port")
    )
    preview_url = result.preview_url
    if preview_url is None and host_port is not None:
        preview_url = _external_pipeline_localhost_url(
            host_port=host_port,
            path=_metadata_string(docker_service.get("path_prefix")) or service.path_prefix,
            scheme=_metadata_string(docker_service.get("internal_scheme"))
            or service.internal_scheme,
        )
    health_url = (
        result.health_url
        or _metadata_string(docker_service.get("deploy_health_url"))
        or (
            _external_pipeline_localhost_url(
                host_port=host_port,
                path=_metadata_string(docker_service.get("health_path")) or service.health_path,
                scheme=_metadata_string(docker_service.get("internal_scheme"))
                or service.internal_scheme,
            )
            if host_port is not None
            else service.internal_health_url
        )
    )
    return {
        "service_id": service.service_id,
        "service_name": service.name,
        "port": host_port or service.internal_port,
        "preview_url": preview_url,
        "health_url": health_url,
        "service_url": preview_url,
        "required": service.required,
    }


def _external_pipeline_docker_service_for_pipeline_service(
    service: PipelineServiceSpec,
    docker_services: list[Mapping[str, Any]],
) -> Mapping[str, Any]:
    service_id = service.service_id.lower()
    service_name = service.name.lower()
    for item in docker_services:
        item_id = (
            _metadata_string(item.get("service_id") or item.get("id") or item.get("name")) or ""
        ).lower()
        item_name = (_metadata_string(item.get("name")) or "").lower()
        if item_id and (item_id == service_id or item_id in service_id):
            return item
        if item_name and item_name == service_name:
            return item
    return {}


def _external_pipeline_default_deployment_spec(
    contract: PipelineContractSpec,
    result: PipelineRunResult,
) -> dict[str, Any]:
    deploy = contract.deploy
    docker = deploy.docker if deploy is not None else {}
    host_port = _metadata_optional_int(docker.get("deploy_host_port") or docker.get("host_port"))
    preview_url = result.preview_url
    if preview_url is None and host_port is not None:
        preview_url = _external_pipeline_localhost_url(host_port=host_port, path="/")
    health_url = result.health_url or _metadata_string(docker.get("deploy_health_url"))
    return {
        "service_id": deploy.target if deploy is not None else None,
        "service_name": deploy.target if deploy is not None else None,
        "port": host_port,
        "preview_url": preview_url,
        "health_url": health_url,
        "service_url": preview_url,
        "required": deploy.required if deploy is not None else True,
    }


def _external_pipeline_deployment_command(contract: PipelineContractSpec) -> str:
    deploy = contract.deploy
    if deploy is None:
        return f"{contract.provider}:pipeline"
    return f"{contract.provider}:{deploy.stage}:{deploy.mode}"


def _external_pipeline_localhost_url(
    *,
    host_port: int,
    path: str,
    scheme: str = "http",
) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{scheme}://localhost:{host_port}{normalized_path}"


def _metadata_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


async def _pipeline_root_metadata(
    *,
    session: AsyncSession,
    workspace_id: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    root_task_id = (
        _payload_string(payload, ROOT_GOAL_TASK_ID)
        or _payload_string(payload, "root_goal_task_id")
        or await _resolve_root_task_id(session, workspace_id, payload)
    )
    if not root_task_id:
        return {}
    task = await SqlWorkspaceTaskRepository(session).find_by_id(root_task_id)
    if task is None or task.workspace_id != workspace_id:
        return {}
    return dict(task.metadata or {})


def _pipeline_contract_for_workspace(
    *,
    project_id: str,
    workspace_id: str,
    workspace_metadata: dict[str, Any],
    root_metadata: dict[str, Any],
) -> PipelineContractSpec:
    from src.infrastructure.agent.workspace.code_context import load_workspace_code_context

    code_context = load_workspace_code_context(
        project_id=project_id,
        root_metadata=root_metadata,
        workspace_metadata=workspace_metadata,
    )
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata=workspace_metadata,
        fallback_code_root=code_context.sandbox_code_root,
        fallback_host_code_root=code_context.host_code_root,
    )
    return _workspace_scoped_pipeline_contract(contract, workspace_id=workspace_id)


def _can_reflect_existing_pipeline_run(
    *,
    run: WorkspacePipelineRunModel,
    contract: PipelineContractSpec,
    node: PlanNode,
) -> bool:
    if run.status == "running":
        return False
    if run.status != "success":
        return False
    if _requires_drone_docker_deploy_validation(contract):
        metadata = dict(run.metadata_json or {})
        if metadata.get("deploy_validation") != DRONE_DOCKER_DEPLOY_VALIDATION:
            return False
    return not _requires_preview_deployment(contract) or _node_has_required_deployment_health(
        node,
        contract=contract,
    )


def _pipeline_run_matches_requested_commit(
    run: WorkspacePipelineRunModel,
    *,
    requested_source_commit_ref: str | None,
) -> bool:
    requested = _commit_ref_token(requested_source_commit_ref)
    if not requested:
        return True
    actual = _pipeline_run_source_commit_ref(run)
    return bool(actual and _git_commit_refs_match(actual, requested))


def _pipeline_run_source_commit_ref(run: WorkspacePipelineRunModel) -> str | None:
    metadata = dict(run.metadata_json or {})
    return _commit_ref_token(metadata.get("source_publish_source_commit_ref")) or _commit_ref_token(
        getattr(run, "commit_ref", None)
    )


def _requires_drone_docker_deploy_validation(contract: PipelineContractSpec) -> bool:
    deploy = contract.deploy
    return (
        contract.provider == DRONE_PROVIDER
        and deploy is not None
        and deploy.enabled
        and deploy.required
        and deploy.mode == "docker"
    )


_DRONE_DEPLOY_PHASES = frozenset({"deploy", "review"})


def _pipeline_contract_for_node_phase(
    contract: PipelineContractSpec,
    *,
    node: PlanNode,
) -> PipelineContractSpec:
    if contract.provider != DRONE_PROVIDER or contract.deploy is None:
        return contract
    if contract.auto_deploy and contract.deploy.required:
        return contract
    phase = _metadata_string(dict(node.metadata or {}).get("iteration_phase"))
    if phase in _DRONE_DEPLOY_PHASES:
        if not contract.deploy.enabled:
            return replace(contract, deploy=replace(contract.deploy, enabled=True))
        return contract
    provider_config = dict(contract.provider_config)
    provider_config["deploy_suppressed_for_phase"] = phase or "unknown"
    return replace(contract, deploy=None, provider_config=provider_config)


def _needs_agent_managed_pipeline_proposal(contract: PipelineContractSpec) -> bool:
    if contract.provider != SANDBOX_NATIVE_PROVIDER:
        return False
    if not contract.agent_managed or not contract.auto_deploy:
        return False
    if contract.contract_source != PLANNING_CONTRACT_SOURCE:
        return True
    return not contract.services and not contract.deploy_command and not contract.health_url


def _requires_preview_deployment(contract: PipelineContractSpec) -> bool:
    return contract.provider == SANDBOX_NATIVE_PROVIDER and contract.auto_deploy


def _node_has_required_deployment_health(
    node: PlanNode,
    *,
    contract: PipelineContractSpec,
) -> bool:
    refs = _merge_string_values(node.metadata.get("pipeline_evidence_refs"), [])
    required_service_ids = [service.service_id for service in contract.services if service.required]
    if required_service_ids:
        return all(
            f"deployment_health:passed:{service_id}" in refs for service_id in required_service_ids
        )
    return "deployment_health:passed" in refs or any(
        ref.startswith("deployment_health:passed:") for ref in refs
    )


def _workspace_scoped_pipeline_contract(
    contract: PipelineContractSpec,
    *,
    workspace_id: str,
) -> PipelineContractSpec:
    if not contract.services:
        return contract
    service_id_map = {
        service.service_id: _workspace_proxy_service_id(
            workspace_id=workspace_id,
            service_id=service.service_id,
        )
        for service in contract.services
    }
    services = tuple(
        replace(service, service_id=service_id_map[service.service_id])
        for service in contract.services
    )
    stages = tuple(
        replace(stage, service_id=service_id_map.get(stage.service_id, stage.service_id))
        if stage.service_id
        else stage
        for stage in contract.stages
    )
    return replace(contract, services=services, stages=stages)


def _workspace_proxy_service_id(*, workspace_id: str, service_id: str) -> str:
    prefix = _workspace_proxy_service_prefix(workspace_id)
    if service_id.startswith(f"{prefix}-"):
        return service_id
    fragment = re.sub(r"[^a-z0-9-]+", "-", service_id.lower()).strip("-") or "service"
    digest = hashlib.sha1(f"{workspace_id}:{service_id}".encode()).hexdigest()[:8]
    return f"{prefix}-{fragment[:24].strip('-') or 'service'}-{digest}"


def _workspace_proxy_service_prefix(workspace_id: str) -> str:
    fragment = re.sub(r"[^a-z0-9]+", "", workspace_id.lower())[:8]
    return f"ws-{fragment or 'workspace'}"


def _metadata_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _mark_pipeline_skipped(
    *,
    session: AsyncSession,
    plan: Plan,
    node: PlanNode,
    reason: str,
) -> None:
    metadata = dict(node.metadata or {})
    metadata.update(
        {
            "pipeline_status": "skipped",
            "pipeline_gate_status": "skipped",
            "pipeline_skip_reason": reason,
            "pipeline_required": False,
        }
    )
    plan.replace_node(
        replace(
            node, execution=TaskExecution.REPORTED, metadata=metadata, updated_at=datetime.now(UTC)
        )
    )
    await SqlPlanRepository(session).save(plan)


async def _suspend_plan_for_pipeline(
    *,
    session: AsyncSession,
    plan: Plan,
    node: PlanNode,
    reason: str,
) -> None:
    metadata = dict(node.metadata or {})
    metadata.update(
        {
            "pipeline_status": "suspended",
            "pipeline_gate_status": "suspended",
            "pipeline_stop_reason": reason,
        }
    )
    plan.replace_node(replace(node, execution=TaskExecution.IDLE, metadata=metadata))
    plan = replace(plan, status=PlanStatus.SUSPENDED, updated_at=datetime.now(UTC))
    await SqlPlanRepository(session).save(plan)


async def _reflect_existing_pipeline_run(
    *,
    session: AsyncSession,
    plan: Plan,
    node: PlanNode,
    run_id: str,
    status: str,
) -> None:
    metadata = dict(node.metadata or {})
    now = datetime.now(UTC)
    run = await session.get(WorkspacePipelineRunModel, run_id)
    if run is not None:
        metadata.update(_pipeline_node_metadata_projection(dict(run.metadata_json or {})))
    metadata.update(
        {
            "pipeline_run_id": run_id,
            "pipeline_status": status,
            "pipeline_gate_status": status,
        }
    )
    intent = node.intent
    execution = node.execution
    if status == "success":
        metadata["pipeline_evidence_refs"] = _merge_string_values(
            metadata.get("pipeline_evidence_refs"),
            ["ci_pipeline:passed", f"pipeline_run:success:{run_id}"],
        )
        metadata.update(
            {
                "last_verification_summary": "harness-native CI/CD pipeline passed",
                "last_verification_passed": True,
                "last_verification_hard_fail": False,
                "last_verification_ran_at": now.isoformat().replace("+00:00", "Z"),
            }
        )
        intent, execution = _pipeline_completion_node_state(node=node, status=status)
    plan.replace_node(
        replace(node, intent=intent, execution=execution, metadata=metadata, updated_at=now)
    )
    await SqlPlanRepository(session).save(plan)


async def _mark_pipeline_running(
    *,
    session: AsyncSession,
    plan: Plan,
    node: PlanNode,
    run_id: str,
) -> None:
    metadata = dict(node.metadata or {})
    metadata.update(
        {
            "pipeline_run_id": run_id,
            "pipeline_status": "running",
            "pipeline_gate_status": "running",
            "pipeline_started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    plan.replace_node(replace(node, execution=TaskExecution.IDLE, metadata=metadata))
    await SqlPlanRepository(session).save(plan)


async def _finish_pipeline_on_node(
    *,
    session: AsyncSession,
    plan: Plan,
    node: PlanNode,
    run_id: str,
    status: str,
    reason: str | None,
    evidence_refs: list[str],
    preview_url: str | None,
    health_url: str | None,
) -> None:
    metadata = dict(node.metadata or {})
    finished_at = datetime.now(UTC)
    summary = reason or "harness-native CI/CD pipeline passed"
    run = await session.get(WorkspacePipelineRunModel, run_id)
    if run is not None:
        metadata.update(_pipeline_node_metadata_projection(dict(run.metadata_json or {})))
    metadata.update(
        {
            "pipeline_run_id": run_id,
            "pipeline_status": status,
            "pipeline_gate_status": status,
            "pipeline_finished_at": finished_at.isoformat().replace("+00:00", "Z"),
            "pipeline_last_summary": summary,
            "pipeline_evidence_refs": _merge_string_values(
                metadata.get("pipeline_evidence_refs"),
                evidence_refs,
            ),
            "execution_verifications": _merge_string_values(
                metadata.get("execution_verifications"),
                evidence_refs,
            ),
            "evidence_refs": _merge_string_values(metadata.get("evidence_refs"), evidence_refs),
        }
    )
    if preview_url:
        metadata["preview_url"] = preview_url
    if health_url:
        metadata["health_url"] = health_url
    if status == "success":
        metadata.update(
            {
                "last_verification_summary": summary,
                "last_verification_passed": True,
                "last_verification_hard_fail": False,
                "last_verification_ran_at": finished_at.isoformat().replace("+00:00", "Z"),
            }
        )
        metadata.pop("pipeline_stop_reason", None)
    intent, execution = _pipeline_completion_node_state(node=node, status=status)
    plan.replace_node(
        replace(
            node,
            intent=intent,
            execution=execution,
            metadata=metadata,
            updated_at=finished_at,
        )
    )
    await SqlPlanRepository(session).save(plan)
    if status == "success":
        await _project_pipeline_success_to_workspace_task(
            session=session,
            node=node,
            run_id=run_id,
            summary=summary,
            evidence_refs=evidence_refs,
            now=finished_at,
        )


def _pipeline_node_metadata_projection(run_metadata: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, value in run_metadata.items():
        if key.startswith("source_publish_"):
            projected[key] = value
    for key in (
        "deploy_mode",
        "deploy_validation",
        "deployment_status",
        "external_id",
        "external_provider",
        "external_url",
        "pipeline_failed_stage",
        "pipeline_failure_summary",
        "pipeline_last_summary",
    ):
        if key in run_metadata:
            projected[key] = run_metadata[key]
    return projected


def _pipeline_result_summary(result: PipelineRunResult) -> str:
    if result.status == "success":
        return result.reason or "harness-native CI/CD pipeline passed"

    failed_stage = _first_failed_pipeline_stage(result.stage_results)
    if failed_stage is None:
        return result.reason or "harness-native CI/CD pipeline failed"

    parts = [result.reason or "harness-native CI/CD pipeline failed"]
    stage_label = f"failing stage {failed_stage.stage}"
    if failed_stage.exit_code is not None:
        stage_label += f" exited {failed_stage.exit_code}"
    parts.append(stage_label)
    stage_preview = _pipeline_stage_failure_preview(failed_stage)
    if stage_preview:
        parts.append(stage_preview)
    return _compact_pipeline_failure_text("; ".join(parts), limit=1800)


def _first_failed_pipeline_stage(
    stage_results: Iterable[PipelineStageResult],
) -> PipelineStageResult | None:
    for stage_result in stage_results:
        if not stage_result.passed:
            return stage_result
    return None


def _pipeline_stage_failure_preview(stage_result: PipelineStageResult) -> str:
    previews = []
    drone_error = stage_result.metadata.get("drone_error")
    if isinstance(drone_error, str) and drone_error.strip():
        previews.append(drone_error.strip())
    preview = (stage_result.stderr_preview or stage_result.stdout_preview or "").strip()
    if preview and preview not in previews:
        previews.append(preview)
    if not previews:
        return ""
    return _compact_pipeline_failure_text("; ".join(previews), limit=1200)


def _compact_pipeline_failure_text(value: str, *, limit: int) -> str:
    compacted = value.strip().replace("\n", "\\n")
    if len(compacted) <= limit:
        return compacted
    marker = "...[truncated]..."
    head_size = max(1, (limit - len(marker)) // 2)
    tail_size = max(1, limit - len(marker) - head_size)
    return f"{compacted[:head_size]}{marker}{compacted[-tail_size:]}"


async def _project_pipeline_success_to_workspace_task(
    *,
    session: AsyncSession,
    node: PlanNode,
    run_id: str,
    summary: str,
    evidence_refs: list[str],
    now: datetime,
) -> None:
    attempt_id = node.current_attempt_id
    if attempt_id:
        attempt = await session.get(WorkspaceTaskSessionAttemptModel, attempt_id)
        if attempt is not None:
            attempt.status = WorkspaceTaskSessionAttemptStatus.ACCEPTED.value
            attempt.leader_feedback = summary or "pipeline gate passed"
            attempt.adjudication_reason = "pipeline_gate_passed"
            attempt.completed_at = now
            attempt.updated_at = now

    if not node.workspace_task_id:
        return
    task = await session.get(WorkspaceTaskModel, node.workspace_task_id)
    if task is None:
        return
    run = await session.get(WorkspacePipelineRunModel, run_id)
    commit_ref = (
        _metadata_string(getattr(run, "commit_ref", None)) if run is not None else None
    ) or _pipeline_commit_ref(node)
    projected_refs = list(evidence_refs)
    if commit_ref:
        projected_refs.append(f"commit_ref:{commit_ref}")
    metadata = dict(node.metadata or {})
    git_diff_summary = _metadata_string(metadata.get("verified_git_diff_summary"))
    test_commands = list(_iter_config_strings(metadata.get("verified_test_commands")))
    await _project_verification_to_task(
        db=session,
        task=task,
        attempt_id=attempt_id,
        passed=True,
        hard_fail=False,
        summary=summary or "pipeline gate passed",
        evidence_refs=list(dict.fromkeys(projected_refs)),
        commit_ref=commit_ref,
        git_diff_summary=git_diff_summary,
        test_commands=test_commands,
        now=now,
    )


def _pipeline_completion_node_state(
    *,
    node: PlanNode,
    status: str,
) -> tuple[TaskIntent, TaskExecution]:
    if status != "success":
        return TaskIntent.IN_PROGRESS, TaskExecution.REPORTED
    phase = _metadata_string(dict(node.metadata or {}).get("iteration_phase"))
    if phase in {"test", "deploy", "review"} or node.current_attempt_id:
        return TaskIntent.DONE, TaskExecution.IDLE
    return TaskIntent.IN_PROGRESS, TaskExecution.REPORTED


def _pipeline_commit_ref(
    node: PlanNode,
    *,
    current_attempt: WorkspaceTaskSessionAttemptModel | None = None,
) -> str | None:
    metadata = dict(node.metadata or {})
    candidates = (
        _current_attempt_candidate_commit_ref(node, current_attempt),
        _current_attempt_report_commit_ref(node, metadata=metadata),
        _integration_commit_ref_from_metadata(metadata),
        _first_prefixed_ref(
            _merge_string_values(metadata.get("accepted_repair_evidence_refs"), []),
            "commit_ref:",
        ),
    )
    for candidate in candidates:
        if candidate:
            return candidate
    feature = node.feature_checkpoint
    if feature is not None and feature.commit_ref:
        return feature.commit_ref
    return _first_prefixed_ref(
        _merge_string_values(metadata.get("evidence_refs"), []), "commit_ref:"
    )


def _pipeline_run_commit_ref(
    contract: PipelineContractSpec,
    *,
    node: PlanNode,
    current_attempt: WorkspaceTaskSessionAttemptModel | None = None,
    attempt_id: str | None,
) -> str | None:
    contract_ref = _pipeline_contract_commit_ref(contract)
    if contract_ref:
        return contract_ref
    if not attempt_id:
        return None
    return _pipeline_commit_ref(node, current_attempt=current_attempt)


def _current_attempt_candidate_commit_ref(
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttemptModel | None,
) -> str | None:
    current_attempt_id = str(node.current_attempt_id or "").strip()
    if not current_attempt_id or attempt is None or str(attempt.id) != current_attempt_id:
        return None
    verification_refs = _attempt_list_field(
        attempt,
        domain_field="candidate_verifications",
        model_field="candidate_verifications_json",
    )
    artifact_refs = _attempt_list_field(
        attempt,
        domain_field="candidate_artifacts",
        model_field="candidate_artifacts_json",
    )
    return _preferred_report_commit_ref(
        verification_refs=verification_refs,
        artifact_refs=artifact_refs,
        summary=getattr(attempt, "candidate_summary", None),
    )


def _preferred_report_commit_ref(
    *,
    verification_refs: list[str],
    artifact_refs: list[str],
    summary: object = None,
) -> str | None:
    verification_commits = _prefixed_ref_values(verification_refs, "commit_ref:")
    artifact_commits = _prefixed_ref_values(artifact_refs, "commit_ref:")
    summary_commit = _summary_report_commit_ref(
        summary,
        candidates=[*verification_commits, *artifact_commits],
    )
    if summary_commit:
        return summary_commit
    if len(verification_commits) > 1:
        return verification_commits[-1]
    if len(artifact_commits) > 1:
        return artifact_commits[-1]
    if verification_commits:
        return verification_commits[-1]
    if artifact_commits:
        return artifact_commits[-1]
    return None


def _summary_report_commit_ref(
    summary: object,
    *,
    candidates: list[str],
) -> str | None:
    if not isinstance(summary, str) or not candidates:
        return None
    candidate_by_lower = {candidate.lower(): candidate for candidate in candidates}
    matching_tokens = [
        match.group(1).lower()
        for match in re.finditer(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{7,40})(?![0-9A-Fa-f])", summary)
        if match.group(1).lower() in candidate_by_lower
    ]
    if not matching_tokens:
        return None
    return candidate_by_lower[matching_tokens[-1]]


def _prefixed_ref_values(refs: list[str], prefix: str) -> list[str]:
    values: list[str] = []
    for ref in refs:
        value = _prefixed_ref(ref, prefix)
        if value:
            values.append(value)
    return values


def _current_attempt_report_commit_ref(
    node: PlanNode,
    *,
    metadata: Mapping[str, object],
) -> str | None:
    current_attempt_id = str(node.current_attempt_id or "").strip()
    if not current_attempt_id and node.execution is not TaskExecution.REPORTED:
        return None
    report_attempt_id = str(metadata.get("last_worker_report_attempt_id") or "").strip()
    if current_attempt_id and report_attempt_id and report_attempt_id != current_attempt_id:
        return None
    if (
        current_attempt_id
        and not report_attempt_id
        and node.execution is not TaskExecution.REPORTED
    ):
        return None
    verification_refs: list[str] = []
    for key in (
        "candidate_verifications",
        "last_worker_report_verifications",
    ):
        verification_refs.extend(_merge_string_values(metadata.get(key), []))
    artifact_refs: list[str] = []
    for key in (
        "candidate_artifacts",
        "last_worker_report_artifacts",
    ):
        artifact_refs.extend(_merge_string_values(metadata.get(key), []))
    return _preferred_report_commit_ref(
        verification_refs=verification_refs,
        artifact_refs=artifact_refs,
        summary=metadata.get("last_worker_report_summary"),
    )


def _pipeline_contract_commit_ref(contract: PipelineContractSpec) -> str | None:
    value = contract.provider_config.get("commit")
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _register_pipeline_service_preview(
    *,
    project_id: str,
    sandbox_runner: _WorkspaceSandboxCommandRunner,
    redis_client: redis.Redis | None,
    service: PipelineServiceSpec,
) -> tuple[str, str | None, str]:
    """Register a pipeline-managed service with the sandbox HTTP proxy."""
    from src.infrastructure.adapters.primary.web.routers import project_sandbox

    sandbox_id, adapter = await sandbox_runner.ensure_sandbox()
    sandbox_ip = await project_sandbox._resolve_sandbox_container_ip(adapter, sandbox_id)
    service_url = (
        f"{service.internal_scheme}://{sandbox_ip}:{service.internal_port}{service.path_prefix}"
    )
    preview_url = project_sandbox._build_http_preview_proxy_url(project_id, service.service_id)
    ws_preview_url = project_sandbox._build_http_preview_ws_proxy_url(
        project_id,
        service.service_id,
    )
    now_iso = datetime.now(UTC).isoformat()
    restart_token = str(int(datetime.now(UTC).timestamp() * 1000))
    service_info = project_sandbox.HttpServiceProxyInfo(
        service_id=service.service_id,
        name=service.name,
        source_type=project_sandbox.HttpServiceSourceType.SANDBOX_INTERNAL,
        status="running",
        service_url=service_url,
        preview_url=preview_url,
        ws_preview_url=ws_preview_url,
        sandbox_id=sandbox_id,
        auto_open=service.auto_open,
        restart_token=restart_token,
        updated_at=now_iso,
    )
    await project_sandbox._upsert_http_service(project_id, service_info, redis_client)
    return preview_url, ws_preview_url, service_url


def _required_services_healthy(
    services: Iterable[PipelineServiceSpec],
    service_status: Mapping[str, str],
) -> bool:
    required_services = [service for service in services if service.required]
    if not required_services:
        return False
    return all(service_status.get(service.service_id) == "healthy" for service in required_services)


def _pipeline_preview_url(health_url: str | None, port: int | None) -> str | None:
    if health_url:
        return health_url
    _ = port
    return None


def _merge_string_values(existing: object, values: Iterable[str]) -> list[str]:
    output: list[str] = []
    if isinstance(existing, str) and existing:
        output.append(existing)
    elif isinstance(existing, Iterable) and not isinstance(existing, (bytes, dict)):
        output.extend(str(item) for item in existing if item)
    output.extend(str(item) for item in values if item)
    return list(dict.fromkeys(output))


def _first_int(value: str) -> int | None:
    match = re.search(r"\b(\d+)\b", value)
    return int(match.group(1)) if match else None


async def _attach_handoff_to_plan_node(
    *,
    session: AsyncSession,
    plan_id: str,
    node_id: str,
    task: WorkspaceTask,
    attempt: WorkspaceTaskSessionAttempt,
    worker_agent_id: str,
    worker_binding_id: str,
    handoff: HandoffPackage,
) -> PlanNode | None:
    plan = await SqlPlanRepository(session).get(plan_id)
    if plan is None:
        return None
    node = plan.nodes.get(PlanNodeId(node_id))
    if node is None:
        return None

    node.workspace_task_id = task.id
    node.current_attempt_id = attempt.id
    node.assignee_agent_id = worker_agent_id
    node.intent = TaskIntent.IN_PROGRESS
    node.execution = TaskExecution.RUNNING
    node.handoff_package = handoff
    node.metadata = {
        **_clear_stale_attempt_metadata(node.metadata or {}),
        "workspace_task_id": task.id,
        WORKSPACE_AGENT_BINDING_ID: worker_binding_id,
    }
    _apply_attempt_worktree_checkpoint(node, attempt.id)
    plan.replace_node(node)
    await SqlPlanRepository(session).save(plan)
    return node


def _build_handoff_package(
    *,
    event_type: str,
    payload: Mapping[str, Any],
    task: WorkspaceTask,
    metadata: Mapping[str, Any],
) -> HandoffPackage:
    summary = (
        _payload_string(payload, "summary")
        or _mapping_string(metadata, LAST_WORKER_REPORT_SUMMARY)
        or f"Resume workspace task after {event_type}."
    )
    previous_attempt_id = _payload_string(payload, "previous_attempt_id")
    completed_steps = [
        value
        for value in (
            f"previous_attempt_id={previous_attempt_id}" if previous_attempt_id else None,
            f"last_report={_mapping_string(metadata, 'last_worker_report_type')}"
            if _mapping_string(metadata, "last_worker_report_type")
            else None,
        )
        if value
    ]
    return HandoffPackage(
        reason=_handoff_reason_for_event(event_type, _payload_string(payload, "reason")),
        summary=summary,
        completed_steps=tuple(completed_steps),
        next_steps=(
            "Inspect the checkpoint, existing worktree, recent git status, and any prior diff.",
            "Continue from the durable plan node and report completion with evidence.",
        ),
        changed_files=tuple(_prefixed_metadata_values(metadata, "changed_file:")),
        git_head=_first_prefixed_metadata_value(metadata, "commit_ref:"),
        git_diff_summary=_first_prefixed_metadata_value(metadata, "git_diff_summary:") or "",
        test_commands=tuple(_known_test_commands(metadata)),
        verification_notes=_verification_notes(metadata) or "",
    )


def _handoff_reason_for_event(event_type: str, raw_reason: str | None) -> HandoffReason:
    if raw_reason:
        with contextlib.suppress(ValueError):
            return HandoffReason(raw_reason)
    if event_type == ATTEMPT_RETRY_EVENT:
        return HandoffReason.RETRY
    return HandoffReason.WORKER_RESTART


def _handoff_only_brief(handoff: HandoffPackage) -> str:
    lines = [
        "[handoff-package]",
        f"reason={handoff.reason.value}",
        f"created_at={handoff.created_at.isoformat()}",
        f"summary={handoff.summary}",
    ]
    lines.extend(f"completed_step={step}" for step in handoff.completed_steps)
    lines.extend(f"next_step={step}" for step in handoff.next_steps)
    lines.extend(f"changed_file={path}" for path in handoff.changed_files)
    lines.extend(f"test_command={command}" for command in handoff.test_commands)
    lines.append("[/handoff-package]")
    lines.extend(_rehydration_guidance_lines())
    return "\n".join(lines)


def _prefixed_metadata_values(metadata: Mapping[str, Any], prefix: str) -> list[str]:
    return [
        value.removeprefix(prefix)
        for value in _metadata_string_values(metadata, "evidence_refs")
        if value.startswith(prefix)
    ]


def _first_prefixed_metadata_value(metadata: Mapping[str, Any], prefix: str) -> str | None:
    for value in _metadata_string_values(metadata, "evidence_refs"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return None


def _known_test_commands(metadata: Mapping[str, Any]) -> list[str]:
    commands: list[str] = []
    commands.extend(_metadata_string_values(metadata, "verification_commands"))
    commands.extend(
        value.removeprefix("test_run:")
        for value in _metadata_string_values(metadata, "execution_verifications")
        if value.startswith("test_run:")
    )
    feature = metadata.get("feature_checkpoint")
    if isinstance(feature, Mapping):
        commands.extend(_iter_config_strings(feature.get("test_commands")))
    return list(dict.fromkeys(command for command in commands if command))


def _verification_notes(metadata: Mapping[str, Any]) -> str | None:
    verifications = _metadata_string_values(metadata, "execution_verifications")
    if not verifications:
        return None
    return "; ".join(verifications[:8])


def _metadata_string_values(metadata: Mapping[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


async def _worker_launch_worktree_context(
    preparer: WorktreePreparer,
    *,
    session: AsyncSession,
    workspace_id: str,
    task: WorkspaceTask,
    extra_instructions: str | None,
    attempt_id: str | None,
) -> AttemptWorktreeContext | None:
    try:
        result = await preparer(session, workspace_id, task, extra_instructions, attempt_id)
        return _coerce_worktree_prepare_result(result, attempt_id=attempt_id)
    except Exception as exc:
        logger.warning(
            "workspace_plan.worker_launch.worktree_prepare_failed",
            extra={
                "event": "workspace_plan.worker_launch.worktree_prepare_failed",
                "workspace_id": workspace_id,
                "task_id": task.id,
                "attempt_id": attempt_id,
            },
            exc_info=True,
        )
        return AttemptWorktreeContext(
            workspace_root=None,
            sandbox_code_root=None,
            active_root=None,
            worktree_path=None,
            branch_name=None,
            base_ref=None,
            attempt_id=attempt_id,
            is_isolated=False,
            setup_status="failed",
            setup_reason=f"preparer raised: {exc}",
        )


def _coerce_worktree_prepare_result(
    result: str | AttemptWorktreeContext | None,
    *,
    attempt_id: str | None,
) -> AttemptWorktreeContext | None:
    if result is None or isinstance(result, AttemptWorktreeContext):
        return result
    fields = _worktree_setup_note_fields(result)
    status = fields.get("status")
    if not status:
        return None
    worktree_path = fields.get("worktree_path")
    active_root = posixpath.normpath(worktree_path) if worktree_path else None
    return AttemptWorktreeContext(
        workspace_root=None,
        sandbox_code_root=None,
        active_root=active_root,
        worktree_path=active_root,
        branch_name=fields.get("branch_name"),
        base_ref=fields.get("base_ref"),
        attempt_id=attempt_id,
        is_isolated=bool(active_root),
        setup_status=status,
        setup_reason=fields.get("reason"),
        setup_output=fields.get("output"),
        original_base_ref=fields.get("original_base_ref"),
        resolved_base_ref=fields.get("resolved_base_ref"),
        fallback_reason=fields.get("fallback_reason"),
        git_fsck_summary=fields.get("git_fsck_summary"),
        pruned_worktrees_count=_worktree_note_int(fields.get("pruned_worktrees_count")),
    )


def _worktree_setup_note_fields(note: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in note.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def _worktree_note_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


async def _persist_worker_launch_worktree_context(
    *,
    session: AsyncSession,
    task: WorkspaceTask,
    context: AttemptWorktreeContext | None,
) -> None:
    if context is None:
        return
    task_model = await session.get(WorkspaceTaskModel, task.id)
    if task_model is None:
        return
    metadata = dict(task_model.metadata_json or {})
    metadata.update(context.metadata_patch())
    task_model.metadata_json = metadata
    task_model.updated_at = datetime.now(UTC)
    task.metadata = metadata


async def _block_task_for_worktree_setup_failure(
    *,
    session: AsyncSession,
    task: WorkspaceTask,
    context: AttemptWorktreeContext,
    attempt_id: str | None = None,
    plan_id: str | None = None,
    node_id: str | None = None,
) -> None:
    task_model = await session.get(WorkspaceTaskModel, task.id)
    if task_model is None:
        return
    reason = context.setup_reason or "attempt worktree setup failed"
    summary = f"worktree_setup_failed: {reason}"
    metadata = dict(task_model.metadata_json or {})
    metadata.update(context.metadata_patch())
    metadata["launch_state"] = "worktree_setup_failed"
    metadata["last_attempt_status"] = WorkspaceTaskSessionAttemptStatus.BLOCKED.value
    if attempt_id:
        metadata[CURRENT_ATTEMPT_ID] = attempt_id
    task_model.metadata_json = metadata
    task_model.status = WorkspaceTaskStatus.BLOCKED.value
    task_model.blocker_reason = summary
    task_model.updated_at = datetime.now(UTC)
    task.metadata = metadata
    task.status = WorkspaceTaskStatus.BLOCKED
    task.blocker_reason = task_model.blocker_reason

    if attempt_id:
        attempt = await session.get(WorkspaceTaskSessionAttemptModel, attempt_id)
        if attempt is not None:
            attempt.status = WorkspaceTaskSessionAttemptStatus.BLOCKED.value
            attempt.leader_feedback = summary
            attempt.adjudication_reason = "worktree_setup_failed"
            attempt.completed_at = datetime.now(UTC)
            attempt.updated_at = attempt.completed_at

    if plan_id and node_id:
        plan_repo = SqlPlanRepository(session)
        plan = await plan_repo.get(plan_id)
        node = plan.nodes.get(PlanNodeId(node_id)) if plan is not None else None
        if plan is not None and node is not None:
            node_metadata = dict(node.metadata or {})
            node_metadata.update(context.metadata_patch())
            node_metadata["worktree_setup_failure_summary"] = summary
            node_metadata["last_attempt_status"] = WorkspaceTaskSessionAttemptStatus.BLOCKED.value
            if attempt_id:
                node_metadata["terminal_attempt_status"] = (
                    WorkspaceTaskSessionAttemptStatus.BLOCKED.value
                )
                node_metadata["terminal_attempt_reconciled_at"] = (
                    datetime.now(UTC).isoformat().replace("+00:00", "Z")
                )
            plan.replace_node(
                replace(
                    node,
                    intent=TaskIntent.BLOCKED,
                    execution=TaskExecution.IDLE,
                    current_attempt_id=None,
                    metadata=node_metadata,
                    updated_at=datetime.now(UTC),
                )
            )
            await plan_repo.save(plan)


def _append_launch_instruction_note(instructions: str | None, note: str | None) -> str | None:
    if not note:
        return instructions
    if not instructions:
        return note.strip()
    return f"{instructions.rstrip()}\n\n{note.strip()}"


async def _prepare_attempt_worktree_if_available(
    session: AsyncSession,
    workspace_id: str,
    task: WorkspaceTask,
    _extra_instructions: str | None,
    attempt_id: str | None,
) -> str | None:
    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    preparation_agent = (
        WorkspaceWorktreeAgentPreparer(
            tenant_id=workspace.tenant_id,
            project_id=workspace.project_id,
        )
        if workspace is not None
        else None
    )
    context = await WorkspaceWorktreeManager(
        session,
        runner_factory=_WorkspaceSandboxCommandRunner,
        preparation_agent=preparation_agent,
    ).prepare_attempt(
        workspace_id=workspace_id,
        task=task,
        attempt_id=attempt_id,
    )
    return context.setup_note() if context is not None else None


def _default_attempt_worktree_path(*, sandbox_code_root: str, attempt_id: str) -> str:
    return _manager_default_attempt_worktree_path(
        sandbox_code_root=sandbox_code_root,
        attempt_id=attempt_id,
    )


async def _active_attempt_worktree_names(  # pyright: ignore[reportUnusedFunction]
    session: AsyncSession, workspace_id: str
) -> tuple[str, ...]:
    rows = await session.execute(
        select(WorkspaceTaskSessionAttemptModel.id)
        .where(WorkspaceTaskSessionAttemptModel.workspace_id == workspace_id)
        .where(
            WorkspaceTaskSessionAttemptModel.status.in_(
                [
                    WorkspaceTaskSessionAttemptStatus.PENDING.value,
                    WorkspaceTaskSessionAttemptStatus.RUNNING.value,
                    WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value,
                ]
            )
        )
    )
    return tuple(sorted(str(row[0]) for row in rows.all() if row[0]))


def _worktree_setup_command(  # pyright: ignore[reportUnusedFunction]
    *,
    sandbox_code_root: str,
    worktree_path: str,
    branch_name: str,
    base_ref: str,
    protected_worktree_names: Iterable[str] = (),
) -> str:
    return _manager_worktree_setup_command(
        sandbox_code_root=sandbox_code_root,
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
        protected_worktree_names=protected_worktree_names,
    )


def _worktree_setup_note(  # pyright: ignore[reportUnusedFunction]
    *,
    status: str,
    reason: str | None = None,
    output: str | None = None,
    worktree_path: str | None = None,
    branch_name: str | None = None,
    base_ref: str | None = None,
) -> str:
    return _manager_worktree_setup_note(
        status=status,
        reason=reason,
        output=output,
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
    )


def _compact_command_output(value: str, *, limit: int = 1000) -> str:
    return _manager_compact_command_output(value, limit=limit)


async def _ensure_root_started_for_dispatch(
    *,
    task_service: WorkspaceTaskService,
    command_service: WorkspaceTaskCommandService,
    workspace_id: str,
    root_task_id: str,
    actor_user_id: str,
    leader_agent_id: str,
) -> None:
    root_task = await task_service.get_task(
        workspace_id=workspace_id,
        task_id=root_task_id,
        actor_user_id=actor_user_id,
    )
    if root_task.status is not WorkspaceTaskStatus.TODO:
        return
    _ = await command_service.start_task(
        workspace_id=workspace_id,
        task_id=root_task.id,
        actor_user_id=actor_user_id,
        actor_type="agent",
        actor_agent_id=leader_agent_id,
        reason="workspace_plan.dispatch.start_root",
        authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
    )


async def _project_dispatch_attempt_to_task(
    *,
    command_service: WorkspaceTaskCommandService,
    workspace_id: str,
    actor_user_id: str,
    task: WorkspaceTask,
    attempt: WorkspaceTaskSessionAttempt,
    worker_agent_id: str,
    worker_binding_id: str,
    leader_agent_id: str,
    plan_metadata: Mapping[str, object] | None = None,
) -> WorkspaceTask:
    """Synchronize a durable dispatch onto the workspace task projection.

    Durable V2 is the source of truth, while the blackboard UI reads projected
    ``WorkspaceTask`` rows. Project the running attempt before
    the async worker launcher fills in conversation details so dispatched work
    never appears stuck at TODO.
    """

    metadata_patch: dict[str, object] = {
        **dict(plan_metadata or {}),
        CURRENT_ATTEMPT_ID: attempt.id,
        "current_attempt_number": attempt.attempt_number,
        "current_attempt_worker_agent_id": worker_agent_id,
        CURRENT_ATTEMPT_WORKER_BINDING_ID: worker_binding_id,
        "last_attempt_status": WorkspaceTaskSessionAttemptStatus.RUNNING.value,
        "launch_state": "scheduled",
        EXECUTION_STATE: _build_dispatch_execution_state(actor_id=leader_agent_id),
    }
    task_status = task.status.value
    target_status = WorkspaceTaskStatus.IN_PROGRESS if task_status != "done" else None
    return await command_service.update_task(
        workspace_id=workspace_id,
        task_id=task.id,
        actor_user_id=actor_user_id,
        status=target_status,
        metadata=metadata_patch,
        actor_type="agent",
        actor_agent_id=leader_agent_id,
        workspace_agent_binding_id=worker_binding_id,
        reason="workspace_plan.dispatch.project_attempt",
        authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
    )


def _make_sql_attempt_context(session: AsyncSession) -> AttemptContextProvider:
    async def _attempt_context(workspace_id: str, node: PlanNode) -> VerificationContext:
        stdout = ""
        artifacts: dict[str, Any] = {}
        sandbox: _WorkspaceSandboxCommandRunner | None = None
        workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
        if workspace is not None and getattr(workspace, "project_id", None):
            sandbox = _WorkspaceSandboxCommandRunner(
                project_id=workspace.project_id,
                tenant_id=getattr(workspace, "tenant_id", None),
                allowed_commands=_node_allowed_sandbox_commands(node),
            )
        if node.workspace_task_id:
            task = await SqlWorkspaceTaskRepository(session).find_by_id(node.workspace_task_id)
            if task is not None:
                stdout, artifacts = _extract_task_evidence(
                    task,
                    current_attempt_id=node.current_attempt_id,
                )

        if node.current_attempt_id:
            attempt = await SqlWorkspaceTaskSessionAttemptRepository(session).find_by_id(
                node.current_attempt_id
            )
            if attempt is not None:
                stdout = attempt.candidate_summary or stdout
                if attempt.candidate_artifacts:
                    artifacts["candidate_artifacts"] = list(attempt.candidate_artifacts)
                if attempt.candidate_verifications:
                    artifacts["candidate_verifications"] = list(attempt.candidate_verifications)

        return VerificationContext(
            workspace_id=workspace_id,
            node=node,
            attempt_id=node.current_attempt_id,
            artifacts=artifacts,
            stdout=stdout,
            sandbox=sandbox,
        )

    return _attempt_context


class _WorkspaceSandboxCommandRunner:
    """Small adapter that lets durable criteria run commands in the project sandbox."""

    def __init__(
        self,
        *,
        project_id: str,
        tenant_id: str | None = None,
        allowed_commands: set[str] | None = None,
    ) -> None:
        self._project_id = project_id
        self._tenant_id = tenant_id
        self._allowed_commands = allowed_commands

    async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
        if not self._command_allowed(command):
            return {
                "exit_code": 126,
                "stdout": "",
                "stderr": f"command not allowed by workspace harness: {command}",
            }
        sandbox_id, adapter = await self.ensure_sandbox()
        raw = await adapter.call_tool(
            sandbox_id,
            "bash",
            {
                "command": command,
                "timeout": timeout,
            },
            timeout=float(timeout) + 5.0,
        )
        text = _normalize_sandbox_no_output_text(_tool_result_text(raw))
        is_error = bool(raw.get("is_error") or raw.get("isError"))
        return {
            "exit_code": 1 if is_error else 0,
            "stdout": "" if is_error else text,
            "stderr": text if is_error else "",
        }

    async def ensure_sandbox(self) -> tuple[str, MCPSandboxAdapter]:
        from src.infrastructure.agent.state.agent_worker_state import (
            _resolve_project_sandbox_id,
            get_mcp_sandbox_adapter,
            set_mcp_sandbox_adapter,
        )

        adapter = get_mcp_sandbox_adapter()
        if adapter is None:
            adapter = await _api_process_sandbox_adapter()
            set_mcp_sandbox_adapter(adapter)
        sandbox_id = await _resolve_project_sandbox_id(
            self._project_id,
            tenant_id=self._tenant_id,
        )
        if not sandbox_id:
            sandbox_id = await _ensure_project_sandbox_for_runner(
                project_id=self._project_id,
                tenant_id=self._tenant_id,
                adapter=adapter,
            )
        if not sandbox_id:
            raise RuntimeError(f"no sandbox found for project {self._project_id}")
        return sandbox_id, adapter

    def _command_allowed(self, command: str) -> bool:
        if self._allowed_commands is None:
            return True
        return (
            command in self._allowed_commands
            or _is_structural_sandbox_command(command)
            or _is_allowed_worktree_command_rewrite(command, self._allowed_commands)
        )


_LEADING_CD_COMMAND_RE = re.compile(
    r"^cd\s+(?P<path>'[^']+'|\"[^\"]+\"|[^&;\s|]+)\s*&&\s*(?P<body>.+)\s*$",
    re.DOTALL,
)


def _is_allowed_worktree_command_rewrite(command: str, allowed_commands: set[str]) -> bool:
    split = _split_leading_cd_command(command)
    if split is None:
        return False
    path, body = split
    if "/.memstack/worktrees/" not in path:
        return False
    return body in {_allowlist_command_body(allowed) for allowed in allowed_commands}


def _split_leading_cd_command(command: str) -> tuple[str, str] | None:
    match = _LEADING_CD_COMMAND_RE.match(command.strip())
    if match is None:
        return None
    path_token = match.group("path")
    try:
        path_parts = shlex.split(path_token)
    except ValueError:
        return None
    if len(path_parts) != 1:
        return None
    return path_parts[0], match.group("body").strip()


def _allowlist_command_body(command: str) -> str:
    split = _split_leading_cd_command(command)
    if split is not None:
        return split[1]
    return command.strip()


async def _api_process_sandbox_adapter() -> MCPSandboxAdapter:
    """Return the API-process sandbox adapter when no agent-worker adapter exists."""

    from src.infrastructure.adapters.primary.web.routers.sandbox.utils import (
        ensure_sandbox_sync,
        get_sandbox_adapter,
    )

    adapter = get_sandbox_adapter()
    await ensure_sandbox_sync()
    return adapter


async def _ensure_project_sandbox_for_runner(
    *,
    project_id: str,
    tenant_id: str | None,
    adapter: MCPSandboxAdapter,
) -> str | None:
    """Create or recover a project sandbox for harness-owned command execution."""

    if not tenant_id:
        with contextlib.suppress(Exception):
            await adapter.sync_from_docker()
            return await adapter.get_sandbox_id_by_project(project_id)
        return None

    from src.application.services.project_sandbox_lifecycle_service import (
        ProjectSandboxLifecycleService,
    )
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
        SqlProjectSandboxRepository,
    )

    async with async_session_factory() as db:
        sandbox_repo = SqlProjectSandboxRepository(db)
        lifecycle = ProjectSandboxLifecycleService(
            repository=sandbox_repo,
            sandbox_adapter=adapter,
        )
        info = await lifecycle.get_or_create_sandbox(
            project_id=project_id,
            tenant_id=tenant_id,
        )
        await db.commit()
        return info.sandbox_id


def _node_allowed_sandbox_commands(node: PlanNode) -> set[str]:
    commands: set[str] = set()
    raw_commands = node.metadata.get("verification_commands")
    if isinstance(raw_commands, list):
        commands.update(str(command) for command in raw_commands if command)

    raw_preflight = node.metadata.get("preflight_checks")
    if isinstance(raw_preflight, list):
        for item in raw_preflight:
            if isinstance(item, Mapping):
                command = item.get("command")
                if isinstance(command, str) and command:
                    commands.add(command)

    feature = node.feature_checkpoint
    if feature is not None:
        if feature.init_command:
            commands.add(feature.init_command)
        commands.update(command for command in feature.test_commands if command)
    return commands


def _is_structural_sandbox_command(command: str) -> bool:
    if command.startswith('[ -e "') and 'wc -c < "' in command:
        return True
    return (
        "\n" not in command
        and command.startswith("git -C ")
        and command.endswith(" status --short")
    )


async def _resolve_root_task_id(
    session: AsyncSession,
    workspace_id: str,
    payload: Mapping[str, Any],
) -> str | None:
    direct = _payload_string(payload, "root_task_id") or _payload_string(payload, ROOT_GOAL_TASK_ID)
    if direct:
        return direct
    stmt = (
        select(WorkspaceTaskModel)
        .where(WorkspaceTaskModel.workspace_id == workspace_id)
        .where(WorkspaceTaskModel.metadata_json[TASK_ROLE].as_string() == "goal_root")
        .where(WorkspaceTaskModel.archived_at.is_(None))
        .order_by(WorkspaceTaskModel.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return row.id if row is not None else None


async def _resolve_actor_user_id(
    session: AsyncSession,
    workspace_id: str,
    payload: Mapping[str, Any],
) -> str:
    direct = _payload_string(payload, "actor_user_id") or _payload_string(payload, "created_by")
    if direct:
        return direct
    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        raise ValueError(f"Workspace {workspace_id} not found")
    return workspace.created_by


async def _find_task_for_plan_node(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan_id: str,
    node_id: str,
) -> WorkspaceTask | None:
    stmt = (
        select(WorkspaceTaskModel)
        .where(WorkspaceTaskModel.workspace_id == workspace_id)
        .where(WorkspaceTaskModel.metadata_json[WORKSPACE_PLAN_ID].as_string() == plan_id)
        .where(WorkspaceTaskModel.metadata_json[WORKSPACE_PLAN_NODE_ID].as_string() == node_id)
        .where(WorkspaceTaskModel.archived_at.is_(None))
        .order_by(WorkspaceTaskModel.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return SqlWorkspaceTaskRepository(session)._to_domain(row)


def _extract_task_evidence(
    task: WorkspaceTask,
    *,
    current_attempt_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    metadata = dict(task.metadata or {})
    report_attempt_id = metadata.get(LAST_WORKER_REPORT_ATTEMPT_ID) or metadata.get(
        "last_attempt_id"
    )
    report_attempt_id_text = report_attempt_id if isinstance(report_attempt_id, str) else None
    report_belongs_to_current_attempt = not current_attempt_id or (
        report_attempt_id_text is not None and report_attempt_id_text == current_attempt_id
    )
    summary = metadata.get(LAST_WORKER_REPORT_SUMMARY) if report_belongs_to_current_attempt else ""
    stdout = summary if isinstance(summary, str) else json.dumps(summary or "", ensure_ascii=False)
    artifacts: dict[str, Any] = {}
    for key in (
        "evidence_refs",
        "execution_verifications",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "preflight_checks",
        "pipeline_evidence_refs",
    ):
        if not report_belongs_to_current_attempt and key in {
            "evidence_refs",
            "execution_verifications",
            "last_worker_report_artifacts",
            "last_worker_report_verifications",
        }:
            continue
        value = metadata.get(key)
        if isinstance(value, list):
            if key == "preflight_checks":
                artifacts[key] = [
                    dict(item) for item in value if isinstance(item, Mapping) and item
                ]
            else:
                artifacts[key] = [str(item) for item in value if item]
    for key in (
        "current_attempt_conversation_id",
        CURRENT_ATTEMPT_ID,
        "last_attempt_id",
        LAST_WORKER_REPORT_ATTEMPT_ID,
        "last_attempt_status",
        "last_worker_report_summary",
        "last_worker_report_type",
        "pipeline_status",
        "preview_url",
        "health_url",
    ):
        if not report_belongs_to_current_attempt and key in {
            "last_worker_report_summary",
            "last_worker_report_type",
        }:
            continue
        value = metadata.get(key)
        if isinstance(value, str) and value:
            artifacts[key] = value
    code_context = metadata.get("code_context")
    if isinstance(code_context, Mapping):
        artifacts["code_context"] = dict(code_context)
    return stdout, artifacts


def _execution_task_metadata_from_node(node: PlanNode) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if node.feature_checkpoint is not None:
        metadata["feature_checkpoint"] = node.feature_checkpoint.to_json()
    if node.handoff_package is not None:
        metadata["handoff_package"] = node.handoff_package.to_json()
    harness_feature_id = node.metadata.get("harness_feature_id") or node.metadata.get("feature_id")
    if isinstance(harness_feature_id, str) and harness_feature_id:
        metadata["harness_feature_id"] = harness_feature_id
    preflight_checks = node.metadata.get("preflight_checks")
    if isinstance(preflight_checks, list):
        metadata["preflight_checks"] = [
            dict(item)
            for item in preflight_checks
            if isinstance(item, Mapping) and item.get("check_id")
        ]
    write_set = node.metadata.get("write_set")
    if isinstance(write_set, list):
        metadata["write_set"] = [str(item) for item in write_set if item]
    commands = node.metadata.get("verification_commands")
    if isinstance(commands, list):
        metadata["verification_commands"] = [str(item) for item in commands if item]
    return metadata


def _apply_attempt_worktree_checkpoint(node: PlanNode, attempt_id: str) -> None:
    feature = node.feature_checkpoint
    if feature is None:
        return
    branch_name = _worktree_branch_name(node_id=node.id, attempt_id=attempt_id)
    worktree_path = f"${{sandbox_code_root}}/../.memstack/worktrees/{attempt_id}"
    node.feature_checkpoint = replace(
        feature,
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=_attempt_retry_base_ref(node) or feature.commit_ref or feature.base_ref or "HEAD",
    )


def _attempt_retry_base_ref(node: PlanNode) -> str | None:
    metadata = dict(node.metadata or {})
    for key in (
        "source_publish_commit_ref",
        "source_publish_source_commit_ref",
        "worktree_integration_commit_ref",
        "verified_commit_ref",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


_STALE_ATTEMPT_METADATA_KEYS = frozenset(
    {
        "last_verification_summary",
        "last_verification_passed",
        "last_verification_hard_fail",
        "last_verification_attempt_id",
        "last_verification_ran_at",
        "last_verification_judge_confidence",
        "last_verification_judge_failed_criteria",
        "last_verification_judge_next_action_kind",
        "last_verification_judge_rationale",
        "last_verification_judge_repair_brief",
        "last_verification_judge_required_next_action",
        "last_verification_judge_verdict",
        "current_repair_turn",
        "verification_evidence_refs",
        "verified_commit_ref",
        "verified_git_diff_summary",
        "verified_test_commands",
        "retry_last_reason",
        "terminal_attempt_status",
        "terminal_attempt_reconciled_at",
    }
)


def _clear_stale_attempt_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    cleaned = dict(metadata)
    for key in _STALE_ATTEMPT_METADATA_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _worktree_branch_name(*, node_id: str, attempt_id: str) -> str:
    return _manager_worktree_branch_name(node_id=node_id, attempt_id=attempt_id)


def _safe_git_token(value: str) -> str:  # pyright: ignore[reportUnusedFunction]
    return _manager_safe_git_token(value)


def _tool_result_text(raw: Mapping[str, Any]) -> str:
    content = raw.get("content")
    if isinstance(content, list):
        parts = [
            str(item.get("text") or "")
            for item in content
            if isinstance(item, Mapping) and item.get("text")
        ]
        if parts:
            return "\n".join(parts)
    output = raw.get("output")
    if isinstance(output, str):
        return output
    text = raw.get("text")
    if isinstance(text, str):
        return text
    return ""


def _normalize_sandbox_no_output_text(value: str) -> str:
    text = value.strip()
    return "" if text.casefold() in _NO_OUTPUT_SENTINELS else text


def _node_worker_brief(node: PlanNode) -> str:
    lines = [
        "[workspace-plan-node]",
        f"plan_id={node.plan_id}",
        f"node_id={node.id}",
        f"title={node.title}",
    ]
    lines.extend(_feature_checkpoint_brief_lines(node))
    lines.extend(_handoff_package_brief_lines(node))
    lines.extend(_verification_feedback_brief_lines(node))
    lines.extend(_rehydration_guidance_lines())
    if node.description:
        lines.extend(["", str(node.description)])
    return "\n".join(lines)


def _verification_feedback_brief_lines(node: PlanNode) -> list[str]:
    metadata = dict(node.metadata or {})
    lines: list[str] = []
    for label, key in (
        ("last_verification_attempt_id", "last_verification_attempt_id"),
        ("pipeline_status", "pipeline_status"),
        ("pipeline_failed_stage", "pipeline_failed_stage"),
        ("pipeline_run_id", "pipeline_run_id"),
        ("source_publish_status", "source_publish_status"),
        ("source_publish_reason", "source_publish_reason"),
        ("last_verification_judge_verdict", "last_verification_judge_verdict"),
        ("last_verification_judge_next_action_kind", "last_verification_judge_next_action_kind"),
    ):
        value = _brief_metadata_text(metadata.get(key), limit=320)
        if value:
            lines.append(f"{label}={value}")

    for label, key in (
        ("pipeline_last_summary", "pipeline_last_summary"),
        ("pipeline_failure_summary", "pipeline_failure_summary"),
        ("last_verification_summary", "last_verification_summary"),
        (
            "last_verification_judge_required_next_action",
            "last_verification_judge_required_next_action",
        ),
        ("retry_last_reason", "retry_last_reason"),
    ):
        value = _brief_metadata_text(metadata.get(key), limit=900)
        if value:
            lines.append(f"{label}={value}")

    failed_criteria = list(
        dict.fromkeys(_iter_config_strings(metadata.get("last_verification_judge_failed_criteria")))
    )
    if failed_criteria:
        lines.append("last_verification_judge_failed_criteria=" + ", ".join(failed_criteria[:8]))

    feedback_items = _worker_feedback_items(metadata)
    if not feedback_items:
        raw_feedback_items = metadata.get("last_verification_feedback_items")
        if isinstance(raw_feedback_items, list):
            feedback_items = [
                dict(item) for item in raw_feedback_items if isinstance(item, Mapping)
            ]
    for index, item in enumerate(feedback_items[:5], start=1):
        rendered = _feedback_item_brief(item)
        if rendered:
            lines.append(f"feedback_item_{index}={rendered}")

    if not lines:
        return []
    return [
        "",
        "[verification-feedback]",
        (
            "This is the latest durable verifier/pipeline feedback for this node. "
            "Use it as the active repair target before repeating prior fixes."
        ),
        *lines,
        "[/verification-feedback]",
    ]


def _feedback_item_brief(item: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "target_layer",
        "feedback_kind",
        "severity",
        "recommended_action",
        "failure_signature",
    ):
        value = _brief_metadata_text(item.get(key), limit=120)
        if value:
            parts.append(f"{key}={value}")
    summary = _brief_metadata_text(item.get("summary"), limit=700)
    if summary:
        parts.append(f"summary={summary}")
    evidence_refs = list(dict.fromkeys(_iter_config_strings(item.get("evidence_refs"))))
    if evidence_refs:
        parts.append("evidence_refs=" + ", ".join(evidence_refs[:6]))
    return "; ".join(parts)


def _brief_metadata_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 15)].rstrip() + " ...[truncated]"


def _feature_checkpoint_brief_lines(node: PlanNode) -> list[str]:
    feature = node.feature_checkpoint
    if feature is None:
        return []
    lines = [
        "",
        "[feature-checkpoint]",
        f"feature_id={feature.feature_id}",
        f"sequence={feature.sequence}",
        f"title={feature.title or node.title}",
    ]
    if feature.init_command:
        lines.append(f"init_command={feature.init_command}")
    if feature.commit_ref:
        lines.append(f"commit_ref={feature.commit_ref}")
    if feature.worktree_path:
        lines.append(f"worktree_path={feature.worktree_path}")
    if feature.branch_name:
        lines.append(f"branch_name={feature.branch_name}")
    if feature.base_ref:
        lines.append(f"base_ref={feature.base_ref}")
    lines.extend(f"test_command={command}" for command in feature.test_commands)
    lines.extend(f"expected_artifact={artifact}" for artifact in feature.expected_artifacts)
    if feature.handoff_notes:
        lines.append(f"handoff_notes={feature.handoff_notes}")
    lines.append("[/feature-checkpoint]")
    preflight_checks = node.metadata.get("preflight_checks")
    if isinstance(preflight_checks, list):
        lines.extend(_preflight_check_brief_lines(preflight_checks))
    return lines


def _preflight_check_brief_lines(preflight_checks: list[object]) -> list[str]:
    lines = ["", "[preflight-checks]"]
    for item in preflight_checks:
        if not isinstance(item, Mapping):
            continue
        check_id = item.get("check_id")
        if not check_id:
            continue
        kind = item.get("kind") or "custom"
        required = item.get("required")
        command = item.get("command")
        suffix = f" kind={kind}"
        if required is not None:
            suffix += f" required={bool(required)}"
        if command:
            suffix += f" command={command}"
        lines.append(f"check_id={check_id}{suffix}")
    lines.append("[/preflight-checks]")
    return lines if len(lines) > 2 else []


def _handoff_package_brief_lines(node: PlanNode) -> list[str]:
    handoff = node.handoff_package
    if handoff is None:
        return []
    lines = [
        "",
        "[handoff-package]",
        f"reason={handoff.reason.value}",
        f"created_at={handoff.created_at.isoformat()}",
        f"summary={handoff.summary}",
    ]
    if handoff.git_head:
        lines.append(f"git_head={handoff.git_head}")
    if handoff.git_diff_summary:
        lines.append(f"git_diff_summary={handoff.git_diff_summary}")
    if handoff.verification_notes:
        lines.append(f"verification_notes={handoff.verification_notes}")
    lines.extend(f"completed_step={step}" for step in handoff.completed_steps)
    lines.extend(f"next_step={step}" for step in handoff.next_steps)
    lines.extend(f"changed_file={path}" for path in handoff.changed_files)
    lines.extend(f"test_command={command}" for command in handoff.test_commands)
    lines.append("[/handoff-package]")
    return lines


def _rehydration_guidance_lines() -> list[str]:
    return [
        "",
        (
            "Before changing files, get up to speed from the checkpoint: inspect git status, "
            "recent commits, existing diffs, and any listed test commands from the code root."
        ),
        (
            "If a worktree_path is listed, create or reuse that git worktree from base_ref, "
            "switch to branch_name, and perform edits/tests there instead of the main checkout."
        ),
        (
            "When reporting completion, include artifacts, verification evidence, remaining risk, "
            "commit_ref, changed_file entries, test_run evidence, and any diff summary needed by "
            "the next worker."
        ),
    ]


def _payload_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _mapping_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _payload_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _required_payload_string(payload: Mapping[str, Any], key: str) -> str:
    value = _payload_string(payload, key)
    if value is None:
        raise ValueError(f"worker launch payload requires {key}")
    return value


def _iter_config_strings(value: object) -> Iterable[str]:
    if isinstance(value, str) and value:
        yield value
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        for item in value:
            if isinstance(item, str) and item:
                yield item


def _string_set(values: Iterable[str | None]) -> frozenset[str]:
    return frozenset(str(value).strip().lower() for value in values if value and str(value).strip())


__all__ = [
    "ATTEMPT_RETRY_EVENT",
    "DEPLOYMENT_HEALTH_CHECK_EVENT",
    "DEPLOYMENT_REQUESTED_EVENT",
    "HANDOFF_RESUME_EVENT",
    "PIPELINE_LOGS_SYNC_EVENT",
    "PIPELINE_RUN_REQUESTED_EVENT",
    "PIPELINE_STAGE_EXECUTE_EVENT",
    "SUPERVISOR_TICK_EVENT",
    "WORKER_LAUNCH_EVENT",
    "make_attempt_retry_handler",
    "make_handoff_resume_handler",
    "make_pipeline_run_requested_handler",
    "make_supervisor_tick_handler",
    "make_worker_launch_handler",
]
