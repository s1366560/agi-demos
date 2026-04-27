"""Post-commit drain helper for worker session launches.

``WorkspaceTaskCommandService`` queues ``(task, actor_user_id, leader_agent_id)``
triples whenever ``create_task`` / ``assign_task_to_agent`` touches an
execution task with an assignee. The queue exists because
the worker-launch outbox handler opens its own DB session and must see the
committed task state before it can look up the attempt / assignee.

Async write sites that instantiate a ``WorkspaceTaskCommandService`` MUST call
:func:`drain_pending_worker_launches_to_outbox` after ``await db.commit()``.
Forgetting the drain leaves assigned execution tasks stranded in ``TODO``
with no running conversation — this was the root cause of the
``2c11849d-…`` workspace being stuck.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.application.services.workspace_task_command_service import (
        WorkspaceTaskCommandService,
    )
    from src.domain.model.workspace.workspace_task import WorkspaceTask

logger = logging.getLogger(__name__)

PendingWorkerLaunch = tuple["WorkspaceTask", str, str | None]


async def drain_pending_worker_launches_to_outbox(
    command_service: WorkspaceTaskCommandService,
    session: AsyncSession,
) -> int:
    """Durably enqueue queued worker launches.

    This is the preferred post-commit drain path for async request/runtime
    handlers. The enqueue transaction is committed here because callers invoke
    the drain only after their task mutation transaction is already committed.
    """

    pending = _consume_pending_worker_launches(command_service)
    launchable = [entry for entry in pending if _worker_agent_id(entry[0])]
    if not launchable:
        return 0
    try:
        for task, actor_user_id, leader_agent_id in launchable:
            await _enqueue_worker_launch(session, task, actor_user_id, leader_agent_id)
        await session.commit()
        return len(launchable)
    except Exception:
        try:
            await session.rollback()
        except Exception:
            logger.warning(
                "worker_launch.drain.rollback_failed",
                extra={"event": "worker_launch.drain.rollback_failed"},
                exc_info=True,
            )
        logger.warning(
            "worker_launch.drain.outbox_enqueue_failed",
            extra={"event": "worker_launch.drain.outbox_enqueue_failed"},
            exc_info=True,
        )
        raise


def _consume_pending_worker_launches(
    command_service: WorkspaceTaskCommandService,
) -> list[PendingWorkerLaunch]:
    try:
        return list(command_service.consume_pending_worker_launches())
    except Exception:
        logger.warning(
            "worker_launch.drain.consume_failed",
            extra={"event": "worker_launch.drain.consume_failed"},
            exc_info=True,
        )
        return []


async def _enqueue_worker_launch(
    session: AsyncSession,
    task: WorkspaceTask,
    actor_user_id: str,
    leader_agent_id: str | None,
) -> None:
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
        SqlWorkspacePlanOutboxRepository,
    )
    from src.infrastructure.agent.workspace_plan.outbox_handlers import WORKER_LAUNCH_EVENT

    worker_agent_id = _worker_agent_id(task)
    if not worker_agent_id:
        return
    metadata = _task_metadata(task)
    payload: dict[str, Any] = {
        "workspace_id": task.workspace_id,
        "task_id": task.id,
        "worker_agent_id": worker_agent_id,
        "actor_user_id": actor_user_id,
    }
    leader = _mapping_string(metadata, "leader_agent_id") or leader_agent_id
    if leader:
        payload["leader_agent_id"] = leader
    attempt_id = _mapping_string(metadata, CURRENT_ATTEMPT_ID)
    if attempt_id:
        payload["attempt_id"] = attempt_id
    node_id = _mapping_string(metadata, WORKSPACE_PLAN_NODE_ID)
    if node_id:
        payload["node_id"] = node_id

    _ = await SqlWorkspacePlanOutboxRepository(session).enqueue(
        plan_id=_mapping_string(metadata, WORKSPACE_PLAN_ID),
        workspace_id=task.workspace_id,
        event_type=WORKER_LAUNCH_EVENT,
        payload=payload,
        metadata={"source": "workspace.worker_launch_drain"},
    )


def _worker_agent_id(task: WorkspaceTask) -> str | None:
    value = getattr(task, "assignee_agent_id", None)
    if isinstance(value, str) and value:
        return value
    return None


def _task_metadata(task: WorkspaceTask) -> dict[str, Any]:
    metadata = getattr(task, "metadata", {})
    return dict(metadata) if isinstance(metadata, dict) else {}


def _mapping_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


__all__ = ["drain_pending_worker_launches_to_outbox"]
