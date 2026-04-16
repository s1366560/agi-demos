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
    async def find_root_by_objective_id(
        self,
        workspace_id: str,
        objective_id: str,
    ) -> WorkspaceTask | None:
        """Find an existing projected root goal task for a workspace objective."""

    @abstractmethod
    async def find_by_root_goal_task_id(
        self,
        workspace_id: str,
        root_goal_task_id: str,
    ) -> list[WorkspaceTask]:
        """List execution tasks linked to a root goal task."""

    @abstractmethod
    async def delete(self, task_id: str) -> bool:
        """Delete workspace task by ID."""
