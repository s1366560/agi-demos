"""Workspace autonomy idle waker initialization for startup.

Periodically scans for workspaces with non-terminal ``goal_root`` tasks and
schedules an autonomy tick for each, so initial decomposition or idle goals
eventually get re-examined without a human click.

Opt-in. Disabled by default; enable with
``WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED=true``.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

if TYPE_CHECKING:
    from src.application.services.workspace_autonomy_idle_waker import (
        WorkspaceAutonomyIdleWaker,
    )

logger = logging.getLogger(__name__)

_ENABLED_ENV = "WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED"
_INTERVAL_ENV = "WORKSPACE_AUTONOMY_IDLE_WAKE_INTERVAL_SECONDS"
_DEFAULT_INTERVAL_SECONDS = 300

# Module-level reference for shutdown
_idle_waker: WorkspaceAutonomyIdleWaker | None = None


def _enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV)
    if raw is None:
        return False  # opt-in: default OFF
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _interval_seconds() -> int:
    raw = os.environ.get(_INTERVAL_ENV)
    if raw is None:
        return _DEFAULT_INTERVAL_SECONDS
    try:
        parsed = int(raw.strip())
    except ValueError:
        return _DEFAULT_INTERVAL_SECONDS
    return parsed if parsed > 0 else _DEFAULT_INTERVAL_SECONDS


async def initialize_autonomy_idle_waker() -> WorkspaceAutonomyIdleWaker | None:
    """Start the idle-waker background loop if enabled."""
    global _idle_waker

    if not _enabled():
        logger.info(
            "workspace_autonomy_idle_waker.disabled",
            extra={"event": "workspace_autonomy_idle_waker.disabled"},
        )
        return None

    try:
        from src.application.services.workspace_autonomy_idle_waker import (
            WorkspaceAutonomyIdleWaker,
        )
        from src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap import (
            schedule_autonomy_tick,
        )

        _idle_waker = WorkspaceAutonomyIdleWaker(
            check_interval_seconds=_interval_seconds(),
            session_factory=async_session_factory,
            schedule_tick=schedule_autonomy_tick,
        )
        _idle_waker.start()
        return _idle_waker
    except Exception:
        logger.warning(
            "workspace_autonomy_idle_waker.start_failed",
            exc_info=True,
            extra={"event": "workspace_autonomy_idle_waker.start_failed"},
        )
        return None


async def shutdown_autonomy_idle_waker() -> None:
    global _idle_waker
    if _idle_waker is None:
        return
    try:
        await _idle_waker.stop()
    except Exception:
        logger.warning(
            "workspace_autonomy_idle_waker.stop_failed",
            exc_info=True,
            extra={"event": "workspace_autonomy_idle_waker.stop_failed"},
        )
    finally:
        _idle_waker = None
