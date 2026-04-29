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
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_autonomy_profiles import resolve_workspace_type
from src.domain.model.workspace_plan.plan import PlanStatus
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    PlanModel,
    WorkspaceTaskModel,
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
from src.infrastructure.agent.subagent.task_decomposer import TaskDecomposer
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    ROOT_GOAL_TASK_ID,
    WORKSPACE_PLAN_ID,
)
from src.infrastructure.agent.workspace_plan import build_sql_orchestrator
from src.infrastructure.agent.workspace_plan.outbox_handlers import SUPERVISOR_TICK_EVENT

if TYPE_CHECKING:
    from src.infrastructure.agent.workspace_plan.orchestrator import WorkspaceOrchestrator
    from src.infrastructure.agent.workspace_plan.planner import (
        DecompositionResultLike,
        TaskDecomposerProtocol,
    )

logger = logging.getLogger(__name__)

# Test hook only. Production uses SQL-backed, request-scoped orchestrators.
_orchestrator_singleton: WorkspaceOrchestrator | None = None
_DEFAULT_WORKSPACE_DECOMPOSER_MAX_SUBTASKS = 8
_DEFAULT_SOFTWARE_WORKSPACE_MAX_SUBTASKS = 6
_DEFAULT_SOFTWARE_WORKSPACE_MIN_SUBTASKS = 6
_MAX_WORKSPACE_DECOMPOSER_MAX_SUBTASKS = 12
_SOFTWARE_ITERATION_PHASES = ("research", "plan", "implement", "test", "deploy", "review")


class _WorkspacePlanTaskDecomposerAdapter:
    """Adapter for planner's keyword-only decomposer protocol."""

    def __init__(self, decomposer: TaskDecomposer, extra_context: str | None = None) -> None:
        super().__init__()
        self._decomposer = decomposer
        self._extra_context = extra_context

    async def decompose(
        self,
        *,
        query: str,
        conversation_context: str | None = None,
    ) -> DecompositionResultLike:
        context = _join_context(self._extra_context, conversation_context)
        result = await self._decomposer.decompose(
            query=query,
            conversation_context=context,
        )
        return cast("DecompositionResultLike", result)


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
            if await _completed_plan_exists_for_root_task(
                db,
                workspace_id=workspace_id,
                root_task_id=root_task_id,
            ):
                logger.info(
                    "v2_bridge: skipping duplicate kickoff for completed root plan",
                    extra={
                        "workspace_id": workspace_id,
                        "root_task_id": root_task_id,
                    },
                )
                return True
            decomposer = await _build_workspace_task_decomposer(
                db,
                workspace_id,
                root_task_id=root_task_id,
            )
            orchestrator = build_sql_orchestrator(db, decomposer=decomposer)
            plan = await orchestrator.start_goal(
                workspace_id=workspace_id,
                title=title,
                description=description,
                created_by=created_by,
                start_supervisor=False,
            )
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


async def _completed_plan_exists_for_root_task(
    db: AsyncSession,
    *,
    workspace_id: str,
    root_task_id: str | None,
) -> bool:
    if not root_task_id:
        return False

    active_stmt = (
        select(PlanModel.id)
        .where(PlanModel.workspace_id == workspace_id)
        .where(PlanModel.status.in_((PlanStatus.ACTIVE.value, PlanStatus.DRAFT.value)))
        .limit(1)
    )
    if (await db.execute(active_stmt)).scalar_one_or_none() is not None:
        return False

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
    if not plan_ids:
        return False

    completed_stmt = (
        select(PlanModel.id)
        .where(PlanModel.workspace_id == workspace_id)
        .where(PlanModel.id.in_(plan_ids))
        .where(PlanModel.status == PlanStatus.COMPLETED.value)
        .limit(1)
    )
    return (await db.execute(completed_stmt)).scalar_one_or_none() is not None


async def _build_workspace_task_decomposer(
    db: AsyncSession,
    workspace_id: str,
    *,
    root_task_id: str | None = None,
) -> TaskDecomposerProtocol | None:
    """Build the same LLM-backed decomposer V2 needs to produce a real DAG."""
    try:
        workspace = await SqlWorkspaceRepository(db).find_by_id(workspace_id)
        if workspace is None:
            return None
        root_metadata: Mapping[str, Any] | None = None
        if root_task_id:
            root_task = await SqlWorkspaceTaskRepository(db).find_by_id(root_task_id)
            if root_task is not None and root_task.workspace_id == workspace_id:
                root_metadata = root_task.metadata

        from src.domain.llm_providers.models import OperationType
        from src.infrastructure.llm.provider_factory import AIServiceFactory

        factory = AIServiceFactory()
        provider = await factory.resolve_provider(
            workspace.tenant_id,
            operation_type=OperationType.LLM,
        )
        llm_client = factory.create_unified_llm_client(provider, temperature=0.0)
        workspace_type = resolve_workspace_type(root_metadata, workspace.metadata)
        max_subtasks = _workspace_decomposer_max_subtasks(
            root_metadata=root_metadata,
            workspace_metadata=workspace.metadata,
        )
        return _WorkspacePlanTaskDecomposerAdapter(
            TaskDecomposer(
                llm_client=llm_client,
                max_subtasks=max_subtasks,
                min_subtasks=_workspace_decomposer_min_subtasks(
                    root_metadata=root_metadata,
                    workspace_metadata=workspace.metadata,
                    max_subtasks=max_subtasks,
                ),
            ),
            extra_context=_workspace_iteration_decomposition_context(
                workspace_type=workspace_type,
                max_subtasks=max_subtasks,
            ),
        )
    except Exception:
        logger.warning(
            "v2_bridge: task decomposer unavailable for workspace=%s",
            workspace_id,
            exc_info=True,
        )
        return None


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
        "and should name concrete evidence or artifacts."
    )


def _join_context(*parts: str | None) -> str | None:
    values = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    if not values:
        return None
    return "\n\n".join(values)


__all__ = [
    "kickoff_v2_plan",
    "reset_orchestrator_singleton_for_testing",
    "set_orchestrator_singleton_for_testing",
]
