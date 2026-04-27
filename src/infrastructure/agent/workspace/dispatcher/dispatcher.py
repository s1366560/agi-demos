"""Execution-task dispatcher (P2d M2).

Pure, stateless logic for choosing which worker binding should receive a newly
created execution task, plus the thin wrapper that calls
``WorkspaceTaskCommandService.assign_task_to_agent``.

This module is the first runtime consumer of
:mod:`src.infrastructure.agent.workspace.state_machine` — we assert that the
planned ``TODO → DISPATCHED`` transition is legal before invoking the command
service. An illegal status (e.g. the task is already DISPATCHED, or terminally
DONE) produces a structured WARN log and the task is skipped. The dispatcher
never raises: assignment failures are a scheduling concern, not a contract
violation.

Behavior intentionally matches the current ``_assign_execution_tasks_to_workers``
contract (same filter, same stable sort, same round-robin), so wiring this in
is a pure refactor covered by the workspace_goal_runtime regression tests.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import WorkspaceTaskAuthorityContext
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.infrastructure.agent.workspace.state_machine import (
    IllegalTransitionError,
    TaskRole,
    transition,
)

logger = logging.getLogger(__name__)

__all__ = [
    "assign_execution_tasks_round_robin",
    "filter_worker_bindings",
    "pair_tasks_with_workers",
    "sort_bindings",
]


def filter_worker_bindings(
    bindings: Sequence[WorkspaceAgent],
    *,
    leader_agent_id: str | None,
) -> list[WorkspaceAgent]:
    """Return the subset of ``bindings`` eligible to receive execution tasks.

    Rules:
    * Prefer bindings whose ``agent_id`` differs from the leader.
    * If that filter would leave the pool empty (leader is the only active
      agent), fall back to the full active list — the leader dispatches to
      itself rather than stalling.
    """
    if not bindings:
        return []
    non_leader = [b for b in bindings if b.agent_id != leader_agent_id]
    if non_leader:
        return non_leader
    return list(bindings)


def sort_bindings(bindings: Sequence[WorkspaceAgent]) -> list[WorkspaceAgent]:
    """Stable sort bindings by display_name, label, agent_id, id."""
    return sorted(
        bindings,
        key=lambda binding: (
            binding.display_name or "",
            binding.label or "",
            binding.agent_id,
            binding.id,
        ),
    )


def pair_tasks_with_workers(
    tasks: Sequence[WorkspaceTask],
    workers: Sequence[WorkspaceAgent],
) -> list[tuple[WorkspaceTask, WorkspaceAgent]]:
    """Round-robin pair tasks with workers. Pure.

    Returns empty list if either input is empty. Worker order is taken as-is
    (caller is expected to have sorted); the `i`-th task goes to
    ``workers[i % len(workers)]``.
    """
    if not tasks or not workers:
        return []
    pairs: list[tuple[WorkspaceTask, WorkspaceAgent]] = []
    for index, task in enumerate(tasks):
        pairs.append((task, workers[index % len(workers)]))
    return pairs


def _can_dispatch(task: WorkspaceTask) -> bool:
    """Guard: only tasks currently in TODO can be dispatched.

    Returns False and emits a structured WARN for any illegal state — callers
    skip the task rather than abort the whole batch.
    """
    try:
        transition(TaskRole.EXECUTION, task.status, WorkspaceTaskStatus.DISPATCHED)
    except IllegalTransitionError as err:
        logger.warning(
            "workspace_dispatcher.skip_illegal_state",
            extra={
                "task_id": task.id,
                "workspace_id": task.workspace_id,
                "current_status": task.status.value,
                "target_status": WorkspaceTaskStatus.DISPATCHED.value,
                "reasons": err.reasons,
            },
        )
        return False
    return True


async def assign_execution_tasks_round_robin(
    *,
    workspace_id: str,
    actor_user_id: str,
    created_tasks: Sequence[WorkspaceTask],
    active_bindings: Sequence[WorkspaceAgent],
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
    reason: str,
) -> int:
    """Assign ``created_tasks`` to worker bindings round-robin.

    Returns the number of tasks actually assigned (tasks skipped due to
    illegal state or missing resources are not counted). Never raises for
    per-task assignment failures; those are logged and skipped.

    This is a thin orchestration wrapper; selection logic lives in the pure
    helpers above and is directly unit-tested.
    """
    if not created_tasks or not leader_agent_id or not active_bindings:
        return 0

    workers = sort_bindings(
        filter_worker_bindings(active_bindings, leader_agent_id=leader_agent_id)
    )
    if not workers:
        return 0

    dispatchable = [t for t in created_tasks if _can_dispatch(t)]
    if not dispatchable:
        return 0

    pairs = pair_tasks_with_workers(dispatchable, workers)
    assigned = 0
    for task, binding in pairs:
        try:
            _ = await command_service.assign_task_to_agent(
                workspace_id=workspace_id,
                task_id=task.id,
                actor_user_id=actor_user_id,
                workspace_agent_id=binding.id,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason=reason,
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )
            assigned += 1
        except Exception as exc:
            logger.warning(
                "workspace_dispatcher.assign_failed",
                extra={
                    "task_id": task.id,
                    "binding_id": binding.id,
                    "workspace_id": workspace_id,
                    "error": str(exc),
                },
                exc_info=True,
            )
    return assigned
