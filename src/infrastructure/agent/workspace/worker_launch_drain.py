"""Post-commit drain helper for worker session launches.

``WorkspaceTaskCommandService`` queues ``(task, actor_user_id, leader_agent_id)``
triples whenever ``create_task`` / ``assign_task_to_agent`` touches an
execution task with an assignee. The queue exists because
``worker_launch.schedule_worker_session`` opens its own DB session and must
see the committed task state before it can look up the attempt / assignee.

Every write site that instantiates a ``WorkspaceTaskCommandService`` MUST
call :func:`drain_pending_worker_launches` after ``await db.commit()``.
Forgetting the drain leaves assigned execution tasks stranded in ``TODO``
with no running conversation — this was the root cause of the
``2c11849d-…`` workspace being stuck.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.infrastructure.agent.workspace import worker_launch as worker_launch_mod

if TYPE_CHECKING:
    from src.application.services.workspace_task_command_service import (
        WorkspaceTaskCommandService,
    )

logger = logging.getLogger(__name__)


def drain_pending_worker_launches(command_service: WorkspaceTaskCommandService) -> int:
    """Fire a worker session launch for every queued entry; return count fired.

    Safe to call even when the queue is empty. Exceptions are swallowed so
    that a downstream launch failure cannot roll back the caller's already-
    committed transaction — the launcher itself logs any errors.
    """
    try:
        pending = command_service.consume_pending_worker_launches()
    except Exception:
        logger.warning(
            "worker_launch.drain.consume_failed",
            extra={"event": "worker_launch.drain.consume_failed"},
            exc_info=True,
        )
        return 0
    fired = 0
    for task, actor_user_id, leader_agent_id in pending:
        worker_agent_id = getattr(task, "assignee_agent_id", None)
        if not worker_agent_id:
            continue
        try:
            worker_launch_mod.schedule_worker_session(
                workspace_id=task.workspace_id,
                task=task,
                worker_agent_id=worker_agent_id,
                actor_user_id=actor_user_id,
                leader_agent_id=leader_agent_id,
            )
            fired += 1
        except Exception:
            logger.warning(
                "worker_launch.drain.schedule_failed",
                extra={
                    "event": "worker_launch.drain.schedule_failed",
                    "workspace_id": getattr(task, "workspace_id", None),
                    "task_id": getattr(task, "id", None),
                    "worker_agent_id": worker_agent_id,
                },
                exc_info=True,
            )
    return fired


__all__ = ["drain_pending_worker_launches"]
