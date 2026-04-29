"""Workspace Autonomy Idle Waker — periodic wake-up for stuck workspace goals.

When no worker ever submits a terminal report (e.g., initial decomposition
never happened, or leader crashed mid-execution), the P1 auto-tick hook is
never triggered and the workspace goal sits idle forever.

This service periodically scans for active workspaces that have a non-terminal
``goal_root`` task and schedules an autonomy tick for each one. The existing
per-root cooldown (60s) and per-workspace inflight dedup naturally prevent
spamming; the wake loop only provides a lower-bound heartbeat so forgotten
goals eventually get re-examined. Sweeps are bounded so startup/reload cannot
wake every historical goal at once.

Enabled by default. Disable via ``WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED=false``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceModel,
    WorkspaceTaskModel,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    TASK_ROLE,
)

logger = logging.getLogger(__name__)


# Root statuses that should not be reawakened by the idle waker.
#
# A blocked root needs explicit repair / replan input; blindly waking it during
# startup can revive every stale child node in historical workspaces and flood a
# shared sandbox.
_TERMINAL_ROOT_STATUSES: frozenset[str] = frozenset(
    {
        WorkspaceTaskStatus.DONE.value,
        WorkspaceTaskStatus.BLOCKED.value,
    }
)


class WorkspaceAutonomyIdleWaker:
    """Background loop that nudges idle workspace goals back into motion.

    Each sweep:
      1. Opens a fresh ``AsyncSession`` via ``session_factory()``.
      2. Selects active workspaces with at least one active ``goal_root``
         task (no archived, no terminal root state).
      3. For each eligible root, calls ``schedule_autonomy_tick(workspace_id,
         actor_user_id)``. The scheduler itself honors the existing cooldown
         and inflight-dedup, so a fresh tick does not fire if one ran recently.

    The loop sleeps ``check_interval_seconds`` between sweeps. ``stop()``
    cancels the task cleanly.
    """

    def __init__(
        self,
        *,
        check_interval_seconds: int,
        session_factory: Callable[[], AsyncSession],
        schedule_tick: Callable[[str, str], None],
        max_roots_per_sweep: int = 3,
        max_root_idle_age_seconds: int = 86_400,
    ) -> None:
        if check_interval_seconds <= 0:
            msg = f"check_interval_seconds must be > 0, got {check_interval_seconds}"
            raise ValueError(msg)
        if max_roots_per_sweep <= 0:
            msg = f"max_roots_per_sweep must be > 0, got {max_roots_per_sweep}"
            raise ValueError(msg)
        if max_root_idle_age_seconds <= 0:
            msg = (
                "max_root_idle_age_seconds must be > 0, "
                f"got {max_root_idle_age_seconds}"
            )
            raise ValueError(msg)
        self._check_interval_seconds = check_interval_seconds
        self._max_roots_per_sweep = max_roots_per_sweep
        self._max_root_idle_age_seconds = max_root_idle_age_seconds
        self._session_factory = session_factory
        self._schedule_tick = schedule_tick
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            logger.debug("WorkspaceAutonomyIdleWaker already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="workspace-autonomy-idle-waker")
        logger.info(
            "workspace_autonomy_idle_waker.started",
            extra={
                "event": "workspace_autonomy_idle_waker.started",
                "check_interval_seconds": self._check_interval_seconds,
                "max_roots_per_sweep": self._max_roots_per_sweep,
                "max_root_idle_age_seconds": self._max_root_idle_age_seconds,
            },
        )

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        logger.info(
            "workspace_autonomy_idle_waker.stopped",
            extra={"event": "workspace_autonomy_idle_waker.stopped"},
        )

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "workspace_autonomy_idle_waker.sweep_failed",
                    exc_info=True,
                    extra={"event": "workspace_autonomy_idle_waker.sweep_failed"},
                )
            try:
                await asyncio.sleep(self._check_interval_seconds)
            except asyncio.CancelledError:
                raise

    async def _sweep_once(self) -> int:
        """Run a single sweep. Returns count of workspaces nudged."""
        rows = await self._fetch_eligible_roots()
        nudged = 0
        for workspace_id, actor_user_id, root_task_id in rows:
            try:
                self._schedule_tick(workspace_id, actor_user_id)
                nudged += 1
            except Exception:
                logger.warning(
                    "workspace_autonomy_idle_waker.schedule_failed",
                    exc_info=True,
                    extra={
                        "event": "workspace_autonomy_idle_waker.schedule_failed",
                        "workspace_id": workspace_id,
                        "root_task_id": root_task_id,
                    },
                )
        if nudged > 0:
            logger.info(
                "workspace_autonomy_idle_waker.sweep_done",
                extra={
                    "event": "workspace_autonomy_idle_waker.sweep_done",
                    "nudged": nudged,
                },
            )
        return nudged

    async def _fetch_eligible_roots(self) -> list[tuple[str, str, str]]:
        """Return (workspace_id, actor_user_id, root_task_id) for eligible roots.

        Eligibility:
          - Workspace is active (``status != 'archived'``).
          - Root task has ``metadata_json.task_role == 'goal_root'``.
          - Root task is not archived.
          - Root task status is not terminal.
          - Roots must have changed recently enough to be considered active.
          - Most recently active roots are considered first, up to the configured
            per-sweep cap.

        Cooldown is NOT checked here — it is enforced downstream by
        ``maybe_auto_trigger_existing_root_execution``.
        """
        async with self._session_factory() as session:
            last_activity = func.coalesce(
                WorkspaceTaskModel.updated_at,
                WorkspaceTaskModel.created_at,
            )
            cutoff = datetime.now(UTC) - timedelta(seconds=self._max_root_idle_age_seconds)
            query = (
                select(
                    WorkspaceTaskModel.workspace_id,
                    WorkspaceTaskModel.created_by,
                    WorkspaceTaskModel.id,
                )
                .join(WorkspaceModel, WorkspaceModel.id == WorkspaceTaskModel.workspace_id)
                .where(WorkspaceTaskModel.metadata_json[TASK_ROLE].as_string() == "goal_root")
                .where(WorkspaceTaskModel.archived_at.is_(None))
                .where(WorkspaceTaskModel.status.notin_(list(_TERMINAL_ROOT_STATUSES)))
                .where(WorkspaceModel.is_archived.is_(False))
                .where(last_activity >= cutoff)
                .order_by(
                    last_activity.desc(),
                    WorkspaceTaskModel.created_at.desc(),
                    WorkspaceTaskModel.id.asc(),
                )
                .limit(self._max_roots_per_sweep)
            )
            result = await session.execute(refresh_select_statement(query))
            return [(row[0], row[1], row[2]) for row in result.all()]
