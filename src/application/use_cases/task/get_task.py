"""
Use case for getting a task log by ID.
"""

from dataclasses import dataclass
from typing import Optional

from src.domain.model.task.task_log import TaskLog
from src.domain.ports.repositories.task_repository import TaskRepository


@dataclass
class GetTaskQuery:
    """Query to get a task by ID"""

    task_id: str


class GetTaskUseCase:
    """Use case for retrieving a single task"""

    def __init__(self, task_repository: TaskRepository):
        self._task_repo = task_repository

    async def execute(self, query: GetTaskQuery) -> Optional[TaskLog]:
        """
        Get a task by ID.

        Args:
            query: GetTaskQuery containing task_id

        Returns:
            TaskLog if found, None otherwise
        """
        return await self._task_repo.find_by_id(query.task_id)
