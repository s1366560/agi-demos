"""Root goal decomposition — delegates to :class:`TaskDecomposer`.

When ``WORKSPACE_V2_ENABLED`` is true this also kicks off the new
:class:`WorkspaceOrchestrator` for side-by-side execution visibility.
The V2 path is best-effort and never blocks the legacy return value so
behavior stays identical if V2 is disabled or misconfigured.
"""

from __future__ import annotations

import logging

from src.infrastructure.agent.workspace.goal_runtime.activation import TaskDecomposerProtocol

logger = logging.getLogger(__name__)


async def _decompose_root_goal(
    *,
    task_decomposer: TaskDecomposerProtocol | None,
    root_title: str,
    user_query: str,
) -> list[tuple[str | None, str]]:
    query = user_query.strip() or root_title.strip()
    if not query:
        return []
    if task_decomposer is not None and hasattr(task_decomposer, "decompose"):
        try:
            result = await task_decomposer.decompose(query)
            if result.subtasks:
                return [
                    (subtask.id or None, subtask.description)
                    for subtask in result.subtasks
                    if subtask.description
                ]
        except Exception:
            logger.warning("Workspace goal runtime decomposition failed", exc_info=True)
    return [(None, f"Execute goal: {query}")]


__all__ = ["_decompose_root_goal"]
