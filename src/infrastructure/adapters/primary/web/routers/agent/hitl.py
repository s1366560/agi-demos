"""Human-in-the-loop (HITL) endpoints for Agent API.

Provides endpoints for human intervention during agent execution:
- get_pending_hitl_requests: Get pending requests for a conversation
- get_project_pending_hitl_requests: Get pending requests for a project
- respond_to_hitl: Unified endpoint to respond to any HITL request

Architecture (Dual-Channel for low-latency + reliability):
    Frontend → POST /hitl/respond
                    ├─ Redis Stream (primary, ~30ms) → Agent Worker → Session
                    └─ Temporal Signal (backup, ~500ms) → Workflow → Activity
"""

import asyncio
import json
import logging
from datetime import datetime
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
        raise HTTPException(status_code=500, detail=f"Failed to get pending HITL requests: {e!s}")


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
        raise HTTPException(status_code=500, detail=f"Failed to get pending HITL requests: {e!s}")


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

        # Get project_id and conversation_id for channel routing
        project_id = hitl_request.project_id
        conversation_id = hitl_request.conversation_id

        # Dual-Channel Architecture:
        # 1. Redis Stream (primary, low-latency ~30ms) - direct delivery to Agent Worker
        # 2. Temporal Signal (backup, reliable ~500ms) - fallback through Workflow

        # Channel 1: Publish to Redis Stream (primary channel)
        # This allows Agent Worker to receive response directly in-memory
        redis_sent = await _publish_hitl_response_to_redis(
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            request_id=request.request_id,
            hitl_type=request.hitl_type,
            response_data=request.response_data,
            user_id=str(current_user.id),
        )
        if redis_sent:
            logger.info(
                f"HITL response published to Redis Stream (fast path): {request.request_id}"
            )

        # Channel 2: Send Temporal Signal (backup channel) - fire-and-forget
        # Use create_task so we don't block on slower Temporal signal
        asyncio.create_task(
            _send_hitl_signal_to_workflow_async(
                tenant_id=tenant_id,
                project_id=project_id,
                request_id=request.request_id,
                hitl_type=request.hitl_type,
                response_data=request.response_data,
                user_id=str(current_user.id),
            )
        )

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
            f"(type={request.hitl_type}) via dual-channel (Redis={redis_sent})"
        )

        return HumanInteractionResponse(
            success=True,
            message=f"{request.hitl_type.capitalize()} response received",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error responding to HITL request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to respond to HITL request: {e!s}",
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

        logger.info(f"User {current_user.id} cancelled HITL {request.request_id}: {request.reason}")

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
            detail=f"Failed to cancel HITL request: {e!s}",
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
        from src.domain.model.agent.hitl_types import HITL_RESPONSE_SIGNAL
        from src.infrastructure.adapters.secondary.temporal.client import (
            TemporalClientFactory,
        )
        from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
            get_project_agent_workflow_id,
        )

        # Get Temporal client (reuse singleton for lower latency)
        client = await TemporalClientFactory.get_client()

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
        from src.infrastructure.adapters.secondary.temporal.client import (
            TemporalClientFactory,
        )
        from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
            get_project_agent_workflow_id,
        )

        # Get Temporal client (reuse singleton for lower latency)
        client = await TemporalClientFactory.get_client()

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


async def _publish_hitl_response_to_redis(
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    request_id: str,
    hitl_type: str,
    response_data: dict,
    user_id: str,
) -> bool:
    """
    Publish HITL response to Redis Stream for fast delivery.

    This is the primary (fast) channel that allows Agent Workers
    to receive responses directly without going through Temporal.

    Stream key: hitl:response:{tenant_id}:{project_id}

    Returns:
        True if published successfully, False otherwise
    """
    try:
        from src.configuration.config import get_settings
        from src.infrastructure.cache.redis_client import get_redis_pool

        settings = get_settings()

        # Check if real-time HITL is enabled
        if not getattr(settings, "hitl_realtime_enabled", True):
            logger.debug("HITL real-time disabled, skipping Redis Stream publish")
            return False

        redis = await get_redis_pool()

        stream_key = f"hitl:response:{tenant_id}:{project_id}"
        message_data = {
            "request_id": request_id,
            "hitl_type": hitl_type,
            "response_data": json.dumps(response_data),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Add to stream with maxlen to prevent unbounded growth
        await redis.xadd(
            stream_key,
            {"data": json.dumps(message_data)},
            maxlen=1000,  # Keep last 1000 messages
        )

        logger.debug(f"[HITL Redis] Published response to {stream_key}: request_id={request_id}")
        return True

    except Exception as e:
        logger.warning(
            f"Failed to publish HITL response to Redis Stream: {e}. "
            f"Temporal Signal backup will be used."
        )
        return False


async def _send_hitl_signal_to_workflow_async(
    tenant_id: str,
    project_id: str,
    request_id: str,
    hitl_type: str,
    response_data: dict,
    user_id: str,
) -> None:
    """
    Async wrapper for sending HITL signal to workflow (fire-and-forget).

    This is used as the backup channel. Errors are logged but not propagated
    since the Redis Stream is the primary delivery mechanism.
    """
    try:
        success = await _send_hitl_signal_to_workflow(
            tenant_id=tenant_id,
            project_id=project_id,
            request_id=request_id,
            hitl_type=hitl_type,
            response_data=response_data,
            user_id=user_id,
        )
        if success:
            logger.debug(f"[HITL Temporal] Backup signal sent for {request_id}")
    except Exception as e:
        logger.warning(f"[HITL Temporal] Backup signal failed for {request_id}: {e}")
