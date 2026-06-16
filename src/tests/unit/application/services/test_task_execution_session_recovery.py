"""Unit tests for TaskExecutionSessionRecoveryService."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.task_execution_session_monitor import (
    TaskExecutionIncident,
    TaskExecutionSessionState,
    TaskRecoveryActionResult,
)
from src.application.services.task_execution_session_recovery import (
    TaskExecutionSessionRecoveryCandidate,
    TaskExecutionSessionRecoveryService,
)


class _Session:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> _Session:
        return self._session

    async def __aexit__(self, *_args: object) -> None:
        return None


def _degraded_state(
    *,
    recovery_actions: tuple[dict[str, Any], ...] = (),
    recommended_action: str = "new_attempt",
    incident_type: str = "agent_initialization_failed",
) -> TaskExecutionSessionState:
    now = datetime(2026, 5, 7, 12, 0, tzinfo=UTC)
    return TaskExecutionSessionState(
        workspace_id="workspace-recovery-1",
        task_id="task-recovery-1",
        task_status="in_progress",
        health="degraded",
        session_status="initialization_failed",
        conversation_id="conv-recovery-1",
        attempt_id="attempt-recovery-1",
        attempt_status="running",
        execution_status=None,
        last_event_at=now,
        last_assistant_event_at=None,
        last_error="Agent initialization failed",
        has_user_input=True,
        has_assistant_output=False,
        incidents=(
            TaskExecutionIncident(
                type=incident_type,
                severity="error",
                summary="Agent initialization failed before any assistant response.",
                opened_at=now,
            ),
        ),
        recommended_recovery_action=recommended_action,
        available_interventions=("new_attempt", "mark_human_blocked"),
        recovery_actions=recovery_actions,
    )


@pytest.mark.unit
class TestTaskExecutionSessionRecoveryService:
    async def test_startup_sweep_applies_new_attempt_for_silent_initialization_failure(
        self,
    ) -> None:
        session = _Session()
        state = _degraded_state()
        result = TaskRecoveryActionResult(
            workspace_id=state.workspace_id,
            task_id=state.task_id,
            action="new_attempt",
            status="queued",
            message="Fresh worker attempt queued.",
            conversation_id=state.conversation_id,
            attempt_id=state.attempt_id,
            outbox_id="outbox-recovery-1",
            session=state,
        )
        monitor = MagicMock()
        monitor.get_state = AsyncMock(return_value=state)
        monitor.apply_recovery_action = AsyncMock(return_value=result)
        command_service = MagicMock()
        command_service.consume_pending_events.return_value = []
        service = TaskExecutionSessionRecoveryService(
            session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
            monitor_factory=lambda _session: (monitor, command_service),  # type: ignore[return-value]
            redis_client=None,
            action_cooldown_seconds=180,
        )
        service._fetch_candidates = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                TaskExecutionSessionRecoveryCandidate(
                    workspace_id=state.workspace_id,
                    task_id=state.task_id,
                    actor_user_id="user-recovery-1",
                )
            ]
        )

        recovered = await service.startup_sweep()

        assert recovered == 1
        monitor.apply_recovery_action.assert_awaited_once_with(
            workspace_id=state.workspace_id,
            task_id=state.task_id,
            actor_user_id="user-recovery-1",
            action="new_attempt",
            reason=(
                "startup task execution session recovery: new_attempt; "
                "incidents=agent_initialization_failed"
            ),
            system_recovery=True,
        )
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()
        command_service.consume_pending_events.assert_called_once_with()

    async def test_recent_queued_recovery_suppresses_duplicate_attempt(self) -> None:
        session = _Session()
        state = _degraded_state(
            recovery_actions=(
                {
                    "action": "new_attempt",
                    "status": "queued",
                    "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                },
            )
        )
        monitor = MagicMock()
        monitor.get_state = AsyncMock(return_value=state)
        monitor.apply_recovery_action = AsyncMock()
        command_service = MagicMock()
        service = TaskExecutionSessionRecoveryService(
            session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
            monitor_factory=lambda _session: (monitor, command_service),  # type: ignore[return-value]
            redis_client=None,
            action_cooldown_seconds=180,
        )
        service._fetch_candidates = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                TaskExecutionSessionRecoveryCandidate(
                    workspace_id=state.workspace_id,
                    task_id=state.task_id,
                    actor_user_id="user-recovery-1",
                )
            ]
        )

        recovered = await service.periodic_sweep()

        assert recovered == 0
        monitor.apply_recovery_action.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_recovery_budget_exhaustion_does_not_auto_mark_human_blocked(self) -> None:
        session = _Session()
        state = _degraded_state(
            recommended_action="mark_human_blocked",
            recovery_actions=(
                {"action": "new_attempt", "status": "completed", "at": "2026-05-07T11:00:00Z"},
                {"action": "new_attempt", "status": "completed", "at": "2026-05-07T11:10:00Z"},
                {"action": "retry_launch", "status": "completed", "at": "2026-05-07T11:20:00Z"},
            ),
        )
        monitor = MagicMock()
        monitor.get_state = AsyncMock(return_value=state)
        monitor.apply_recovery_action = AsyncMock()
        command_service = MagicMock()
        service = TaskExecutionSessionRecoveryService(
            session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
            monitor_factory=lambda _session: (monitor, command_service),  # type: ignore[return-value]
            redis_client=None,
            action_cooldown_seconds=0,
        )
        service._fetch_candidates = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                TaskExecutionSessionRecoveryCandidate(
                    workspace_id=state.workspace_id,
                    task_id=state.task_id,
                    actor_user_id="user-recovery-1",
                )
            ]
        )

        recovered = await service.periodic_sweep()

        assert recovered == 0
        monitor.apply_recovery_action.assert_not_awaited()
        session.commit.assert_not_awaited()
