"""Task execution session recovery startup wiring."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, cast

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

if TYPE_CHECKING:
    from src.application.services.task_execution_session_recovery import (
        TaskExecutionSessionRecoveryService,
    )

logger = logging.getLogger(__name__)

_ENABLED_ENV = "WORKSPACE_TASK_EXECUTION_SESSION_RECOVERY_ENABLED"
_INTERVAL_ENV = "WORKSPACE_TASK_EXECUTION_SESSION_RECOVERY_INTERVAL_SECONDS"
_MAX_TASKS_ENV = "WORKSPACE_TASK_EXECUTION_SESSION_RECOVERY_MAX_TASKS_PER_SWEEP"
_COOLDOWN_ENV = "WORKSPACE_TASK_EXECUTION_SESSION_RECOVERY_ACTION_COOLDOWN_SECONDS"

_recovery: TaskExecutionSessionRecoveryService | None = None


def _enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV)
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, *, allow_zero: bool = False) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        parsed = int(raw.strip())
    except ValueError:
        return default
    if parsed > 0 or (allow_zero and parsed == 0):
        return parsed
    return default


async def initialize_task_execution_session_recovery(
    *,
    container: DIContainer,
    redis_client: redis.Redis | None,
) -> TaskExecutionSessionRecoveryService | None:
    """Start the task execution session recovery loop if enabled."""

    global _recovery

    if _recovery is not None and _recovery.is_running:
        return _recovery

    if not _enabled():
        logger.info(
            "task_execution_session_recovery.disabled",
            extra={"event": "task_execution_session_recovery.disabled"},
        )
        return None

    try:
        from src.application.services.task_execution_session_monitor import (
            TaskExecutionSessionMonitor,
        )
        from src.application.services.task_execution_session_recovery import (
            DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_ACTION_COOLDOWN_SECONDS,
            DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_INTERVAL_SECONDS,
            DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_MAX_TASKS_PER_SWEEP,
            TaskExecutionSessionRecoveryService,
        )

        def _monitor_factory(
            db: AsyncSession,
        ) -> tuple[TaskExecutionSessionMonitor, WorkspaceTaskCommandService]:
            scoped = container.with_db(db)
            task_service = WorkspaceTaskService(
                workspace_repo=scoped.workspace_repository(),
                workspace_member_repo=scoped.workspace_member_repository(),
                workspace_agent_repo=scoped.workspace_agent_repository(),
                workspace_task_repo=scoped.workspace_task_repository(),
            )
            command_service = WorkspaceTaskCommandService(task_service)
            return (
                TaskExecutionSessionMonitor(
                    db=db,
                    task_service=task_service,
                    command_service=command_service,
                    attempt_repo=scoped.workspace_task_session_attempt_repository(),
                ),
                command_service,
            )

        _recovery = TaskExecutionSessionRecoveryService(
            session_factory=cast(
                Callable[[], AbstractAsyncContextManager[AsyncSession]],
                async_session_factory,
            ),
            monitor_factory=_monitor_factory,
            redis_client=redis_client,
            check_interval_seconds=_int_env(
                _INTERVAL_ENV,
                DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_INTERVAL_SECONDS,
            ),
            max_tasks_per_sweep=_int_env(
                _MAX_TASKS_ENV,
                DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_MAX_TASKS_PER_SWEEP,
            ),
            action_cooldown_seconds=_int_env(
                _COOLDOWN_ENV,
                DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_ACTION_COOLDOWN_SECONDS,
                allow_zero=True,
            ),
        )
        await _recovery.start()
        return _recovery
    except Exception:
        logger.warning(
            "task_execution_session_recovery.start_failed",
            exc_info=True,
            extra={"event": "task_execution_session_recovery.start_failed"},
        )
        return None


async def shutdown_task_execution_session_recovery() -> None:
    global _recovery
    if _recovery is None:
        return
    try:
        await _recovery.stop()
    except Exception:
        logger.warning(
            "task_execution_session_recovery.stop_failed",
            exc_info=True,
            extra={"event": "task_execution_session_recovery.stop_failed"},
        )
    finally:
        _recovery = None


__all__ = [
    "initialize_task_execution_session_recovery",
    "shutdown_task_execution_session_recovery",
]
