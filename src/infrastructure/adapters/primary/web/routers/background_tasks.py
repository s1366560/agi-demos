"""
Background task API routes.

This router provides endpoints for managing long-running background tasks.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.background_tasks import task_manager
from src.infrastructure.adapters.secondary.persistence.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}")
async def get_task_status(task_id: str, current_user: User = Depends(get_current_user)) -> Any:
    """
    Get the status of a background task.

    Args:
        task_id: Task UUID

    Returns:
        Task status and progress information
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task.to_dict()


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """
    Cancel a running background task.

    Args:
        task_id: Task UUID

    Returns:
        Confirmation of cancellation
    """
    success = await task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"status": "success", "message": f"Task {task_id} cancelled", "task_id": task_id}


@router.get("/")
async def list_tasks(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List all background tasks.

    Args:
        status: Optional status filter (pending, running, completed, failed, cancelled)
        limit: Maximum tasks to return

    Returns:
        List of tasks
    """
    tasks = list(task_manager.tasks.values())

    # Filter by status if provided
    if status:
        tasks = [t for t in tasks if t.status.value == status]

    # Sort by created_at descending
    tasks.sort(key=lambda t: t.created_at, reverse=True)

    # Limit results
    tasks = tasks[:limit]

    return {"tasks": [task.to_dict() for task in tasks], "total": len(tasks)}
