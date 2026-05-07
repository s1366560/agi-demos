"""Background recovery for degraded task execution sessions."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import redis.asyncio as redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.task_execution_session_monitor import (
    TaskExecutionSessionMonitor,
    TaskExecutionSessionState,
    TaskRecoveryAction,
    TaskRecoveryActionResult,
)
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_event_publisher import WorkspaceTaskEventPublisher
from src.domain.events.envelope import EventEnvelope
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceModel,
    WorkspaceTaskModel,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import TASK_ROLE

logger = logging.getLogger(__name__)

DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_INTERVAL_SECONDS = 60
DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_MAX_TASKS_PER_SWEEP = 5
DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_ACTION_COOLDOWN_SECONDS = 180

_AUTO_RECOVERABLE_INCIDENTS = frozenset(
    {
        "agent_initialization_failed",
        "no_assistant_response",
        "stale_processing",
        "lost_binding",
    }
)
_AUTO_RECOVERY_ACTIONS = frozenset(
    {
        "new_attempt",
        "retry_launch",
    }
)
_PENDING_RECOVERY_STATUSES = frozenset({"queued", "recovering"})

MonitorFactory = Callable[
    [AsyncSession],
    tuple[TaskExecutionSessionMonitor, WorkspaceTaskCommandService],
]


@dataclass(frozen=True, slots=True)
class TaskExecutionSessionRecoveryCandidate:
    workspace_id: str
    task_id: str
    actor_user_id: str


class TaskExecutionSessionRecoveryService:
    """Sweeps processing tasks and applies monitor-recommended recovery actions."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]],
        monitor_factory: MonitorFactory,
        redis_client: redis.Redis | None = None,
        check_interval_seconds: int = DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_INTERVAL_SECONDS,
        max_tasks_per_sweep: int = DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_MAX_TASKS_PER_SWEEP,
        action_cooldown_seconds: int = (
            DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_ACTION_COOLDOWN_SECONDS
        ),
    ) -> None:
        if check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be > 0")
        if max_tasks_per_sweep <= 0:
            raise ValueError("max_tasks_per_sweep must be > 0")
        if action_cooldown_seconds < 0:
            raise ValueError("action_cooldown_seconds must be >= 0")
        self._session_factory = session_factory
        self._monitor_factory = monitor_factory
        self._redis_client = redis_client
        self._check_interval_seconds = check_interval_seconds
        self._max_tasks_per_sweep = max_tasks_per_sweep
        self._action_cooldown_seconds = action_cooldown_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Run a startup sweep and start the periodic watchdog."""

        try:
            await self.startup_sweep()
        except Exception:
            logger.warning(
                "task_execution_session_recovery.startup_sweep_failed",
                exc_info=True,
                extra={"event": "task_execution_session_recovery.startup_sweep_failed"},
            )
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="task-execution-session-recovery")
        logger.info(
            "task_execution_session_recovery.started",
            extra={
                "event": "task_execution_session_recovery.started",
                "check_interval_seconds": self._check_interval_seconds,
                "max_tasks_per_sweep": self._max_tasks_per_sweep,
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
            "task_execution_session_recovery.stopped",
            extra={"event": "task_execution_session_recovery.stopped"},
        )

    async def startup_sweep(self) -> int:
        recovered = await self._sweep_once(source="startup")
        if recovered:
            logger.warning(
                "task_execution_session_recovery.startup_swept",
                extra={
                    "event": "task_execution_session_recovery.startup_swept",
                    "recovered": recovered,
                },
            )
        return recovered

    async def periodic_sweep(self) -> int:
        recovered = await self._sweep_once(source="periodic")
        if recovered:
            logger.warning(
                "task_execution_session_recovery.periodic_swept",
                extra={
                    "event": "task_execution_session_recovery.periodic_swept",
                    "recovered": recovered,
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
                    "task_execution_session_recovery.periodic_sweep_failed",
                    exc_info=True,
                    extra={"event": "task_execution_session_recovery.periodic_sweep_failed"},
                )

    async def _sweep_once(self, *, source: str) -> int:
        recovered = 0
        async with self._session_factory() as session:
            candidates = await self._fetch_candidates(session)
            monitor, command_service = self._monitor_factory(session)
            for candidate in candidates:
                try:
                    did_recover = await self._recover_candidate(
                        session=session,
                        monitor=monitor,
                        command_service=command_service,
                        candidate=candidate,
                        source=source,
                    )
                    if did_recover:
                        recovered += 1
                except Exception:
                    await session.rollback()
                    logger.warning(
                        "task_execution_session_recovery.candidate_failed",
                        exc_info=True,
                        extra={
                            "event": "task_execution_session_recovery.candidate_failed",
                            "workspace_id": candidate.workspace_id,
                            "task_id": candidate.task_id,
                        },
                    )
        return recovered

    async def _fetch_candidates(
        self,
        session: AsyncSession,
    ) -> list[TaskExecutionSessionRecoveryCandidate]:
        last_activity = func.coalesce(
            WorkspaceTaskModel.updated_at,
            WorkspaceTaskModel.created_at,
        )
        stmt = (
            select(
                WorkspaceTaskModel.workspace_id,
                WorkspaceTaskModel.id,
                WorkspaceTaskModel.created_by,
            )
            .join(WorkspaceModel, WorkspaceModel.id == WorkspaceTaskModel.workspace_id)
            .where(WorkspaceTaskModel.status == WorkspaceTaskStatus.IN_PROGRESS.value)
            .where(WorkspaceTaskModel.metadata_json[TASK_ROLE].as_string() == "execution_task")
            .where(WorkspaceTaskModel.archived_at.is_(None))
            .where(WorkspaceModel.is_archived.is_(False))
            .order_by(last_activity.asc(), WorkspaceTaskModel.id.asc())
            .limit(self._max_tasks_per_sweep)
        )
        result = await session.execute(refresh_select_statement(stmt))
        return [
            TaskExecutionSessionRecoveryCandidate(
                workspace_id=str(row[0]),
                task_id=str(row[1]),
                actor_user_id=str(row[2]),
            )
            for row in result.all()
        ]

    async def _recover_candidate(
        self,
        *,
        session: AsyncSession,
        monitor: TaskExecutionSessionMonitor,
        command_service: WorkspaceTaskCommandService,
        candidate: TaskExecutionSessionRecoveryCandidate,
        source: str,
    ) -> bool:
        state = await monitor.get_state(
            workspace_id=candidate.workspace_id,
            task_id=candidate.task_id,
            actor_user_id=candidate.actor_user_id,
        )
        action = _automatic_recovery_action(
            state,
            now=datetime.now(UTC),
            cooldown_seconds=self._action_cooldown_seconds,
        )
        if action is None:
            return False
        result = await monitor.apply_recovery_action(
            workspace_id=candidate.workspace_id,
            task_id=candidate.task_id,
            actor_user_id=candidate.actor_user_id,
            action=action,
            reason=_automatic_recovery_reason(state, action, source),
        )
        await session.commit()
        await self._publish_recovery_events(
            command_service=command_service,
            before=state,
            result=result,
        )
        logger.warning(
            "task_execution_session_recovery.action_applied",
            extra={
                "event": "task_execution_session_recovery.action_applied",
                "workspace_id": candidate.workspace_id,
                "task_id": candidate.task_id,
                "action": action,
                "source": source,
            },
        )
        return True

    async def _publish_recovery_events(
        self,
        *,
        command_service: WorkspaceTaskCommandService,
        before: TaskExecutionSessionState,
        result: TaskRecoveryActionResult,
    ) -> None:
        if self._redis_client is None:
            command_service.consume_pending_events()
            return
        try:
            await WorkspaceTaskEventPublisher(self._redis_client).publish_pending_events(
                command_service.consume_pending_events()
            )
            payload = result.to_dict()
            await self._publish_session_event(
                workspace_id=result.workspace_id,
                event_type=AgentEventType.TASK_RECOVERY_ACTION_STARTED,
                payload=payload,
                task_id=result.task_id,
                source="task_execution_session.recovery",
            )
            session_payload = (result.session or before).to_dict()
            await self._publish_session_event(
                workspace_id=result.workspace_id,
                event_type=AgentEventType.TASK_EXECUTION_SESSION_UPDATED,
                payload=session_payload,
                task_id=result.task_id,
                source="task_execution_session.monitor",
            )
            for incident in before.incidents:
                await self._publish_session_event(
                    workspace_id=result.workspace_id,
                    event_type=AgentEventType.TASK_EXECUTION_INCIDENT_OPENED,
                    payload={
                        "workspace_id": result.workspace_id,
                        "task_id": result.task_id,
                        "conversation_id": before.conversation_id,
                        "attempt_id": before.attempt_id,
                        "incident": incident.to_dict(),
                    },
                    task_id=result.task_id,
                    source="task_execution_session.monitor",
                )
            await self._publish_session_event(
                workspace_id=result.workspace_id,
                event_type=AgentEventType.TASK_RECOVERY_ACTION_COMPLETED,
                payload=payload,
                task_id=result.task_id,
                source="task_execution_session.recovery",
            )
        except Exception:
            logger.warning(
                "task_execution_session_recovery.publish_failed",
                exc_info=True,
                extra={
                    "event": "task_execution_session_recovery.publish_failed",
                    "workspace_id": result.workspace_id,
                    "task_id": result.task_id,
                },
            )

    async def _publish_session_event(
        self,
        *,
        workspace_id: str,
        event_type: AgentEventType,
        payload: Mapping[str, object],
        task_id: str,
        source: str,
    ) -> None:
        if self._redis_client is None:
            return
        envelope = EventEnvelope.wrap(
            event_type=event_type,
            payload=dict(payload),
            correlation_id=task_id,
            metadata={"source": source, "task_id": task_id},
        )
        routing_key = f"workspace:{workspace_id}:{event_type.value}"
        await RedisUnifiedEventBusAdapter(self._redis_client).publish(envelope, routing_key)


def _automatic_recovery_action(
    state: TaskExecutionSessionState,
    *,
    now: datetime,
    cooldown_seconds: int,
) -> TaskRecoveryAction | None:
    action = state.recommended_recovery_action
    if action not in _AUTO_RECOVERY_ACTIONS:
        return None
    incident_types = {incident.type for incident in state.incidents}
    if not incident_types.intersection(_AUTO_RECOVERABLE_INCIDENTS):
        return None
    if _has_recent_pending_recovery(
        state.recovery_actions,
        now=now,
        cooldown_seconds=cooldown_seconds,
    ):
        return None
    return cast(TaskRecoveryAction, action)


def _has_recent_pending_recovery(
    recovery_actions: Sequence[Mapping[str, object]],
    *,
    now: datetime,
    cooldown_seconds: int,
) -> bool:
    if cooldown_seconds <= 0:
        return False
    cutoff = now - timedelta(seconds=cooldown_seconds)
    for entry in recovery_actions:
        action = entry.get("action")
        status = entry.get("status")
        if action not in _AUTO_RECOVERY_ACTIONS or status not in _PENDING_RECOVERY_STATUSES:
            continue
        action_at = _parse_datetime(entry.get("at"))
        if action_at is not None and action_at >= cutoff:
            return True
    return False


def _automatic_recovery_reason(
    state: TaskExecutionSessionState,
    action: TaskRecoveryAction,
    source: str,
) -> str:
    incident_types = ", ".join(incident.type for incident in state.incidents) or "unknown"
    return f"{source} task execution session recovery: {action}; incidents={incident_types}"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


__all__ = [
    "DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_ACTION_COOLDOWN_SECONDS",
    "DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_INTERVAL_SECONDS",
    "DEFAULT_TASK_EXECUTION_SESSION_RECOVERY_MAX_TASKS_PER_SWEEP",
    "TaskExecutionSessionRecoveryCandidate",
    "TaskExecutionSessionRecoveryService",
]
