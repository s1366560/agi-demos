"""SubAgent execution control endpoints.

Provides endpoints for managing running SubAgent executions,
such as cancellation of background SubAgents.

Architecture:
    Frontend -> POST /subagent/{execution_id}/cancel
                    -> Redis key signal -> BackgroundExecutor orphan sweep picks it up
                    -> OR immediate cancel if actor is reachable via Ray
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


class CancelSubAgentRequest(BaseModel):
    """Optional request body for cancel endpoint."""

    conversation_id: str | None = None
    reason: str | None = None


class CancelSubAgentResponse(BaseModel):
    """Response for cancel endpoint."""

    execution_id: str
    cancelled: bool
    message: str


@router.post(
    "/subagent/{execution_id}/cancel",
    response_model=CancelSubAgentResponse,
)
async def cancel_subagent_execution(
    execution_id: str,
    request: Request,
    body: CancelSubAgentRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CancelSubAgentResponse:
    """Cancel a running background SubAgent execution.

    Sets a Redis cancel signal that the BackgroundExecutor's orphan sweep
    will pick up. This is the cross-process safe approach since the
    BackgroundExecutor runs inside the Ray Actor process.

    Args:
        execution_id: The SubAgent execution ID to cancel.
        request: FastAPI request.
        body: Optional request body with conversation_id and reason.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        CancelSubAgentResponse with cancellation status.
    """
    try:
        container = get_container_with_db(request, db)
        redis_client = container.redis()

        if redis_client is None:
            raise HTTPException(
                status_code=503,
                detail="Redis is not available. Cannot signal cancellation.",
            )

        reason = body.reason if body else None
        conversation_id = body.conversation_id if body else None

        # Set a cancel signal in Redis that BackgroundExecutor will pick up
        cancel_key = f"subagent:cancel:{execution_id}"
        cancel_data: dict[str, Any] = {
            "requested_by": current_user.id,
            "reason": reason or "Cancelled by user",
        }
        if conversation_id:
            cancel_data["conversation_id"] = conversation_id

        cancel_data["timestamp"] = datetime.now(UTC).isoformat()

        # Set with TTL of 600 seconds (10 minutes) — enough for sweep to pick up
        await redis_client.set(
            cancel_key,
            json.dumps(cancel_data),
            ex=600,
        )

        logger.info(
            f"[SubAgentRouter] Cancel signal set for execution {execution_id} "
            f"by user {current_user.id}"
        )

        return CancelSubAgentResponse(
            execution_id=execution_id,
            cancelled=True,
            message="Cancel signal sent. The SubAgent will be terminated shortly.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling SubAgent execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel SubAgent execution: {e!s}",
        ) from e
