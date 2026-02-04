"""Human-in-the-loop (HITL) endpoints for Agent API.

Provides endpoints for human intervention during agent execution:
- get_pending_hitl_requests: Get pending requests for a conversation
- get_project_pending_hitl_requests: Get pending requests for a project
- respond_to_hitl: Unified endpoint to respond to any HITL request (Temporal Signal)

Architecture:
    Frontend → POST /hitl/respond → Temporal Signal → Workflow → Agent
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)

from .schemas import (
    HITLCancelRequest,
    HITLRequestResponse,
    HITLResponseRequest,
    HumanInteractionResponse,
    PendingHITLResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/conversations/{conversation_id}/pending",
    response_model=PendingHITLResponse,
)
async def get_pending_hitl_requests(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> PendingHITLResponse:
    """
    Get all pending HITL requests for a conversation.

    This endpoint allows the frontend to query for pending HITL requests
    after a page refresh, enabling recovery of the conversation state.
    """
    try:
        conv_repo = SqlConversationRepository(db)
        conversation = await conv_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

        # Verify user has access (same tenant)
        if conversation.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied to this conversation")

        # Query pending requests
        repo = SqlHITLRequestRepository(db)
        pending = await repo.get_pending_by_conversation(
            conversation_id=conversation_id,
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            exclude_expired=False,  # Show all pending, let user decide
        )

        requests = [
            HITLRequestResponse(
                id=r.id,
                request_type=r.request_type.value,
                conversation_id=r.conversation_id,
                message_id=r.message_id,
                question=r.question,
                options=r.options,
                context=r.context,
                metadata=r.metadata,
                status=r.status.value,
                created_at=r.created_at.isoformat() if r.created_at else "",
                expires_at=r.expires_at.isoformat() if r.expires_at else "",
            )
            for r in pending
        ]

        return PendingHITLResponse(
            requests=requests,
            total=len(requests),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pending HITL requests: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get pending HITL requests: {str(e)}"
        )


@router.get("/projects/{project_id}/pending", response_model=PendingHITLResponse)
async def get_project_pending_hitl_requests(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> PendingHITLResponse:
    """
    Get all pending HITL requests for a project.

    This endpoint allows querying all pending HITL requests across all
    conversations in a project.
    """
    try:
        repo = SqlHITLRequestRepository(db)
        pending = await repo.get_pending_by_project(
            tenant_id=current_user.tenant_id,
            project_id=project_id,
            limit=limit,
        )

        requests = [
            HITLRequestResponse(
                id=r.id,
                request_type=r.request_type.value,
                conversation_id=r.conversation_id,
                message_id=r.message_id,
                question=r.question,
                options=r.options,
                context=r.context,
                metadata=r.metadata,
                status=r.status.value,
                created_at=r.created_at.isoformat() if r.created_at else "",
                expires_at=r.expires_at.isoformat() if r.expires_at else "",
            )
            for r in pending
        ]

        return PendingHITLResponse(
            requests=requests,
            total=len(requests),
        )

    except Exception as e:
        logger.error(f"Error getting project pending HITL requests: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get pending HITL requests: {str(e)}"
        )


# =============================================================================
# Unified HITL Response Endpoint (Temporal-based)
# =============================================================================


@router.post("/respond", response_model=HumanInteractionResponse)
async def respond_to_hitl(
    request: HITLResponseRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> HumanInteractionResponse:
    """
    Unified endpoint to respond to any HITL request.

    This endpoint sends a Temporal Signal to the running workflow,
    replacing the legacy manager-based approach.

    Request body:
    - request_id: The HITL request ID
    - hitl_type: Type of request ("clarification", "decision", "env_var", "permission")
    - response_data: Type-specific response data
        - clarification: {"answer": "user answer"}
        - decision: {"decision": "option_id"}
        - env_var: {"values": {"VAR_NAME": "value"}, "save": true}
        - permission: {"action": "allow", "remember": false}
    """

    logger.info(
        f"HITL respond request: request_id={request.request_id}, "
        f"hitl_type={request.hitl_type}, response_data={request.response_data}"
    )

    try:
        # Validate HITL type
        valid_types = ["clarification", "decision", "env_var", "permission"]
        if request.hitl_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid hitl_type '{request.hitl_type}'. Must be one of: {valid_types}",
            )

        # Get the HITL request from database to find the conversation
        repo = SqlHITLRequestRepository(db)
        hitl_request = await repo.get_by_id(request.request_id)

        if not hitl_request:
            logger.warning(f"HITL request not found in database: {request.request_id}")
            raise HTTPException(
                status_code=404,
                detail=f"HITL request {request.request_id} not found",
            )

        logger.info(
            f"Found HITL request: id={hitl_request.id}, tenant={hitl_request.tenant_id}, "
            f"project={hitl_request.project_id}, status={hitl_request.status}"
        )

        # Verify tenant access
        if hitl_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this HITL request",
            )

        # Check if already answered
        from src.domain.model.agent.hitl_request import HITLRequestStatus

        if hitl_request.status != HITLRequestStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"HITL request {request.request_id} is no longer pending (status: {hitl_request.status.value})",
            )

        # Get project_id for workflow lookup
        project_id = hitl_request.project_id

        # Try to send Temporal Signal
        signal_sent = await _send_hitl_signal_to_workflow(
            tenant_id=tenant_id,
            project_id=project_id,
            request_id=request.request_id,
            hitl_type=request.hitl_type,
            response_data=request.response_data,
            user_id=str(current_user.id),
        )

        if signal_sent:
            # Update database record
            response_str = (
                request.response_data.get("answer")
                or request.response_data.get("decision")
                or str(request.response_data.get("values", {}))
                or request.response_data.get("action")
            )
            await repo.update_response(request.request_id, response_str)
            await repo.mark_completed(request.request_id)
            await db.commit()

            logger.info(
                f"User {current_user.id} responded to HITL {request.request_id} "
                f"(type={request.hitl_type}) via Temporal Signal"
            )

            return HumanInteractionResponse(
                success=True,
                message=f"{request.hitl_type.capitalize()} response received",
            )
        else:
            # Workflow not found - no fallback
            logger.warning(
                f"Failed to send HITL signal for request {request.request_id}. "
                f"Workflow may have terminated. tenant={tenant_id}, project={project_id}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"Workflow not found for HITL request {request.request_id}. "
                "The agent workflow may have terminated or timed out.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error responding to HITL request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to respond to HITL request: {str(e)}",
        )


@router.post("/cancel", response_model=HumanInteractionResponse)
async def cancel_hitl_request(
    request: HITLCancelRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> HumanInteractionResponse:
    """
    Cancel a pending HITL request.

    This sends a cancellation signal to the workflow.
    """
    try:
        repo = SqlHITLRequestRepository(db)
        hitl_request = await repo.get_by_id(request.request_id)

        if not hitl_request:
            raise HTTPException(
                status_code=404,
                detail=f"HITL request {request.request_id} not found",
            )

        if hitl_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied to this HITL request",
            )

        # Send cancel signal to workflow
        await _send_hitl_cancel_signal_to_workflow(
            tenant_id=tenant_id,
            project_id=hitl_request.project_id,
            request_id=request.request_id,
            reason=request.reason,
        )

        # Update database
        await repo.mark_cancelled(request.request_id, request.reason)
        await db.commit()

        logger.info(
            f"User {current_user.id} cancelled HITL {request.request_id}: {request.reason}"
        )

        return HumanInteractionResponse(
            success=True,
            message="HITL request cancelled",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling HITL request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel HITL request: {str(e)}",
        )


async def _send_hitl_signal_to_workflow(
    tenant_id: str,
    project_id: str,
    request_id: str,
    hitl_type: str,
    response_data: dict,
    user_id: str,
) -> bool:
    """Send HITL response signal to the Temporal workflow."""
    from datetime import datetime

    try:
        from temporalio.client import Client

        from src.configuration.temporal_config import get_temporal_settings
        from src.domain.model.agent.hitl_types import HITL_RESPONSE_SIGNAL
        from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
            get_project_agent_workflow_id,
        )

        temporal_settings = get_temporal_settings()

        # Get Temporal client
        client = await Client.connect(
            temporal_settings.temporal_host,
            namespace=temporal_settings.temporal_namespace,
        )

        # Get workflow ID
        workflow_id = get_project_agent_workflow_id(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        logger.info(f"Attempting to send HITL signal to workflow: {workflow_id}")

        # Build signal payload
        signal_payload = {
            "request_id": request_id,
            "hitl_type": hitl_type,
            "response_data": response_data,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Get workflow handle and send signal
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(HITL_RESPONSE_SIGNAL, signal_payload)

        logger.info(f"Sent HITL signal to workflow {workflow_id}: {request_id}")
        return True

    except Exception as e:
        logger.warning(
            f"Failed to send HITL signal to workflow: {e}. "
            f"tenant={tenant_id}, project={project_id}, request={request_id}"
        )
        return False


async def _send_hitl_cancel_signal_to_workflow(
    tenant_id: str,
    project_id: str,
    request_id: str,
    reason: Optional[str],
) -> bool:
    """Send HITL cancellation signal to the Temporal workflow."""
    try:
        from temporalio.client import Client

        from src.configuration.temporal_config import get_temporal_settings
        from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
            get_project_agent_workflow_id,
        )

        temporal_settings = get_temporal_settings()

        client = await Client.connect(
            temporal_settings.temporal_host,
            namespace=temporal_settings.temporal_namespace,
        )

        workflow_id = get_project_agent_workflow_id(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("cancel_hitl_request", request_id, reason)

        logger.info(f"Sent HITL cancel signal to workflow {workflow_id}: {request_id}")
        return True

    except Exception as e:
        logger.warning(f"Failed to send HITL cancel signal: {e}")
        return False
