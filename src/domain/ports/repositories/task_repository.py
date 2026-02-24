from abc import ABC, abstractmethod

from src.domain.model.task.task_log import TaskLog


class TaskRepository(ABC):
    """Repository interface for TaskLog entity"""

    @abstractmethod
    async def save(self, task: TaskLog) -> None:
        """Save a task log (create or update)"""

    @abstractmethod
    async def find_by_id(self, task_id: str) -> TaskLog | None:
        """Find a task by ID"""

    @abstractmethod
    async def find_by_group(self, group_id: str, limit: int = 50, offset: int = 0) -> list[TaskLog]:
        """List all tasks in a group"""

    @abstractmethod
    async def list_recent(self, limit: int = 100) -> list[TaskLog]:
        """List recent tasks across all groups"""

    @abstractmethod
    async def list_by_status(self, status: str, limit: int = 50, offset: int = 0) -> list[TaskLog]:
        """List tasks by status"""

    @abstractmethod
    async def delete(self, task_id: str) -> None:
        """Delete a task"""
