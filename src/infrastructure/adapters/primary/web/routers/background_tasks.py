"""
Background task API routes.

This router provides endpoints for managing long-running background tasks.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.background_tasks import task_manager
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _is_superuser(current_user: User) -> bool:
    return bool(getattr(current_user, "is_superuser", False))


async def _accessible_project_ids(
    db: AsyncSession,
    current_user: User,
) -> set[str] | None:
    if _is_superuser(current_user):
        return None

    result = await db.execute(
        refresh_select_statement(
            select(UserProject.project_id).where(UserProject.user_id == current_user.id)
        )
    )
    return set(result.scalars().all())


def _is_task_accessible(
    task: Any,
    current_user: User,
    project_ids: set[str] | None,
) -> bool:
    if project_ids is None:
        return True

    owner_user_id = getattr(task, "owner_user_id", None)
    if isinstance(owner_user_id, str) and owner_user_id == str(current_user.id):
        return True

    project_id = getattr(task, "project_id", None)
    return isinstance(project_id, str) and project_id in project_ids


async def _ensure_task_access(
    task: Any,
    current_user: User,
    db: AsyncSession,
) -> None:
    if not _is_task_accessible(task, current_user, await _accessible_project_ids(db, current_user)):
        raise HTTPException(status_code=403, detail=_("Access denied to task"))


@router.get("/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Get the status of a background task.

    Args:
        task_id: Task UUID

    Returns:
        Task status and progress information
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_("Task not found"))

    await _ensure_task_access(task, current_user, db)

    return task.to_dict()


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Cancel a running background task.

    Args:
        task_id: Task UUID

    Returns:
        Confirmation of cancellation
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_("Task not found"))

    await _ensure_task_access(task, current_user, db)
    await task.cancel()

    return {"status": "success", "message": f"Task {task_id} cancelled", "task_id": task_id}


@router.get("/")
async def list_tasks(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List all background tasks.

    Args:
        status: Optional status filter (pending, running, completed, failed, cancelled)
        limit: Maximum tasks to return

    Returns:
        List of tasks
    """
    project_ids = await _accessible_project_ids(db, current_user)
    tasks = [
        task
        for task in task_manager.tasks.values()
        if _is_task_accessible(task, current_user, project_ids)
    ]

    # Filter by status if provided
    if status:
        tasks = [t for t in tasks if t.status.value == status]

    # Sort by created_at descending
    tasks.sort(key=lambda t: t.created_at, reverse=True)

    total = len(tasks)
    tasks = tasks[:limit]

    return {"tasks": [task.to_dict() for task in tasks], "total": total}
