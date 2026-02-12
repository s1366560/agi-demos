"""Plan Mode API endpoints.

Simple mode switch for Plan Mode (read-only analysis) vs Build Mode (full execution).
Inspired by Claude Code / OpenCode approach: Plan Mode is a permission/prompt mode
switch, not a workflow engine.
"""

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_db,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as ConversationModel,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])


# === Request/Response Schemas ===


class SwitchModeRequest(BaseModel):
    conversation_id: str
    mode: Literal["plan", "build"]


class ModeResponse(BaseModel):
    conversation_id: str
    mode: str
    switched_at: str


class ConversationModeResponse(BaseModel):
    conversation_id: str
    mode: str


# === Endpoints ===


@router.post("/mode")
async def switch_mode(
    request_body: SwitchModeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModeResponse:
    """Switch conversation between Plan Mode (read-only) and Build Mode (full)."""
    try:
        stmt = (
            update(ConversationModel)
            .where(ConversationModel.id == request_body.conversation_id)
            .where(ConversationModel.user_id == current_user.id)
            .values(
                current_mode=request_body.mode,
                current_plan_id=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        result = await db.execute(stmt)
        await db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Conversation not found")

        logger.info(
            f"Conversation {request_body.conversation_id} switched to "
            f"{request_body.mode} mode by user {current_user.id}"
        )

        return ModeResponse(
            conversation_id=request_body.conversation_id,
            mode=request_body.mode,
            switched_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error switching mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to switch mode: {e!s}")


@router.get("/mode/{conversation_id}")
async def get_mode(
    conversation_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationModeResponse:
    """Get the current mode for a conversation."""
    try:
        stmt = (
            select(ConversationModel.current_mode)
            .where(ConversationModel.id == conversation_id)
            .where(ConversationModel.user_id == current_user.id)
        )
        result = await db.execute(stmt)
        mode = result.scalar_one_or_none()

        if mode is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return ConversationModeResponse(
            conversation_id=conversation_id,
            mode=mode,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get mode: {e!s}")
