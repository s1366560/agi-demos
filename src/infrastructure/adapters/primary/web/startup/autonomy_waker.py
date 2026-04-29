"""Workspace autonomy idle waker initialization for startup.

Periodically scans for workspaces with non-terminal ``goal_root`` tasks and
schedules an autonomy tick for each, so initial decomposition or idle goals
eventually get re-examined without a human click.

Enabled by default; disable with
``WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED=false``. Sweeps are capped with
``WORKSPACE_AUTONOMY_IDLE_WAKE_MAX_ROOTS_PER_SWEEP`` to avoid startup storms.
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
_MAX_ROOTS_ENV = "WORKSPACE_AUTONOMY_IDLE_WAKE_MAX_ROOTS_PER_SWEEP"
_MAX_ROOT_IDLE_AGE_ENV = "WORKSPACE_AUTONOMY_IDLE_WAKE_MAX_ROOT_IDLE_AGE_SECONDS"
_DEFAULT_INTERVAL_SECONDS = 60
_DEFAULT_MAX_ROOTS_PER_SWEEP = 3
_DEFAULT_MAX_ROOT_IDLE_AGE_SECONDS = 86_400

# Module-level reference for shutdown
_idle_waker: WorkspaceAutonomyIdleWaker | None = None


def _enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV)
    if raw is None:
        return True
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


def _max_roots_per_sweep() -> int:
    raw = os.environ.get(_MAX_ROOTS_ENV)
    if raw is None:
        return _DEFAULT_MAX_ROOTS_PER_SWEEP
    try:
        parsed = int(raw.strip())
    except ValueError:
        return _DEFAULT_MAX_ROOTS_PER_SWEEP
    return parsed if parsed > 0 else _DEFAULT_MAX_ROOTS_PER_SWEEP


def _max_root_idle_age_seconds() -> int:
    raw = os.environ.get(_MAX_ROOT_IDLE_AGE_ENV)
    if raw is None:
        return _DEFAULT_MAX_ROOT_IDLE_AGE_SECONDS
    try:
        parsed = int(raw.strip())
    except ValueError:
        return _DEFAULT_MAX_ROOT_IDLE_AGE_SECONDS
    return parsed if parsed > 0 else _DEFAULT_MAX_ROOT_IDLE_AGE_SECONDS


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
            max_roots_per_sweep=_max_roots_per_sweep(),
            max_root_idle_age_seconds=_max_root_idle_age_seconds(),
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
