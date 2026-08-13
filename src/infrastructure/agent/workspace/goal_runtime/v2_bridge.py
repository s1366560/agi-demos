"""Compatibility boundary for the retired Python Workspace Plan V2 kickoff.

Avernet Workspace Core owns Plan creation, idempotency, outbox progression, and
task linkage. Python callers must not recreate that authority from platform SQL.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.agent.workspace_plan.orchestrator import WorkspaceOrchestrator

logger = logging.getLogger(__name__)

_orchestrator_singleton: WorkspaceOrchestrator | None = None
_SOFTWARE_ITERATION_PHASES = ("research", "plan", "implement", "test", "deploy", "review")


class LegacyWorkspacePlanRuntimeRetiredError(RuntimeError):
    """Raised when a caller tries to execute the retired Python Plan runtime."""


def set_orchestrator_singleton_for_testing(orchestrator: WorkspaceOrchestrator | None) -> None:
    """Retain the historical test seam without enabling production SQL authority."""
    global _orchestrator_singleton
    _orchestrator_singleton = orchestrator


def reset_orchestrator_singleton_for_testing() -> None:
    """Clear the historical in-memory test seam."""
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
    """Reject production SQL kickoff after Core became Plan authority.

    An explicitly injected in-memory orchestrator remains available to isolated
    domain tests. It cannot read or mutate platform Workspace persistence.
    """
    if _orchestrator_singleton is not None:
        _ = await _orchestrator_singleton.start_goal(
            workspace_id=workspace_id,
            title=title,
            description=description,
            created_by=created_by,
        )
        return True

    _ = root_task_id, leader_agent_id
    logger.warning(
        "Python Workspace Plan V2 kickoff is retired; Avernet Core owns plan progression",
        extra={"workspace_id": workspace_id},
    )
    raise LegacyWorkspacePlanRuntimeRetiredError(
        "Python Workspace Plan V2 kickoff is retired; use Avernet Workspace Core"
    )


def _workspace_iteration_decomposition_context(
    *,
    workspace_type: str,
    max_subtasks: int,
) -> str | None:
    """Keep the pure anti-documentation planning guidance available to Core dispatch."""
    if workspace_type != "software_development":
        return None
    phases = ", ".join(_SOFTWARE_ITERATION_PHASES)
    return (
        "Software workspace planning contract: create only the current Scrum-style sprint, "
        f"using at most {max_subtasks} subtasks. Cover phases in this order when possible: "
        f"{phases}. IMPLEMENTATION FIRST: every subtask must change application code, tests, "
        "configs, schemas, or infrastructure. No subtask may be purely documentation. "
        "Required README, CHANGELOG, architecture, INDEX.md, and acceptance-evidence updates "
        "must be embedded in the implementation or verification subtask that owns the change."
    )


__all__ = [
    "LegacyWorkspacePlanRuntimeRetiredError",
    "_workspace_iteration_decomposition_context",
    "kickoff_v2_plan",
    "reset_orchestrator_singleton_for_testing",
    "set_orchestrator_singleton_for_testing",
]
