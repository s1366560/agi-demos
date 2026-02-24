"""
Use case for updating a task log.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from src.domain.model.task.task_log import TaskLog
from src.domain.ports.repositories.task_repository import TaskRepository


class UpdateTaskCommand(BaseModel):
    """Command to update a task"""

    model_config = {"frozen": True}

    task_id: str
    status: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    worker_id: Optional[str] = None

    @field_validator("task_id")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v


class UpdateTaskUseCase:
    """Use case for updating task logs"""

    def __init__(self, task_repository: TaskRepository):
        self._task_repo = task_repository

    async def execute(self, command: UpdateTaskCommand) -> Optional[TaskLog]:
        """
        Update a task.

        Args:
            command: UpdateTaskCommand with updates

        Returns:
            Updated TaskLog if found, None otherwise
        """
        # Get existing task
        task = await self._task_repo.find_by_id(command.task_id)

        if not task:
            return None

        # Update fields
        if command.status is not None:
            task.status = command.status
        if command.error_message is not None:
            task.error_message = command.error_message
        if command.started_at is not None:
            task.started_at = command.started_at
        if command.completed_at is not None:
            task.completed_at = command.completed_at
        if command.stopped_at is not None:
            task.stopped_at = command.stopped_at
        if command.worker_id is not None:
            task.worker_id = command.worker_id

        # Save changes
        await self._task_repo.save(task)
        return task
