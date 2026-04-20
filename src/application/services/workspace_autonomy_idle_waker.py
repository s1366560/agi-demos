"""Workspace Autonomy Idle Waker — periodic wake-up for stuck workspace goals.

When no worker ever submits a terminal report (e.g., initial decomposition
never happened, or leader crashed mid-execution), the P1 auto-tick hook is
never triggered and the workspace goal sits idle forever.

This service periodically scans for active workspaces that have a non-terminal
``goal_root`` task and schedules an autonomy tick for each one. The existing
per-root cooldown (60s) and per-workspace inflight dedup naturally prevent
spamming; the wake loop only provides a lower-bound heartbeat so forgotten
goals eventually get re-examined.

Disabled by default. Enable via ``WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED=true``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceModel,
    WorkspaceTaskModel,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    TASK_ROLE,
)

logger = logging.getLogger(__name__)


# Tasks whose status still permits further autonomy progress.
# ``done`` is terminal; ``cancelled`` / ``failed`` are not used for goal roots
# in practice, so we treat anything other than ``done`` as eligible.
_TERMINAL_ROOT_STATUSES: frozenset[str] = frozenset({"done"})


class WorkspaceAutonomyIdleWaker:
    """Background loop that nudges idle workspace goals back into motion.

    Each sweep:
      1. Opens a fresh ``AsyncSession`` via ``session_factory()``.
      2. Selects active workspaces with at least one non-terminal ``goal_root``
         task (no archived, no ``done``).
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
    ) -> None:
        if check_interval_seconds <= 0:
            msg = f"check_interval_seconds must be > 0, got {check_interval_seconds}"
            raise ValueError(msg)
        self._check_interval_seconds = check_interval_seconds
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
          - Root task status is not terminal (``done``).

        Cooldown is NOT checked here — it is enforced downstream by
        ``maybe_auto_trigger_existing_root_execution``.
        """
        async with self._session_factory() as session:
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
            )
            result = await session.execute(query)
            return [(row[0], row[1], row[2]) for row in result.all()]
