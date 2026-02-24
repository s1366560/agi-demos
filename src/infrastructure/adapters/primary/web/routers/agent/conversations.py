"""Conversation management endpoints.

CRUD operations for Agent conversations.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
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
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as ConversationModel,
    Message as MessageModel,
    ToolExecutionRecord,
    User,
)

from .schemas import (
    ConversationResponse,
    CreateConversationRequest,
    PaginatedConversationsResponse,
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
    request: Request | None = None,
) -> ConversationResponse:
    """Create a new conversation."""
    try:
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
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
        raise HTTPException(status_code=400, detail=f"Invalid request: {e!s}") from e
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
        ) from e
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
        ) from e


@router.get("/conversations", response_model=PaginatedConversationsResponse)
async def list_conversations(
    project_id: str = Query(..., description="Project ID to filter by"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> PaginatedConversationsResponse:
    """List conversations for a project with pagination."""
    try:
        engine = db.get_bind()
        pool = engine.pool
        logger.debug(
            f"[Connection Pool] size={pool.size()}, checked_out={pool.checkedout()}, "
            f"overflow={pool.overflow()}, queue_size={pool.size() - pool.checkedout()}"
        )

        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        use_case = container.list_conversations_use_case(llm)
        conv_status = ConversationStatus(status) if status else None

        conversations = await use_case.execute(
            project_id=project_id,
            user_id=current_user.id,
            limit=limit,
            offset=offset,
            status=conv_status,
        )

        total = await use_case.count(
            project_id=project_id,
            user_id=current_user.id,
            status=conv_status,
        )

        items = [ConversationResponse.from_domain(c) for c in conversations]
        has_more = offset + limit < total

        return PaginatedConversationsResponse(
            items=items,
            total=total,
            has_more=has_more,
            offset=offset,
            limit=limit,
        )

    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list conversations: {e!s}") from e


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> ConversationResponse:
    """Get a conversation by ID."""
    try:
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
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
        raise HTTPException(status_code=500, detail=f"Failed to get conversation: {e!s}") from e


@router.get("/conversations/{conversation_id}/context-status")
async def get_context_status(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> dict[str, Any]:
    """Get context window status for a conversation.

    Returns the cached context summary info (if any) and message count,
    so the frontend can restore the context status indicator after page
    refresh or conversation switch.
    """
    try:
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        use_case = container.get_conversation_use_case(llm)

        conversation = await use_case.execute(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Load cached context summary from conversation meta
        adapter = container.context_summary_adapter()
        summary = await adapter.get_summary(conversation_id)

        result: dict[str, Any] = {
            "conversation_id": conversation_id,
            "message_count": conversation.message_count,
            "has_summary": summary is not None,
        }

        if summary:
            result.update(
                {
                    "summary_tokens": summary.summary_tokens,
                    "messages_in_summary": summary.messages_covered_count,
                    "compression_level": summary.compression_level,
                    "from_cache": True,
                }
            )
        else:
            result.update(
                {
                    "summary_tokens": 0,
                    "messages_in_summary": 0,
                    "compression_level": "none",
                    "from_cache": False,
                }
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting context status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get context status: {e!s}") from e


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> None:
    """Delete a conversation and all its messages."""
    try:
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
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
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {e!s}") from e


@router.patch("/conversations/{conversation_id}/title", response_model=ConversationResponse)
async def update_conversation_title(
    conversation_id: str,
    data: UpdateConversationTitleRequest,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> ConversationResponse:
    """Update conversation title."""
    try:
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
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
            summary=updated_conversation.summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating conversation title: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update conversation title: {e!s}"
        ) from e


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
    request: Request | None = None,
) -> ConversationResponse:
    """
    Generate and update a friendly conversation title based on the first user message.

    .. deprecated::
        Title generation is now handled automatically by the backend.
    """
    try:
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
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

        # Use DB provider config (same as ReActAgent) for title generation
        title_llm = await agent_service._get_title_llm()
        generated_title = await agent_service.generate_conversation_title(
            first_message=first_user_message,
            llm=title_llm,
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
            summary=updated_conversation.summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating conversation title: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate conversation title: {e!s}"
        ) from e


@router.post(
    "/conversations/{conversation_id}/summary",
    response_model=ConversationResponse,
)
async def generate_summary(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> ConversationResponse:
    """Generate an AI summary of the conversation."""
    try:
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
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
            limit=50,
        )

        messages_text = ""
        for event in message_events:
            role = event.event_type.replace("_message", "")
            content = event.event_data.get("content", "")
            if content:
                messages_text += f"{role}: {content[:500]}\n"

        if not messages_text.strip():
            raise HTTPException(
                status_code=400,
                detail="No messages found to generate summary from",
            )

        title_llm = await agent_service._get_title_llm()
        from src.domain.llm_providers.llm_types import Message as LLMMessage

        prompt = (
            "Summarize this conversation in 1-2 concise sentences. "
            "Focus on the main topic and key outcomes.\n\n"
            f"Messages:\n{messages_text[:3000]}\n\nSummary:"
        )
        response = await title_llm.ainvoke(
            [
                LLMMessage.system(
                    "You are a helpful assistant that generates concise conversation summaries."
                ),
                LLMMessage.user(prompt),
            ]
        )
        summary = response.content.strip()
        if len(summary) > 500:
            summary = summary[:497] + "..."

        conversation.summary = summary
        from datetime import datetime

        conversation.updated_at = datetime.now(UTC)
        await agent_service._conversation_repo.save_and_commit(conversation)

        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating conversation summary: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate conversation summary: {e!s}",
        ) from e


@router.post("/conversations/{conversation_id}/fork")
async def fork_conversation(
    conversation_id: str,
    message_id: str = Query(..., description="Message ID to fork from"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fork a conversation from a specific message point."""
    try:
        original = await db.get(ConversationModel, conversation_id)
        if not original:
            raise HTTPException(status_code=404, detail="Conversation not found")

        new_id = str(uuid.uuid4())
        new_conv = ConversationModel(
            id=new_id,
            project_id=original.project_id,
            tenant_id=original.tenant_id,
            user_id=current_user.id,
            title=f"{original.title} (fork)",
            status="active",
            parent_conversation_id=conversation_id,
            branch_point_message_id=message_id,
        )
        db.add(new_conv)

        query = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.created_at)
        )
        result = await db.execute(query)
        messages = result.scalars().all()

        copied = 0
        for msg in messages:
            new_msg = MessageModel(
                id=str(uuid.uuid4()),
                conversation_id=new_id,
                role=msg.role,
                content=msg.content,
                message_type=msg.message_type,
                created_at=msg.created_at,
            )
            db.add(new_msg)
            copied += 1
            if msg.id == message_id:
                break

        new_conv.message_count = copied
        await db.commit()

        return {
            "id": new_conv.id,
            "title": new_conv.title,
            "parent_id": conversation_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error forking conversation: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fork conversation: {e!s}",
        ) from e


