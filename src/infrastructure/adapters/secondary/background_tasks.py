"""
Background task management system.

This module provides a simple in-memory task queue for tracking long-running operations
like community rebuilding. For production, consider using Redis or a database-backed queue.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackgroundTask:
    def __init__(
        self, task_id: str, task_type: str, func: Callable, *args: Any, **kwargs: Any
    ) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now(UTC)
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.progress = 0
        self.message = "Task queued"
        self.result: Any | None = None
        self.error: str | None = None
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        """Execute the task and update status."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now(UTC)
        self.message = "Task started"

        try:
            logger.info(f"Task {self.task_id} started")
            self.result = await self.func(*self.args, **self.kwargs)
            self.status = TaskStatus.COMPLETED
            self.completed_at = datetime.now(UTC)
            self.message = "Task completed successfully"
            self.progress = 100
            logger.info(f"Task {self.task_id} completed successfully")
        except Exception as e:
            self.status = TaskStatus.FAILED
            self.completed_at = datetime.now(UTC)
            self.error = str(e)
            self.message = f"Task failed: {e!s}"
            logger.error(f"Task {self.task_id} failed: {e}")
            raise

    async def cancel(self) -> None:
        """Cancel the task if it's running."""
        if self._task and not self._task.done():
            self._task.cancel()
            self.status = TaskStatus.CANCELLED
            self.completed_at = datetime.now(UTC)
            self.message = "Task cancelled"
            logger.info(f"Task {self.task_id} cancelled")

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
        }


class TaskManager:
    """Simple in-memory task manager."""

    def __init__(self) -> None:
        self.tasks: dict[str, BackgroundTask] = {}
        self._cleanup_task: asyncio.Task | None = None

    def start_cleanup(self) -> None:
        """Start background cleanup of completed tasks."""

        async def cleanup_old_tasks() -> None:
            while True:
                await asyncio.sleep(3600)  # Cleanup every hour
                now = datetime.now(UTC)
                to_remove = []
                for task_id, task in self.tasks.items():
                    # Remove tasks completed more than 24 hours ago
                    if (
                        task.status
                        in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
                        and task.completed_at
                        and (now - task.completed_at).total_seconds() > 86400
                    ):
                        to_remove.append(task_id)
                for task_id in to_remove:
                    del self.tasks[task_id]
                    logger.info(f"Cleaned up old task {task_id}")

        self._cleanup_task = asyncio.create_task(cleanup_old_tasks())

    def create_task(
        self, task_type: str, func: Callable, *args: Any, **kwargs: Any
    ) -> BackgroundTask:
        """Create a new background task."""
        task_id = str(uuid4())
        task = BackgroundTask(task_id, task_type, func, *args, **kwargs)
        self.tasks[task_id] = task
        return task

    async def submit_task(self, task_type: str, func: Callable, *args: Any, **kwargs: Any) -> str:
        """Submit a task for background execution."""
        task = self.create_task(task_type, func, *args, **kwargs)
        task._task = asyncio.create_task(task.run())
        return task.task_id

    def get_task(self, task_id: str) -> BackgroundTask | None:
        """Get task by ID."""
        return self.tasks.get(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        task = self.get_task(task_id)
        if task:
            await task.cancel()
            return True
        return False


# Global task manager instance
task_manager = TaskManager()
