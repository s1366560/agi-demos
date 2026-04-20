"""Application service for workspace task session attempt lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.ports.repositories.workspace.workspace_task_session_attempt_repository import (
    WorkspaceTaskSessionAttemptRepository,
)


class WorkspaceTaskSessionAttemptService:
    """Manage session attempts for a workspace task."""

    def __init__(
        self,
        attempt_repo: WorkspaceTaskSessionAttemptRepository,
    ) -> None:
        self._attempt_repo = attempt_repo

    async def get_attempt(self, attempt_id: str) -> WorkspaceTaskSessionAttempt | None:
        """Return an attempt by ID."""
        return await self._attempt_repo.find_by_id(attempt_id)

    async def get_active_attempt(
        self,
        workspace_task_id: str,
    ) -> WorkspaceTaskSessionAttempt | None:
        """Return the active attempt for a workspace task, if any."""
        return await self._attempt_repo.find_active_by_workspace_task_id(workspace_task_id)

    async def create_attempt(
        self,
        *,
        workspace_task_id: str,
        root_goal_task_id: str,
        workspace_id: str,
        worker_agent_id: str | None,
        leader_agent_id: str | None,
        conversation_id: str | None = None,
    ) -> WorkspaceTaskSessionAttempt:
        active_attempt = await self.get_active_attempt(workspace_task_id)
        if active_attempt is not None:
            raise ValueError("Workspace task already has an active session attempt")

        prior_attempts = await self._attempt_repo.find_by_workspace_task_id(
            workspace_task_id,
            limit=1,
        )
        next_attempt_number = (prior_attempts[0].attempt_number + 1) if prior_attempts else 1
        now = datetime.now(UTC)
        attempt = WorkspaceTaskSessionAttempt(
            id=WorkspaceTaskSessionAttempt.generate_id(),
            workspace_task_id=workspace_task_id,
            root_goal_task_id=root_goal_task_id,
            workspace_id=workspace_id,
            attempt_number=next_attempt_number,
            status=WorkspaceTaskSessionAttemptStatus.PENDING,
            conversation_id=conversation_id,
            worker_agent_id=worker_agent_id,
            leader_agent_id=leader_agent_id,
            created_at=now,
            updated_at=now,
        )
        return await self._attempt_repo.save(attempt)

    async def mark_running(self, attempt_id: str) -> WorkspaceTaskSessionAttempt:
        return await self._set_status(attempt_id, WorkspaceTaskSessionAttemptStatus.RUNNING)

    async def bind_conversation(
        self,
        attempt_id: str,
        conversation_id: str,
    ) -> WorkspaceTaskSessionAttempt:
        """Bind a conversation to an attempt. Idempotent for same id; rejects rebind."""
        if not conversation_id:
            raise ValueError("conversation_id is required")
        attempt = await self._require_attempt(attempt_id)
        terminal = {
            WorkspaceTaskSessionAttemptStatus.ACCEPTED,
            WorkspaceTaskSessionAttemptStatus.REJECTED,
            WorkspaceTaskSessionAttemptStatus.BLOCKED,
        }
        if attempt.status in terminal:
            raise ValueError(
                f"Cannot bind conversation to attempt in terminal status {attempt.status}"
            )
        if attempt.conversation_id == conversation_id:
            return attempt
        if attempt.conversation_id and attempt.conversation_id != conversation_id:
            raise ValueError(
                f"Attempt already bound to a different conversation ({attempt.conversation_id})"
            )
        attempt.conversation_id = conversation_id
        attempt.updated_at = datetime.now(UTC)
        return await self._attempt_repo.save(attempt)

    async def record_candidate_output(
        self,
        attempt_id: str,
        *,
        summary: str | None,
        artifacts: list[str],
        verifications: list[str],
        conversation_id: str | None = None,
    ) -> WorkspaceTaskSessionAttempt:
        attempt = await self._require_attempt(attempt_id)
        if conversation_id:
            attempt.conversation_id = conversation_id
        attempt.candidate_summary = summary
        attempt.candidate_artifacts = list(dict.fromkeys(artifacts))
        attempt.candidate_verifications = list(dict.fromkeys(verifications))
        attempt.status = WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION
        attempt.updated_at = datetime.now(UTC)
        return await self._attempt_repo.save(attempt)

    async def accept(
        self,
        attempt_id: str,
        *,
        leader_feedback: str | None = None,
    ) -> WorkspaceTaskSessionAttempt:
        attempt = await self._require_attempt(attempt_id)
        attempt.status = WorkspaceTaskSessionAttemptStatus.ACCEPTED
        attempt.leader_feedback = leader_feedback
        attempt.completed_at = datetime.now(UTC)
        attempt.updated_at = attempt.completed_at
        return await self._attempt_repo.save(attempt)

    async def reject(
        self,
        attempt_id: str,
        *,
        leader_feedback: str,
        adjudication_reason: str | None = None,
    ) -> WorkspaceTaskSessionAttempt:
        attempt = await self._require_attempt(attempt_id)
        attempt.status = WorkspaceTaskSessionAttemptStatus.REJECTED
        attempt.leader_feedback = leader_feedback
        attempt.adjudication_reason = adjudication_reason
        attempt.completed_at = datetime.now(UTC)
        attempt.updated_at = attempt.completed_at
        return await self._attempt_repo.save(attempt)

    async def block(
        self,
        attempt_id: str,
        *,
        leader_feedback: str,
        adjudication_reason: str | None = None,
    ) -> WorkspaceTaskSessionAttempt:
        attempt = await self._require_attempt(attempt_id)
        attempt.status = WorkspaceTaskSessionAttemptStatus.BLOCKED
        attempt.leader_feedback = leader_feedback
        attempt.adjudication_reason = adjudication_reason
        attempt.completed_at = datetime.now(UTC)
        attempt.updated_at = attempt.completed_at
        return await self._attempt_repo.save(attempt)

    async def _set_status(
        self,
        attempt_id: str,
        status: WorkspaceTaskSessionAttemptStatus,
    ) -> WorkspaceTaskSessionAttempt:
        attempt = await self._require_attempt(attempt_id)
        attempt.status = status
        attempt.updated_at = datetime.now(UTC)
        return await self._attempt_repo.save(attempt)

    async def _require_attempt(self, attempt_id: str) -> WorkspaceTaskSessionAttempt:
        attempt = await self.get_attempt(attempt_id)
        if attempt is None:
            raise ValueError(f"Workspace task session attempt {attempt_id} not found")
        return attempt
