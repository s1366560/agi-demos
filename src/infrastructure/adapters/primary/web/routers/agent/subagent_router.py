"""SubAgent execution control endpoints.

Provides endpoints for managing running SubAgent executions,
such as cancellation of background SubAgents.

Architecture:
    Frontend -> POST /subagent/{execution_id}/cancel
                    -> authorize exact conversation/run -> persist cancellation intent
                    -> generation-owned Redis signal -> actual execution owner acknowledgement
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent_run import SubAgentRunStatus
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.agent_subagent_control_http_application_authority_v2 import (
    AgentSubAgentControlHttpApplicationAuthorityV2,
    agent_subagent_control_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.agent.subagent.async_run_registry_v2 import registry_call_v2
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    AgentSubAgentControlUnavailableV2,
)
from src.infrastructure.plugins.v2.subagent_run_registry_projection import (
    current_subagent_run_registry_v2,
)

from .trace_router import _get_accessible_conversation

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
    cancel_requested: bool = False
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
    subagent_control: AgentSubAgentControlHttpApplicationAuthorityV2 = Depends(
        agent_subagent_control_http_application_authority_dependency_v2
    ),
) -> CancelSubAgentResponse:
    """Request cancellation after access checks; terminal status requires owner acknowledgement."""
    try:
        reason = body.reason if body else None
        conversation_id = body.conversation_id if body else None
        if not conversation_id:
            raise HTTPException(status_code=400, detail=_("conversation_id is required"))
        await _get_accessible_conversation(db, current_user, conversation_id)
        registry = current_subagent_run_registry_v2()
        run = await registry_call_v2(registry, "get_run", conversation_id, execution_id)
        if run is None:
            raise HTTPException(status_code=404, detail=_("SubAgent run not found"))
        if run.status not in {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}:
            return CancelSubAgentResponse(
                execution_id=execution_id,
                cancelled=run.status is SubAgentRunStatus.CANCELLED,
                message=_("SubAgent run is already terminal"),
            )
        requested = await registry_call_v2(
            registry,
            "attach_metadata",
            conversation_id,
            execution_id,
            {"cancel_requested": True, "cancel_requested_by": str(current_user.id)},
            expected_statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
        )
        if requested is None:
            return CancelSubAgentResponse(
                execution_id=execution_id,
                cancelled=False,
                message=_("SubAgent state changed; refresh its status"),
            )
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
            cancelled=False,
            cancel_requested=True,
            message=_("Cancellation requested; awaiting execution owner acknowledgement."),
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
