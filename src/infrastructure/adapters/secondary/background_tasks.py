"""
Background task management system.

This module provides a simple in-memory task queue for tracking long-running operations
like community rebuilding. For production, consider using Redis or a database-backed queue.
"""

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackgroundTask:
    def __init__(self, task_id: str, task_type: str, func: Callable, *args, **kwargs):
        self.task_id = task_id
        self.task_type = task_type
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now(timezone.utc)
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.progress = 0
        self.message = "Task queued"
        self.result: Optional[Any] = None
        self.error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None

    async def run(self):
        """Execute the task and update status."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)
        self.message = "Task started"

        try:
            logger.info(f"Task {self.task_id} started")
            self.result = await self.func(*self.args, **self.kwargs)
            self.status = TaskStatus.COMPLETED
            self.completed_at = datetime.now(timezone.utc)
            self.message = "Task completed successfully"
            self.progress = 100
            logger.info(f"Task {self.task_id} completed successfully")
        except Exception as e:
            self.status = TaskStatus.FAILED
            self.completed_at = datetime.now(timezone.utc)
            self.error = str(e)
            self.message = f"Task failed: {str(e)}"
            logger.error(f"Task {self.task_id} failed: {e}")
            raise

    async def cancel(self):
        """Cancel the task if it's running."""
        if self._task and not self._task.done():
            self._task.cancel()
            self.status = TaskStatus.CANCELLED
            self.completed_at = datetime.now(timezone.utc)
            self.message = "Task cancelled"
            logger.info(f"Task {self.task_id} cancelled")

    def to_dict(self) -> Dict[str, Any]:
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

    def __init__(self):
        self.tasks: Dict[str, BackgroundTask] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    def start_cleanup(self):
        """Start background cleanup of completed tasks."""

        async def cleanup_old_tasks():
            while True:
                await asyncio.sleep(3600)  # Cleanup every hour
                now = datetime.now(timezone.utc)
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

    def create_task(self, task_type: str, func: Callable, *args, **kwargs) -> BackgroundTask:
        """Create a new background task."""
        task_id = str(uuid4())
        task = BackgroundTask(task_id, task_type, func, *args, **kwargs)
        self.tasks[task_id] = task
        return task

    async def submit_task(self, task_type: str, func: Callable, *args, **kwargs) -> str:
        """Submit a task for background execution."""
        task = self.create_task(task_type, func, *args, **kwargs)
        task._task = asyncio.create_task(task.run())
        return task.task_id

    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
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
