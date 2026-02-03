"""Human-in-the-loop (HITL) endpoints for Agent API.

Provides endpoints for human intervention during agent execution:
- get_pending_hitl_requests: Get pending requests for a conversation
- get_project_pending_hitl_requests: Get pending requests for a project
- respond_to_clarification: Respond to clarification request
- respond_to_decision: Respond to decision request
- respond_to_env_var_request: Respond to environment variable request
- respond_to_doom_loop: Respond to doom loop intervention
"""

import logging

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
    ClarificationResponseRequest,
    DecisionResponseRequest,
    DoomLoopResponseRequest,
    EnvVarResponseRequest,
    HITLRequestResponse,
    HumanInteractionResponse,
    PendingHITLResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/conversations/{conversation_id}/hitl/pending",
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


@router.get("/projects/{project_id}/hitl/pending", response_model=PendingHITLResponse)
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


@router.post("/clarification/respond", response_model=HumanInteractionResponse)
async def respond_to_clarification(
    request: ClarificationResponseRequest,
    current_user: User = Depends(get_current_user),
) -> HumanInteractionResponse:
    """
    Respond to a pending clarification request.

    This endpoint allows users to provide answers to clarification questions
    asked by the agent during the planning phase.
    """
    try:
        from src.infrastructure.agent.tools.clarification import get_clarification_manager

        manager = get_clarification_manager()
        success = await manager.respond(request.request_id, request.answer)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Clarification request {request.request_id} not found or already answered",
            )

        logger.info(f"User {current_user.id} responded to clarification {request.request_id}")

        return HumanInteractionResponse(
            success=True,
            request_id=request.request_id,
            message="Clarification response received",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error responding to clarification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to respond to clarification: {str(e)}")


@router.post("/decision/respond", response_model=HumanInteractionResponse)
async def respond_to_decision(
    request: DecisionResponseRequest,
    current_user: User = Depends(get_current_user),
) -> HumanInteractionResponse:
    """
    Respond to a pending decision request.

    This endpoint allows users to provide decisions at critical execution points
    when the agent requires user confirmation or choice between options.
    """
    try:
        from src.infrastructure.agent.tools.decision import get_decision_manager

        manager = get_decision_manager()
        success = await manager.respond(request.request_id, request.decision)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Decision request {request.request_id} not found or already answered",
            )

        logger.info(f"User {current_user.id} responded to decision {request.request_id}")

        return HumanInteractionResponse(
            success=True,
            request_id=request.request_id,
            message="Decision response received",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error responding to decision: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to respond to decision: {str(e)}")


@router.post("/env-var/respond", response_model=HumanInteractionResponse)
async def respond_to_env_var_request(
    request: EnvVarResponseRequest,
    current_user: User = Depends(get_current_user),
) -> HumanInteractionResponse:
    """
    Respond to a pending environment variable request.

    This endpoint allows users to provide environment variable values
    requested by the agent for tool configuration.
    """
    try:
        from src.infrastructure.agent.tools.env_var_tools import get_env_var_manager

        manager = get_env_var_manager()
        success = await manager.respond(request.request_id, request.values)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Environment variable request {request.request_id} not found or already answered",
            )

        logger.info(
            f"User {current_user.id} provided env vars for request {request.request_id}: "
            f"{list(request.values.keys())}"
        )

        return HumanInteractionResponse(
            success=True,
            request_id=request.request_id,
            message="Environment variables received and saved",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error responding to env var request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to respond to env var request: {str(e)}"
        )


@router.post("/doom-loop/respond", response_model=HumanInteractionResponse)
async def respond_to_doom_loop(
    request: DoomLoopResponseRequest,
    current_user: User = Depends(get_current_user),
) -> HumanInteractionResponse:
    """
    Respond to a pending doom loop intervention request.

    This endpoint allows users to intervene when the agent is detected
    to be in a repetitive loop, choosing to continue or stop execution.
    """
    try:
        if request.action not in ["continue", "stop"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action '{request.action}'. Must be 'continue' or 'stop'.",
            )

        from src.infrastructure.agent.permission import get_permission_manager

        # Doom loop interventions are handled through the permission system
        manager = get_permission_manager()

        # Check if request exists
        if request.request_id not in manager.pending:
            raise HTTPException(
                status_code=404,
                detail=f"Doom loop request {request.request_id} not found or already answered",
            )

        # Map action to permission response: continue -> once, stop -> reject
        permission_response = "once" if request.action == "continue" else "reject"

        await manager.reply(request.request_id, permission_response)

        logger.info(
            f"User {current_user.id} responded to doom loop {request.request_id}: {request.action}"
        )

        return HumanInteractionResponse(
            success=True,
            request_id=request.request_id,
            message=f"Doom loop intervention: {request.action}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error responding to doom loop: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to respond to doom loop: {str(e)}")
