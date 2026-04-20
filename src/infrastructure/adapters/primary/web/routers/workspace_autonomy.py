"""Workspace autonomy manual control endpoints.

Exposes an explicit trigger so operators (or the blackboard UI) can request
that the workspace leader picks up the next autonomy step, bypassing the
implicit ``GET /goal-candidates`` polling path.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap import (
    maybe_auto_trigger_existing_root_execution,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/autonomy",
    tags=["workspace-autonomy"],
)
logger = logging.getLogger(__name__)


class AutonomyTickRequest(BaseModel):
    force: bool = Field(
        default=False,
        description="Bypass the per-root cooldown window and trigger immediately.",
    )


class AutonomyTickResponse(BaseModel):
    triggered: bool
    root_task_id: str | None = None
    reason: str


@router.post(
    "/tick",
    response_model=AutonomyTickResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_workspace_autonomy_tick(
    workspace_id: str,
    request: Request,
    payload: AutonomyTickRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AutonomyTickResponse:
    """Ask the leader to advance the next workspace autonomy step.

    The endpoint is idempotent within a 60 second cooldown per root task.
    Pass ``force=true`` to bypass the cooldown (e.g. after the user clicks
    the "Run Autonomy" button a second time intentionally).
    """
    force = bool(payload.force) if payload is not None else False
    try:
        outcome: dict[str, Any] = await maybe_auto_trigger_existing_root_execution(
            request=request,
            db=db,
            workspace_id=workspace_id,
            current_user=current_user,
            force=force,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        logger.exception(
            "Workspace autonomy tick failed",
            extra={"workspace_id": workspace_id, "user_id": current_user.id},
        )
        raise

    if outcome.get("reason") == "workspace_not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        )

    return AutonomyTickResponse(
        triggered=bool(outcome.get("triggered", False)),
        root_task_id=outcome.get("root_task_id"),
        reason=str(outcome.get("reason", "")),
    )
