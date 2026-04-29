"""Startup wiring for :class:`WorkspaceAttemptRecoveryService`.

Always-on. Runs a sweep at boot to recover orphaned attempts left over from
a prior process and then starts the periodic watchdog loop that rescues
attempts stale from this process.

Disable only for tests / emergencies via
``WORKSPACE_ATTEMPT_RECOVERY_ENABLED=false``.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

if TYPE_CHECKING:
    from src.domain.model.workspace.workspace_task_session_attempt import (
        WorkspaceTaskSessionAttempt,
    )
    from src.infrastructure.agent.workspace.workspace_attempt_recovery import (
        WorkspaceAttemptRecoveryService,
    )

logger = logging.getLogger(__name__)

_ENABLED_ENV = "WORKSPACE_ATTEMPT_RECOVERY_ENABLED"
_STALE_ENV = "WORKSPACE_ATTEMPT_RECOVERY_STALE_SECONDS"
_INTERVAL_ENV = "WORKSPACE_ATTEMPT_RECOVERY_INTERVAL_SECONDS"
_GRACE_ENV = "WORKSPACE_ATTEMPT_RECOVERY_STARTUP_GRACE_SECONDS"
_MAX_ATTEMPTS_ENV = "WORKSPACE_ATTEMPT_RECOVERY_MAX_ATTEMPTS_PER_SWEEP"
_ERROR_EVENT_GRACE_ENV = "WORKSPACE_ATTEMPT_RECOVERY_ERROR_EVENT_GRACE_SECONDS"

_recovery: WorkspaceAttemptRecoveryService | None = None


def _enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV)
    if raw is None:
        return True  # always-on by default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


async def _enqueue_handoff_resume(
    attempt: WorkspaceTaskSessionAttempt,
    summary: str,
    actor_user_id: str,
) -> None:
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
        SqlWorkspacePlanOutboxRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
        SqlWorkspaceTaskRepository,
    )
    from src.infrastructure.agent.workspace.workspace_metadata_keys import (
        ROOT_GOAL_TASK_ID,
        WORKSPACE_PLAN_ID,
        WORKSPACE_PLAN_NODE_ID,
    )
    from src.infrastructure.agent.workspace_plan.outbox_handlers import HANDOFF_RESUME_EVENT

    async with async_session_factory() as db:
        task = await SqlWorkspaceTaskRepository(db).find_by_id(attempt.workspace_task_id)
        if task is None:
            return
        worker_agent_id = attempt.worker_agent_id or task.assignee_agent_id
        if not worker_agent_id:
            return

        metadata = dict(task.metadata or {})
        raw_plan_id = metadata.get(WORKSPACE_PLAN_ID)
        plan_id = raw_plan_id if isinstance(raw_plan_id, str) and raw_plan_id else None
        raw_node_id = metadata.get(WORKSPACE_PLAN_NODE_ID)
        node_id = raw_node_id if isinstance(raw_node_id, str) and raw_node_id else None
        root_goal_task_id = attempt.root_goal_task_id
        if not root_goal_task_id:
            raw_root_id = metadata.get(ROOT_GOAL_TASK_ID)
            root_goal_task_id = raw_root_id if isinstance(raw_root_id, str) else ""

        _ = await SqlWorkspacePlanOutboxRepository(db).enqueue(
            plan_id=plan_id,
            workspace_id=attempt.workspace_id,
            event_type=HANDOFF_RESUME_EVENT,
            payload={
                "workspace_id": attempt.workspace_id,
                "task_id": attempt.workspace_task_id,
                "node_id": node_id,
                "worker_agent_id": worker_agent_id,
                "actor_user_id": actor_user_id,
                "leader_agent_id": attempt.leader_agent_id,
                "previous_attempt_id": attempt.id,
                "root_goal_task_id": root_goal_task_id,
                "summary": summary,
                "reason": "worker_restart"
                if summary == "recovered_after_restart_no_heartbeat"
                else "retry",
                "force_schedule": True,
            },
            metadata={
                "source": "workspace_attempt_recovery",
                "previous_attempt_id": attempt.id,
            },
        )
        await db.commit()


async def initialize_attempt_recovery() -> WorkspaceAttemptRecoveryService | None:
    global _recovery

    if _recovery is not None and _recovery.is_running:
        return _recovery

    if not _enabled():
        logger.info(
            "workspace_attempt_recovery.disabled",
            extra={"event": "workspace_attempt_recovery.disabled"},
        )
        return None

    try:
        from src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap import (
            schedule_autonomy_tick,
        )
        from src.infrastructure.agent.workspace.workspace_attempt_recovery import (
            DEFAULT_CHECK_INTERVAL_SECONDS,
            DEFAULT_ERROR_EVENT_GRACE_SECONDS,
            DEFAULT_MAX_ATTEMPTS_PER_SWEEP,
            DEFAULT_STALE_SECONDS,
            DEFAULT_STARTUP_GRACE_SECONDS,
            WorkspaceAttemptRecoveryService,
        )
        from src.infrastructure.agent.workspace.workspace_goal_runtime import (
            apply_workspace_worker_report,
        )
        from src.infrastructure.agent.workspace.workspace_supervisor import (
            get_workspace_supervisor,
        )

        stale_seconds = _int_env(_STALE_ENV, DEFAULT_STALE_SECONDS)
        check_interval_seconds = _int_env(_INTERVAL_ENV, DEFAULT_CHECK_INTERVAL_SECONDS)
        startup_grace_seconds = _int_env(_GRACE_ENV, DEFAULT_STARTUP_GRACE_SECONDS)
        max_attempts_per_sweep = _int_env(
            _MAX_ATTEMPTS_ENV, DEFAULT_MAX_ATTEMPTS_PER_SWEEP
        )
        error_event_grace_seconds = _int_env(
            _ERROR_EVENT_GRACE_ENV, DEFAULT_ERROR_EVENT_GRACE_SECONDS
        )

        def _liveness_lookup() -> list[str]:
            supervisor = get_workspace_supervisor()
            if supervisor is None:
                return []
            snapshot = supervisor.get_liveness_snapshot()
            current_monotonic = time.monotonic()
            max_live_age = stale_seconds + check_interval_seconds + 5
            live: list[str] = []
            for attempt_id, info in snapshot.items():
                last_seen = info.get("last_seen_monotonic")
                if not isinstance(last_seen, int | float):
                    continue
                if current_monotonic - last_seen <= max_live_age:
                    live.append(attempt_id)
            return live

        _recovery = WorkspaceAttemptRecoveryService(
            session_factory=async_session_factory,
            apply_report=apply_workspace_worker_report,
            schedule_tick=schedule_autonomy_tick,
            enqueue_resume=_enqueue_handoff_resume,
            liveness_lookup=_liveness_lookup,
            stale_seconds=stale_seconds,
            startup_grace_seconds=startup_grace_seconds,
            check_interval_seconds=check_interval_seconds,
            max_attempts_per_sweep=max_attempts_per_sweep,
            error_event_grace_seconds=error_event_grace_seconds,
        )
        await _recovery.start()
        return _recovery
    except Exception:
        logger.warning(
            "workspace_attempt_recovery.start_failed",
            exc_info=True,
            extra={"event": "workspace_attempt_recovery.start_failed"},
        )
        return None


async def recover_workspace_attempts_once(workspace_id: str) -> int:
    recovery = await initialize_attempt_recovery()
    if recovery is None:
        return 0
    return await recovery.workspace_sweep(workspace_id)


async def shutdown_attempt_recovery() -> None:
    global _recovery
    if _recovery is None:
        return
    try:
        await _recovery.stop()
    except Exception:
        logger.warning(
            "workspace_attempt_recovery.stop_failed",
            exc_info=True,
            extra={"event": "workspace_attempt_recovery.stop_failed"},
        )
    finally:
        _recovery = None
