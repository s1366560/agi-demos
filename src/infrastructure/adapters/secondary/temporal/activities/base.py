"""Base utilities for Temporal Activities.

This module provides utility functions for Temporal Activities,
including progress tracking and status updates.
"""

import logging
from typing import Any, Optional

from temporalio import activity

logger = logging.getLogger(__name__)


async def update_task_progress(
    task_id: Optional[str],
    progress: int,
    message: Optional[str] = None,
    status: str = "PROCESSING",
    error_message: Optional[str] = None,
    result: Optional[dict] = None,
) -> None:
    """Update both Temporal heartbeat and database TaskLog.

    This is a standalone utility function for Activities to report progress.

    Args:
        task_id: TaskLog ID for database update (can be None)
        progress: Progress percentage (0-100)
        message: Optional status message
        status: Task status (PROCESSING, COMPLETED, FAILED)
        error_message: Optional error message for failed tasks
        result: Optional result dict for completed tasks
    """
    from sqlalchemy import update

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    # Send Temporal heartbeat
    activity.heartbeat({"progress": progress, "message": message, "status": status})

    # Update database record if task_id is provided
    if task_id:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = update(TaskLog).where(TaskLog.id == task_id).values(status=status)
                if progress is not None:
                    stmt = stmt.values(progress=progress)
                if message is not None:
                    stmt = stmt.values(message=message)
                if error_message is not None:
                    stmt = stmt.values(error_message=error_message)
                if result is not None:
                    stmt = stmt.values(result=result)
                await session.execute(stmt)


async def update_memory_status(memory_id: Optional[str], status: Any) -> None:
    """Update memory processing status in database.

    Args:
        memory_id: Memory ID for database update (can be None)
        status: ProcessingStatus enum or string value
    """
    from sqlalchemy import update

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import Memory

    if memory_id:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    update(Memory)
                    .where(Memory.id == memory_id)
                    .values(processing_status=status.value if hasattr(status, "value") else status)
                )
                await session.execute(stmt)


async def mark_task_completed(
    task_id: Optional[str],
    message: str = "Completed",
    result: Optional[dict] = None,
) -> None:
    """Mark task as completed in both Temporal and database.

    Args:
        task_id: TaskLog ID for database update
        message: Completion message
        result: Optional result dict
    """
    from datetime import datetime, timezone

    from sqlalchemy import update

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    activity.heartbeat({"progress": 100, "status": "completed", "message": message})

    if task_id:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    update(TaskLog)
                    .where(TaskLog.id == task_id)
                    .values(
                        status="COMPLETED",
                        progress=100,
                        message=message,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                if result is not None:
                    stmt = stmt.values(result=result)
                await session.execute(stmt)


async def mark_task_failed(
    task_id: Optional[str],
    error_message: str,
) -> None:
    """Mark task as failed in both Temporal and database.

    Args:
        task_id: TaskLog ID for database update
        error_message: Error message describing the failure
    """
    from datetime import datetime, timezone

    from sqlalchemy import update

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    activity.heartbeat({"status": "failed", "error": error_message})

    if task_id:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    update(TaskLog)
                    .where(TaskLog.id == task_id)
                    .values(
                        status="FAILED",
                        error_message=error_message,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await session.execute(stmt)
