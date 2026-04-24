"""Default-wiring factory for :class:`WorkspaceOrchestrator`.

Returns an orchestrator configured with in-memory adapters (:class:`InMemoryPlanRepository`,
:class:`InMemoryBlackboard`) and stub supervisor callables (no-op dispatcher /
empty agent pool). The DI container uses this as the initial singleton; future
milestones swap in SQL repositories and real dispatchers.
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
from src.infrastructure.agent.workspace.workspace_metadata_keys import PENDING_LEADER_ADJUDICATION
from src.infrastructure.agent.workspace_plan.allocator import CapabilityAllocator
from src.infrastructure.agent.workspace_plan.blackboard import InMemoryBlackboard
from src.infrastructure.agent.workspace_plan.orchestrator import (
    OrchestratorConfig,
    WorkspaceOrchestrator,
)
from src.infrastructure.agent.workspace_plan.planner import LLMGoalPlanner
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
        await SqlWorkspacePlanEventRepository(db).append(
            plan_id=node.plan_id,
            workspace_id=workspace_id,
            node_id=node.id,
            attempt_id=_payload_string(payload, "attempt_id") or node.current_attempt_id,
            event_type=event_type,
            source="workspace_plan_verifier",
            payload=payload,
        )
        if event_type == "verification_completed":
            await _project_verification_to_legacy_runtime(db, node, payload)

    return _sink


async def _project_verification_to_legacy_runtime(
    db: AsyncSession,
    node: PlanNode,
    payload: dict[str, Any],
) -> None:
    """Keep compatibility task/session projections in sync with V2 verifier authority."""
    attempt_id = _payload_string(payload, "attempt_id") or node.current_attempt_id
    passed = bool(payload.get("passed"))
    hard_fail = bool(payload.get("hard_fail"))
    summary = str(payload.get("summary") or "")
    now = datetime.now(UTC)

    if attempt_id:
        attempt = await db.get(WorkspaceTaskSessionAttemptModel, attempt_id)
        if attempt is not None:
            if passed:
                attempt.status = WorkspaceTaskSessionAttemptStatus.ACCEPTED.value
                attempt.leader_feedback = summary or "accepted by durable plan verifier"
                attempt.completed_at = now
            elif hard_fail:
                attempt.status = WorkspaceTaskSessionAttemptStatus.BLOCKED.value
                attempt.leader_feedback = summary or "blocked by durable plan verifier"
                attempt.completed_at = now
            else:
                attempt.status = WorkspaceTaskSessionAttemptStatus.REJECTED.value
                attempt.leader_feedback = summary or "replan requested by durable plan verifier"
                attempt.completed_at = now
            attempt.updated_at = now

    if node.workspace_task_id:
        task = await db.get(WorkspaceTaskModel, node.workspace_task_id)
        if task is not None:
            metadata = dict(task.metadata_json or {})
            metadata[PENDING_LEADER_ADJUDICATION] = False
            metadata["durable_plan_verdict"] = (
                "accepted" if passed else "blocked" if hard_fail else "replan_requested"
            )
            metadata["durable_plan_verification_summary"] = summary
            metadata["durable_plan_verified_at"] = now.isoformat().replace("+00:00", "Z")
            metadata["last_attempt_status"] = (
                WorkspaceTaskSessionAttemptStatus.ACCEPTED.value
                if passed
                else WorkspaceTaskSessionAttemptStatus.BLOCKED.value
                if hard_fail
                else WorkspaceTaskSessionAttemptStatus.REJECTED.value
            )
            task.metadata_json = metadata
            if passed:
                task.status = "done"
                task.blocker_reason = None
                task.completed_at = now
            elif hard_fail:
                task.status = "blocked"
                task.blocker_reason = summary or "durable plan verification failed"
            task.updated_at = now


def _payload_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def build_default_orchestrator(
    *,
    config: OrchestratorConfig | None = None,
) -> WorkspaceOrchestrator:
    """Wire a default, side-effect-free :class:`WorkspaceOrchestrator`.

    Suitable for unit tests, CLI tools, and the initial DI singleton. Real
    production wiring will replace the stub callables with the worker-launch
    dispatcher and SQL-backed repositories.
    """
    cfg = config or OrchestratorConfig.from_env()
    plan_repo = InMemoryPlanRepository()
    planner = LLMGoalPlanner(decomposer=None)
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
        heartbeat_seconds=cfg.heartbeat_seconds,
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
    agent_pool: AgentPoolProvider | None = None,
    dispatcher: Dispatcher | None = None,
    attempt_context: AttemptContextProvider | None = None,
    progress_sink: ProgressSink | None = None,
    event_sink: PlanEventSink | None = None,
) -> WorkspaceOrchestrator:
    """Wire a SQL-backed Workspace V2 orchestrator without changing legacy runtime.

    This is an explicit boundary for request-scoped or job-scoped callers. The
    caller owns the provided ``AsyncSession`` lifetime and commit. Long-lived
    production supervisors should use a future session-factory/outbox wrapper
    rather than retaining a request session indefinitely.
    """
    cfg = config or OrchestratorConfig.from_env()
    plan_repo = SqlPlanRepository(db)
    planner = LLMGoalPlanner(decomposer=None)
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
        heartbeat_seconds=cfg.heartbeat_seconds,
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
