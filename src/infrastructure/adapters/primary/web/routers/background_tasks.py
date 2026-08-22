"""Background task API endpoints backed exclusively by a pinned V2 generation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from src.infrastructure.adapters.primary.web.background_task_application_authority_v2 import (
    BackgroundTaskApplicationAuthorityV2,
    background_task_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/")
async def list_tasks(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    background_task_application: BackgroundTaskApplicationAuthorityV2 = Depends(
        background_task_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """List identity-visible in-memory workflow tasks from the pinned generation."""
    page = await background_task_application.services.list_tasks(
        user_id=str(current_user.id),
        is_superuser=bool(getattr(current_user, "is_superuser", False)),
        status=status,
        limit=limit,
    )
    return {"tasks": [dict(task) for task in page.tasks], "total": page.total}
