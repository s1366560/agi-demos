"""Recovery service for workspace task session attempts that were orphaned.

The in-process ``WorkspaceSupervisor._liveness`` map tracks "is this attempt
alive?" using heartbeat envelopes received on the WTP stream. On a backend
restart (or crash) that map is lost, so any attempt left in a non-terminal
status (``pending``, ``running``, ``awaiting_leader_adjudication``) can never
be flipped by the supervisor watchdog — it silently stalls forever.

This service closes the gap with two sweeps:

* ``startup_sweep`` — runs once at API boot. Finds every non-terminal attempt
  older than a small grace window and marks it ``blocked`` via
  :func:`apply_workspace_worker_report`, then schedules an autonomy tick for
  each unique parent root goal so the leader can re-plan.

* ``periodic_sweep`` — runs on an interval. Same logic, but only flips
  attempts that have been stale longer than ``stale_seconds`` AND are *not*
  currently tracked by the supervisor liveness map. This prevents us from
  clobbering attempts that are alive in this process.

Always-on. Unlike :class:`WorkspaceAutonomyIdleWaker`, which only nudges the
root goal, this service rescues *execution* attempts — without it a single
restart leaves subtasks stuck forever and the whole goal grinds to a halt.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_session_attempt_repository import (
    SqlWorkspaceTaskSessionAttemptRepository,
)

logger = logging.getLogger(__name__)

# Defaults chosen to stay well clear of normal in-flight latency but not so
# long that a user sees a stalled workspace for many minutes after a restart.
DEFAULT_STALE_SECONDS = 180
DEFAULT_STARTUP_GRACE_SECONDS = 15
DEFAULT_CHECK_INTERVAL_SECONDS = 60
RECOVERY_SUMMARY_RESTART = "recovered_after_restart_no_heartbeat"
RECOVERY_SUMMARY_STALE = "recovered_stale_no_heartbeat"


ApplyReportCallable = Callable[..., Awaitable[object]]
LivenessLookup = Callable[[], Iterable[str]]
ScheduleTickCallable = Callable[[str, str], None]
EnqueueResumeCallable = Callable[[WorkspaceTaskSessionAttempt, str, str], Awaitable[None]]


class WorkspaceAttemptRecoveryService:
    """Detect and recover orphaned workspace task session attempts."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession],
        apply_report: ApplyReportCallable,
        schedule_tick: ScheduleTickCallable,
        enqueue_resume: EnqueueResumeCallable | None = None,
        liveness_lookup: LivenessLookup | None = None,
        stale_seconds: int = DEFAULT_STALE_SECONDS,
        startup_grace_seconds: int = DEFAULT_STARTUP_GRACE_SECONDS,
        check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS,
    ) -> None:
        if stale_seconds <= 0:
            raise ValueError("stale_seconds must be > 0")
        if startup_grace_seconds < 0:
            raise ValueError("startup_grace_seconds must be >= 0")
        if check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be > 0")
        self._session_factory = session_factory
        self._apply_report = apply_report
        self._schedule_tick = schedule_tick
        self._enqueue_resume = enqueue_resume
        self._liveness_lookup: LivenessLookup = liveness_lookup or (lambda: ())
        self._stale_seconds = stale_seconds
        self._startup_grace_seconds = startup_grace_seconds
        self._check_interval_seconds = check_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Run a startup sweep then launch the periodic loop."""
        try:
            await self.startup_sweep()
        except Exception:
            logger.exception("workspace_attempt_recovery.startup_sweep_failed")
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="workspace-attempt-recovery")
        logger.info(
            "workspace_attempt_recovery.started",
            extra={
                "event": "workspace_attempt_recovery.started",
                "stale_seconds": self._stale_seconds,
                "check_interval_seconds": self._check_interval_seconds,
            },
        )

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        logger.info(
            "workspace_attempt_recovery.stopped",
            extra={"event": "workspace_attempt_recovery.stopped"},
        )

    async def startup_sweep(self) -> int:
        """Recover any non-terminal attempt older than the startup grace.

        Returns the number of attempts recovered.
        """
        threshold = datetime.now(UTC) - timedelta(seconds=self._startup_grace_seconds)
        stale = await self._fetch_stale(threshold)
        recovered = await self._recover_all(stale, RECOVERY_SUMMARY_RESTART)
        if recovered:
            logger.warning(
                "workspace_attempt_recovery.startup_swept",
                extra={
                    "event": "workspace_attempt_recovery.startup_swept",
                    "recovered": recovered,
                    "total_candidates": len(stale),
                },
            )
        return recovered

    async def periodic_sweep(self) -> int:
        """Recover non-terminal attempts stale for ``stale_seconds`` and
        not present in the supervisor liveness map. Returns the recovered count.
        """
        threshold = datetime.now(UTC) - timedelta(seconds=self._stale_seconds)
        stale = await self._fetch_stale(threshold)
        if not stale:
            return 0
        live_ids = set(self._liveness_lookup() or ())
        candidates = [a for a in stale if a.id not in live_ids]
        recovered = await self._recover_all(candidates, RECOVERY_SUMMARY_STALE)
        if recovered:
            logger.warning(
                "workspace_attempt_recovery.periodic_swept",
                extra={
                    "event": "workspace_attempt_recovery.periodic_swept",
                    "recovered": recovered,
                    "total_candidates": len(candidates),
                    "live_skipped": len(stale) - len(candidates),
                },
            )
        return recovered

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._check_interval_seconds
                )
                return
            except TimeoutError:
                pass
            try:
                await self.periodic_sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "workspace_attempt_recovery.periodic_sweep_failed",
                    exc_info=True,
                    extra={"event": "workspace_attempt_recovery.periodic_sweep_failed"},
                )

    async def _fetch_stale(self, older_than: datetime) -> list[WorkspaceTaskSessionAttempt]:
        async with self._session_factory() as session:
            repo = SqlWorkspaceTaskSessionAttemptRepository(session)
            return await repo.find_stale_non_terminal(older_than=older_than)

    async def _recover_all(
        self,
        attempts: list[WorkspaceTaskSessionAttempt],
        summary: str,
    ) -> int:
        recovered = 0
        scheduled_roots: set[tuple[str, str]] = set()
        terminal_parent_statuses = {
            WorkspaceTaskStatus.DONE,
            WorkspaceTaskStatus.BLOCKED,
        }
        for attempt in attempts:
            resolution = await self._resolve_parent_task(attempt.workspace_task_id)
            if resolution is None:
                logger.info(
                    "workspace_attempt_recovery.skip_no_parent_task",
                    extra={
                        "event": "workspace_attempt_recovery.skip_no_parent_task",
                        "attempt_id": attempt.id,
                        "workspace_task_id": attempt.workspace_task_id,
                    },
                )
                # Parent task was deleted -- mark the orphan attempt terminal
                # directly so we stop re-discovering it.
                await self._quiet_block_attempt(attempt, reason="parent_task_missing")
                continue
            actor_user_id, parent_status = resolution
            if parent_status in terminal_parent_statuses:
                # Parent already completed / blocked. Do NOT cascade a new
                # worker report -- that would attempt an invalid transition
                # (e.g. done -> blocked). Just flip the dangling attempt row.
                logger.info(
                    "workspace_attempt_recovery.parent_already_terminal",
                    extra={
                        "event": "workspace_attempt_recovery.parent_already_terminal",
                        "attempt_id": attempt.id,
                        "workspace_task_id": attempt.workspace_task_id,
                        "parent_status": parent_status.value,
                    },
                )
                await self._quiet_block_attempt(attempt, reason=f"parent_{parent_status.value}")
                continue
            try:
                result = await self._apply_report(
                    workspace_id=attempt.workspace_id,
                    root_goal_task_id=attempt.root_goal_task_id,
                    task_id=attempt.workspace_task_id,
                    attempt_id=attempt.id,
                    conversation_id=attempt.conversation_id or "",
                    actor_user_id=actor_user_id,
                    worker_agent_id=attempt.worker_agent_id or "",
                    report_type="blocked",
                    summary=summary,
                    artifacts=None,
                    leader_agent_id=attempt.leader_agent_id,
                    report_id=f"recovery:{attempt.id}",
                )
                if result is None:
                    # Cascade failed internally (the function swallows the
                    # exception and returns None). Still flip the attempt row
                    # so we do not loop forever on the same broken attempt.
                    logger.info(
                        "workspace_attempt_recovery.cascade_returned_none",
                        extra={
                            "event": "workspace_attempt_recovery.cascade_returned_none",
                            "attempt_id": attempt.id,
                            "workspace_task_id": attempt.workspace_task_id,
                        },
                    )
                    await self._quiet_block_attempt(attempt, reason="cascade_returned_none")
                    continue
                recovered += 1
                await self._enqueue_resume_if_configured(
                    attempt=attempt,
                    summary=summary,
                    actor_user_id=actor_user_id,
                )
                scheduled_roots.add((attempt.workspace_id, actor_user_id))
                logger.warning(
                    "workspace_attempt_recovery.attempt_blocked",
                    extra={
                        "event": "workspace_attempt_recovery.attempt_blocked",
                        "attempt_id": attempt.id,
                        "workspace_task_id": attempt.workspace_task_id,
                        "workspace_id": attempt.workspace_id,
                        "reason": summary,
                    },
                )
            except Exception:
                logger.exception(
                    "workspace_attempt_recovery.apply_report_failed attempt=%s",
                    attempt.id,
                )
                # Still flip the attempt itself so we don't loop forever on
                # the same broken row.
                await self._quiet_block_attempt(attempt, reason="apply_report_failed")
        for workspace_id, actor_user_id in scheduled_roots:
            try:
                self._schedule_tick(workspace_id, actor_user_id)
            except Exception:
                logger.warning(
                    "workspace_attempt_recovery.schedule_tick_failed",
                    exc_info=True,
                    extra={
                        "event": "workspace_attempt_recovery.schedule_tick_failed",
                        "workspace_id": workspace_id,
                    },
                )
        return recovered

    async def _enqueue_resume_if_configured(
        self,
        *,
        attempt: WorkspaceTaskSessionAttempt,
        summary: str,
        actor_user_id: str,
    ) -> None:
        if self._enqueue_resume is None:
            return
        try:
            await self._enqueue_resume(attempt, summary, actor_user_id)
        except Exception:
            logger.warning(
                "workspace_attempt_recovery.enqueue_resume_failed",
                exc_info=True,
                extra={
                    "event": "workspace_attempt_recovery.enqueue_resume_failed",
                    "attempt_id": attempt.id,
                    "workspace_id": attempt.workspace_id,
                    "workspace_task_id": attempt.workspace_task_id,
                },
            )

    async def _resolve_parent_task(
        self, workspace_task_id: str
    ) -> tuple[str, WorkspaceTaskStatus] | None:
        """Return ``(actor_user_id, task_status)`` or None if the task is gone."""
        try:
            async with self._session_factory() as session:
                task_repo = SqlWorkspaceTaskRepository(session)
                task = await task_repo.find_by_id(workspace_task_id)
                if task is None:
                    return None
                if not task.created_by:
                    return None
                return task.created_by, task.status
        except Exception:
            logger.exception(
                "workspace_attempt_recovery.resolve_parent_failed task=%s",
                workspace_task_id,
            )
            return None

    async def _quiet_block_attempt(
        self, attempt: WorkspaceTaskSessionAttempt, *, reason: str
    ) -> None:
        """Mark an attempt BLOCKED at the attempt-row level only (no cascade).

        Used when the parent workspace_task is already terminal or deleted;
        cascading a blocked report would raise an invalid transition, but
        we still need to stop re-discovering the dangling attempt on each
        sweep.
        """
        if attempt.status == WorkspaceTaskSessionAttemptStatus.BLOCKED:
            return
        try:
            async with self._session_factory() as session:
                repo = SqlWorkspaceTaskSessionAttemptRepository(session)
                stored = await repo.find_by_id(attempt.id)
                if stored is None:
                    return
                if stored.status == WorkspaceTaskSessionAttemptStatus.BLOCKED:
                    return
                stored.status = WorkspaceTaskSessionAttemptStatus.BLOCKED
                stored.leader_feedback = stored.leader_feedback or f"recovery:{reason}"
                stored.adjudication_reason = stored.adjudication_reason or f"recovery:{reason}"
                now = datetime.now(UTC)
                stored.completed_at = stored.completed_at or now
                stored.updated_at = now
                await repo.save(stored)
                await session.commit()
        except Exception:
            logger.exception(
                "workspace_attempt_recovery.quiet_block_failed attempt=%s",
                attempt.id,
            )
