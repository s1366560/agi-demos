"""Conversation management endpoints.

CRUD operations for Agent conversations.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
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
    UpdateConversationConfigRequest,
    UpdateConversationModeRequest,
    UpdateConversationTitleRequest,
)
from .utils import get_container_with_db

if TYPE_CHECKING:
    from src.configuration.di_container import DIContainer
    from src.domain.model.agent.conversation.conversation import Conversation

router = APIRouter()
logger = logging.getLogger(__name__)


async def _enforce_conversation_invariants(
    conversation: "Conversation",
    *,
    container: "DIContainer",
) -> None:
    """Run the post-mutation invariant checks for a Conversation.

    Raises :class:`HTTPException(422)` wrapping the underlying
    :class:`ConversationDomainError` / :class:`ParticipantNotPresentError`.

    Extracted from ``update_conversation_mode`` to keep the handler
    below the linter's complexity thresholds; ``POST /conversations``
    will share the same helper in G4-follow-up.
    """
    from src.application.services.agent.workspace_roster_validator import (
        WorkspaceRosterValidator,
    )
    from src.domain.model.agent.conversation.errors import (
        ConversationDomainError,
        ParticipantNotPresentError,
    )

    if conversation.conversation_mode is not None:
        try:
            conversation.assert_autonomous_invariants(conversation.conversation_mode)
        except ConversationDomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if conversation.workspace_id and conversation.participant_agents:
        validator = WorkspaceRosterValidator(
            workspace_agent_repository=container.workspace_agent_repository()
        )
        try:
            await validator.assert_valid(conversation)
        except ParticipantNotPresentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: CreateConversationRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Create a new conversation."""
    try:
        assert request is not None
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
    request: Request,
    project_id: str = Query(..., description="Project ID to filter by"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> PaginatedConversationsResponse:
    """List conversations for a project with pagination."""
    try:
        engine = db.get_bind()
        pool = engine.pool  # type: ignore[union-attr]
        logger.debug(
            f"[Connection Pool] size={pool.size()}, checked_out={pool.checkedout()}, "  # type: ignore[union-attr]
            f"overflow={pool.overflow()}, queue_size={pool.size() - pool.checkedout()}"  # type: ignore[union-attr]
        )

        assert request is not None
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
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Get a conversation by ID."""
    try:
        assert request is not None
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
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get context window status for a conversation.

    Returns the cached context summary info (if any) and message count,
    so the frontend can restore the context status indicator after page
    refresh or conversation switch.
    """
    try:
        assert request is not None
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
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation and all its messages."""
    try:
        assert request is not None
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
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Update conversation title."""
    try:
        assert request is not None
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

        assert updated_conversation is not None
        return ConversationResponse.from_domain(updated_conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating conversation title: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update conversation title: {e!s}"
        ) from e


@router.patch("/conversations/{conversation_id}/config", response_model=ConversationResponse)
async def update_conversation_config(
    conversation_id: str,
    data: UpdateConversationConfigRequest,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Update conversation-level LLM configuration (model override, LLM params)."""
    try:
        assert request is not None
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

        config_patch: dict[str, Any] = {}
        if data.llm_model_override is not None:
            cleaned = data.llm_model_override.strip()
            config_patch["llm_model_override"] = cleaned or None
        if data.llm_overrides is not None:
            cleaned_overrides = {k: v for k, v in data.llm_overrides.items() if v is not None}
            config_patch["llm_overrides"] = cleaned_overrides or None

        conversation.update_agent_config(config_patch)
        await agent_service._conversation_repo.save(conversation)  # type: ignore[attr-defined]
        await db.commit()

        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating conversation config: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update conversation config: {e!s}"
        ) from e


@router.patch("/conversations/{conversation_id}/mode", response_model=ConversationResponse)
async def update_conversation_mode(
    conversation_id: str,
    data: UpdateConversationModeRequest,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Update a conversation's mode override.

    Allows switching between ``single_agent``, ``multi_agent_shared``,
    ``multi_agent_isolated`` and ``autonomous`` modes. Goal + budget
    constraints for autonomous mode are sourced from the linked
    Workspace / WorkspaceTask (Track G) — not from this payload.
    """
    from src.domain.model.agent.conversation.conversation_mode import ConversationMode

    try:
        assert request is not None
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

        fields = data.model_fields_set

        if "conversation_mode" in fields:
            raw_mode = data.conversation_mode
            if raw_mode is None:
                conversation.conversation_mode = None
            else:
                try:
                    conversation.conversation_mode = ConversationMode(raw_mode)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Invalid conversation_mode '{raw_mode}'. Must be one of: "
                            f"{[m.value for m in ConversationMode]}"
                        ),
                    ) from exc

        # Track G2 — workspace linkage fields. Both are explicitly-optional:
        # presence in ``model_fields_set`` means apply the value (including
        # clearing to ``None``); absence means leave untouched.
        if "workspace_id" in fields:
            conversation.workspace_id = data.workspace_id
        if "linked_workspace_task_id" in fields:
            conversation.linked_workspace_task_id = data.linked_workspace_task_id

        # Enforce post-mutation invariants (autonomous + workspace roster).
        await _enforce_conversation_invariants(conversation, container=container)

        conversation.updated_at = datetime.now(UTC)
        await agent_service._conversation_repo.save(conversation)  # type: ignore[attr-defined]
        await db.commit()

        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        logger.warning(f"Invalid conversation mode update for {conversation_id}: {e}")
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating conversation mode: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update conversation mode: {e!s}"
        ) from e


@router.post(
    "/conversations/{conversation_id}/generate-title",
    response_model=ConversationResponse,
    deprecated=True,
)
async def generate_conversation_title(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """
    Generate and update a friendly conversation title based on the first user message.

    .. deprecated::
        Title generation is now handled automatically by the backend.
    """
    try:
        assert request is not None
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
        title_llm = await agent_service.get_title_llm()
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

        return ConversationResponse.from_domain(updated_conversation)

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
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Generate an AI summary of the conversation."""
    try:
        assert request is not None
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

        title_llm = await agent_service.get_title_llm()
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
        await agent_service._conversation_repo.save_and_commit(conversation)  # type: ignore[attr-defined]

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
        result = await db.execute(refresh_select_statement(query))
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
