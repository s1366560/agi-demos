"""Unit tests for TaskExecutionSessionMonitor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.application.services.task_execution_session_monitor as monitor_module
from src.application.services.task_execution_session_monitor import (
    TaskExecutionIncident,
    TaskExecutionSessionMonitor,
    TaskExecutionSessionState,
)
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    Conversation,
    Project,
    User,
)

_NOW = datetime(2020, 1, 1, 9, 0, tzinfo=UTC)


def _task() -> WorkspaceTask:
    return WorkspaceTask(
        id="task-session-monitor-1",
        workspace_id="workspace-session-monitor-1",
        title="Diagnose silent worker session",
        description="Task is processing but the worker conversation never responds.",
        created_by="user-session-monitor-1",
        status=WorkspaceTaskStatus.IN_PROGRESS,
        assignee_agent_id="agent-1",
        metadata={
            "current_attempt_id": "attempt-session-monitor-1",
            "current_attempt_conversation_id": "conv-session-monitor-1",
            "last_attempt_status": "awaiting_leader_adjudication",
            "task_role": "execution_task",
        },
        created_at=_NOW - timedelta(minutes=5),
        updated_at=_NOW - timedelta(minutes=2),
    )


def _attempt() -> WorkspaceTaskSessionAttempt:
    return WorkspaceTaskSessionAttempt(
        id="attempt-session-monitor-1",
        workspace_task_id="task-session-monitor-1",
        root_goal_task_id="root-session-monitor-1",
        workspace_id="workspace-session-monitor-1",
        attempt_number=1,
        status=WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION,
        conversation_id="conv-session-monitor-1",
        worker_agent_id="agent-1",
        created_at=_NOW - timedelta(minutes=5),
        updated_at=_NOW - timedelta(minutes=2),
    )


@pytest.mark.unit
class TestTaskExecutionSessionMonitor:
    def test_recommends_new_attempt_for_terminal_failed_attempt(self) -> None:
        task = _task()
        incident = TaskExecutionIncident(
            type="stale_processing",
            severity="warning",
            summary="Task is still processing but execution activity is stale.",
            opened_at=_NOW,
        )

        action = monitor_module._recommended_recovery_action(
            task=task,
            incidents=(incident,),
            metadata=task.metadata,
            attempt_status=WorkspaceTaskSessionAttemptStatus.REJECTED.value,
        )

        assert action == "new_attempt"

    async def test_retry_launch_on_terminal_failed_attempt_queues_fresh_attempt(
        self,
        db_session: AsyncSession,
    ) -> None:
        task = _task()
        attempt = _attempt()
        attempt.status = WorkspaceTaskSessionAttemptStatus.REJECTED
        before = TaskExecutionSessionState(
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_status="in_progress",
            health="warning",
            session_status="degraded",
            conversation_id="conv-session-monitor-1",
            attempt_id=attempt.id,
            attempt_status=WorkspaceTaskSessionAttemptStatus.REJECTED.value,
            execution_status=None,
            last_event_at=_NOW,
            last_assistant_event_at=_NOW,
            last_error=None,
            has_user_input=True,
            has_assistant_output=True,
            incidents=(
                TaskExecutionIncident(
                    type="stale_processing",
                    severity="warning",
                    summary="Task is still processing but execution activity is stale.",
                    opened_at=_NOW,
                ),
            ),
            recommended_recovery_action="new_attempt",
            available_interventions=("new_attempt", "retry_launch"),
        )
        task_service = AsyncMock()
        task_service.get_task.return_value = task
        command_service = AsyncMock()
        attempt_repo = AsyncMock()
        attempt_repo.find_by_id.return_value = attempt
        service = TaskExecutionSessionMonitor(
            db=db_session,
            task_service=task_service,
            command_service=command_service,
            attempt_repo=attempt_repo,
        )
        service.get_state = AsyncMock(return_value=before)  # type: ignore[method-assign]
        service._enqueue_attempt_retry = AsyncMock(  # type: ignore[method-assign]
            return_value="outbox-new-attempt"
        )
        service._enqueue_worker_launch = AsyncMock()  # type: ignore[method-assign]

        result = await service.apply_recovery_action(
            workspace_id=task.workspace_id,
            task_id=task.id,
            actor_user_id="user-session-monitor-1",
            action="retry_launch",
        )

        assert result.action == "new_attempt"
        assert result.outbox_id == "outbox-new-attempt"
        service._enqueue_attempt_retry.assert_awaited_once()
        service._enqueue_worker_launch.assert_not_awaited()

    async def test_detects_current_silent_initialization_failure_from_execution_events(
        self,
        db_session: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        task = _task()
        attempt = _attempt()
        task_service = AsyncMock()
        task_service.get_task.return_value = task
        attempt_repo = AsyncMock()
        attempt_repo.find_by_workspace_task_id.return_value = [attempt]

        db_session.add(
            Conversation(
                id="conv-session-monitor-1",
                project_id=test_project_db.id,
                tenant_id=test_project_db.tenant_id,
                user_id=test_user.id,
                title="Silent worker conversation",
                status="active",
                workspace_id=None,
                linked_workspace_task_id=None,
            )
        )
        db_session.add_all(
            [
                AgentExecutionEvent(
                    id="evt-session-monitor-user",
                    conversation_id="conv-session-monitor-1",
                    message_id="msg-session-monitor-user",
                    event_type="user_message",
                    event_data={"role": "user", "content": "Start task"},
                    event_time_us=1,
                    event_counter=1,
                    created_at=_NOW - timedelta(minutes=2),
                ),
                AgentExecutionEvent(
                    id="evt-session-monitor-error",
                    conversation_id="conv-session-monitor-1",
                    message_id="msg-session-monitor-user",
                    event_type="error",
                    event_data={
                        "message": "Agent initialization failed",
                        "code": "AGENT_NOT_INITIALIZED",
                    },
                    event_time_us=2,
                    event_counter=2,
                    created_at=_NOW - timedelta(minutes=2),
                ),
            ]
        )
        await db_session.flush()

        service = TaskExecutionSessionMonitor(
            db=db_session,
            task_service=task_service,
            command_service=AsyncMock(),
            attempt_repo=attempt_repo,
        )

        state = await service.get_state(
            workspace_id=task.workspace_id,
            task_id=task.id,
            actor_user_id=test_user.id,
        )

        incident_types = {incident.type for incident in state.incidents}
        assert state.health == "degraded"
        assert state.session_status == "initialization_failed"
        assert state.conversation_id == "conv-session-monitor-1"
        assert state.attempt_id == "attempt-session-monitor-1"
        assert state.execution_status is None
        assert state.has_user_input is True
        assert state.has_assistant_output is False
        assert state.last_error == "Agent initialization failed"
        assert state.recommended_recovery_action == "new_attempt"
        assert {
            "agent_initialization_failed",
            "no_assistant_response",
            "lost_binding",
        }.issubset(incident_types)
        assert "missing_execution_status" not in incident_types
        assert "new_attempt" in state.available_interventions
        assert "mark_human_blocked" in state.available_interventions

        task_service.get_task.assert_awaited_once_with(
            workspace_id=task.workspace_id,
            task_id=task.id,
            actor_user_id=test_user.id,
        )
        attempt_repo.find_by_workspace_task_id.assert_awaited_once_with(task.id, limit=5)

    async def test_detects_missing_execution_status_when_conversation_has_no_events(
        self,
        db_session: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        task = _task()
        attempt = _attempt()
        task_service = AsyncMock()
        task_service.get_task.return_value = task
        attempt_repo = AsyncMock()
        attempt_repo.find_by_workspace_task_id.return_value = [attempt]
        db_session.add(
            Conversation(
                id="conv-session-monitor-1",
                project_id=test_project_db.id,
                tenant_id=test_project_db.tenant_id,
                user_id=test_user.id,
                title="Silent worker conversation",
                status="active",
                workspace_id=task.workspace_id,
                linked_workspace_task_id=task.id,
            )
        )
        await db_session.flush()

        service = TaskExecutionSessionMonitor(
            db=db_session,
            task_service=task_service,
            command_service=AsyncMock(),
            attempt_repo=attempt_repo,
        )

        state = await service.get_state(
            workspace_id=task.workspace_id,
            task_id=task.id,
            actor_user_id=test_user.id,
        )

        incident_types = {incident.type for incident in state.incidents}
        assert "missing_execution_status" in incident_types
        assert "lost_binding" not in incident_types

    async def test_mark_human_blocked_patches_current_attempt_id_for_task_guard(
        self,
        db_session: AsyncSession,
    ) -> None:
        task = _task()
        task.metadata.pop("current_attempt_id")
        before = TaskExecutionSessionState(
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_status="in_progress",
            health="degraded",
            session_status="initialization_failed",
            conversation_id="conv-session-monitor-1",
            attempt_id="attempt-session-monitor-1",
            attempt_status="running",
            execution_status=None,
            last_event_at=_NOW,
            last_assistant_event_at=None,
            last_error="Agent initialization failed",
            has_user_input=True,
            has_assistant_output=False,
            incidents=(
                TaskExecutionIncident(
                    type="agent_initialization_failed",
                    severity="error",
                    summary="Agent initialization failed.",
                    opened_at=_NOW,
                ),
            ),
            recommended_recovery_action="mark_human_blocked",
            available_interventions=("mark_human_blocked",),
        )
        task_service = AsyncMock()
        task_service.get_task.return_value = task
        command_service = AsyncMock()
        attempt_repo = AsyncMock()
        attempt_repo.find_by_id.return_value = _attempt()
        attempt_repo.save = AsyncMock(side_effect=lambda attempt: attempt)
        service = TaskExecutionSessionMonitor(
            db=db_session,
            task_service=task_service,
            command_service=command_service,
            attempt_repo=attempt_repo,
        )
        service.get_state = AsyncMock(side_effect=[before, before])  # type: ignore[method-assign]

        result = await service.apply_recovery_action(
            workspace_id=task.workspace_id,
            task_id=task.id,
            actor_user_id="user-session-monitor-1",
            action="mark_human_blocked",
            reason="recovery budget exhausted",
        )

        assert result.status == "completed"
        metadata = command_service.update_task.await_args.kwargs["metadata"]
        assert metadata["current_attempt_id"] == "attempt-session-monitor-1"
        assert metadata["task_execution_session_status"] == "initialization_failed"

    async def test_mark_human_blocked_creates_attempt_when_monitor_has_none(
        self,
        db_session: AsyncSession,
    ) -> None:
        task = _task()
        task.metadata.pop("current_attempt_id")
        before = TaskExecutionSessionState(
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_status="in_progress",
            health="degraded",
            session_status="missing_execution_status",
            conversation_id="conv-session-monitor-1",
            attempt_id=None,
            attempt_status=None,
            execution_status=None,
            last_event_at=_NOW,
            last_assistant_event_at=None,
            last_error="No execution attempt was found",
            has_user_input=True,
            has_assistant_output=False,
            incidents=(
                TaskExecutionIncident(
                    type="missing_execution_status",
                    severity="error",
                    summary="No execution status exists for this task.",
                    opened_at=_NOW,
                ),
            ),
            recommended_recovery_action="mark_human_blocked",
            available_interventions=("mark_human_blocked",),
        )
        task_service = AsyncMock()
        task_service.get_task.return_value = task
        command_service = AsyncMock()
        saved_attempts: dict[str, WorkspaceTaskSessionAttempt] = {}

        async def _save_attempt(
            attempt: WorkspaceTaskSessionAttempt,
        ) -> WorkspaceTaskSessionAttempt:
            saved_attempts[attempt.id] = attempt
            return attempt

        async def _find_attempt(attempt_id: str) -> WorkspaceTaskSessionAttempt | None:
            return saved_attempts.get(attempt_id)

        attempt_repo = AsyncMock()
        attempt_repo.lock_attempt_creation = AsyncMock()
        attempt_repo.find_active_by_workspace_task_id = AsyncMock(return_value=None)
        attempt_repo.find_by_workspace_task_id = AsyncMock(return_value=[])
        attempt_repo.find_by_id = AsyncMock(side_effect=_find_attempt)
        attempt_repo.save = AsyncMock(side_effect=_save_attempt)
        service = TaskExecutionSessionMonitor(
            db=db_session,
            task_service=task_service,
            command_service=command_service,
            attempt_repo=attempt_repo,
        )
        service.get_state = AsyncMock(side_effect=[before, before])  # type: ignore[method-assign]

        result = await service.apply_recovery_action(
            workspace_id=task.workspace_id,
            task_id=task.id,
            actor_user_id="user-session-monitor-1",
            action="mark_human_blocked",
            reason="recovery budget exhausted",
        )

        assert result.status == "completed"
        assert attempt_repo.lock_attempt_creation.await_args.args == (task.id,)
        created_attempt = next(iter(saved_attempts.values()))
        assert created_attempt.status is WorkspaceTaskSessionAttemptStatus.BLOCKED
        assert created_attempt.conversation_id == "conv-session-monitor-1"
        metadata = command_service.update_task.await_args.kwargs["metadata"]
        assert metadata["current_attempt_id"] == created_attempt.id
        assert metadata["execution_recovery_actions"][0]["attempt_id"] == created_attempt.id
