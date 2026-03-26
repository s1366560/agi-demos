from abc import ABC, abstractmethod

from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus


class WorkspaceTaskRepository(ABC):
    """Repository interface for workspace tasks."""

    @abstractmethod
    async def save(self, task: WorkspaceTask) -> WorkspaceTask:
        """Save a workspace task (create or update)."""

    @abstractmethod
    async def find_by_id(self, task_id: str) -> WorkspaceTask | None:
        """Find workspace task by ID."""

    @abstractmethod
    async def find_by_workspace(
        self,
        workspace_id: str,
        status: WorkspaceTaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceTask]:
        """List tasks in a workspace."""

    @abstractmethod
    async def delete(self, task_id: str) -> bool:
        """Delete workspace task by ID."""
