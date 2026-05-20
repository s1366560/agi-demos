"""Durable WorkspaceOrchestrator kickoff for root goals.

This module creates a durable V2 ``Plan`` and enqueues a supervisor tick so
the multi-agent architecture (planner → allocator → verifier → projector →
blackboard) receives root goals through the current plan runtime.

Kickoff is non-blocking:

* All exceptions are swallowed and logged so caller task mutations stay
  resilient.
* The outbox worker owns durable supervisor progress after the plan is saved.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_autonomy_profiles import resolve_workspace_type
from src.domain.model.workspace_plan.plan import Plan, PlanStatus
from src.domain.model.workspace_plan.plan_node import PlanNodeKind
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    PlanModel,
    PlanNodeModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import (
    SqlPlanRepository,
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
from src.infrastructure.agent.workspace.planner_agent_decomposer import (
    RuntimeWorkspacePlannerAgentTurnRunner,
    WorkspacePlannerAgentDecomposer,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    ROOT_GOAL_TASK_ID,
    WORKSPACE_PLAN_ID,
)
from src.infrastructure.agent.workspace_plan import build_sql_orchestrator
from src.infrastructure.agent.workspace_plan.outbox_handlers import SUPERVISOR_TICK_EVENT

if TYPE_CHECKING:
    from src.infrastructure.agent.workspace_plan.orchestrator import WorkspaceOrchestrator
    from src.infrastructure.agent.workspace_plan.planner import TaskDecomposerProtocol

logger = logging.getLogger(__name__)

# Test hook only. Production uses SQL-backed, request-scoped orchestrators.
_orchestrator_singleton: WorkspaceOrchestrator | None = None
_DEFAULT_WORKSPACE_DECOMPOSER_MAX_SUBTASKS = 8
_DEFAULT_SOFTWARE_WORKSPACE_MAX_SUBTASKS = 6
_DEFAULT_SOFTWARE_WORKSPACE_MIN_SUBTASKS = 6
_MAX_WORKSPACE_DECOMPOSER_MAX_SUBTASKS = 12
_SOFTWARE_ITERATION_PHASES = ("research", "plan", "implement", "test", "deploy", "review")
_ROOT_PLAN_DEDUP_STATUSES = (
    PlanStatus.ACTIVE.value,
    PlanStatus.DRAFT.value,
    PlanStatus.COMPLETED.value,
)
_ROOT_PLAN_RESUMABLE_STATUSES = (
    PlanStatus.ACTIVE.value,
    PlanStatus.DRAFT.value,
)


def set_orchestrator_singleton_for_testing(orchestrator: WorkspaceOrchestrator | None) -> None:
    """Test hook — inject an in-memory orchestrator and bypass SQL wiring."""
    global _orchestrator_singleton
    _orchestrator_singleton = orchestrator


def reset_orchestrator_singleton_for_testing() -> None:
    """Test hook — clears the cached orchestrator."""
    global _orchestrator_singleton
    _orchestrator_singleton = None


async def kickoff_v2_plan(
    *,
    workspace_id: str,
    title: str,
    description: str = "",
    created_by: str = "",
    root_task_id: str | None = None,
    leader_agent_id: str | None = None,
) -> bool:
    """Fire-and-forget durable workspace plan kickoff.

    Never raises: any failure is logged and swallowed so the caller's task
    mutation path stays resilient.
    """
    try:
        if _orchestrator_singleton is not None:
            _ = await _orchestrator_singleton.start_goal(
                workspace_id=workspace_id,
                title=title,
                description=description,
                created_by=created_by,
            )
            return True

        async with async_session_factory() as db:
            await _acquire_root_kickoff_lock(
                db,
                workspace_id=workspace_id,
                root_task_id=root_task_id,
            )
            existing_plan = await _root_plan_for_kickoff_dedup(
                db,
                workspace_id=workspace_id,
                root_task_id=root_task_id,
            )
            if existing_plan is not None:
                plan_id, plan_status = existing_plan
                if plan_status in _ROOT_PLAN_RESUMABLE_STATUSES:
                    _ = await _enqueue_existing_root_plan_supervisor_tick(
                        db,
                        plan_id=plan_id,
                        workspace_id=workspace_id,
                        root_task_id=root_task_id,
                        actor_user_id=created_by,
                        leader_agent_id=leader_agent_id,
                    )
                    await db.commit()
                logger.info(
                    "v2_bridge: skipping duplicate kickoff for existing root plan",
                    extra={
                        "workspace_id": workspace_id,
                        "root_task_id": root_task_id,
                        "plan_id": plan_id,
                        "plan_status": plan_status,
                    },
                )
                return True
            planning_context = await _workspace_planning_contract_context(
                db,
                workspace_id,
                root_task_id=root_task_id,
            )
            decomposer = await _build_workspace_task_decomposer(
                db,
                workspace_id,
                root_task_id=root_task_id,
                extra_context=planning_context,
            )
            orchestrator = build_sql_orchestrator(db, decomposer=decomposer)
            plan = await orchestrator.start_goal(
                workspace_id=workspace_id,
                title=title,
                description=description,
                created_by=created_by,
                conversation_context=planning_context,
                start_supervisor=False,
            )
            if root_task_id:
                await _attach_root_task_id_to_plan(db, plan=plan, root_task_id=root_task_id)
            if plan.status is PlanStatus.SUSPENDED and plan.goal_node.metadata.get(
                "planner_contract_missing"
            ):
                await SqlWorkspacePlanEventRepository(db).append(
                    plan_id=plan.id,
                    workspace_id=workspace_id,
                    node_id=plan.goal_id.value,
                    actor_id=created_by or None,
                    event_type="planner_contract_missing",
                    source="v2_bridge",
                    payload=dict(plan.goal_node.metadata),
                )
                await db.commit()
                return True
            _ = await SqlWorkspacePlanOutboxRepository(db).enqueue(
                plan_id=plan.id,
                workspace_id=workspace_id,
                event_type=SUPERVISOR_TICK_EVENT,
                payload={
                    "workspace_id": workspace_id,
                    "root_task_id": root_task_id,
                    "actor_user_id": created_by,
                    "leader_agent_id": leader_agent_id,
                },
                metadata={"source": "v2_bridge"},
            )
            await db.commit()
            return True
    except Exception:
        logger.warning(
            "v2_bridge: start_goal failed for workspace=%s",
            workspace_id,
            exc_info=True,
        )
        return False


async def _root_plan_for_kickoff_dedup(
    db: AsyncSession,
    *,
    workspace_id: str,
    root_task_id: str | None,
) -> tuple[str, str] | None:
    if not root_task_id:
        return None

    plan_ids = await _root_task_plan_ids(
        db,
        workspace_id=workspace_id,
        root_task_id=root_task_id,
    )
    if not plan_ids:
        return None

    existing_stmt = (
        select(PlanModel.id, PlanModel.status)
        .where(PlanModel.workspace_id == workspace_id)
        .where(PlanModel.id.in_(plan_ids))
        .where(PlanModel.status.in_(_ROOT_PLAN_DEDUP_STATUSES))
        .limit(1)
    )
    row = (await db.execute(existing_stmt)).one_or_none()
    if row is None:
        return None
    plan_id, status = row
    return str(plan_id), str(status)


async def _enqueue_existing_root_plan_supervisor_tick(
    db: AsyncSession,
    *,
    plan_id: str,
    workspace_id: str,
    root_task_id: str | None,
    actor_user_id: str,
    leader_agent_id: str | None,
) -> bool:
    pending_stmt = (
        select(WorkspacePlanOutboxModel.id)
        .where(WorkspacePlanOutboxModel.workspace_id == workspace_id)
        .where(WorkspacePlanOutboxModel.plan_id == plan_id)
        .where(WorkspacePlanOutboxModel.event_type == SUPERVISOR_TICK_EVENT)
        .where(WorkspacePlanOutboxModel.status.in_(["pending", "processing", "failed"]))
        .limit(1)
    )
    if (await db.execute(pending_stmt)).scalar_one_or_none() is not None:
        return False

    _ = await SqlWorkspacePlanOutboxRepository(db).enqueue(
        plan_id=plan_id,
        workspace_id=workspace_id,
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": workspace_id,
            "root_task_id": root_task_id,
            "actor_user_id": actor_user_id,
            "leader_agent_id": leader_agent_id,
        },
        metadata={"source": "v2_bridge", "resume_existing_root_plan": True},
    )
    return True


async def _root_task_plan_ids(
    db: AsyncSession,
    *,
    workspace_id: str,
    root_task_id: str,
) -> set[str]:
    task_stmt = (
        select(WorkspaceTaskModel.metadata_json)
        .where(WorkspaceTaskModel.workspace_id == workspace_id)
        .where(WorkspaceTaskModel.metadata_json[ROOT_GOAL_TASK_ID].as_string() == root_task_id)
        .where(WorkspaceTaskModel.metadata_json[WORKSPACE_PLAN_ID].as_string().is_not(None))
    )
    metadata_rows = (await db.execute(task_stmt)).scalars().all()
    plan_ids = {
        plan_id
        for metadata in metadata_rows
        if isinstance(metadata, dict)
        for plan_id in (metadata.get(WORKSPACE_PLAN_ID),)
        if isinstance(plan_id, str) and plan_id
    }

    goal_stmt = (
        select(PlanNodeModel.plan_id)
        .join(PlanModel, PlanModel.id == PlanNodeModel.plan_id)
        .where(PlanModel.workspace_id == workspace_id)
        .where(PlanNodeModel.kind == PlanNodeKind.GOAL.value)
        .where(PlanNodeModel.metadata_json[ROOT_GOAL_TASK_ID].as_string() == root_task_id)
    )
    plan_ids.update(str(plan_id) for plan_id in (await db.execute(goal_stmt)).scalars().all())
    return plan_ids


async def _attach_root_task_id_to_plan(
    db: AsyncSession,
    *,
    plan: Plan,
    root_task_id: str,
) -> None:
    goal_node = plan.goal_node
    if goal_node.metadata.get(ROOT_GOAL_TASK_ID) == root_task_id:
        return
    plan.replace_node(
        replace(
            goal_node,
            metadata={**dict(goal_node.metadata or {}), ROOT_GOAL_TASK_ID: root_task_id},
        )
    )
    await SqlPlanRepository(db).save(plan)


async def _acquire_root_kickoff_lock(
    db: AsyncSession,
    *,
    workspace_id: str,
    root_task_id: str | None,
) -> None:
    if not root_task_id:
        return
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    lock_name = f"workspace_v2_kickoff:{workspace_id}:{root_task_id}"
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(lock_name))))


async def _build_workspace_task_decomposer(
    db: AsyncSession,
    workspace_id: str,
    *,
    root_task_id: str | None = None,
    extra_context: str | None = None,
) -> TaskDecomposerProtocol | None:
    """Build the builtin workspace planner decomposer V2 needs to produce a real DAG."""
    try:
        workspace = await SqlWorkspaceRepository(db).find_by_id(workspace_id)
        if workspace is None:
            return None
        root_metadata: Mapping[str, Any] | None = None
        if root_task_id:
            root_task = await SqlWorkspaceTaskRepository(db).find_by_id(root_task_id)
            if root_task is not None and root_task.workspace_id == workspace_id:
                root_metadata = root_task.metadata

        workspace_type = resolve_workspace_type(root_metadata, workspace.metadata)
        max_subtasks = _workspace_decomposer_max_subtasks(
            root_metadata=root_metadata,
            workspace_metadata=workspace.metadata,
        )
        if extra_context is None:
            extra_context = _workspace_iteration_decomposition_context(
                workspace_type=workspace_type,
                max_subtasks=max_subtasks,
            )
        return cast(
            "TaskDecomposerProtocol",
            WorkspacePlannerAgentDecomposer(
                tenant_id=workspace.tenant_id,
                project_id=workspace.project_id,
                workspace_id=workspace_id,
                root_task_id=root_task_id,
                actor_user_id=getattr(workspace, "created_by", None),
                workspace_metadata=workspace.metadata,
                root_metadata=root_metadata,
                max_subtasks=max_subtasks,
                min_subtasks=_workspace_decomposer_min_subtasks(
                    root_metadata=root_metadata,
                    workspace_metadata=workspace.metadata,
                    max_subtasks=max_subtasks,
                ),
                extra_context=extra_context,
                session=db,
                turn_runner=_build_workspace_planner_agent_turn_runner(
                    tenant_id=workspace.tenant_id,
                    project_id=workspace.project_id,
                ),
            ),
        )
    except Exception:
        logger.warning(
            "v2_bridge: task decomposer unavailable for workspace=%s",
            workspace_id,
            exc_info=True,
        )
        return None


def _build_workspace_planner_agent_turn_runner(
    *,
    tenant_id: str,
    project_id: str,
) -> RuntimeWorkspacePlannerAgentTurnRunner:
    return RuntimeWorkspacePlannerAgentTurnRunner(
        tenant_id=tenant_id,
        project_id=project_id,
    )


async def _workspace_planning_contract_context(
    db: AsyncSession,
    workspace_id: str,
    *,
    root_task_id: str | None = None,
) -> str | None:
    workspace = await SqlWorkspaceRepository(db).find_by_id(workspace_id)
    if workspace is None:
        return None
    root_metadata: Mapping[str, Any] | None = None
    if root_task_id:
        root_task = await SqlWorkspaceTaskRepository(db).find_by_id(root_task_id)
        if root_task is not None and root_task.workspace_id == workspace_id:
            root_metadata = root_task.metadata
    workspace_type = resolve_workspace_type(root_metadata, workspace.metadata)
    max_subtasks = _workspace_decomposer_max_subtasks(
        root_metadata=root_metadata,
        workspace_metadata=workspace.metadata,
    )
    return _workspace_iteration_decomposition_context(
        workspace_type=workspace_type,
        max_subtasks=max_subtasks,
    )


def _workspace_decomposer_max_subtasks(
    *,
    root_metadata: Mapping[str, Any] | None = None,
    workspace_metadata: Mapping[str, Any] | None = None,
) -> int:
    is_software = (
        resolve_workspace_type(root_metadata, workspace_metadata) == "software_development"
    )
    env_name = "WORKSPACE_V2_SOFTWARE_MAX_SUBTASKS" if is_software else "WORKSPACE_V2_MAX_SUBTASKS"
    default = (
        _DEFAULT_SOFTWARE_WORKSPACE_MAX_SUBTASKS
        if is_software
        else _DEFAULT_WORKSPACE_DECOMPOSER_MAX_SUBTASKS
    )
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(1, min(value, _MAX_WORKSPACE_DECOMPOSER_MAX_SUBTASKS))


def _workspace_decomposer_min_subtasks(
    *,
    root_metadata: Mapping[str, Any] | None = None,
    workspace_metadata: Mapping[str, Any] | None = None,
    max_subtasks: int,
) -> int:
    if resolve_workspace_type(root_metadata, workspace_metadata) != "software_development":
        return 1
    raw_value = os.getenv("WORKSPACE_V2_SOFTWARE_MIN_SUBTASKS")
    if raw_value is None:
        value = _DEFAULT_SOFTWARE_WORKSPACE_MIN_SUBTASKS
    else:
        try:
            value = int(raw_value)
        except ValueError:
            value = _DEFAULT_SOFTWARE_WORKSPACE_MIN_SUBTASKS
    return max(1, min(value, max_subtasks))


def _workspace_iteration_decomposition_context(
    *,
    workspace_type: str,
    max_subtasks: int,
) -> str | None:
    if workspace_type != "software_development":
        return None
    phases = ", ".join(_SOFTWARE_ITERATION_PHASES)
    return (
        "Software workspace planning contract: create only the current Scrum-style sprint, "
        "not the full future backlog. Use at most "
        f"{max_subtasks} subtasks total. Cover the iteration lifecycle in this order when "
        f"possible: {phases}. Treat later unknown work as feedback for a future sprint, "
        "not as extra tasks in this plan. Each subtask should be independently verifiable "
        "and should name concrete evidence or artifacts. "
        "IMPLEMENTATION FIRST: every subtask must change application code, tests, configs, "
        "schemas, or infrastructure. No subtask may be purely documentation. Required "
        "README/CHANGELOG/architecture-doc updates must be embedded inside the implementation "
        "subtask that owns the changed code, not as a standalone task. Acceptance evidence "
        "(test reports, parity reports, release reports, INDEX.md, BUILD-REPORT.md, "
        "SANDBOX-PREVIEW-EVIDENCE.md, GOAL-COMPLETION.md, acceptance checklists) is the "
        "verification subtask's own output; never allocate it as a separate subtask. Do not "
        "emit subtasks shaped as 'document X', 'update SPEC.md', 'reconcile reports', "
        "'finalize architecture documentation', 'create release checklist', or 'generate "
        "acceptance evidence'. "
        "For CI/CD and deploy phases, use "
        "the MemStack sandbox-native delivery harness: pipeline run, sandbox preview proxy, "
        "health check, and preview evidence. The planning-stage builtin workspace planner "
        "must submit any discovered services via workspace_submit_planning_contract so "
        "workspace.metadata.delivery_cicd is written before deployment. Do not plan Vercel, "
        "Netlify, Railway, Render, "
        "GitHub Actions, Drone, Kubernetes, or other external production deployment work "
        "unless the user explicitly asks for external deployment credentials and approval."
    )


__all__ = [
    "kickoff_v2_plan",
    "reset_orchestrator_singleton_for_testing",
    "set_orchestrator_singleton_for_testing",
]
