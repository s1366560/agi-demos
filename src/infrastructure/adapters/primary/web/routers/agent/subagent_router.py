"""SubAgent execution control endpoints.

Provides endpoints for managing running SubAgent executions,
such as cancellation of background SubAgents.

Architecture:
    Frontend -> POST /subagent/{execution_id}/cancel
                    -> Redis key signal -> BackgroundExecutor orphan sweep picks it up
                    -> OR immediate cancel if actor is reachable via Ray
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.agent_subagent_control_http_application_authority_v2 import (
    AgentSubAgentControlHttpApplicationAuthorityV2,
    agent_subagent_control_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    AgentSubAgentControlUnavailableV2,
)

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
    subagent_control: AgentSubAgentControlHttpApplicationAuthorityV2 = Depends(
        agent_subagent_control_http_application_authority_dependency_v2
    ),
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
        subagent_control: Generation-pinned SubAgent control authority.

    Returns:
        CancelSubAgentResponse with cancellation status.
    """
    try:
        reason = body.reason if body else None
        conversation_id = body.conversation_id if body else None
        await subagent_control.service.request_cancel(
            execution_id=execution_id,
            requested_by=str(current_user.id),
            reason=reason,
            conversation_id=conversation_id,
        )

        logger.info(
            "[SubAgentRouter] Cancel signal set for execution %s by user %s",
            execution_id,
            current_user.id,
        )

        return CancelSubAgentResponse(
            execution_id=execution_id,
            cancelled=True,
            message="Cancel signal sent. The SubAgent will be terminated shortly.",
        )

    except AgentSubAgentControlUnavailableV2 as exc:
        raise HTTPException(
            status_code=503,
            detail=_("Redis is not available. Cannot signal cancellation."),
        ) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error cancelling SubAgent execution")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to cancel SubAgent execution"),
        ) from e
