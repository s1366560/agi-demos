"""
Use case for creating a new task log.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.domain.model.task.task_log import TaskLog, TaskLogStatus
from src.domain.ports.repositories.task_repository import TaskRepository


class CreateTaskCommand(BaseModel):
    """Command to create a new task log"""

    model_config = {"frozen": True}

    group_id: str
    task_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    entity_id: str | None = None
    entity_type: str | None = None
    parent_task_id: str | None = None

    @field_validator("group_id", "task_type")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("payload", mode="before")
    @classmethod
    def coerce_none_payload(cls, v: dict[str, Any] | None) -> dict[str, Any]:
        return v if v is not None else {}


class CreateTaskUseCase:
    """Use case for creating task logs"""

    def __init__(self, task_repository: TaskRepository) -> None:
        self._task_repo = task_repository

    async def execute(self, command: CreateTaskCommand) -> TaskLog:
        """
        Create a new task log.

        Args:
            command: CreateTaskCommand with task details

        Returns:
            Created TaskLog entity
        """
        task = TaskLog(
            group_id=command.group_id,
            task_type=command.task_type,
            payload=command.payload,
            entity_id=command.entity_id,
            entity_type=command.entity_type,
            parent_task_id=command.parent_task_id,
            status=TaskLogStatus.PENDING,
        )

        await self._task_repo.save(task)
        return task
