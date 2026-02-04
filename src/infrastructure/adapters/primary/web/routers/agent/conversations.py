"""Conversation management endpoints.

CRUD operations for Agent conversations.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.constants.error_ids import AGENT_CONVERSATION_CREATE_FAILED
from src.configuration.factories import create_llm_client
from src.domain.model.agent import ConversationStatus
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

from .schemas import (
    ConversationResponse,
    CreateConversationRequest,
    UpdateConversationTitleRequest,
)
from .utils import get_container_with_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ConversationResponse:
    """Create a new conversation."""
    try:
        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
        use_case = container.create_conversation_use_case(llm)
        conversation = await use_case.execute(
            project_id=data.project_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
            title=data.title,
            agent_config=data.agent_config,
        )
        await db.commit()
        return ConversationResponse.from_domain(conversation)

    except (ValueError, AttributeError) as e:
        await db.rollback()
        logger.error(
            f"Validation error creating conversation: {e}",
            exc_info=True,
            extra={"error_id": AGENT_CONVERSATION_CREATE_FAILED},
        )
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error creating conversation: {e}",
            exc_info=True,
            extra={"error_id": AGENT_CONVERSATION_CREATE_FAILED},
        )
        raise HTTPException(
            status_code=500,
            detail="A database error occurred while creating the conversation",
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Unexpected error creating conversation: {e}",
            exc_info=True,
            extra={"error_id": AGENT_CONVERSATION_CREATE_FAILED},
        )
        raise HTTPException(
            status_code=500,
            detail="An error occurred while creating the conversation",
        )


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    project_id: str = Query(..., description="Project ID to filter by"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number to return"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> list[ConversationResponse]:
    """List conversations for a project."""
    try:
        engine = db.get_bind()
        pool = engine.pool
        logger.debug(
            f"[Connection Pool] size={pool.size()}, checked_out={pool.checkedout()}, "
            f"overflow={pool.overflow()}, queue_size={pool.size() - pool.checkedout()}"
        )

        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
        use_case = container.list_conversations_use_case(llm)
        conv_status = ConversationStatus(status) if status else None

        conversations = await use_case.execute(
            project_id=project_id,
            user_id=current_user.id,
            limit=limit,
            status=conv_status,
        )
        return [ConversationResponse.from_domain(c) for c in conversations]

    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list conversations: {str(e)}")


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ConversationResponse:
    """Get a conversation by ID."""
    try:
        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
        use_case = container.get_conversation_use_case(llm)

        conversation = await use_case.execute(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get conversation: {str(e)}")


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> None:
    """Delete a conversation and all its messages."""
    try:
        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        await agent_service.delete_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {str(e)}")


@router.patch("/conversations/{conversation_id}/title", response_model=ConversationResponse)
async def update_conversation_title(
    conversation_id: str,
    data: UpdateConversationTitleRequest,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ConversationResponse:
    """Update conversation title."""
    try:
        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        updated_conversation = await agent_service.update_conversation_title(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            title=data.title,
        )

        return ConversationResponse(
            id=updated_conversation.id,
            project_id=updated_conversation.project_id,
            user_id=updated_conversation.user_id,
            tenant_id=updated_conversation.tenant_id,
            title=updated_conversation.title,
            status=updated_conversation.status.value,
            message_count=updated_conversation.message_count,
            created_at=updated_conversation.created_at.isoformat(),
            updated_at=updated_conversation.updated_at.isoformat()
            if updated_conversation.updated_at
            else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating conversation title: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update conversation title: {str(e)}"
        )


@router.post(
    "/conversations/{conversation_id}/generate-title",
    response_model=ConversationResponse,
    deprecated=True,
)
async def generate_conversation_title(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ConversationResponse:
    """
    Generate and update a friendly conversation title based on the first user message.

    .. deprecated::
        Title generation is now handled automatically by the backend.
    """
    try:
        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        message_events = await agent_service.get_conversation_messages(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=10,
        )

        first_user_message = None
        for event in message_events:
            if event.event_type == "user_message":
                first_user_message = event.event_data.get("content", "")
                break

        if not first_user_message:
            raise HTTPException(
                status_code=400, detail="No user message found to generate title from"
            )

        generated_title = await agent_service.generate_conversation_title(
            first_message=first_user_message,
            llm=llm,
        )

        updated_conversation = await agent_service.update_conversation_title(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            title=generated_title,
        )

        if not updated_conversation:
            raise HTTPException(status_code=500, detail="Failed to update conversation title")

        return ConversationResponse(
            id=updated_conversation.id,
            project_id=updated_conversation.project_id,
            user_id=updated_conversation.user_id,
            tenant_id=updated_conversation.tenant_id,
            title=updated_conversation.title,
            status=updated_conversation.status.value,
            message_count=updated_conversation.message_count,
            created_at=updated_conversation.created_at.isoformat(),
            updated_at=updated_conversation.updated_at.isoformat()
            if updated_conversation.updated_at
            else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating conversation title: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate conversation title: {str(e)}"
        )
