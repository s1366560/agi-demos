"""V2 legacy bridge — best-effort kickoff of WorkspaceOrchestrator.

When ``settings.workspace_v2_enabled`` is True this module is called
immediately after the legacy decomposer runs. It creates a parallel V2
``Plan`` in the in-memory repository so the multi-agent architecture
(planner → allocator → verifier → projector → blackboard) receives the
same goals that the legacy ``WorkspaceTask`` tree does.

The bridge is *best-effort*:

* Process-local singleton cache of the orchestrator (via ``build_default_orchestrator``)
* All exceptions are swallowed and logged — legacy autonomy must never
  regress on V2 errors
* No-op when the flag is off (zero overhead)

Once the V2 path reaches feature-parity the legacy decomposer can be
retired and this bridge becomes the single writer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.agent.workspace_plan.orchestrator import WorkspaceOrchestrator

logger = logging.getLogger(__name__)

_orchestrator_singleton: WorkspaceOrchestrator | None = None


def _get_orchestrator() -> WorkspaceOrchestrator | None:
    global _orchestrator_singleton
    if _orchestrator_singleton is not None:
        return _orchestrator_singleton
    try:
        from src.infrastructure.agent.workspace_plan import build_default_orchestrator

        _orchestrator_singleton = build_default_orchestrator()
        return _orchestrator_singleton
    except Exception:
        logger.warning("v2_bridge: failed to build WorkspaceOrchestrator", exc_info=True)
        return None


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

    orchestrator = _get_orchestrator()
    if orchestrator is None or not orchestrator.enabled:
        return

    try:
        await orchestrator.start_goal(
            workspace_id=workspace_id,
            title=title,
            description=description,
            created_by=created_by,
        )
    except Exception:
        logger.warning(
            "v2_bridge: start_goal failed for workspace=%s",
            workspace_id,
            exc_info=True,
        )


__all__ = ["kickoff_v2_plan_if_enabled", "reset_orchestrator_singleton_for_testing"]