@router.put("/conversations/{conversation_id}/messages/{message_id}")
async def edit_message(
    conversation_id: str,
    message_id: str,
    data: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Edit a message and increment version."""
    try:
        msg = await db.get(MessageModel, message_id)
        if not msg or msg.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="Message not found")

        if msg.original_content is None:
            msg.original_content = msg.content
        msg.content = data.get("content", msg.content)
        msg.version = (msg.version or 1) + 1
        msg.edited_at = datetime.now(UTC)

        await db.commit()
        return {
            "id": msg.id,
            "content": msg.content,
            "version": msg.version,
            "edited_at": str(msg.edited_at),
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error editing message: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to edit message: {e!s}",
        ) from e


@router.post("/conversations/{conversation_id}/tools/{execution_id}/undo")
async def request_tool_undo(
    conversation_id: str,
    execution_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Request undo of a tool execution.

    Creates a follow-up user message asking the agent to undo
    the specified tool execution.
    """
    try:
        exec_record = await db.get(ToolExecutionRecord, execution_id)
        if not exec_record:
            raise HTTPException(status_code=404, detail="Tool execution not found")

        if exec_record.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="Tool execution not found")

        undo_msg = MessageModel(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="user",
            content=(
                f"Please undo the previous tool execution: {exec_record.tool_name}. "
                "Revert any changes made."
            ),
            created_at=datetime.now(UTC),
        )
        db.add(undo_msg)
        await db.commit()

        return {
            "status": "undo_requested",
            "message_id": undo_msg.id,
            "tool_name": exec_record.tool_name,
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error requesting tool undo: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to request tool undo: {e!s}",
        ) from e
