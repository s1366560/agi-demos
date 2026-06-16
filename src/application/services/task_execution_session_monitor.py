"""Task-to-conversation execution session health monitor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import (
    WorkspaceTaskAuthorityContext,
    WorkspaceTaskService,
)
from src.application.services.workspace_task_session_attempt_service import (
    WorkspaceTaskSessionAttemptService,
)
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.ports.repositories.workspace.workspace_task_session_attempt_repository import (
    WorkspaceTaskSessionAttemptRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    Conversation,
    MessageExecutionStatus,
    WorkspaceMemberModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    ROOT_GOAL_TASK_ID,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    ATTEMPT_RETRY_EVENT,
    WORKER_LAUNCH_EVENT,
)

TaskRecoveryAction = Literal[
    "retry_launch",
    "new_attempt",
    "reassign",
    "mark_human_blocked",
    "terminate_stale_conversation",
]

_NO_ASSISTANT_RESPONSE_SECONDS = 30
_STALE_PROCESSING_SECONDS = 15 * 60
_MAX_RECOVERY_LEDGER_ITEMS = 20
_MAX_AUTOMATIC_RECOVERY_ATTEMPTS = 3
_EDITOR_ROLES = frozenset({"owner", "editor", "admin"})

_ASSISTANT_OUTPUT_EVENT_TYPES = frozenset(
    {
        "assistant_message",
        "text_start",
        "text_delta",
        "text_end",
        "thought",
        "thought_delta",
        "act",
        "act_delta",
        "observe",
        "task_list_updated",
        "task_updated",
        "tool_result",
        "workspace_worker_report_submitted",
    }
)


@dataclass(frozen=True)
class TaskExecutionIncident:
    """Derived execution-session incident for one workspace task."""

    type: str
    severity: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    opened_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "opened_at": _datetime_iso(self.opened_at),
        }


@dataclass(frozen=True)
class TaskExecutionSessionState:
    """Read-only task/conversation execution state."""

    workspace_id: str
    task_id: str
    task_status: str
    health: str
    session_status: str
    conversation_id: str | None
    attempt_id: str | None
    attempt_status: str | None
    execution_status: str | None
    last_event_at: datetime | None
    last_assistant_event_at: datetime | None
    last_error: str | None
    has_user_input: bool
    has_assistant_output: bool
    incidents: tuple[TaskExecutionIncident, ...]
    recommended_recovery_action: str | None
    available_interventions: tuple[str, ...]
    recent_events: tuple[dict[str, Any], ...] = ()
    recovery_actions: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "task_status": self.task_status,
            "health": self.health,
            "session_status": self.session_status,
            "conversation_id": self.conversation_id,
            "attempt_id": self.attempt_id,
            "attempt_status": self.attempt_status,
            "execution_status": self.execution_status,
            "last_event_at": _datetime_iso(self.last_event_at),
            "last_assistant_event_at": _datetime_iso(self.last_assistant_event_at),
            "last_error": self.last_error,
            "has_user_input": self.has_user_input,
            "has_assistant_output": self.has_assistant_output,
            "incidents": [incident.to_dict() for incident in self.incidents],
            "recommended_recovery_action": self.recommended_recovery_action,
            "available_interventions": list(self.available_interventions),
            "recent_events": list(self.recent_events),
            "recovery_actions": list(self.recovery_actions),
        }


@dataclass(frozen=True)
class TaskRecoveryActionResult:
    """Outcome of one explicit task recovery action."""

    workspace_id: str
    task_id: str
    action: str
    status: str
    message: str
    conversation_id: str | None = None
    attempt_id: str | None = None
    outbox_id: str | None = None
    session: TaskExecutionSessionState | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "action": self.action,
            "status": self.status,
            "message": self.message,
            "conversation_id": self.conversation_id,
            "attempt_id": self.attempt_id,
            "outbox_id": self.outbox_id,
            "session": self.session.to_dict() if self.session is not None else None,
        }


class TaskExecutionSessionMonitor:
    """Build task execution health from task, attempt, and conversation signals."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        task_service: WorkspaceTaskService,
        command_service: WorkspaceTaskCommandService,
        attempt_repo: WorkspaceTaskSessionAttemptRepository,
    ) -> None:
        self._db = db
        self._task_service = task_service
        self._command_service = command_service
        self._attempt_repo = attempt_repo

    async def get_state(
        self,
        *,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> TaskExecutionSessionState:
        task = await self._task_service.get_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        attempts = await self._attempt_repo.find_by_workspace_task_id(task.id, limit=5)
        attempt = _current_attempt(task, attempts)
        conversation_id = _conversation_id(task, attempt)
        conversation = await self._load_conversation(conversation_id)
        events = await self._load_events(conversation_id)
        execution_rows = await self._load_execution_statuses(conversation_id)
        return self._build_state(
            task=task,
            attempt=attempt,
            conversation=conversation,
            events=events,
            execution_rows=execution_rows,
        )

    async def apply_recovery_action(
        self,
        *,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        action: TaskRecoveryAction,
        reason: str | None = None,
        workspace_agent_id: str | None = None,
        system_recovery: bool = False,
    ) -> TaskRecoveryActionResult:
        await self._require_recovery_actor(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            system_recovery=system_recovery,
        )
        before = await self.get_state(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        task = await self._task_service.get_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        attempt = (
            await self._attempt_repo.find_by_id(before.attempt_id) if before.attempt_id else None
        )
        action_reason = reason or _default_action_reason(before, action)
        if action == "retry_launch" and _attempt_status_requires_fresh_attempt(
            before.attempt_status
        ):
            action = "new_attempt"
            if reason is None:
                action_reason = _default_action_reason(before, action)

        if action == "mark_human_blocked":
            blocked_attempt = await self._ensure_attempt_for_human_block(
                task=task,
                attempt=attempt,
                before=before,
                reason=action_reason,
            )
            await self._command_service.update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                status=WorkspaceTaskStatus.BLOCKED,
                blocker_reason=action_reason,
                metadata=_metadata_patch(
                    task,
                    action,
                    before,
                    action_reason,
                    "requires_human",
                    current_attempt_id=blocked_attempt.id,
                ),
                reason=action_reason,
                authority=_leader_authority(task),
            )
            after = await self.get_state(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            return TaskRecoveryActionResult(
                workspace_id=workspace_id,
                task_id=task_id,
                action=action,
                status="completed",
                message="Task marked as requiring human intervention.",
                conversation_id=before.conversation_id,
                attempt_id=before.attempt_id,
                session=after,
            )

        if action == "terminate_stale_conversation":
            if not before.conversation_id:
                raise ValueError("No conversation is linked to this task execution")
            await self._db.execute(
                update(Conversation)
                .where(Conversation.id == before.conversation_id)
                .values(status="archived", updated_at=datetime.now(UTC))
            )
            await self._command_service.update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                metadata=_metadata_patch(task, action, before, action_reason, "completed"),
                reason=action_reason,
                authority=_leader_authority(task),
            )
            after = await self.get_state(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            return TaskRecoveryActionResult(
                workspace_id=workspace_id,
                task_id=task_id,
                action=action,
                status="completed",
                message="Stale conversation archived.",
                conversation_id=before.conversation_id,
                attempt_id=before.attempt_id,
                session=after,
            )

        if action == "reassign":
            if not workspace_agent_id:
                raise ValueError("workspace_agent_id is required for reassign recovery")
            if attempt is not None:
                await self._terminalize_attempt_for_retry(attempt, action_reason)
            task = await self._command_service.assign_task_to_agent(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                workspace_agent_id=workspace_agent_id,
                reason=action_reason,
                authority=_leader_authority(task),
            )
            outbox = await self._enqueue_attempt_retry(
                task=task,
                actor_user_id=actor_user_id,
                reason=action_reason,
                previous_attempt_id=before.attempt_id,
            )
            await self._command_service.update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                metadata=_metadata_patch(task, action, before, action_reason, "queued"),
                reason=action_reason,
                authority=_leader_authority(task),
            )
            after = await self.get_state(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            return TaskRecoveryActionResult(
                workspace_id=workspace_id,
                task_id=task_id,
                action=action,
                status="queued",
                message="Task reassigned and queued for a fresh attempt.",
                conversation_id=before.conversation_id,
                attempt_id=before.attempt_id,
                outbox_id=outbox,
                session=after,
            )

        if action == "new_attempt":
            if attempt is not None:
                await self._terminalize_attempt_for_retry(attempt, action_reason)
            outbox = await self._enqueue_attempt_retry(
                task=task,
                actor_user_id=actor_user_id,
                reason=action_reason,
                previous_attempt_id=before.attempt_id,
            )
            await self._command_service.update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                metadata=_metadata_patch(task, action, before, action_reason, "queued"),
                reason=action_reason,
                authority=_leader_authority(task),
            )
            after = await self.get_state(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            return TaskRecoveryActionResult(
                workspace_id=workspace_id,
                task_id=task_id,
                action=action,
                status="queued",
                message="Fresh worker attempt queued.",
                conversation_id=before.conversation_id,
                attempt_id=before.attempt_id,
                outbox_id=outbox,
                session=after,
            )

        if action == "retry_launch":
            outbox = await self._enqueue_worker_launch(
                task=task,
                actor_user_id=actor_user_id,
                attempt_id=before.attempt_id,
                reason=action_reason,
            )
            await self._command_service.update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                metadata=_metadata_patch(task, action, before, action_reason, "queued"),
                reason=action_reason,
                authority=_leader_authority(task),
            )
            after = await self.get_state(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            return TaskRecoveryActionResult(
                workspace_id=workspace_id,
                task_id=task_id,
                action=action,
                status="queued",
                message="Existing attempt launch queued.",
                conversation_id=before.conversation_id,
                attempt_id=before.attempt_id,
                outbox_id=outbox,
                session=after,
            )

        raise ValueError(f"Unsupported recovery action: {action}")

    async def _require_recovery_actor(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        system_recovery: bool,
    ) -> None:
        if system_recovery:
            return
        await self._require_editor_role(workspace_id=workspace_id, actor_user_id=actor_user_id)

    async def _require_editor_role(self, *, workspace_id: str, actor_user_id: str) -> None:
        role = (
            await self._db.execute(
                refresh_select_statement(
                    select(WorkspaceMemberModel.role).where(
                        WorkspaceMemberModel.workspace_id == workspace_id,
                        WorkspaceMemberModel.user_id == actor_user_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if str(role) not in _EDITOR_ROLES:
            raise PermissionError("Insufficient permission to recover workspace task execution")

    async def _load_conversation(self, conversation_id: str | None) -> Conversation | None:
        if not conversation_id:
            return None
        return await self._db.get(Conversation, conversation_id)

    async def _load_events(self, conversation_id: str | None) -> list[AgentExecutionEvent]:
        if not conversation_id:
            return []
        result = await self._db.execute(
            refresh_select_statement(
                select(AgentExecutionEvent)
                .where(AgentExecutionEvent.conversation_id == conversation_id)
                .order_by(
                    AgentExecutionEvent.event_time_us.desc(),
                    AgentExecutionEvent.event_counter.desc(),
                )
                .limit(50)
            )
        )
        return list(result.scalars().all())

    async def _load_execution_statuses(
        self, conversation_id: str | None
    ) -> list[MessageExecutionStatus]:
        if not conversation_id:
            return []
        result = await self._db.execute(
            refresh_select_statement(
                select(MessageExecutionStatus)
                .where(MessageExecutionStatus.conversation_id == conversation_id)
                .order_by(MessageExecutionStatus.started_at.desc())
                .limit(5)
            )
        )
        return list(result.scalars().all())

    def _build_state(
        self,
        *,
        task: WorkspaceTask,
        attempt: WorkspaceTaskSessionAttempt | None,
        conversation: Conversation | None,
        events: Sequence[AgentExecutionEvent],
        execution_rows: Sequence[MessageExecutionStatus],
    ) -> TaskExecutionSessionState:
        metadata = _metadata(task)
        conversation_id = _conversation_id(task, attempt)
        recent_events = tuple(_event_row(event) for event in events[:8])
        has_user_input = _has_user_input(events)
        has_assistant_output = _has_assistant_output(events)
        error_event = _latest_error_event(events)
        execution_status = execution_rows[0].status if execution_rows else None
        last_event_at = _latest_activity_time(task, attempt, events, execution_rows)
        last_user_input_at = _latest_user_input_time(events)
        last_assistant_event_at = _latest_assistant_time(events)
        incidents = self._incidents(
            task=task,
            attempt=attempt,
            conversation=conversation,
            events=events,
            execution_rows=execution_rows,
            last_event_at=last_event_at,
            last_user_input_at=last_user_input_at,
            has_user_input=has_user_input,
            has_assistant_output=has_assistant_output,
        )
        session_status = _session_status(
            task=task,
            conversation_id=conversation_id,
            has_user_input=has_user_input,
            has_assistant_output=has_assistant_output,
            incidents=incidents,
        )
        health = _health(task=task, incidents=incidents, session_status=session_status)
        return TaskExecutionSessionState(
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_status=task.status.value,
            health=health,
            session_status=session_status,
            conversation_id=conversation_id,
            attempt_id=attempt.id if attempt else _text(metadata.get(CURRENT_ATTEMPT_ID)),
            attempt_status=(
                attempt.status.value if attempt else _text(metadata.get("last_attempt_status"))
            ),
            execution_status=execution_status,
            last_event_at=last_event_at,
            last_assistant_event_at=last_assistant_event_at,
            last_error=_error_message(error_event),
            has_user_input=has_user_input,
            has_assistant_output=has_assistant_output,
            incidents=tuple(incidents),
            recommended_recovery_action=_recommended_recovery_action(
                task=task,
                incidents=incidents,
                metadata=metadata,
                attempt_status=(
                    attempt.status.value if attempt else _text(metadata.get("last_attempt_status"))
                ),
            ),
            available_interventions=_available_interventions(task, incidents, conversation_id),
            recent_events=recent_events,
            recovery_actions=tuple(_recovery_ledger(metadata)),
        )

    def _incidents(
        self,
        *,
        task: WorkspaceTask,
        attempt: WorkspaceTaskSessionAttempt | None,
        conversation: Conversation | None,
        events: Sequence[AgentExecutionEvent],
        execution_rows: Sequence[MessageExecutionStatus],
        last_event_at: datetime | None,
        last_user_input_at: datetime | None,
        has_user_input: bool,
        has_assistant_output: bool,
    ) -> list[TaskExecutionIncident]:
        if task.status is not WorkspaceTaskStatus.IN_PROGRESS:
            return []
        now = datetime.now(UTC)
        incidents: list[TaskExecutionIncident] = []
        conversation_id = _conversation_id(task, attempt)
        error_event = _latest_error_event(events)
        if error_event is not None and _is_agent_initialization_failure(error_event):
            incidents.append(
                TaskExecutionIncident(
                    type="agent_initialization_failed",
                    severity="error",
                    summary="Agent initialization failed before any assistant response.",
                    evidence=_event_evidence(error_event),
                    opened_at=error_event.created_at,
                )
            )
        if conversation_id and not execution_rows and not events:
            incidents.append(
                TaskExecutionIncident(
                    type="missing_execution_status",
                    severity="warning",
                    summary="Conversation is bound but has no message execution status row.",
                    evidence={"conversation_id": conversation_id},
                    opened_at=attempt.updated_at if attempt else task.updated_at,
                )
            )
        if (
            has_user_input
            and not has_assistant_output
            and _older_than(last_user_input_at, now, _NO_ASSISTANT_RESPONSE_SECONDS)
        ):
            incidents.append(
                TaskExecutionIncident(
                    type="no_assistant_response",
                    severity="error",
                    summary="Conversation accepted input but produced no assistant/tool/progress output.",
                    evidence={
                        "conversation_id": conversation_id,
                        "last_user_input_at": _datetime_iso(last_user_input_at),
                        "last_event_at": _datetime_iso(last_event_at),
                    },
                    opened_at=last_user_input_at or last_event_at,
                )
            )
        if _older_than(last_event_at, now, _STALE_PROCESSING_SECONDS):
            incidents.append(
                TaskExecutionIncident(
                    type="stale_processing",
                    severity="warning",
                    summary="Task is still processing but execution activity is stale.",
                    evidence={"last_event_at": _datetime_iso(last_event_at)},
                    opened_at=last_event_at,
                )
            )
        if attempt and not conversation_id:
            incidents.append(
                TaskExecutionIncident(
                    type="lost_binding",
                    severity="error",
                    summary="Attempt exists but no conversation is bound to the task execution.",
                    evidence={"attempt_id": attempt.id},
                    opened_at=attempt.updated_at or attempt.created_at,
                )
            )
        elif conversation_id and conversation is None:
            incidents.append(
                TaskExecutionIncident(
                    type="lost_binding",
                    severity="error",
                    summary="Attempt references a conversation that no longer exists.",
                    evidence={"conversation_id": conversation_id},
                    opened_at=attempt.updated_at if attempt else task.updated_at,
                )
            )
        elif conversation_id and conversation is not None:
            linked_task_id = getattr(conversation, "linked_workspace_task_id", None)
            workspace_id = getattr(conversation, "workspace_id", None)
            if workspace_id != task.workspace_id or linked_task_id != task.id:
                incidents.append(
                    TaskExecutionIncident(
                        type="lost_binding",
                        severity="warning",
                        summary="Conversation lacks canonical workspace task linkage.",
                        evidence={
                            "conversation_id": conversation_id,
                            "conversation_workspace_id": workspace_id,
                            "linked_workspace_task_id": linked_task_id,
                        },
                        opened_at=getattr(conversation, "updated_at", None)
                        or getattr(conversation, "created_at", None),
                    )
                )
        return incidents

    async def _terminalize_attempt_for_retry(
        self,
        attempt: WorkspaceTaskSessionAttempt,
        reason: str,
    ) -> None:
        if attempt.status in {
            WorkspaceTaskSessionAttemptStatus.ACCEPTED,
            WorkspaceTaskSessionAttemptStatus.REJECTED,
            WorkspaceTaskSessionAttemptStatus.BLOCKED,
            WorkspaceTaskSessionAttemptStatus.CANCELLED,
        }:
            return
        attempt_service = WorkspaceTaskSessionAttemptService(self._attempt_repo)
        await attempt_service.block(
            attempt.id,
            leader_feedback=reason,
            adjudication_reason="task_execution_session_recovery",
        )

    async def _ensure_attempt_for_human_block(
        self,
        *,
        task: WorkspaceTask,
        attempt: WorkspaceTaskSessionAttempt | None,
        before: TaskExecutionSessionState,
        reason: str,
    ) -> WorkspaceTaskSessionAttempt:
        attempt_service = WorkspaceTaskSessionAttemptService(self._attempt_repo)
        if attempt is None:
            metadata = _metadata(task)
            attempt = await attempt_service.create_attempt(
                workspace_task_id=task.id,
                root_goal_task_id=_root_goal_task_id(task) or task.id,
                workspace_id=task.workspace_id,
                worker_agent_id=task.assignee_agent_id,
                leader_agent_id=_text(metadata.get("leader_agent_id")),
                conversation_id=before.conversation_id,
            )
        elif before.conversation_id and not attempt.conversation_id:
            attempt = await attempt_service.bind_conversation(attempt.id, before.conversation_id)
        return await attempt_service.block(
            attempt.id,
            leader_feedback=reason,
            adjudication_reason="task_execution_session_recovery",
        )

    async def _enqueue_attempt_retry(
        self,
        *,
        task: WorkspaceTask,
        actor_user_id: str,
        reason: str,
        previous_attempt_id: str | None,
    ) -> str:
        metadata = _metadata(task)
        outbox = await SqlWorkspacePlanOutboxRepository(self._db).enqueue(
            plan_id=_text(metadata.get(WORKSPACE_PLAN_ID)),
            workspace_id=task.workspace_id,
            event_type=ATTEMPT_RETRY_EVENT,
            payload={
                "workspace_id": task.workspace_id,
                "task_id": task.id,
                "worker_agent_id": task.assignee_agent_id,
                "actor_user_id": actor_user_id,
                "leader_agent_id": _text(metadata.get("leader_agent_id")),
                "node_id": _text(metadata.get(WORKSPACE_PLAN_NODE_ID)),
                "root_goal_task_id": _root_goal_task_id(task),
                "previous_attempt_id": previous_attempt_id,
                "reason": "retry",
                "force_schedule": True,
                "extra_instructions": (
                    "Recover this workspace task after a silent or failed execution session. "
                    f"Recovery reason: {reason}"
                ),
            },
            metadata={"source": "task_execution_session.recovery", "action": "new_attempt"},
        )
        return str(outbox.id)

    async def _enqueue_worker_launch(
        self,
        *,
        task: WorkspaceTask,
        actor_user_id: str,
        attempt_id: str | None,
        reason: str,
    ) -> str:
        metadata = _metadata(task)
        outbox = await SqlWorkspacePlanOutboxRepository(self._db).enqueue(
            plan_id=_text(metadata.get(WORKSPACE_PLAN_ID)),
            workspace_id=task.workspace_id,
            event_type=WORKER_LAUNCH_EVENT,
            payload={
                "workspace_id": task.workspace_id,
                "task_id": task.id,
                "worker_agent_id": task.assignee_agent_id,
                "actor_user_id": actor_user_id,
                "leader_agent_id": _text(metadata.get("leader_agent_id")),
                "node_id": _text(metadata.get(WORKSPACE_PLAN_NODE_ID)),
                "attempt_id": attempt_id,
                "extra_instructions": (
                    "Retry this workspace task launch after a silent or failed execution session. "
                    f"Recovery reason: {reason}"
                ),
            },
            metadata={"source": "task_execution_session.recovery", "action": "retry_launch"},
        )
        return str(outbox.id)


def _current_attempt(
    task: WorkspaceTask,
    attempts: Sequence[WorkspaceTaskSessionAttempt],
) -> WorkspaceTaskSessionAttempt | None:
    current_attempt_id = _text(_metadata(task).get(CURRENT_ATTEMPT_ID))
    if current_attempt_id:
        for attempt in attempts:
            if attempt.id == current_attempt_id:
                return attempt
    return attempts[0] if attempts else None


def _conversation_id(
    task: WorkspaceTask,
    attempt: WorkspaceTaskSessionAttempt | None,
) -> str | None:
    if attempt and attempt.conversation_id:
        return attempt.conversation_id
    return _text(_metadata(task).get("current_attempt_conversation_id"))


def _metadata(task: WorkspaceTask) -> dict[str, Any]:
    metadata = getattr(task, "metadata", {}) or {}
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _metadata_patch(
    task: WorkspaceTask,
    action: str,
    before: TaskExecutionSessionState,
    reason: str,
    status: str,
    *,
    current_attempt_id: str | None = None,
) -> dict[str, object]:
    metadata = _metadata(task)
    ledger = _recovery_ledger(metadata)
    attempt_id = current_attempt_id or before.attempt_id
    entry = {
        "action": action,
        "status": status,
        "reason": reason,
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "attempt_id": attempt_id,
        "conversation_id": before.conversation_id,
        "incident_types": [incident.type for incident in before.incidents],
    }
    patch: dict[str, object] = {
        "task_execution_session_health": before.health,
        "task_execution_session_status": before.session_status,
        "task_execution_session_last_error": before.last_error,
        "task_execution_session_last_checked_at": datetime.now(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "execution_recovery_actions": [entry, *ledger][:_MAX_RECOVERY_LEDGER_ITEMS],
    }
    if attempt_id:
        patch[CURRENT_ATTEMPT_ID] = attempt_id
    return patch


def _recovery_ledger(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = metadata.get("execution_recovery_actions")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)][:_MAX_RECOVERY_LEDGER_ITEMS]


def _event_row(event: AgentExecutionEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "type": event.event_type,
        "message_id": event.message_id,
        "at": _datetime_iso(event.created_at),
        "summary": _event_summary(event),
    }


def _event_summary(event: AgentExecutionEvent) -> str:
    payload = event.event_data if isinstance(event.event_data, Mapping) else {}
    for key in ("message", "content", "summary", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value[:240]
    return event.event_type


def _has_user_input(events: Sequence[AgentExecutionEvent]) -> bool:
    for event in events:
        if event.event_type == "user_message":
            return True
        if event.event_type == "message":
            role = _event_role(event)
            if role == "user":
                return True
    return False


def _latest_user_input_time(events: Sequence[AgentExecutionEvent]) -> datetime | None:
    for event in events:
        if event.event_type == "user_message":
            return event.created_at
        if event.event_type == "message" and _event_role(event) == "user":
            return event.created_at
    return None


def _has_assistant_output(events: Sequence[AgentExecutionEvent]) -> bool:
    for event in events:
        if event.event_type in _ASSISTANT_OUTPUT_EVENT_TYPES:
            return True
        if event.event_type == "message" and _event_role(event) == "assistant":
            return True
    return False


def _event_role(event: AgentExecutionEvent) -> str | None:
    payload = event.event_data if isinstance(event.event_data, Mapping) else {}
    role = payload.get("role")
    return role if isinstance(role, str) else None


def _latest_error_event(events: Sequence[AgentExecutionEvent]) -> AgentExecutionEvent | None:
    return next((event for event in events if event.event_type == "error"), None)


def _latest_assistant_time(events: Sequence[AgentExecutionEvent]) -> datetime | None:
    for event in events:
        if event.event_type in _ASSISTANT_OUTPUT_EVENT_TYPES:
            return event.created_at
        if event.event_type == "message" and _event_role(event) == "assistant":
            return event.created_at
    return None


def _latest_activity_time(
    task: WorkspaceTask,
    attempt: WorkspaceTaskSessionAttempt | None,
    events: Sequence[AgentExecutionEvent],
    execution_rows: Sequence[MessageExecutionStatus],
) -> datetime | None:
    candidates: list[datetime] = []
    candidates.extend(event.created_at for event in events)
    for row in execution_rows:
        candidates.append(row.completed_at or row.started_at)
    if attempt is not None:
        candidates.append(attempt.updated_at or attempt.created_at)
    if task.updated_at is not None:
        candidates.append(task.updated_at)
    return max((_as_aware(value) for value in candidates), default=None)


def _is_agent_initialization_failure(error_event: AgentExecutionEvent | None) -> bool:
    if error_event is None:
        return False
    payload = error_event.event_data if isinstance(error_event.event_data, Mapping) else {}
    code = payload.get("code")
    message = payload.get("message")
    return code == "AGENT_NOT_INITIALIZED" or (
        isinstance(message, str) and "agent initialization failed" in message.lower()
    )


def _event_evidence(event: AgentExecutionEvent | None) -> dict[str, Any]:
    if event is None:
        return {}
    payload = event.event_data if isinstance(event.event_data, Mapping) else {}
    return {
        "event_id": event.id,
        "message_id": event.message_id,
        "event_type": event.event_type,
        "code": payload.get("code"),
        "message": payload.get("message"),
    }


def _error_message(error_event: AgentExecutionEvent | None) -> str | None:
    if error_event is None:
        return None
    payload = error_event.event_data if isinstance(error_event.event_data, Mapping) else {}
    message = payload.get("message")
    return message if isinstance(message, str) and message else error_event.event_type


def _available_interventions(
    task: WorkspaceTask,
    incidents: Sequence[TaskExecutionIncident],
    conversation_id: str | None,
) -> tuple[str, ...]:
    if task.status is not WorkspaceTaskStatus.IN_PROGRESS:
        return ()
    incident_types = {incident.type for incident in incidents}
    actions: list[str] = []
    if incident_types:
        actions.extend(["new_attempt", "retry_launch", "mark_human_blocked"])
    if "lost_binding" in incident_types or "agent_initialization_failed" in incident_types:
        actions.append("reassign")
    if conversation_id and (
        "stale_processing" in incident_types or "no_assistant_response" in incident_types
    ):
        actions.append("terminate_stale_conversation")
    return tuple(dict.fromkeys(actions))


def _recommended_recovery_action(
    *,
    task: WorkspaceTask,
    incidents: Sequence[TaskExecutionIncident],
    metadata: Mapping[str, Any],
    attempt_status: str | None,
) -> str:
    if task.status is not WorkspaceTaskStatus.IN_PROGRESS:
        return "suppress"
    incident_types = {incident.type for incident in incidents}
    if not incident_types:
        return "suppress"
    if _recovery_attempt_count(metadata) >= _MAX_AUTOMATIC_RECOVERY_ATTEMPTS:
        return "mark_human_blocked"
    if _attempt_status_requires_fresh_attempt(attempt_status) or incident_types.intersection(
        {
            "agent_initialization_failed",
            "missing_execution_status",
            "no_assistant_response",
            "lost_binding",
        }
    ):
        return "new_attempt"
    if "stale_processing" in incident_types:
        return "retry_launch"
    return "suppress"


def _attempt_status_requires_fresh_attempt(attempt_status: str | None) -> bool:
    return attempt_status in {
        WorkspaceTaskSessionAttemptStatus.REJECTED.value,
        WorkspaceTaskSessionAttemptStatus.BLOCKED.value,
        WorkspaceTaskSessionAttemptStatus.CANCELLED.value,
    }


def _recovery_attempt_count(metadata: Mapping[str, Any]) -> int:
    return sum(
        1
        for item in _recovery_ledger(metadata)
        if item.get("action") in {"retry_launch", "new_attempt", "reassign"}
    )


def _session_status(  # noqa: PLR0911 - explicit projection states keep API output stable.
    *,
    task: WorkspaceTask,
    conversation_id: str | None,
    has_user_input: bool,
    has_assistant_output: bool,
    incidents: Sequence[TaskExecutionIncident],
) -> str:
    if task.status is WorkspaceTaskStatus.DONE:
        return "completed"
    if task.status is WorkspaceTaskStatus.BLOCKED:
        return "needs_human_intervention"
    if task.status is WorkspaceTaskStatus.TODO:
        return "not_started"
    incident_types = {incident.type for incident in incidents}
    if "agent_initialization_failed" in incident_types:
        return "initialization_failed"
    if not conversation_id:
        return "missing_session"
    if incident_types:
        return "degraded"
    if has_assistant_output:
        return "active"
    if has_user_input:
        return "waiting_response"
    return "launched"


def _health(
    *,
    task: WorkspaceTask,
    incidents: Sequence[TaskExecutionIncident],
    session_status: str,
) -> str:
    if task.status is WorkspaceTaskStatus.DONE:
        return "healthy"
    if task.status is WorkspaceTaskStatus.BLOCKED:
        return "blocked"
    if any(incident.severity == "error" for incident in incidents):
        return "degraded"
    if incidents:
        return "warning"
    if session_status in {"active", "waiting_response", "launched"}:
        return "healthy"
    return "unknown"


def _default_action_reason(before: TaskExecutionSessionState, action: str) -> str:
    if before.incidents:
        return f"{action}: {before.incidents[0].summary}"
    return f"{action}: operator requested task execution recovery"


def _root_goal_task_id(task: WorkspaceTask) -> str:
    return _text(_metadata(task).get(ROOT_GOAL_TASK_ID)) or task.id


def _leader_authority(task: WorkspaceTask) -> WorkspaceTaskAuthorityContext:
    return WorkspaceTaskAuthorityContext.leader(_text(_metadata(task).get("leader_agent_id")))


def _older_than(value: datetime | None, now: datetime, seconds: int) -> bool:
    if value is None:
        return True
    return _as_aware(value) < now - timedelta(seconds=seconds)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _datetime_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_aware(value).isoformat().replace("+00:00", "Z")


__all__ = [
    "TaskExecutionIncident",
    "TaskExecutionSessionMonitor",
    "TaskExecutionSessionState",
    "TaskRecoveryAction",
    "TaskRecoveryActionResult",
]
