"""DI sub-container for task domain."""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.task_service import TaskService
from src.application.use_cases.task import (
    CreateTaskUseCase,
    GetTaskUseCase,
    ListTasksUseCase,
    UpdateTaskUseCase,
)
from src.domain.ports.repositories.task_repository import TaskRepository
from src.infrastructure.adapters.secondary.persistence.sql_task_repository import (
    SqlTaskRepository,
)


class TaskContainer:
    """Sub-container for task-related services and use cases.

    Provides factory methods for task repository, service,
    and all task use cases.
    """

    def __init__(self, db: Optional[AsyncSession] = None) -> None:
        self._db = db

    def task_repository(self) -> TaskRepository:
        """Get TaskRepository for task persistence."""
        return SqlTaskRepository(self._db)

    def task_service(self) -> TaskService:
        """Get TaskService for task operations."""
        return TaskService(task_repo=self.task_repository())

    def create_task_use_case(self) -> CreateTaskUseCase:
        """Get CreateTaskUseCase with dependencies injected."""
        return CreateTaskUseCase(self.task_repository())

    def get_task_use_case(self) -> GetTaskUseCase:
        """Get GetTaskUseCase with dependencies injected."""
        return GetTaskUseCase(self.task_repository())

    def list_tasks_use_case(self) -> ListTasksUseCase:
        """Get ListTasksUseCase with dependencies injected."""
        return ListTasksUseCase(self.task_repository())

    def update_task_use_case(self) -> UpdateTaskUseCase:
        """Get UpdateTaskUseCase with dependencies injected."""
        return UpdateTaskUseCase(self.task_repository())
