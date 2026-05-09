"""Handlers for durable workspace plan outbox jobs."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shlex
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import redis.asyncio as redis
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
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgePort,
)
from src.infrastructure.adapters.secondary.persistence.models import (
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
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
    WORKSPACE_AGENT_BINDING_ID,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)
from src.infrastructure.agent.workspace_plan.factory import (
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
    SANDBOX_NATIVE_PROVIDER,
    PipelineContractSpec,
    PipelineServiceSpec,
    SandboxNativePipelineProvider,
    build_pipeline_contract_from_metadata,
)
from src.infrastructure.agent.workspace_plan.supervisor import (
    AgentPoolProvider,
    AttemptContextProvider,
    Dispatcher,
    ProgressSink,
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

WorktreePreparer = Callable[[AsyncSession, str, WorkspaceTask, str | None], Awaitable[str | None]]

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
            "documentation",
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
        if item.plan_id:
            reconciled_terminal_attempt = await _reconcile_plan_nodes_with_terminal_attempts(
                session=session,
                plan_id=item.plan_id,
                workspace_id=workspace_id,
            )
            if reconciled_terminal_attempt:
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
        )
        report = await orchestrator.tick_once(workspace_id)
        if report.errors:
            raise RuntimeError("; ".join(report.errors))

    return _handle


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
        )
    except Exception:
        logger.warning(
            "workspace_plan.verification_judge_unavailable",
            exc_info=True,
            extra={"workspace_id": workspace_id},
        )
        return UnavailableWorkspaceVerificationJudge("workspace verification judge is unavailable")


def _software_iteration_task_budget() -> int:
    raw_value = os.getenv("WORKSPACE_V2_SOFTWARE_MAX_SUBTASKS")
    if raw_value is None:
        return _DEFAULT_SOFTWARE_WORKSPACE_MAX_SUBTASKS
    try:
        value = int(raw_value)
    except ValueError:
        return _DEFAULT_SOFTWARE_WORKSPACE_MAX_SUBTASKS
    return max(1, min(value, _MAX_WORKSPACE_DECOMPOSER_MAX_SUBTASKS))


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
        recoverable_execution = node.execution in {
            TaskExecution.DISPATCHED,
            TaskExecution.RUNNING,
            TaskExecution.REPORTED,
            TaskExecution.VERIFYING,
        }
        recoverable_in_progress_idle = (
            node.intent is TaskIntent.IN_PROGRESS
            and node.execution is TaskExecution.IDLE
            and bool(node.current_attempt_id)
        )
        recoverable_blocked = (
            node.intent is TaskIntent.BLOCKED
            and node.execution is TaskExecution.IDLE
            and bool(node.current_attempt_id)
        )
        recoverable_done_idle = (
            node.intent is TaskIntent.DONE
            and node.execution is TaskExecution.IDLE
            and bool(node.current_attempt_id)
        )
        if not (
            recoverable_execution
            or recoverable_in_progress_idle
            or recoverable_blocked
            or recoverable_done_idle
        ):
            continue
        if not node.current_attempt_id:
            continue
        attempt = await _load_plan_attempt(session, node.current_attempt_id)
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
        if status == "accepted":
            if (
                recoverable_done_idle
                and node.metadata.get("terminal_attempt_status") == "accepted"
                and node.metadata.get("last_verification_attempt_id") == attempt.id
            ):
                continue
            summary = str(
                attempt.leader_feedback or attempt.candidate_summary or "accepted terminal attempt"
            )
            await _project_accepted_terminal_attempt_to_task(
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
                    metadata={
                        **dict(node.metadata or {}),
                        "terminal_attempt_status": status,
                        "terminal_attempt_reconciled_at": now.isoformat().replace("+00:00", "Z"),
                        "last_verification_summary": summary,
                        "last_verification_passed": True,
                        "last_verification_hard_fail": False,
                        "last_verification_attempt_id": attempt.id,
                        "last_verification_ran_at": now.isoformat().replace("+00:00", "Z"),
                        **_accepted_attempt_evidence_metadata(attempt),
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
                terminal_attempt=attempt,
            )
            if accepted_attempt is not None:
                summary = str(
                    accepted_attempt.leader_feedback
                    or accepted_attempt.candidate_summary
                    or "accepted terminal attempt"
                )
                await _project_accepted_terminal_attempt_to_task(
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
                        metadata={
                            **dict(node.metadata or {}),
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


async def _project_accepted_terminal_attempt_to_task(
    *,
    session: AsyncSession,
    workspace_id: str,
    node: PlanNode,
    attempt: WorkspaceTaskSessionAttemptModel,
    summary: str,
    now: datetime,
) -> None:
    task_id = node.workspace_task_id or attempt.workspace_task_id
    if not task_id:
        return
    task = await session.get(WorkspaceTaskModel, task_id)
    if task is None or task.workspace_id != workspace_id:
        return
    evidence_refs = _accepted_attempt_evidence_refs(attempt)
    commit_ref = _first_prefixed_ref(evidence_refs, "commit_ref:")
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


async def _load_plan_attempt(
    session: AsyncSession,
    attempt_id: str,
) -> WorkspaceTaskSessionAttemptModel | None:
    return await session.get(WorkspaceTaskSessionAttemptModel, attempt_id)


async def _load_reconciling_accepted_attempt_for_task(
    *,
    session: AsyncSession,
    workspace_id: str,
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
    if accepted_attempt is None:
        return None
    if accepted_attempt.id == terminal_attempt.id:
        return None
    if accepted_attempt.attempt_number > terminal_attempt.attempt_number:
        return accepted_attempt
    if _attempt_cancelled_because_parent_done(terminal_attempt):
        return accepted_attempt
    return None


def _attempt_cancelled_because_parent_done(
    attempt: WorkspaceTaskSessionAttempt | WorkspaceTaskSessionAttemptModel,
) -> bool:
    if _attempt_status_value(attempt) != "cancelled":
        return False
    reason = str(getattr(attempt, "adjudication_reason", None) or "")
    feedback = str(getattr(attempt, "leader_feedback", None) or "")
    return "recovery:parent_done" in {reason, feedback}


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
            existing_task = await command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=node.title,
                description=node.description or None,
                metadata={
                    AUTONOMY_SCHEMA_VERSION_KEY: AUTONOMY_SCHEMA_VERSION,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: root_task_id,
                    LINEAGE_SOURCE: "agent",
                    DERIVED_FROM_INTERNAL_PLAN_STEP: node.id,
                    WORKSPACE_PLAN_ID: plan_id,
                    WORKSPACE_PLAN_NODE_ID: node.id,
                    **_execution_task_metadata_from_node(node),
                },
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

        setup_note = await _worker_launch_worktree_note(
            worktree_preparer or _prepare_attempt_worktree_if_available,
            session=session,
            workspace_id=workspace_id,
            task=task,
            extra_instructions=extra_instructions,
        )
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
        )
        await _mark_plan_node_running_after_launch_schedule(
            session=session,
            plan_id=item.plan_id,
            node_id=_payload_string(payload, "node_id"),
            attempt_id=attempt_id,
        )

    return _handle


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
    next_action_kind = _mapping_string(metadata, "last_verification_judge_next_action_kind")
    if next_action_kind != "retry_same_node":
        return None
    previous_attempt_id = _mapping_string(metadata, "last_verification_attempt_id")
    if not previous_attempt_id:
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="missing_previous_attempt_id",
        )
    if not _repair_turn_reuse_enabled():
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="reuse_disabled",
            previous_attempt_id=previous_attempt_id,
        )
    repair_turn_count = _nonnegative_int(metadata.get("same_conversation_repair_turn_count"))
    if repair_turn_count >= _repair_turn_reuse_max():
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="max_repair_turns_reached",
            previous_attempt_id=previous_attempt_id,
        )
    previous_attempt = await session.get(WorkspaceTaskSessionAttemptModel, previous_attempt_id)
    if previous_attempt is None:
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="previous_attempt_missing",
            previous_attempt_id=previous_attempt_id,
        )
    if previous_attempt.workspace_task_id != task.id:
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="previous_attempt_task_mismatch",
            previous_attempt_id=previous_attempt_id,
        )
    previous_status = _attempt_status_value(previous_attempt)
    if previous_status != WorkspaceTaskSessionAttemptStatus.REJECTED.value:
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason=f"previous_attempt_status_{previous_status or 'unknown'}",
            previous_attempt_id=previous_attempt_id,
        )
    previous_reason = str(
        previous_attempt.adjudication_reason or previous_attempt.leader_feedback or ""
    ).casefold()
    if any(
        marker in previous_reason
        for marker in (
            "recovery:",
            "orphan",
            "provider",
            "retryable_infrastructure",
            "no_terminal_report",
        )
    ):
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="previous_attempt_infrastructure_or_recovery_failure",
            previous_attempt_id=previous_attempt_id,
        )
    conversation_id = _mapping_string(
        {"conversation_id": previous_attempt.conversation_id}, "conversation_id"
    )
    if not conversation_id:
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="missing_conversation",
            previous_attempt_id=previous_attempt_id,
        )
    if not _node_has_reusable_worktree(node):
        return await _repair_turn_ineligible(
            session=session,
            task=task,
            node=node,
            leader_agent_id=leader_agent_id,
            reason="missing_reusable_worktree",
            previous_attempt_id=previous_attempt_id,
        )

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
    return base


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

    return _handle


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

    async def _handle(  # noqa: C901, PLR0912, PLR0915
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

        runner = _WorkspaceSandboxCommandRunner(
            project_id=workspace.project_id,
            tenant_id=workspace.tenant_id,
        )
        contract = _pipeline_contract_for_workspace(
            project_id=workspace.project_id,
            workspace_id=workspace_id,
            workspace_metadata=workspace_metadata,
            root_metadata=root_metadata,
        )
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
        if contract.provider != SANDBOX_NATIVE_PROVIDER:
            await _suspend_plan_for_pipeline(
                session=session,
                plan=plan,
                node=node,
                reason=f"unsupported pipeline provider: {contract.provider}",
            )
            return

        pipeline_repo = SqlWorkspacePipelineRepository(session)
        latest = await pipeline_repo.latest_run_for_node(
            plan_id=plan_id,
            node_id=node_id,
            attempt_id=attempt_id,
        )
        if latest is not None and (
            latest.status == "running"
            or (
                latest.status == "success"
                and (
                    not _requires_preview_deployment(contract)
                    or _node_has_required_deployment_health(node, contract=contract)
                )
            )
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
            },
        )
        run = await pipeline_repo.create_run(
            contract_id=contract_model.id,
            workspace_id=workspace_id,
            plan_id=plan_id,
            node_id=node_id,
            attempt_id=attempt_id,
            commit_ref=_pipeline_commit_ref(node),
            provider=contract.provider,
            metadata={"reason": payload.get("reason") or "pipeline_gate_required"},
        )
        await _mark_pipeline_running(session=session, plan=plan, node=node, run_id=run.id)

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
        preview_url = next(iter(preview_urls.values()), None) or _pipeline_preview_url(
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
                preview_url=preview_url,
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
            preview_url=preview_url,
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
    )
    return _workspace_scoped_pipeline_contract(contract, workspace_id=workspace_id)


def _needs_agent_managed_pipeline_proposal(contract: PipelineContractSpec) -> bool:
    if not contract.agent_managed or not contract.auto_deploy:
        return False
    if contract.contract_source != PLANNING_CONTRACT_SOURCE:
        return True
    return not contract.services and not contract.deploy_command and not contract.health_url


def _requires_preview_deployment(contract: PipelineContractSpec) -> bool:
    return contract.auto_deploy


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


def _pipeline_commit_ref(node: PlanNode) -> str | None:
    feature = node.feature_checkpoint
    if feature is not None and feature.commit_ref:
        return feature.commit_ref
    metadata = dict(node.metadata or {})
    for value in _merge_string_values(metadata.get("evidence_refs"), []):
        if value.startswith("commit_ref:"):
            return value.removeprefix("commit_ref:")
    return None


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


async def _worker_launch_worktree_note(
    preparer: WorktreePreparer,
    *,
    session: AsyncSession,
    workspace_id: str,
    task: WorkspaceTask,
    extra_instructions: str | None,
) -> str | None:
    try:
        return await preparer(session, workspace_id, task, extra_instructions)
    except Exception as exc:
        logger.warning(
            "workspace_plan.worker_launch.worktree_prepare_failed",
            extra={
                "event": "workspace_plan.worker_launch.worktree_prepare_failed",
                "workspace_id": workspace_id,
                "task_id": task.id,
            },
            exc_info=True,
        )
        return _worktree_setup_note(status="failed", reason=f"preparer raised: {exc}")


def _append_launch_instruction_note(instructions: str | None, note: str | None) -> str | None:
    if not note:
        return instructions
    if not instructions:
        return note.strip()
    return f"{instructions.rstrip()}\n\n{note.strip()}"


async def _prepare_attempt_worktree_if_available(  # noqa: PLR0911
    session: AsyncSession,
    workspace_id: str,
    task: WorkspaceTask,
    _extra_instructions: str | None,
) -> str | None:
    metadata = dict(task.metadata or {})
    feature_checkpoint = metadata.get("feature_checkpoint")
    if not isinstance(feature_checkpoint, Mapping):
        return None
    feature_metadata = cast(Mapping[str, Any], feature_checkpoint)

    worktree_path_template = _mapping_string(feature_metadata, "worktree_path")
    branch_name = _mapping_string(feature_metadata, "branch_name")
    base_ref = _mapping_string(feature_metadata, "base_ref") or "HEAD"
    if not worktree_path_template or not branch_name:
        return _worktree_setup_note(
            status="skipped",
            reason="feature checkpoint does not include worktree_path and branch_name",
        )

    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        return _worktree_setup_note(status="skipped", reason="workspace not found")

    root_metadata: Mapping[str, Any] = {}
    root_task_id = _mapping_string(metadata, ROOT_GOAL_TASK_ID)
    if root_task_id:
        root_task = await SqlWorkspaceTaskRepository(session).find_by_id(root_task_id)
        if root_task is not None and root_task.workspace_id == workspace_id:
            root_metadata = dict(root_task.metadata or {})

    from src.infrastructure.agent.workspace.code_context import (
        load_workspace_code_context,
    )

    workspace_metadata = dict(getattr(workspace, "metadata", {}) or {})
    code_context = load_workspace_code_context(
        project_id=workspace.project_id,
        root_metadata=root_metadata,
        workspace_metadata=workspace_metadata,
    )
    if not code_context.sandbox_code_root:
        return _worktree_setup_note(
            status="skipped",
            reason="sandbox_code_root is not available for this workspace",
        )

    worktree_path = worktree_path_template.replace(
        "${sandbox_code_root}", code_context.sandbox_code_root
    )
    if "${sandbox_code_root}" in worktree_path:
        return _worktree_setup_note(
            status="skipped",
            reason="worktree_path still contains an unresolved sandbox_code_root placeholder",
        )

    command = _worktree_setup_command(
        sandbox_code_root=code_context.sandbox_code_root,
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
    )
    try:
        result = await _WorkspaceSandboxCommandRunner(
            project_id=workspace.project_id,
            tenant_id=workspace.tenant_id,
        ).run_command(command, timeout=120)
    except Exception as exc:
        return _worktree_setup_note(
            status="failed",
            reason=str(exc),
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
        )

    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    if int(result.get("exit_code") or 0) != 0:
        return _worktree_setup_note(
            status="failed",
            reason=_compact_command_output(stderr or stdout),
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
        )
    return _worktree_setup_note(
        status="prepared",
        output=_compact_command_output(stdout),
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
    )


def _worktree_setup_command(
    *,
    sandbox_code_root: str,
    worktree_path: str,
    branch_name: str,
    base_ref: str,
) -> str:
    code_root = shlex.quote(sandbox_code_root)
    worktree = shlex.quote(worktree_path)
    branch = shlex.quote(branch_name)
    base = shlex.quote(base_ref)
    return "\n".join(
        [
            "set -e",
            f"cd {code_root}",
            'repo_name="$(basename "$(pwd)")"',
            'fallback_remote="$(dirname "$(pwd)")/.memstack/git-remotes/${repo_name}.git"',
            "if ! git remote get-url origin >/dev/null 2>&1; then",
            '  mkdir -p "$(dirname "$fallback_remote")"',
            '  git init --bare "$fallback_remote" >/dev/null',
            '  git remote add origin "$fallback_remote"',
            "fi",
            "git config push.default current",
            f'mkdir -p "$(dirname {worktree})"',
            f"if [ -e {worktree}/.git ] || [ -f {worktree}/.git ]; then",
            f"  git -C {worktree} checkout {branch}",
            "else",
            f"  git worktree add -B {branch} {worktree} {base}",
            "fi",
            f'printf "git_head=%s\\n" "$(git -C {worktree} rev-parse HEAD)"',
            f"git -C {worktree} status --short",
            f"git -C {worktree} diff --stat -- || true",
        ]
    )


def _worktree_setup_note(
    *,
    status: str,
    reason: str | None = None,
    output: str | None = None,
    worktree_path: str | None = None,
    branch_name: str | None = None,
    base_ref: str | None = None,
) -> str:
    lines = ["[worktree-setup]", f"status={status}"]
    if worktree_path:
        lines.append(f"worktree_path={worktree_path}")
    if branch_name:
        lines.append(f"branch_name={branch_name}")
    if base_ref:
        lines.append(f"base_ref={base_ref}")
    if reason:
        lines.append(f"reason={_compact_command_output(reason)}")
    if output:
        lines.append(f"output={_compact_command_output(output)}")
    lines.append("[/worktree-setup]")
    return "\n".join(lines)


def _compact_command_output(value: str, *, limit: int = 1000) -> str:
    compacted = value.strip().replace("\n", "\\n")
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 15] + "...[truncated]"


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
    report_belongs_to_current_attempt = (
        not current_attempt_id
        or not isinstance(report_attempt_id, str)
        or report_attempt_id == current_attempt_id
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
        base_ref=feature.base_ref or "HEAD",
    )


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
    node_token = _safe_git_token(node_id)[:48]
    attempt_token = _safe_git_token(attempt_id)[:12]
    return f"workspace/{node_token}-{attempt_token}"


def _safe_git_token(value: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value)
    token = token.strip("./-")
    return token or "node"


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
    lines.extend(_rehydration_guidance_lines())
    if node.description:
        lines.extend(["", str(node.description)])
    return "\n".join(lines)


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
