"""
Use case for listing task logs.
"""

from pydantic import BaseModel, Field

from src.domain.model.task.task_log import TaskLog
from src.domain.ports.repositories.task_repository import TaskRepository


class ListTasksQuery(BaseModel):
    """Query to list tasks"""

    model_config = {"frozen": True}

    group_id: str | None = None
    status: str | None = None
    limit: int = Field(default=100, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


class ListTasksUseCase:
    """Use case for listing task logs"""

    def __init__(self, task_repository: TaskRepository) -> None:
        self._task_repo = task_repository

    async def execute(self, query: ListTasksQuery) -> list[TaskLog]:
        """
        List tasks with optional filters.

        Args:
            query: ListTasksQuery with filters and pagination

        Returns:
            List of TaskLog entities
        """
        if query.group_id:
            return await self._task_repo.find_by_group(
                query.group_id, limit=query.limit, offset=query.offset
            )
        elif query.status:
            return await self._task_repo.list_by_status(
                query.status, limit=query.limit, offset=query.offset
            )
        else:
            return await self._task_repo.list_recent(limit=query.limit)
