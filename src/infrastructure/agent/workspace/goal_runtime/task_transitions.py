"""Small state-transition helpers shared by workspace goal-runtime coordinators.

Extracted from :mod:`workspace_goal_runtime` so that the two big coordinator
functions (``apply_workspace_worker_report`` / ``adjudicate_workspace_worker_report``)
can in the future move to their own module without dragging their leaf helpers
along or relying on circular module-level imports.

These helpers are pure orchestration glue — they take injected services
(``command_service``, ``attempt_service``) and a task, mutate them via the
public API, and return the updated domain entity. They do NOT open their own
DB session.
"""

from __future__ import annotations

from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import WorkspaceTaskAuthorityContext
from src.application.services.workspace_task_session_attempt_service import (
    WorkspaceTaskSessionAttemptService,
)
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    ROOT_GOAL_TASK_ID,
)

# Constants previously defined at module level of ``workspace_goal_runtime``.
MAX_AUTO_REPLAN_ATTEMPTS = 2
WORKER_TERMINAL_REPORT_TYPES: frozenset[str] = frozenset(
    {"completed", "failed", "blocked", "needs_replan"}
)


async def ensure_root_task_started(
    *,
    workspace_id: str,
    root_task: WorkspaceTask,
    actor_user_id: str,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
    reason: str,
) -> WorkspaceTask:
    """Start the root task if it is still in the TODO state; no-op otherwise."""
    status_value = getattr(
        getattr(root_task, "status", None), "value", getattr(root_task, "status", None)
    )
    root_task_id = getattr(root_task, "id", None)
    if not isinstance(root_task_id, str) or status_value != "todo":
        return root_task

    return await command_service.start_task(
        workspace_id=workspace_id,
        task_id=root_task_id,
        actor_user_id=actor_user_id,
        actor_type="agent",
        actor_agent_id=leader_agent_id,
        reason=reason,
        authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
    )


async def ensure_execution_attempt(
    *,
    attempt_service: WorkspaceTaskSessionAttemptService,
    task: WorkspaceTask,
    leader_agent_id: str | None,
) -> WorkspaceTaskSessionAttempt:
    """Return the active execution attempt for ``task``, creating one if needed."""
    existing_attempt = await attempt_service.get_active_attempt(task.id)
    if existing_attempt is not None:
        return existing_attempt
    attempt = await attempt_service.create_attempt(
        workspace_task_id=task.id,
        root_goal_task_id=str(task.metadata.get(ROOT_GOAL_TASK_ID) or ""),
        workspace_id=task.workspace_id,
        worker_agent_id=task.assignee_agent_id,
        leader_agent_id=leader_agent_id,
    )
    return await attempt_service.mark_running(attempt.id)


__all__ = [
    "MAX_AUTO_REPLAN_ATTEMPTS",
    "WORKER_TERMINAL_REPORT_TYPES",
    "ensure_execution_attempt",
    "ensure_root_task_started",
]
