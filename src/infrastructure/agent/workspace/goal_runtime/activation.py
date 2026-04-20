"""Workspace authority activation rules + decomposer Protocol.

``should_activate_workspace_authority`` decides whether a given turn
triggers the workspace autonomy codepath. Extracted from the original
``workspace_goal_runtime`` God module so the activation heuristic is
independently testable and re-usable by the V2 orchestrator.
"""

from __future__ import annotations

import re
from typing import Protocol

from src.infrastructure.agent.subagent.task_decomposer import DecompositionResult

_WORKSPACE_AUTONOMY_INTENT = re.compile(
    (
        r"\b(workspace|goal|objective|task|tasks)\b.*"
        r"\b(autonomy|execute|execution|plan|decompose|complete|finish|break down)\b"
        r"|\b(autonomy|execute|execution|plan|decompose|complete|finish|break down)\b.*"
        r"\b(workspace|goal|objective|task|tasks)\b"
    ),
    re.IGNORECASE,
)

_WORKSPACE_TASK_ID_PATTERN = re.compile(
    r"(?:workspace_task_id|task_id|child_task_id)\s*[:=]\s*([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)


def should_activate_workspace_authority(
    user_query: str,
    *,
    has_workspace_binding: bool = False,
    has_open_root: bool = False,
) -> bool:
    """Decide whether to run workspace autonomy for this turn.

    Activation is true when any of the following holds:
    - ``has_workspace_binding`` — the turn is a worker/subagent continuation
      that carries a ``[workspace-task-binding]`` marker;
    - ``has_open_root`` — the caller already knows the workspace has an
      open goal-root task needing progress (e.g. the manual ``/autonomy/tick``
      endpoint looked it up);
    - the English intent regex matches the user query (fallback for
      natural-language triggers).
    """
    if has_workspace_binding or has_open_root:
        return True
    return bool(_WORKSPACE_AUTONOMY_INTENT.search(user_query or ""))


class TaskDecomposerProtocol(Protocol):
    async def decompose(self, query: str) -> DecompositionResult: ...


__all__ = [
    "_WORKSPACE_AUTONOMY_INTENT",
    "_WORKSPACE_TASK_ID_PATTERN",
    "TaskDecomposerProtocol",
    "should_activate_workspace_authority",
]
