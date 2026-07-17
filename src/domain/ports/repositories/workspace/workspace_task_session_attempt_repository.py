from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)


class WorkspaceTaskSessionAttemptRepository(ABC):
    """Repository interface for workspace task session attempts."""

    @abstractmethod
    async def save(self, attempt: WorkspaceTaskSessionAttempt) -> WorkspaceTaskSessionAttempt:
        """Save a workspace task session attempt."""

    @abstractmethod
    async def lock_attempt_creation(self, workspace_task_id: str) -> None:
        """Serialize attempt creation for one workspace task within the current transaction."""

    @abstractmethod
    async def find_by_id(self, attempt_id: str) -> WorkspaceTaskSessionAttempt | None:
        """Find attempt by ID."""

    @abstractmethod
    async def find_by_workspace_task_id(
        self,
        workspace_task_id: str,
        *,
        statuses: list[WorkspaceTaskSessionAttemptStatus] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceTaskSessionAttempt]:
        """List attempts for a workspace task."""

    async def find_by_workspace_task_ids(
        self,
        workspace_task_ids: list[str],
        *,
        limit_per_task: int = 3,
    ) -> dict[str, list[WorkspaceTaskSessionAttempt]]:
        """List the latest attempts per task for many tasks, keyed by task ID.

        The default implementation issues one query per task; backends should
        override it with a single window-function query to avoid N+1 reads.
        """
        attempts_by_task: dict[str, list[WorkspaceTaskSessionAttempt]] = {}
        for workspace_task_id in workspace_task_ids:
            attempts_by_task[workspace_task_id] = await self.find_by_workspace_task_id(
                workspace_task_id,
                limit=limit_per_task,
            )
        return attempts_by_task

    @abstractmethod
    async def find_active_by_workspace_task_id(
        self, workspace_task_id: str
    ) -> WorkspaceTaskSessionAttempt | None:
        """Find the active attempt for a workspace task, if any."""

    @abstractmethod
    async def find_by_conversation_id(
        self, conversation_id: str
    ) -> WorkspaceTaskSessionAttempt | None:
        """Find the attempt bound to a scoped conversation."""

    @abstractmethod
    async def find_stale_non_terminal(
        self,
        *,
        older_than: datetime,
        limit: int = 500,
        workspace_id: str | None = None,
    ) -> list[WorkspaceTaskSessionAttempt]:
        """Return non-terminal attempts (pending/running/awaiting_leader_adjudication)
        whose ``updated_at`` (falling back to ``created_at``) is older than
        ``older_than``. Used by the orphan-recovery sweep.
        """
