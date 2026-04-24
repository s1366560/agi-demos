"""V2 legacy bridge — best-effort kickoff of durable WorkspaceOrchestrator.

When ``settings.workspace_v2_enabled`` is True this module is called
immediately after the legacy decomposer runs. It creates a parallel durable V2
``Plan`` and enqueues a supervisor tick so the multi-agent architecture
(planner → allocator → verifier → projector → blackboard) receives the
same goals that the legacy ``WorkspaceTask`` tree does.

The bridge is *best-effort*:

* All exceptions are swallowed and logged — legacy autonomy must never
  regress on V2 errors
* No-op when the flag is off (zero overhead)

Once the V2 path reaches feature-parity the legacy decomposer can be
retired and this bridge becomes the single writer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)
from src.infrastructure.agent.workspace_plan import build_sql_orchestrator
from src.infrastructure.agent.workspace_plan.outbox_handlers import SUPERVISOR_TICK_EVENT

if TYPE_CHECKING:
    from src.infrastructure.agent.workspace_plan.orchestrator import WorkspaceOrchestrator

logger = logging.getLogger(__name__)

# Test hook only. Production uses SQL-backed, request-scoped orchestrators.
_orchestrator_singleton: WorkspaceOrchestrator | None = None


def set_orchestrator_singleton_for_testing(orchestrator: WorkspaceOrchestrator | None) -> None:
    """Test hook — inject an in-memory orchestrator and bypass SQL wiring."""
    global _orchestrator_singleton
    _orchestrator_singleton = orchestrator


def reset_orchestrator_singleton_for_testing() -> None:
    """Test hook — clears the cached orchestrator."""
    global _orchestrator_singleton
    _orchestrator_singleton = None


async def kickoff_v2_plan_if_enabled(
    *,
    workspace_id: str,
    title: str,
    description: str = "",
    created_by: str = "",
    root_task_id: str | None = None,
    leader_agent_id: str | None = None,
) -> None:
    """Fire-and-forget V2 plan kickoff; no-op when the flag is off.

    Never raises — any failure (config read, DI build, planner error) is
    swallowed so legacy autonomy continues unaffected.
    """
    try:
        from src.configuration.config import get_settings

        if not getattr(get_settings(), "workspace_v2_enabled", True):
            return
    except Exception:
        logger.debug("v2_bridge: settings unreadable; skipping kickoff", exc_info=True)
        return

    try:
        if _orchestrator_singleton is not None:
            if not _orchestrator_singleton.enabled:
                return
            _ = await _orchestrator_singleton.start_goal(
                workspace_id=workspace_id,
                title=title,
                description=description,
                created_by=created_by,
            )
            return

        async with async_session_factory() as db:
            orchestrator = build_sql_orchestrator(db)
            if not orchestrator.enabled:
                return
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
    except Exception:
        logger.warning(
            "v2_bridge: start_goal failed for workspace=%s",
            workspace_id,
            exc_info=True,
        )


__all__ = [
    "kickoff_v2_plan_if_enabled",
    "reset_orchestrator_singleton_for_testing",
    "set_orchestrator_singleton_for_testing",
]
