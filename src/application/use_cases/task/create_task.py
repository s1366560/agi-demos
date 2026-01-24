"""
Use case for creating a new task log.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.domain.model.task.task_log import TaskLog
from src.domain.ports.repositories.task_repository import TaskRepository


@dataclass
class CreateTaskCommand:
    """Command to create a new task log"""

    group_id: str
    task_type: str
    payload: Dict[str, Any] = None
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    parent_task_id: Optional[str] = None

    def __post_init__(self):
        if self.payload is None:
            self.payload = {}


class CreateTaskUseCase:
    """Use case for creating task logs"""

    def __init__(self, task_repository: TaskRepository):
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
            status="PENDING",
        )

        await self._task_repo.save(task)
        return task
