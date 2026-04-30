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
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    PlanModel,
    PlanNodeModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_session_attempt_repository import (
    SqlWorkspaceTaskSessionAttemptRepository,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)

logger = logging.getLogger(__name__)

# Defaults chosen to stay well clear of normal in-flight latency but not so
# long that a user sees a stalled workspace for many minutes after a restart.
DEFAULT_STALE_SECONDS = 180
DEFAULT_STARTUP_GRACE_SECONDS = 15
DEFAULT_CHECK_INTERVAL_SECONDS = 60
DEFAULT_MAX_ATTEMPTS_PER_SWEEP = 3
DEFAULT_ERROR_EVENT_GRACE_SECONDS = 5
RECOVERY_SUMMARY_RESTART = "recovered_after_restart_no_heartbeat"
RECOVERY_SUMMARY_STALE = "recovered_stale_no_heartbeat"
RECOVERY_SUMMARY_AGENT_ERROR_EVENT = "recovered_agent_error_event"
TERMINAL_ATTEMPT_STATUSES = {
    WorkspaceTaskSessionAttemptStatus.ACCEPTED,
    WorkspaceTaskSessionAttemptStatus.REJECTED,
    WorkspaceTaskSessionAttemptStatus.BLOCKED,
    WorkspaceTaskSessionAttemptStatus.CANCELLED,
}
SUPPRESSED_PLAN_STATUSES = {"suspended", "completed", "abandoned"}
SUPPRESSED_LOOP_STATUSES = {"paused", "suspended", "completed"}


def _attempt_summary(summary: str | Mapping[str, str], attempt_id: str) -> str:
    if isinstance(summary, Mapping):
        return summary.get(attempt_id) or RECOVERY_SUMMARY_STALE
    return summary


