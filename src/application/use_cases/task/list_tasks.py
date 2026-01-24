"""
Use case for listing task logs.
"""

from dataclasses import dataclass
from typing import List, Optional

from src.domain.model.task.task_log import TaskLog
from src.domain.ports.repositories.task_repository import TaskRepository


@dataclass
class ListTasksQuery:
    """Query to list tasks"""

    group_id: Optional[str] = None
    status: Optional[str] = None
    limit: int = 100
    offset: int = 0


class ListTasksUseCase:
    """Use case for listing task logs"""

    def __init__(self, task_repository: TaskRepository):
        self._task_repo = task_repository

    async def execute(self, query: ListTasksQuery) -> List[TaskLog]:
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
