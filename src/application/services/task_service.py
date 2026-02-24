"""
TaskService: Business logic for background task management.

This service handles task monitoring, retry logic, and task status queries.
With Temporal as the workflow engine, retry and stop operations work through
Temporal's built-in mechanisms.
"""

import logging
from datetime import UTC, datetime

from typing import Any, cast
from src.domain.model.task.task_log import TaskLog, TaskLogStatus
from src.domain.ports.repositories.task_repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskService:
    """Service for managing background tasks"""

    def __init__(self, task_repo: TaskRepository) -> None:
        self._task_repo = task_repo

    async def get_task_status(self, task_id: str) -> TaskLog | None:
        """
        Get the current status of a task.

        Args:
            task_id: Task ID

        Returns:
            TaskLog if found, None otherwise
        """
        return await self._task_repo.find_by_id(task_id)

    async def list_tasks(
        self, group_id: str, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[TaskLog]:
        """
        List tasks with optional filtering.

        Args:
            group_id: Group ID (usually project_id)
            status: Optional status filter (PENDING, PROCESSING, COMPLETED, FAILED)
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of task logs
        """
        tasks = await self._task_repo.find_by_group(
            group_id, limit=limit, offset=offset
        )
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    async def list_user_tasks(
        self, user_id: str, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[TaskLog]:
        """
        List tasks for a specific user.

        Args:
            user_id: User ID
            status: Optional status filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of task logs
        """
        return cast(list[TaskLog], await self._task_repo.find_by_user(
            user_id, status=status, limit=limit, offset=offset
        ))

    async def retry_task(self, task_id: str) -> bool:
        """
        Retry a failed task.

        Note: With Temporal, retries are typically handled by Temporal's
        built-in retry policies. This method updates the task status
        in the database. For actual re-execution, use Temporal's workflow
        restart capabilities.

        Args:
            task_id: Task ID to retry

        Returns:
            True if task status was updated

        Raises:
            ValueError: If task doesn't exist or is not in FAILED status
        """
        task = await self._task_repo.find_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if task.status != TaskLogStatus.FAILED:
            raise ValueError(f"Task {task_id} is not in FAILED status (current: {task.status})")

        # Check retry count to prevent infinite retries
        if task.retry_count >= 3:
            raise ValueError(f"Task {task_id} has exceeded maximum retry count")

        # Update task for retry - the actual re-execution should be
        # triggered by starting a new Temporal workflow
        task.status = TaskLogStatus.PENDING
        task.retry_count += 1
        task.error_message = None
        await self._task_repo.save(task)

        logger.info(f"Marked task {task_id} for retry (attempt {task.retry_count})")
        return True

    async def stop_task(self, task_id: str) -> bool:
        """
        Stop a running or pending task.

        Note: With Temporal, stopping a workflow should be done through
        Temporal's cancel/terminate APIs. This method only updates
        the database status.

        Args:
            task_id: Task ID to stop

        Returns:
            True if task was stopped successfully

        Raises:
            ValueError: If task doesn't exist or is already completed
        """
        task = await self._task_repo.find_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if task.status in (TaskLogStatus.COMPLETED, TaskLogStatus.FAILED):
            raise ValueError(f"Cannot stop task in {task.status} status")

        # Update task status
        task.status = TaskLogStatus.STOPPED
        task.stopped_at = datetime.now(UTC)
        await self._task_repo.save(task)

        logger.info(f"Stopped task {task_id}")
        return True

    async def delete_task(self, task_id: str) -> None:
        """
        Delete a task log.

        Args:
            task_id: Task ID to delete

        Raises:
            ValueError: If task is currently processing
        """
        task = await self._task_repo.find_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if task.status == TaskLogStatus.PROCESSING:
            raise ValueError("Cannot delete task in PROCESSING status")

        await self._task_repo.delete(task_id)
        logger.info(f"Deleted task {task_id}")

    async def get_task_progress(self, task_id: str) -> dict[str, Any]:
        """
        Get task progress information.

        Args:
            task_id: Task ID

        Returns:
            Dictionary with progress information including:
            - status: Current status
            - created_at: When task was created
            - started_at: When task started processing
            - completed_at: When task completed
            - error_message: Error message if failed
            - retry_count: Number of retry attempts

        Raises:
            ValueError: If task doesn't exist
        """
        task = await self._task_repo.find_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Use progress field if available, otherwise estimate from status
        progress_pct = getattr(task, "progress", 0)
        if task.status == TaskLogStatus.COMPLETED:
            progress_pct = 100
        elif task.status == TaskLogStatus.FAILED:
            progress_pct = 0

        return {
            "task_id": task.id,
            "status": task.status,
            "task_type": task.task_type,
            "progress_pct": progress_pct,
            "message": getattr(task, "message", None),
            "result": getattr(task, "result", None),
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "stopped_at": task.stopped_at.isoformat() if task.stopped_at else None,
            "error_message": task.error_message,
            "retry_count": task.retry_count,
            "worker_id": task.worker_id,
        }