def _error_event_recovery_summary(event_data: object) -> str:
    message = ""
    if isinstance(event_data, Mapping):
        raw = (
            event_data.get("message")
            or event_data.get("error")
            or event_data.get("reason")
            or event_data.get("detail")
        )
        if isinstance(raw, str):
            message = raw.strip()
    if not message:
        return RECOVERY_SUMMARY_AGENT_ERROR_EVENT
    compact = message.replace("\r", "\n").strip()
    if len(compact) > 1800:
        compact = compact[:1785] + "...[truncated]"
    return f"{RECOVERY_SUMMARY_AGENT_ERROR_EVENT}: {compact}"


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
        max_attempts_per_sweep: int = DEFAULT_MAX_ATTEMPTS_PER_SWEEP,
        error_event_grace_seconds: int = DEFAULT_ERROR_EVENT_GRACE_SECONDS,
    ) -> None:
        if stale_seconds <= 0:
            raise ValueError("stale_seconds must be > 0")
        if startup_grace_seconds < 0:
            raise ValueError("startup_grace_seconds must be >= 0")
        if check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be > 0")
        if max_attempts_per_sweep <= 0:
            raise ValueError("max_attempts_per_sweep must be > 0")
        if error_event_grace_seconds < 0:
            raise ValueError("error_event_grace_seconds must be >= 0")
        self._session_factory = session_factory
        self._apply_report = apply_report
        self._schedule_tick = schedule_tick
        self._enqueue_resume = enqueue_resume
        self._liveness_lookup: LivenessLookup = liveness_lookup or (lambda: ())
        self._stale_seconds = stale_seconds
        self._startup_grace_seconds = startup_grace_seconds
        self._check_interval_seconds = check_interval_seconds
        self._max_attempts_per_sweep = max_attempts_per_sweep
        self._error_event_grace_seconds = error_event_grace_seconds
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
                "max_attempts_per_sweep": self._max_attempts_per_sweep,
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
        recovered = await self._recover_error_events()
        stale = await self._fetch_stale(threshold)
        recovered += await self._recover_all(stale, RECOVERY_SUMMARY_RESTART)
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
        recovered = await self._recover_error_events()
        threshold = datetime.now(UTC) - timedelta(seconds=self._stale_seconds)
        stale = await self._fetch_stale(threshold)
        if not stale:
            return recovered
        live_ids = set(self._liveness_lookup() or ())
        candidates = [a for a in stale if a.id not in live_ids]
        recovered += await self._recover_all(candidates, RECOVERY_SUMMARY_STALE)
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

    async def workspace_sweep(self, workspace_id: str) -> int:
        """Recover stale attempts for one workspace without sweeping all history."""
        threshold = datetime.now(UTC) - timedelta(seconds=self._stale_seconds)
        recovered = await self._recover_error_events(workspace_id=workspace_id)
        stale = await self._fetch_stale(threshold, workspace_id=workspace_id)
        if not stale:
            return recovered
        live_ids = set(self._liveness_lookup() or ())
        candidates = [attempt for attempt in stale if attempt.id not in live_ids]
        recovered += await self._recover_all(candidates, RECOVERY_SUMMARY_STALE)
        if recovered:
            logger.warning(
                "workspace_attempt_recovery.workspace_swept",
                extra={
                    "event": "workspace_attempt_recovery.workspace_swept",
                    "workspace_id": workspace_id,
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

    async def _fetch_stale(
        self,
        older_than: datetime,
        *,
        workspace_id: str | None = None,
    ) -> list[WorkspaceTaskSessionAttempt]:
        async with self._session_factory() as session:
            repo = SqlWorkspaceTaskSessionAttemptRepository(session)
            return await repo.find_stale_non_terminal(
                older_than=older_than,
                limit=self._max_attempts_per_sweep,
                workspace_id=workspace_id,
            )

    async def _recover_error_events(self, *, workspace_id: str | None = None) -> int:
        """Recover active attempts whose agent stream already emitted an error event.

        A dev reload or local executor shutdown can cancel ``worker_launch``
        after ``agent_execution_events`` records an ``error`` but before the
        launcher emits a terminal WTP report. Heartbeat liveness alone keeps
        such attempts looking alive for minutes. The persisted error event is
        authoritative enough to close the attempt and enqueue the normal
        handoff/retry path.
        """
        older_than = datetime.now(UTC) - timedelta(seconds=self._error_event_grace_seconds)
        error_attempts = await self._fetch_error_terminated_attempts(
            older_than=older_than,
            workspace_id=workspace_id,
        )
        if not error_attempts:
            return 0
        summaries = {attempt.id: summary for attempt, summary in error_attempts}
        return await self._recover_all(
            [attempt for attempt, _summary in error_attempts],
            summaries,
        )

    async def _fetch_error_terminated_attempts(
        self,
        *,
        older_than: datetime,
        workspace_id: str | None = None,
    ) -> list[tuple[WorkspaceTaskSessionAttempt, str]]:
        non_terminal = [
            WorkspaceTaskSessionAttemptStatus.PENDING.value,
            WorkspaceTaskSessionAttemptStatus.RUNNING.value,
            WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value,
        ]
        async with self._session_factory() as session:
            repo = SqlWorkspaceTaskSessionAttemptRepository(session)
            stmt = (
                select(
                    WorkspaceTaskSessionAttemptModel,
                    AgentExecutionEvent.event_data,
                )
                .join(
                    AgentExecutionEvent,
                    AgentExecutionEvent.conversation_id
                    == WorkspaceTaskSessionAttemptModel.conversation_id,
                )
                .where(WorkspaceTaskSessionAttemptModel.status.in_(non_terminal))
                .where(WorkspaceTaskSessionAttemptModel.conversation_id.is_not(None))
                .where(AgentExecutionEvent.event_type == "error")
                .where(AgentExecutionEvent.created_at >= WorkspaceTaskSessionAttemptModel.created_at)
                .where(AgentExecutionEvent.created_at < older_than)
            )
            if workspace_id:
                stmt = stmt.where(WorkspaceTaskSessionAttemptModel.workspace_id == workspace_id)
            stmt = stmt.order_by(
                WorkspaceTaskSessionAttemptModel.updated_at.asc(),
                AgentExecutionEvent.created_at.desc(),
            ).limit(self._max_attempts_per_sweep * 4)
            result = await session.execute(stmt)
            recovered: list[tuple[WorkspaceTaskSessionAttempt, str]] = []
            seen: set[str] = set()
            for attempt_model, event_data in result.all():
                attempt = repo._to_domain(attempt_model)
                if attempt is None or attempt.id in seen:
                    continue
                seen.add(attempt.id)
                recovered.append((attempt, _error_event_recovery_summary(event_data)))
                if len(recovered) >= self._max_attempts_per_sweep:
                    break
            return recovered

    async def _recover_all(
        self,
        attempts: list[WorkspaceTaskSessionAttempt],
        summary: str | Mapping[str, str],
    ) -> int:
        recovered = 0
        scheduled_roots: set[tuple[str, str]] = set()
        terminal_parent_statuses = {
            WorkspaceTaskStatus.DONE,
            WorkspaceTaskStatus.BLOCKED,
        }
        for attempt in attempts:
            attempt_summary = _attempt_summary(summary, attempt.id)
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
                await self._quiet_finalize_attempt(
                    attempt,
                    reason="parent_task_missing",
                    status=WorkspaceTaskSessionAttemptStatus.CANCELLED,
                )
                continue
            actor_user_id, parent_status, parent_metadata = resolution
            is_v2_plan_linked = self._is_v2_plan_linked(parent_metadata)
            plan_recovery_suppressed = (
                await self._plan_recovery_suppressed(parent_metadata)
                if is_v2_plan_linked
                else False
            )
            awaiting_recovered = await self._recover_awaiting_leader_attempt(
                attempt=attempt,
                parent_status=parent_status,
                terminal_parent_statuses=terminal_parent_statuses,
                plan_recovery_suppressed=plan_recovery_suppressed,
                actor_user_id=actor_user_id,
                attempt_summary=attempt_summary,
                scheduled_roots=scheduled_roots,
            )
            if awaiting_recovered is not None:
                recovered += awaiting_recovered
                continue
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
                await self._quiet_finalize_attempt(
                    attempt,
                    reason=f"parent_{parent_status.value}",
                    status=self._terminal_status_for_parent(parent_status),
                )
                continue
            if is_v2_plan_linked:
                recovered += await self._recover_plan_linked_attempt(
                    attempt,
                    attempt_summary=attempt_summary,
                    actor_user_id=actor_user_id,
                    plan_recovery_suppressed=plan_recovery_suppressed,
                    scheduled_roots=scheduled_roots,
                )
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
                    summary=attempt_summary,
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
                    await self._quiet_finalize_attempt(
                        attempt,
                        reason="cascade_returned_none",
                        status=WorkspaceTaskSessionAttemptStatus.BLOCKED,
                    )
                    continue
                recovered += 1
                await self._enqueue_resume_if_configured(
                    attempt=attempt,
                    summary=attempt_summary,
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
                        "reason": attempt_summary,
                    },
                )
            except Exception:
                logger.exception(
                    "workspace_attempt_recovery.apply_report_failed attempt=%s",
                    attempt.id,
                )
                # Still flip the attempt itself so we don't loop forever on
                # the same broken row.
                await self._quiet_finalize_attempt(
                    attempt,
                    reason="apply_report_failed",
                    status=WorkspaceTaskSessionAttemptStatus.BLOCKED,
                )
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

    async def _recover_awaiting_leader_attempt(
        self,
        *,
        attempt: WorkspaceTaskSessionAttempt,
        parent_status: WorkspaceTaskStatus,
        terminal_parent_statuses: set[WorkspaceTaskStatus],
        plan_recovery_suppressed: bool,
        actor_user_id: str,
        attempt_summary: str,
        scheduled_roots: set[tuple[str, str]],
    ) -> int | None:
        if attempt.status is not WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION:
            return None
        if parent_status in terminal_parent_statuses:
            await self._quiet_finalize_attempt(
                attempt,
                reason=f"parent_{parent_status.value}",
                status=self._terminal_status_for_parent(parent_status),
            )
            return 0
        if plan_recovery_suppressed:
            await self._touch_awaiting_leader_attempt(attempt)
            logger.info(
                "workspace_attempt_recovery.skip_plan_suppressed_awaiting_leader",
                extra={
                    "event": "workspace_attempt_recovery.skip_plan_suppressed_awaiting_leader",
                    "attempt_id": attempt.id,
                    "workspace_task_id": attempt.workspace_task_id,
                    "workspace_id": attempt.workspace_id,
                    "reason": attempt_summary,
                },
            )
            return 0
        await self._touch_awaiting_leader_attempt(attempt)
        scheduled_roots.add((attempt.workspace_id, actor_user_id))
        logger.warning(
            "workspace_attempt_recovery.awaiting_leader_rescheduled",
            extra={
                "event": "workspace_attempt_recovery.awaiting_leader_rescheduled",
                "attempt_id": attempt.id,
                "workspace_task_id": attempt.workspace_task_id,
                "workspace_id": attempt.workspace_id,
                "reason": attempt_summary,
            },
        )
        return 1

    async def _recover_plan_linked_attempt(
        self,
        attempt: WorkspaceTaskSessionAttempt,
        *,
        attempt_summary: str,
        actor_user_id: str,
        plan_recovery_suppressed: bool,
        scheduled_roots: set[tuple[str, str]],
    ) -> int:
        await self._quiet_finalize_attempt(
            attempt,
            reason=attempt_summary,
            status=WorkspaceTaskSessionAttemptStatus.BLOCKED,
        )
        if plan_recovery_suppressed:
            logger.info(
                "workspace_attempt_recovery.skip_plan_suppressed_resume",
                extra={
                    "event": "workspace_attempt_recovery.skip_plan_suppressed_resume",
                    "attempt_id": attempt.id,
                    "workspace_task_id": attempt.workspace_task_id,
                    "workspace_id": attempt.workspace_id,
                    "reason": attempt_summary,
                },
            )
            return 1
        await self._enqueue_resume_if_configured(
            attempt=attempt,
            summary=attempt_summary,
            actor_user_id=actor_user_id,
        )
        scheduled_roots.add((attempt.workspace_id, actor_user_id))
        logger.warning(
            "workspace_attempt_recovery.plan_attempt_resumed",
            extra={
                "event": "workspace_attempt_recovery.plan_attempt_resumed",
                "attempt_id": attempt.id,
                "workspace_task_id": attempt.workspace_task_id,
                "workspace_id": attempt.workspace_id,
                "reason": attempt_summary,
            },
        )
        return 1

    async def _plan_recovery_suppressed(self, metadata: Mapping[str, object]) -> bool:
        """Return True when an operator/loop state should suppress auto-recovery.

        Attempt recovery is a crash/error watchdog, not an override for a paused
        Scrum loop. V2 plan-linked attempts may still be finalized, but they must
        not enqueue handoff resume jobs or schedule ticks while the plan is
        intentionally paused or suspended.
        """
        plan_id = metadata.get(WORKSPACE_PLAN_ID)
        if not isinstance(plan_id, str) or not plan_id:
            return False
        try:
            async with self._session_factory() as session:
                stmt = (
                    select(PlanModel.status, PlanNodeModel.metadata_json)
                    .join(
                        PlanNodeModel,
                        (PlanNodeModel.plan_id == PlanModel.id)
                        & (PlanNodeModel.id == PlanModel.goal_id),
                    )
                    .where(PlanModel.id == plan_id)
                    .limit(1)
                )
                row = (await session.execute(stmt)).one_or_none()
                if row is None:
                    return False
                plan_status, goal_metadata = row
        except Exception:
            logger.warning(
                "workspace_attempt_recovery.plan_state_lookup_failed",
                exc_info=True,
                extra={
                    "event": "workspace_attempt_recovery.plan_state_lookup_failed",
                    "plan_id": plan_id,
                },
            )
            return False
        if str(plan_status or "").lower() in SUPPRESSED_PLAN_STATUSES:
            return True
        if isinstance(goal_metadata, Mapping):
            loop = goal_metadata.get("iteration_loop")
            if isinstance(loop, Mapping):
                loop_status = loop.get("loop_status")
                if str(loop_status or "").lower() in SUPPRESSED_LOOP_STATUSES:
                    return True
        return False

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
    ) -> tuple[str, WorkspaceTaskStatus, Mapping[str, object]] | None:
        """Return parent execution context or None if the task is gone."""
        try:
            async with self._session_factory() as session:
                task_repo = SqlWorkspaceTaskRepository(session)
                task = await task_repo.find_by_id(workspace_task_id)
                if task is None:
                    return None
                if not task.created_by:
                    return None
                metadata = (
                    task.metadata if isinstance(task.metadata, Mapping) else {}
                )
                return task.created_by, task.status, metadata
        except Exception:
            logger.exception(
                "workspace_attempt_recovery.resolve_parent_failed task=%s",
                workspace_task_id,
            )
            return None

    @staticmethod
    def _terminal_status_for_parent(
        parent_status: WorkspaceTaskStatus,
    ) -> WorkspaceTaskSessionAttemptStatus:
        if parent_status is WorkspaceTaskStatus.DONE:
            return WorkspaceTaskSessionAttemptStatus.CANCELLED
        return WorkspaceTaskSessionAttemptStatus.BLOCKED

    @staticmethod
    def _is_v2_plan_linked(metadata: Mapping[str, object]) -> bool:
        plan_id = metadata.get(WORKSPACE_PLAN_ID)
        node_id = metadata.get(WORKSPACE_PLAN_NODE_ID)
        return bool(isinstance(plan_id, str) and plan_id) and bool(
            isinstance(node_id, str) and node_id
        )

    async def _touch_awaiting_leader_attempt(
        self,
        attempt: WorkspaceTaskSessionAttempt,
    ) -> None:
        """Refresh an awaiting-leader attempt after scheduling adjudication recovery."""
        try:
            async with self._session_factory() as session:
                repo = SqlWorkspaceTaskSessionAttemptRepository(session)
                stored = await repo.find_by_id(attempt.id)
                if stored is None:
                    return
                if (
                    stored.status
                    is not WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION
                ):
                    return
                stored.updated_at = datetime.now(UTC)
                await repo.save(stored)
                await session.commit()
        except Exception:
            logger.exception(
                "workspace_attempt_recovery.touch_awaiting_failed attempt=%s",
                attempt.id,
            )

    async def _quiet_finalize_attempt(
        self,
        attempt: WorkspaceTaskSessionAttempt,
        *,
        reason: str,
        status: WorkspaceTaskSessionAttemptStatus,
    ) -> None:
        """Mark a dangling attempt terminal at the attempt-row level only.

        Used when the parent workspace_task is already terminal or deleted;
        cascading a report would raise an invalid transition, but we still
        need to stop re-discovering the dangling attempt on each sweep.
        """
        if attempt.status in TERMINAL_ATTEMPT_STATUSES:
            return
        try:
            async with self._session_factory() as session:
                repo = SqlWorkspaceTaskSessionAttemptRepository(session)
                stored = await repo.find_by_id(attempt.id)
                if stored is None:
                    return
                if stored.status in TERMINAL_ATTEMPT_STATUSES:
                    return
                stored.status = status
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
