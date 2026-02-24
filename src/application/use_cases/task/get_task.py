"""
Use case for getting a task log by ID.
"""

from pydantic import BaseModel, field_validator

from src.domain.model.task.task_log import TaskLog
from src.domain.ports.repositories.task_repository import TaskRepository


class GetTaskQuery(BaseModel):
    """Query to get a task by ID"""

    model_config = {"frozen": True}

    task_id: str

    @field_validator("task_id")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v


class GetTaskUseCase:
    """Use case for retrieving a single task"""

    def __init__(self, task_repository: TaskRepository) -> None:
        self._task_repo = task_repository

    async def execute(self, query: GetTaskQuery) -> TaskLog | None:
        """
        Get a task by ID.

        Args:
            query: GetTaskQuery containing task_id

        Returns:
            TaskLog if found, None otherwise
        """
        return await self._task_repo.find_by_id(query.task_id)
