"""Agent API endpoints.

This module provides REST endpoints for managing conversations.
Streaming is now handled via WebSocket at /api/v1/agent/ws.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.constants.error_ids import AGENT_CONVERSATION_CREATE_FAILED
from src.configuration.di_container import DIContainer
from src.configuration.factories import create_langchain_llm
from src.domain.model.agent import Conversation, ConversationStatus
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])
logger = logging.getLogger(__name__)


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.

    This creates a new container with the request's db session while preserving
    the graph_service, redis_client, and mcp_temporal_adapter from the app state container.
    """
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
        mcp_temporal_adapter=app_container._mcp_temporal_adapter,
    )


# === Request/Response Schemas ===


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""

    project_id: str
    title: Optional[str] = "New Conversation"
    agent_config: Optional[dict] = None


class UpdateConversationTitleRequest(BaseModel):
    """Request to update conversation title."""

    title: str


class ConversationResponse(BaseModel):
    """Response with conversation details."""

    id: str
    project_id: str
    user_id: str
    tenant_id: str
    title: str
    status: str
    message_count: int
    created_at: str
    updated_at: Optional[str] = None

    @classmethod
    def from_domain(cls, conversation: Conversation) -> "ConversationResponse":
        """Create response from domain entity."""
        return cls(
            id=conversation.id,
            project_id=conversation.project_id,
            user_id=conversation.user_id,
            tenant_id=conversation.tenant_id,
            title=conversation.title,
            status=conversation.status.value,
            message_count=conversation.message_count,
            created_at=conversation.created_at.isoformat(),
            updated_at=conversation.updated_at.isoformat() if conversation.updated_at else None,
        )


class ChatRequest(BaseModel):
    """Request to chat with the agent."""

    conversation_id: str
    message: str


class ToolInfo(BaseModel):
    """Information about an available tool."""

    name: str
    description: str


class ToolsListResponse(BaseModel):
    """Response with list of available tools."""

    tools: list[ToolInfo]


# === Endpoints ===


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ConversationResponse:
    """
    Create a new conversation.

    Args:
        data: Conversation creation request
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session
        request: FastAPI Request object

    Returns:
        Created conversation
    """
    try:
        # Get container from app state
        container = get_container_with_db(request, db)

        # Create LLM
        llm = create_langchain_llm(tenant_id)

        # Create conversation
        use_case = container.create_conversation_use_case(llm)
        conversation = await use_case.execute(
            project_id=data.project_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
            title=data.title,
            agent_config=data.agent_config,
        )

        # Explicitly commit the transaction to ensure the conversation is saved
        await db.commit()

        return ConversationResponse.from_domain(conversation)

    except (ValueError, AttributeError) as e:
        await db.rollback()
        logger.error(
            f"Validation error creating conversation: {e}",
            exc_info=True,
            extra={"error_id": AGENT_CONVERSATION_CREATE_FAILED},
        )
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request: {str(e)}",
        )
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
    """
    List conversations for a project.

    Args:
        project_id: Project ID to filter by
        status: Optional status filter
        limit: Maximum number of conversations to return
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session

    Returns:
        List of conversations
    """
    try:
        # Log connection pool metrics for debugging
        engine = db.get_bind()
        pool = engine.pool
        logger.debug(
            f"[Connection Pool] size={pool.size()}, checked_out={pool.checkedout()}, "
            f"overflow={pool.overflow()}, queue_size={pool.size() - pool.checkedout()}"
        )

        container = get_container_with_db(request, db)

        llm = create_langchain_llm(tenant_id)
        use_case = container.list_conversations_use_case(llm)

        # Parse status if provided
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
    """
    Get a conversation by ID.

    Args:
        conversation_id: Conversation ID
        project_id: Project ID for authorization
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session

    Returns:
        Conversation details
    """
    try:
        container = get_container_with_db(request, db)

        llm = create_langchain_llm(tenant_id)
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


@router.get("/tools", response_model=ToolsListResponse)
async def list_tools(
    current_user: User = Depends(get_current_user),
) -> ToolsListResponse:
    """
    List available agent tools.

    Returns:
        List of available tools with descriptions
    """
    tools = [
        ToolInfo(
            name="memory_search",
            description="Search through stored memories and knowledge in the graph for relevant information.",
        ),
        ToolInfo(
            name="entity_lookup",
            description="Look up specific entities (people, organizations, concepts) and their relationships.",
        ),
        ToolInfo(
            name="episode_retrieval",
            description="Retrieve historical episodes and conversations from the knowledge graph.",
        ),
        ToolInfo(
            name="memory_create",
            description="Create a new memory entry in the knowledge graph for future reference.",
        ),
        ToolInfo(
            name="graph_query",
            description="Execute a custom Cypher query on the knowledge graph for complex analysis.",
        ),
        ToolInfo(
            name="summary",
            description="Generate a concise summary of provided information or conversations.",
        ),
    ]

    return ToolsListResponse(tools=tools)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> None:
    """
    Delete a conversation and all its messages.

    Args:
        conversation_id: Conversation ID to delete
        project_id: Project ID for authorization
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session
    """
    try:
        container = get_container_with_db(request, db)

        llm = create_langchain_llm(tenant_id)
        agent_service = container.agent_service(llm)

        # Verify conversation exists and user has access
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
    request: UpdateConversationTitleRequest,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request_obj: Request = None,
) -> ConversationResponse:
    """
    Update conversation title.

    Args:
        conversation_id: Conversation ID to update
        request: Update request with new title
        project_id: Project ID for authorization
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session
    """
    try:
        container = get_container_with_db(request_obj, db)

        llm = create_langchain_llm(tenant_id)
        agent_service = container.agent_service(llm)

        # Verify conversation exists and user has access
        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Update title
        updated_conversation = await agent_service.update_conversation_title(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            title=request.title,
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
    request_obj: Request = None,
) -> ConversationResponse:
    """
    Generate and update a friendly conversation title based on the first user message.

    .. deprecated::
        This endpoint is deprecated. Title generation is now handled automatically
        by the backend after the first agent response completes. The title is delivered
        via the `title_generated` SSE event. This endpoint is kept for backward compatibility
        but may be removed in a future version.

    Args:
        conversation_id: Conversation ID to generate title for
        project_id: Project ID for authorization
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session
    """
    try:
        container = get_container_with_db(request_obj, db)

        llm = create_langchain_llm(tenant_id)
        agent_service = container.agent_service(llm)

        # Verify conversation exists and user has access
        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get the first user message from events to generate title from
        message_events = await agent_service.get_conversation_messages(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=10,
        )

        # Find the first user message
        first_user_message = None
        for event in message_events:
            if event.event_type == "user_message":
                first_user_message = event.event_data.get("content", "")
                break

        if not first_user_message:
            raise HTTPException(
                status_code=400, detail="No user message found to generate title from"
            )

        # Generate title using LLM
        generated_title = await agent_service.generate_conversation_title(
            first_message=first_user_message,
            llm=llm,
        )

        # Update conversation with generated title
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


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    limit: int = Query(50, ge=1, le=500, description="Maximum events to return"),
    from_sequence: int = Query(
        0, description="Starting sequence number (inclusive) for forward pagination"
    ),
    before_sequence: Optional[int] = Query(
        None, description="For backward pagination, get events before this sequence"
    ),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Get conversation timeline from unified event stream with bidirectional pagination.

    This endpoint returns a timeline of all events in the conversation,
    ordered by sequence number. Events include:
    - user_message: User messages
    - assistant_message: Assistant responses
    - thought: Agent reasoning
    - act: Tool calls
    - observe: Tool results

    Args:
        conversation_id: Conversation ID
        project_id: Project ID for authorization
        limit: Maximum number of events to return (default: 100, max: 500)
        from_sequence: Starting sequence number (inclusive) for forward pagination
        before_sequence: For backward pagination, get events before this sequence (exclusive)
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session

    Returns:
        Dictionary with timeline list and pagination metadata:
        - timeline: List of events in chronological order
        - total: Number of events returned
        - has_more: Whether more events exist before this page
        - first_sequence: Sequence number of the first event in this page
        - last_sequence: Sequence number of the last event in this page
    """
    try:
        container = get_container_with_db(request, db)

        llm = create_langchain_llm(tenant_id)
        agent_service = container.agent_service(llm)

        # Verify access
        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get events from unified event timeline
        event_repo = container.agent_execution_event_repository()
        tool_exec_repo = container.tool_execution_record_repository()

        # Define displayable event types - filter at database level for efficiency
        DISPLAYABLE_EVENTS = {
            "user_message",
            "assistant_message",
            "thought",
            "act",
            "observe",
            "work_plan",
            "step_start",
            "step_end",
            "artifact_created",  # Display generated artifacts (images, files, etc.)
        }

        # Calculate pagination parameters for initial load (get the latest N events)
        # When both from_sequence=0 and before_sequence=None, fetch the latest events
        calculated_from_sequence = from_sequence
        calculated_before_sequence = before_sequence

        if from_sequence == 0 and before_sequence is None:
            # Use backward pagination to get the latest N displayable events
            # Set before_sequence to a large value to get the most recent events
            last_seq = await event_repo.get_last_sequence(conversation_id)
            if last_seq > 0:
                # Use backward pagination: get events before (last_seq + 1)
                # This ensures we get the latest events regardless of event type gaps
                calculated_before_sequence = last_seq + 1
                calculated_from_sequence = 0  # Not used in backward mode, but set for clarity

        events = await event_repo.get_events(
            conversation_id=conversation_id,
            from_sequence=calculated_from_sequence,
            limit=limit,
            event_types=DISPLAYABLE_EVENTS,
            before_sequence=calculated_before_sequence,
        )

        # Get tool executions for duration info
        tool_executions = await tool_exec_repo.list_by_conversation(conversation_id)
        tool_exec_map = {}
        for te in tool_executions:
            key = f"{te.message_id}:{te.tool_name}"
            tool_exec_map[key] = {
                "startTime": te.started_at.timestamp() * 1000 if te.started_at else None,
                "endTime": te.completed_at.timestamp() * 1000 if te.completed_at else None,
                "duration": te.duration_ms,
            }

        # Build timeline
        timeline = []
        for event in events:
            event_type = event.event_type
            # Events already filtered at database level by DISPLAYABLE_EVENTS

            data = event.event_data or {}
            item = {
                "id": f"{event_type}-{event.sequence_number}",
                "type": event_type,
                "sequenceNumber": event.sequence_number,
                "timestamp": int(event.created_at.timestamp() * 1000) if event.created_at else None,
            }

            if event_type == "user_message":
                # Keep the unique id generated above, don't override with message_id
                # This prevents React key conflicts when user_message and assistant_message
                # have the same message_id (they are separate events and should render separately)
                item["message_id"] = data.get("message_id")  # Store separately if needed
                item["content"] = data.get("content", "")
                item["role"] = "user"

            elif event_type == "assistant_message":
                # Keep the unique id generated above, don't override with message_id
                item["message_id"] = data.get("message_id")  # Store separately if needed
                item["content"] = data.get("content", "")
                item["role"] = "assistant"

            elif event_type == "thought":
                thought_content = data.get("thought", "")
                if not thought_content or not thought_content.strip():
                    continue
                item["content"] = thought_content

            elif event_type == "act":
                item["toolName"] = data.get("tool_name", "")
                item["toolInput"] = data.get("tool_input", {})
                # Add tool execution timing if available
                key = f"{event.message_id}:{data.get('tool_name', '')}"
                if key in tool_exec_map:
                    item["execution"] = tool_exec_map[key]

            elif event_type == "observe":
                item["toolName"] = data.get("tool_name", "")
                item["toolOutput"] = data.get("observation", "")
                item["isError"] = data.get("is_error", False)

            elif event_type == "work_plan":
                item["steps"] = data.get("steps", [])
                item["status"] = data.get("status", "planning")

            elif event_type == "step_start":
                item["stepIndex"] = data.get("step_index", 0)
                item["stepDescription"] = data.get("description", "")

            elif event_type == "step_end":
                item["stepIndex"] = data.get("step_index", 0)
                item["status"] = data.get("status", "completed")

            elif event_type == "artifact_created":
                # Artifact created by sandbox/MCP tools (images, files, etc.)
                item["artifactId"] = data.get("artifact_id", "")
                item["filename"] = data.get("filename", "")
                item["mimeType"] = data.get("mime_type", "")
                item["category"] = data.get("category", "other")
                item["sizeBytes"] = data.get("size_bytes", 0)
                item["url"] = data.get("url", "")
                item["previewUrl"] = data.get("preview_url", "")
                item["sourceTool"] = data.get("source_tool", "")
                item["metadata"] = data.get("metadata", {})

            timeline.append(item)

        # Calculate pagination metadata
        first_sequence = None
        last_sequence = None
        if timeline:
            first_sequence = timeline[0]["sequenceNumber"]
            last_sequence = timeline[-1]["sequenceNumber"]

        # Determine if there are more events before this page
        has_more = False
        if first_sequence is not None and before_sequence is None:
            # Forward pagination: check if there might be earlier events
            if first_sequence > 0:
                has_more = True
        elif first_sequence is not None and before_sequence is not None:
            # Backward pagination: check if there are events before first_sequence
            # Query once more to check if any events exist before first_sequence
            check_events = await event_repo.get_events(
                conversation_id=conversation_id,
                from_sequence=0,
                limit=1,
                event_types=DISPLAYABLE_EVENTS,
                before_sequence=first_sequence,
            )
            has_more = len(check_events) > 0

        return {
            "conversationId": conversation_id,
            "timeline": timeline,
            "total": len(timeline),
            "has_more": has_more,
            "first_sequence": first_sequence,
            "last_sequence": last_sequence,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.error(f"Error getting conversation messages: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to get messages: {str(e)}")


@router.get("/conversations/{conversation_id}/execution")
async def get_conversation_execution(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    limit: int = Query(50, ge=1, le=100, description="Maximum executions to return"),
    status_filter: Optional[str] = Query(None, description="Filter by execution status"),
    tool_filter: Optional[str] = Query(None, description="Filter by tool name"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Get the agent execution history for a conversation.

    This returns the history of agent executions with multi-level thinking details,
    including work plans, step execution, and tool calls.

    Args:
        conversation_id: Conversation ID
        project_id: Project ID for authorization
        limit: Maximum number of executions to return
        status_filter: Optional filter by execution status
        tool_filter: Optional filter by tool name
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session

    Returns:
        Dictionary with execution history

    Raises:
        404: If conversation not found or unauthorized
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)

        llm = create_langchain_llm(tenant_id)
        agent_service = container.agent_service(llm)

        # Get execution history
        executions = await agent_service.get_execution_history(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=limit,
        )

        # Apply filters
        if status_filter:
            executions = [e for e in executions if e.get("status") == status_filter]

        if tool_filter:
            executions = [e for e in executions if e.get("tool_name") == tool_filter]

        return {
            "conversation_id": conversation_id,
            "executions": executions,
            "total": len(executions),
        }

    except ValueError as e:
        # Conversation not found or unauthorized
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting conversation execution history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution history: {str(e)}")


@router.get("/conversations/{conversation_id}/tool-executions")
async def get_conversation_tool_executions(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    message_id: Optional[str] = Query(None, description="Filter by message ID"),
    limit: int = Query(100, ge=1, le=500, description="Maximum executions to return"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Get the tool execution history for a conversation.

    This returns the history of individual tool executions with full details,
    enabling proper timeline reconstruction when loading historical conversations.

    Args:
        conversation_id: Conversation ID
        project_id: Project ID for authorization
        message_id: Optional filter by message ID
        limit: Maximum number of executions to return
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session

    Returns:
        Dictionary with tool execution history

    Raises:
        404: If conversation not found or unauthorized
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)

        # First verify user has access to the conversation
        conversation_repo = container.conversation_repository()
        conversation = await conversation_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if conversation.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get tool execution records
        tool_execution_repo = container.tool_execution_record_repository()

        if message_id:
            records = await tool_execution_repo.list_by_message(message_id, limit=limit)
        else:
            records = await tool_execution_repo.list_by_conversation(conversation_id, limit=limit)

        return {
            "conversation_id": conversation_id,
            "tool_executions": [record.to_dict() for record in records],
            "total": len(records),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tool execution history: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get tool execution history: {str(e)}"
        )


@router.get("/conversations/{conversation_id}/status")
async def get_conversation_execution_status(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    include_recovery_info: bool = Query(
        False, description="Include event recovery information for stream resumption"
    ),
    from_sequence: int = Query(
        0, description="Client's last known sequence (for recovery calculation)"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Get the current execution status of a conversation with optional recovery info.

    This endpoint checks the Redis is_running key to determine if an agent
    is currently executing for this conversation.

    When include_recovery_info=true, also returns information needed to
    recover event stream after page refresh:
    - last_sequence: Latest sequence number in event stream
    - missed_events_count: Number of events missed since from_sequence
    - can_recover: Whether recovery is possible (stream still exists)

    Args:
        conversation_id: Conversation ID
        project_id: Project ID for authorization
        include_recovery_info: Include recovery information for stream resumption
        from_sequence: Client's last known sequence (for missed_events calculation)
        current_user: Authenticated user
        db: Database session

    Returns:
        Dictionary with execution status and optional recovery info

    Raises:
        404: If conversation not found or unauthorized
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)

        # First verify user has access to the conversation
        conversation_repo = container.conversation_repository()
        conversation = await conversation_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if conversation.user_id != current_user.id or conversation.project_id != project_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Check Redis for active execution
        redis_client = container._redis_client
        is_running = False
        current_message_id = None

        if redis_client:
            import redis.asyncio as redis

            if isinstance(redis_client, redis.Redis):
                key = f"agent:running:{conversation_id}"
                exists = await redis_client.exists(key)
                is_running = bool(exists)

                if is_running:
                    # Get the current message_id being processed
                    message_id_bytes = await redis_client.get(key)
                    if message_id_bytes:
                        current_message_id = (
                            message_id_bytes.decode()
                            if isinstance(message_id_bytes, bytes)
                            else message_id_bytes
                        )

        result = {
            "conversation_id": conversation_id,
            "is_running": is_running,
            "current_message_id": current_message_id,
        }

        # Include recovery info if requested
        if include_recovery_info:
            recovery_info = await _get_recovery_info(
                container=container,
                redis_client=redis_client,
                conversation_id=conversation_id,
                message_id=current_message_id,
                from_sequence=from_sequence,
            )
            result["recovery"] = recovery_info

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation execution status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution status: {str(e)}")


async def _get_recovery_info(
    container,
    redis_client,
    conversation_id: str,
    message_id: Optional[str],
    from_sequence: int,
) -> dict:
    """
    Get event stream recovery information.

    Checks both Redis Stream and database for recovery data.

    Args:
        container: DI container
        redis_client: Redis client
        conversation_id: Conversation ID
        message_id: Current message ID being processed (if any)
        from_sequence: Client's last known sequence

    Returns:
        Dictionary with recovery information:
        - can_recover: Whether recovery is possible
        - last_sequence: Latest sequence in the stream
        - missed_events_count: Events missed since from_sequence
        - stream_exists: Whether Redis Stream exists
        - recovery_source: "stream" or "database"
    """
    recovery_info = {
        "can_recover": False,
        "last_sequence": -1,
        "missed_events_count": 0,
        "stream_exists": False,
        "recovery_source": "none",
    }

    try:
        # Check Redis Stream for live events
        if redis_client and message_id:
            import redis.asyncio as redis

            if isinstance(redis_client, redis.Redis):
                stream_key = f"agent:events:{conversation_id}"
                try:
                    # Check if stream exists
                    stream_info = await redis_client.xinfo_stream(stream_key)
                    if stream_info:
                        recovery_info["stream_exists"] = True
                        # Get last entry to find last sequence
                        last_entry = await redis_client.xrevrange(stream_key, count=1)
                        if last_entry:
                            _, fields = last_entry[0]
                            seq_raw = fields.get(b"seq") or fields.get("seq")
                            if seq_raw:
                                recovery_info["last_sequence"] = int(seq_raw)
                                recovery_info["can_recover"] = True
                                recovery_info["recovery_source"] = "stream"
                                recovery_info["missed_events_count"] = max(
                                    0, recovery_info["last_sequence"] - from_sequence
                                )
                except redis.ResponseError:
                    # Stream doesn't exist
                    pass

        # Fallback to database if stream doesn't exist or no message_id
        if not recovery_info["stream_exists"]:
            event_repo = container.agent_execution_event_repository()
            last_db_seq = await event_repo.get_last_sequence(conversation_id)
            if last_db_seq >= 0:
                recovery_info["last_sequence"] = last_db_seq
                recovery_info["can_recover"] = True
                recovery_info["recovery_source"] = "database"
                recovery_info["missed_events_count"] = max(0, last_db_seq - from_sequence)

    except Exception as e:
        logger.warning(f"Error getting recovery info: {e}")

    return recovery_info


# === Workflow Pattern Endpoints (T080-T083) ===


class PatternStepResponse(BaseModel):
    """Response model for a pattern step."""

    step_number: int
    description: str
    tool_name: str
    expected_output_format: str
    similarity_threshold: float
    tool_parameters: Optional[dict] = None


class WorkflowPatternResponse(BaseModel):
    """Response model for a workflow pattern."""

    id: str
    tenant_id: str
    name: str
    description: str
    steps: list[PatternStepResponse]
    success_rate: float
    usage_count: int
    created_at: str
    updated_at: str
    metadata: Optional[dict] = None


class PatternsListResponse(BaseModel):
    """Response model for patterns list."""

    patterns: list[WorkflowPatternResponse]
    total: int
    page: int
    page_size: int


class ResetPatternsResponse(BaseModel):
    """Response model for pattern reset."""

    deleted_count: int
    tenant_id: str


@router.get("/workflows/patterns", response_model=PatternsListResponse)
async def list_patterns(
    tenant_id: str = Query(..., description="Tenant ID to filter patterns"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    min_success_rate: Optional[float] = Query(
        None, ge=0, le=1, description="Minimum success rate filter"
    ),
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PatternsListResponse:
    """
    List workflow patterns for a tenant (T080).

    Patterns are tenant-scoped and shared across all projects within the tenant.
    Non-admin users have read-only access (FR-019).

    Args:
        tenant_id: Tenant ID to filter patterns
        page: Page number (1-indexed)
        page_size: Number of items per page
        min_success_rate: Optional minimum success rate filter
        current_user: Authenticated user
        db: Database session

    Returns:
        List of workflow patterns for the tenant

    Raises:
        403: If user doesn't have access to the tenant
        500: For server errors
    """
    try:
        # Verify tenant access
        if user_tenant_id != tenant_id and not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Access denied to tenant patterns")

        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        # Get all patterns for tenant
        all_patterns = await pattern_repo.list_by_tenant(tenant_id)

        # Apply optional success rate filter
        if min_success_rate is not None:
            all_patterns = [p for p in all_patterns if p.success_rate >= min_success_rate]

        # Apply pagination
        total = len(all_patterns)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_patterns = all_patterns[start_idx:end_idx]

        return PatternsListResponse(
            patterns=[
                WorkflowPatternResponse(
                    id=p.id,
                    tenant_id=p.tenant_id,
                    name=p.name,
                    description=p.description,
                    steps=[
                        PatternStepResponse(
                            step_number=s.step_number,
                            description=s.description,
                            tool_name=s.tool_name,
                            expected_output_format=s.expected_output_format,
                            similarity_threshold=s.similarity_threshold,
                            tool_parameters=s.tool_parameters,
                        )
                        for s in p.steps
                    ],
                    success_rate=p.success_rate,
                    usage_count=p.usage_count,
                    created_at=p.created_at.isoformat(),
                    updated_at=p.updated_at.isoformat(),
                    metadata=p.metadata,
                )
                for p in paginated_patterns
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing patterns: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list patterns: {str(e)}")


@router.get("/workflows/patterns/{pattern_id}", response_model=WorkflowPatternResponse)
async def get_pattern(
    pattern_id: str,
    tenant_id: str = Query(..., description="Tenant ID for authorization"),
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> WorkflowPatternResponse:
    """
    Get a workflow pattern by ID (T081).

    Args:
        pattern_id: Pattern ID
        tenant_id: Tenant ID for authorization
        current_user: Authenticated user
        user_tenant_id: User's tenant ID
        db: Database session

    Returns:
        Workflow pattern details

    Raises:
        403: If user doesn't have access to the tenant
        404: If pattern not found
        500: For server errors
    """
    try:
        # Verify tenant access
        if user_tenant_id != tenant_id and not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Access denied to tenant patterns")

        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        pattern = await pattern_repo.get_by_id(pattern_id)

        if not pattern:
            raise HTTPException(status_code=404, detail="Pattern not found")

        # Verify pattern belongs to the tenant
        if pattern.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Pattern not found")

        return WorkflowPatternResponse(
            id=pattern.id,
            tenant_id=pattern.tenant_id,
            name=pattern.name,
            description=pattern.description,
            steps=[
                PatternStepResponse(
                    step_number=s.step_number,
                    description=s.description,
                    tool_name=s.tool_name,
                    expected_output_format=s.expected_output_format,
                    similarity_threshold=s.similarity_threshold,
                    tool_parameters=s.tool_parameters,
                )
                for s in pattern.steps
            ],
            success_rate=pattern.success_rate,
            usage_count=pattern.usage_count,
            created_at=pattern.created_at.isoformat(),
            updated_at=pattern.updated_at.isoformat(),
            metadata=pattern.metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pattern: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get pattern: {str(e)}")


@router.delete("/workflows/patterns/{pattern_id}", status_code=200)
async def delete_pattern(
    pattern_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Delete a workflow pattern by ID (T082) - Admin only.

    Args:
        pattern_id: Pattern ID
        current_user: Authenticated user (must be admin)
        db: Database session

    Returns:
        Success message

    Raises:
        403: If user is not an admin
        404: If pattern not found
        500: For server errors
    """
    try:
        # Verify admin access
        if not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required")

        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        # Check if pattern exists
        pattern = await pattern_repo.get_by_id(pattern_id)
        if not pattern:
            raise HTTPException(status_code=404, detail="Pattern not found")

        # Delete pattern
        await pattern_repo.delete(pattern_id)

        return {"message": "Pattern deleted successfully", "pattern_id": pattern_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting pattern: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete pattern: {str(e)}")


@router.post("/workflows/patterns/reset", response_model=ResetPatternsResponse)
async def reset_patterns(
    tenant_id: str = Query(..., description="Tenant ID to reset patterns for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ResetPatternsResponse:
    """
    Reset/delete all workflow patterns for a tenant (T083) - Admin only.

    This is a destructive operation that removes all learned patterns
    for the specified tenant.

    Args:
        tenant_id: Tenant ID to reset patterns for
        current_user: Authenticated user (must be admin)
        db: Database session

    Returns:
        Number of patterns deleted

    Raises:
        403: If user is not an admin
        500: For server errors
    """
    try:
        # Verify admin access
        if not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required")

        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        # Get all patterns for tenant
        all_patterns = await pattern_repo.list_by_tenant(tenant_id)

        # Delete all patterns
        deleted_count = 0
        for pattern in all_patterns:
            await pattern_repo.delete(pattern.id)
            deleted_count += 1

        return ResetPatternsResponse(
            deleted_count=deleted_count,
            tenant_id=tenant_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting patterns: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset patterns: {str(e)}")


# === Tenant Agent Config Endpoints (T096, T097) ===


class TenantAgentConfigResponse(BaseModel):
    """Response model for tenant agent configuration."""

    id: str
    tenant_id: str
    config_type: str
    llm_model: str
    llm_temperature: float
    pattern_learning_enabled: bool
    multi_level_thinking_enabled: bool
    max_work_plan_steps: int
    tool_timeout_seconds: int
    enabled_tools: list[str]
    disabled_tools: list[str]
    created_at: str
    updated_at: str


class UpdateTenantAgentConfigRequest(BaseModel):
    """Request model for updating tenant agent configuration."""

    llm_model: Optional[str] = None
    llm_temperature: Optional[float] = None
    pattern_learning_enabled: Optional[bool] = None
    multi_level_thinking_enabled: Optional[bool] = None
    max_work_plan_steps: Optional[int] = None
    tool_timeout_seconds: Optional[int] = None
    enabled_tools: Optional[list[str]] = None
    disabled_tools: Optional[list[str]] = None


@router.get("/config", response_model=TenantAgentConfigResponse)
async def get_tenant_agent_config(
    tenant_id: str = Query(..., description="Tenant ID to get config for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> TenantAgentConfigResponse:
    """
    Get tenant-level agent configuration (T096).

    All authenticated users can read the configuration (FR-021).

    Args:
        tenant_id: Tenant ID to get config for
        current_user: Authenticated user
        db: Database session

    Returns:
        Tenant agent configuration

    Raises:
        403: If user doesn't have access to the tenant
        500: For server errors
    """
    try:
        # Import repository class
        from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
            SQLTenantAgentConfigRepository,
        )

        # Create repository with the session from request
        config_repo = SQLTenantAgentConfigRepository(db)

        # Get config or return default
        config = await config_repo.get_by_tenant(tenant_id)
        if not config:
            # Return default config
            from src.domain.model.agent.tenant_agent_config import TenantAgentConfig

            config = TenantAgentConfig.create_default(tenant_id=tenant_id)

        return TenantAgentConfigResponse(
            id=config.id,
            tenant_id=config.tenant_id,
            config_type=config.config_type.value,
            llm_model=config.llm_model,
            llm_temperature=config.llm_temperature,
            pattern_learning_enabled=config.pattern_learning_enabled,
            multi_level_thinking_enabled=config.multi_level_thinking_enabled,
            max_work_plan_steps=config.max_work_plan_steps,
            tool_timeout_seconds=config.tool_timeout_seconds,
            enabled_tools=config.enabled_tools,
            disabled_tools=config.disabled_tools,
            created_at=config.created_at.isoformat(),
            updated_at=config.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tenant agent config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get tenant agent config: {str(e)}")


@router.put("/config", response_model=TenantAgentConfigResponse)
async def update_tenant_agent_config(
    update_request: UpdateTenantAgentConfigRequest,
    tenant_id: str = Query(..., description="Tenant ID to update config for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> TenantAgentConfigResponse:
    """
    Update tenant-level agent configuration (T097) - Admin only.

    Only tenant admins can modify the configuration (FR-022).

    Args:
        update_request: Configuration update request
        tenant_id: Tenant ID to update config for
        current_user: Authenticated user (must be tenant admin)
        db: Database session

    Returns:
        Updated tenant agent configuration

    Raises:
        403: If user is not a tenant admin
        500: For server errors
    """
    try:
        # Verify tenant admin access
        from sqlalchemy import select

        from src.infrastructure.adapters.secondary.persistence.models import UserTenant

        result = await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == current_user.id,
                UserTenant.tenant_id == tenant_id,
            )
        )
        user_tenant = result.scalar_one_or_none()

        # Check if user is tenant admin or global admin
        is_global_admin = any(r.role.name == "admin" for r in current_user.roles)
        is_tenant_admin = user_tenant and user_tenant.role in ["admin", "owner"]

        if not is_global_admin and not is_tenant_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

        # Import repository and entity
        from datetime import datetime, timezone

        from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
        from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
            SQLTenantAgentConfigRepository,
        )

        # Create repository with the session from request
        config_repo = SQLTenantAgentConfigRepository(db)

        # Get existing config or create default
        config = await config_repo.get_by_tenant(tenant_id)
        if not config:
            config = TenantAgentConfig.create_default(tenant_id=tenant_id)

        # Apply updates - collect all parameters
        llm_model = (
            update_request.llm_model if update_request.llm_model is not None else config.llm_model
        )
        llm_temperature = (
            update_request.llm_temperature
            if update_request.llm_temperature is not None
            else config.llm_temperature
        )
        pattern_learning_enabled = (
            update_request.pattern_learning_enabled
            if update_request.pattern_learning_enabled is not None
            else config.pattern_learning_enabled
        )
        multi_level_thinking_enabled = (
            update_request.multi_level_thinking_enabled
            if update_request.multi_level_thinking_enabled is not None
            else config.multi_level_thinking_enabled
        )
        max_work_plan_steps = (
            update_request.max_work_plan_steps
            if update_request.max_work_plan_steps is not None
            else config.max_work_plan_steps
        )
        tool_timeout_seconds = (
            update_request.tool_timeout_seconds
            if update_request.tool_timeout_seconds is not None
            else config.tool_timeout_seconds
        )
        enabled_tools = (
            update_request.enabled_tools
            if update_request.enabled_tools is not None
            else list(config.enabled_tools)
        )
        disabled_tools = (
            update_request.disabled_tools
            if update_request.disabled_tools is not None
            else list(config.disabled_tools)
        )

        # Create updated config
        updated_config = TenantAgentConfig(
            id=config.id,
            tenant_id=config.tenant_id,
            config_type=config.config_type,
            llm_model=llm_model,
            llm_temperature=llm_temperature,
            pattern_learning_enabled=pattern_learning_enabled,
            multi_level_thinking_enabled=multi_level_thinking_enabled,
            max_work_plan_steps=max_work_plan_steps,
            tool_timeout_seconds=tool_timeout_seconds,
            enabled_tools=enabled_tools,
            disabled_tools=disabled_tools,
            created_at=config.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        # Save updated config
        saved_config = await config_repo.save(updated_config)

        return TenantAgentConfigResponse(
            id=saved_config.id,
            tenant_id=saved_config.tenant_id,
            config_type=saved_config.config_type.value,
            llm_model=saved_config.llm_model,
            llm_temperature=saved_config.llm_temperature,
            pattern_learning_enabled=saved_config.pattern_learning_enabled,
            multi_level_thinking_enabled=saved_config.multi_level_thinking_enabled,
            max_work_plan_steps=saved_config.max_work_plan_steps,
            tool_timeout_seconds=saved_config.tool_timeout_seconds,
            enabled_tools=saved_config.enabled_tools,
            disabled_tools=saved_config.disabled_tools,
            created_at=saved_config.created_at.isoformat(),
            updated_at=saved_config.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except ValueError as e:
        # Validation error from entity
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating tenant agent config: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update tenant agent config: {str(e)}"
        )


# === Tool Composition Endpoints (T114) ===


class ToolCompositionResponse(BaseModel):
    """Response model for a tool composition."""

    id: str
    name: str
    description: str
    tools: list[str]
    execution_template: dict
    success_rate: float
    success_count: int
    failure_count: int
    usage_count: int
    created_at: str
    updated_at: str


class ToolCompositionsListResponse(BaseModel):
    """Response model for listing tool compositions."""

    compositions: list[ToolCompositionResponse]
    total: int


@router.get("/tools/compositions", response_model=ToolCompositionsListResponse)
async def list_tool_compositions(
    tools: Optional[str] = Query(
        None, description="Comma-separated list of tool names to filter by"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of compositions to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ToolCompositionsListResponse:
    """
    List tool compositions (T114).

    Tool compositions represent chains of tools that work together
    to accomplish complex tasks through intelligent chaining.

    Args:
        tools: Optional comma-separated list of tool names to filter by
        limit: Maximum number of compositions to return
        current_user: Authenticated user
        db: Database session

    Returns:
        List of tool compositions

    Raises:
        500: For server errors
    """
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository import (
            SQLToolCompositionRepository,
        )

        # Create repository
        composition_repo = SQLToolCompositionRepository(db)

        # Get compositions
        if tools:
            tool_names = [t.strip() for t in tools.split(",") if t.strip()]
            compositions = await composition_repo.list_by_tools(tool_names)
        else:
            compositions = await composition_repo.list_all(limit)

        return ToolCompositionsListResponse(
            compositions=[
                ToolCompositionResponse(
                    id=c.id,
                    name=c.name,
                    description=c.description,
                    tools=list(c.tools),
                    execution_template=dict(c.execution_template),
                    success_rate=c.success_rate,
                    success_count=c.success_count,
                    failure_count=c.failure_count,
                    usage_count=c.usage_count,
                    created_at=c.created_at.isoformat(),
                    updated_at=c.updated_at.isoformat(),
                )
                for c in compositions
            ],
            total=len(compositions),
        )

    except Exception as e:
        logger.error(f"Error listing tool compositions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list tool compositions: {str(e)}")


@router.get("/tools/compositions/{composition_id}", response_model=ToolCompositionResponse)
async def get_tool_composition(
    composition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ToolCompositionResponse:
    """
    Get a tool composition by ID (T114).

    Args:
        composition_id: Tool composition ID
        current_user: Authenticated user
        db: Database session

    Returns:
        Tool composition details

    Raises:
        404: If composition not found
        500: For server errors
    """
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository import (
            SQLToolCompositionRepository,
        )

        # Create repository
        composition_repo = SQLToolCompositionRepository(db)

        # Get composition
        composition = await composition_repo.get_by_id(composition_id)

        if not composition:
            raise HTTPException(status_code=404, detail="Tool composition not found")

        return ToolCompositionResponse(
            id=composition.id,
            name=composition.name,
            description=composition.description,
            tools=list(composition.tools),
            execution_template=dict(composition.execution_template),
            success_rate=composition.success_rate,
            success_count=composition.success_count,
            failure_count=composition.failure_count,
            usage_count=composition.usage_count,
            created_at=composition.created_at.isoformat(),
            updated_at=composition.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tool composition: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get tool composition: {str(e)}")


# === Execution Statistics Endpoints (Phase 5) ===


class ExecutionStatsResponse(BaseModel):
    """Response model for execution statistics."""

    total_executions: int
    completed_count: int
    failed_count: int
    average_duration_ms: float
    tool_usage: dict[str, int]
    status_distribution: dict[str, int]
    timeline_data: list[dict]


@router.get("/conversations/{conversation_id}/execution/stats")
async def get_execution_stats(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ExecutionStatsResponse:
    """
    Get execution statistics for a conversation.

    Returns aggregated statistics including:
    - Total execution count
    - Completion/failure rates
    - Average execution duration
    - Tool usage distribution
    - Status distribution
    - Timeline data for visualization

    Args:
        conversation_id: Conversation ID
        project_id: Project ID for authorization
        current_user: Authenticated user
        tenant_id: User's tenant ID
        db: Database session

    Returns:
        Execution statistics

    Raises:
        404: If conversation not found or unauthorized
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)

        llm = create_langchain_llm(tenant_id)
        agent_service = container.agent_service(llm)

        # Get execution history
        executions = await agent_service.get_execution_history(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=1000,
        )

        # Calculate statistics
        total_executions = len(executions)
        completed_count = sum(1 for e in executions if e.get("status") == "COMPLETED")
        failed_count = sum(1 for e in executions if e.get("status") == "FAILED")

        # Calculate average duration
        durations = []
        for e in executions:
            if e.get("started_at") and e.get("completed_at"):
                from datetime import datetime

                started = datetime.fromisoformat(e["started_at"].replace("Z", "+00:00"))
                completed = datetime.fromisoformat(e["completed_at"].replace("Z", "+00:00"))
                duration_ms = (completed - started).total_seconds() * 1000
                durations.append(duration_ms)

        average_duration_ms = sum(durations) / len(durations) if durations else 0.0

        # Tool usage distribution
        tool_usage: dict[str, int] = {}
        for e in executions:
            tool_name = e.get("tool_name")
            if tool_name:
                tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1

        # Status distribution
        status_distribution: dict[str, int] = {}
        for e in executions:
            status = e.get("status", "UNKNOWN")
            status_distribution[status] = status_distribution.get(status, 0) + 1

        # Timeline data (grouped by time buckets)
        timeline_data = []
        if executions:
            from collections import defaultdict
            from datetime import datetime

            time_buckets: dict[str, dict] = defaultdict(
                lambda: {"count": 0, "completed": 0, "failed": 0}
            )

            for e in executions:
                if e.get("started_at"):
                    started = datetime.fromisoformat(e["started_at"].replace("Z", "+00:00"))
                    # Group by hour
                    bucket_key = started.strftime("%Y-%m-%d %H:00")
                    time_buckets[bucket_key]["count"] += 1

                    if e.get("status") == "COMPLETED":
                        time_buckets[bucket_key]["completed"] += 1
                    elif e.get("status") == "FAILED":
                        time_buckets[bucket_key]["failed"] += 1

            timeline_data = [{"time": k, **v} for k, v in sorted(time_buckets.items())]

        return ExecutionStatsResponse(
            total_executions=total_executions,
            completed_count=completed_count,
            failed_count=failed_count,
            average_duration_ms=average_duration_ms,
            tool_usage=tool_usage,
            status_distribution=status_distribution,
            timeline_data=timeline_data,
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting execution statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution statistics: {str(e)}")


# === Human-in-the-Loop Response Endpoints ===


class HITLRequestResponse(BaseModel):
    """Response model for a pending HITL request."""

    id: str
    request_type: str  # clarification | decision | env_var
    conversation_id: str
    message_id: Optional[str] = None
    question: str
    options: Optional[list] = None
    context: Optional[dict] = None
    metadata: Optional[dict] = None
    status: str
    created_at: str
    expires_at: str


class PendingHITLResponse(BaseModel):
    """Response for pending HITL requests query."""

    requests: list[HITLRequestResponse]
    total: int


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

    Args:
        conversation_id: The conversation ID to query

    Returns:
        List of pending HITL requests for the conversation
    """
    try:
        # Get tenant_id and project_id from conversation
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlAlchemyConversationRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SQLHITLRequestRepository,
        )

        conv_repo = SqlAlchemyConversationRepository(db)
        conversation = await conv_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

        # Verify user has access (same tenant)
        if conversation.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied to this conversation")

        # Query pending requests
        # Note: Don't exclude expired - show all pending requests so users can respond
        # The recovery service will handle requests when Agent is not waiting
        repo = SQLHITLRequestRepository(db)
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

    Args:
        project_id: The project ID to query
        limit: Maximum number of results (default 50)

    Returns:
        List of pending HITL requests for the project
    """
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SQLHITLRequestRepository,
        )

        repo = SQLHITLRequestRepository(db)
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


class ClarificationResponseRequest(BaseModel):
    """Request to respond to a clarification."""

    request_id: str
    answer: str


class DecisionResponseRequest(BaseModel):
    """Request to respond to a decision."""

    request_id: str
    decision: str


class DoomLoopResponseRequest(BaseModel):
    """Request to respond to a doom loop intervention."""

    request_id: str
    action: str  # "continue" or "stop"


class EnvVarResponseRequest(BaseModel):
    """Request to respond to an environment variable request."""

    request_id: str
    values: dict[str, str]  # variable_name -> value mapping


class HumanInteractionResponse(BaseModel):
    """Response for human interaction endpoints."""

    success: bool
    request_id: str
    message: str


@router.post("/clarification/respond", response_model=HumanInteractionResponse)
async def respond_to_clarification(
    request: ClarificationResponseRequest,
    current_user: User = Depends(get_current_user),
) -> HumanInteractionResponse:
    """
    Respond to a pending clarification request.

    This endpoint allows users to provide answers to clarification questions
    asked by the agent during the planning phase.

    Args:
        request: Clarification response with request_id and answer
        current_user: Authenticated user

    Returns:
        Success status

    Raises:
        404: If clarification request not found
        500: For server errors
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

    Args:
        request: Decision response with request_id and decision
        current_user: Authenticated user

    Returns:
        Success status

    Raises:
        404: If decision request not found
        500: For server errors
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

    Args:
        request: Env var response with request_id and values mapping
        current_user: Authenticated user

    Returns:
        Success status

    Raises:
        404: If env var request not found
        500: For server errors
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

    Args:
        request: Doom loop response with request_id and action
        current_user: Authenticated user

    Returns:
        Success status

    Raises:
        404: If doom loop request not found
        400: If action is invalid
        500: For server errors
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


# === Plan Mode Endpoints ===


class EnterPlanModeRequest(BaseModel):
    """Request to enter Plan Mode."""

    conversation_id: str
    title: str
    description: Optional[str] = None


class ExitPlanModeRequest(BaseModel):
    """Request to exit Plan Mode."""

    conversation_id: str
    plan_id: str
    approve: bool = True
    summary: Optional[str] = None


class UpdatePlanRequest(BaseModel):
    """Request to update a plan."""

    content: Optional[str] = None
    title: Optional[str] = None
    explored_files: Optional[list[str]] = None
    critical_files: Optional[list[dict]] = None
    metadata: Optional[dict] = None


class PlanResponse(BaseModel):
    """Response with plan details."""

    id: str
    conversation_id: str
    title: str
    content: str
    status: str
    version: int
    metadata: dict
    created_at: str
    updated_at: str


class PlanModeStatusResponse(BaseModel):
    """Response with plan mode status."""

    is_in_plan_mode: bool
    current_mode: str
    current_plan_id: Optional[str] = None
    plan: Optional[PlanResponse] = None


@router.post("/plan/enter", response_model=PlanResponse)
async def enter_plan_mode(
    data: EnterPlanModeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanResponse:
    """
    Enter Plan Mode for a conversation.

    Creates a new Plan document and switches the conversation to Plan Mode,
    which provides read-only access to the codebase plus plan editing capability.

    Args:
        data: Plan mode entry request with conversation_id and title
        current_user: Authenticated user
        db: Database session

    Returns:
        The created Plan document

    Raises:
        400: If already in Plan Mode
        404: If conversation not found
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.enter_plan_mode_use_case()

        plan = await use_case.execute(
            conversation_id=data.conversation_id,
            title=data.title,
            description=data.description,
        )

        await db.commit()

        logger.info(
            f"User {current_user.id} entered Plan Mode for conversation {data.conversation_id}"
        )

        return PlanResponse(
            id=plan.id,
            conversation_id=plan.conversation_id,
            title=plan.title,
            content=plan.content,
            status=plan.status.value,
            version=plan.version,
            metadata=plan.metadata,
            created_at=plan.created_at.isoformat(),
            updated_at=plan.updated_at.isoformat(),
        )

    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        if "already in Plan Mode" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        logger.error(f"Error entering Plan Mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to enter Plan Mode: {str(e)}")


@router.post("/plan/exit", response_model=PlanResponse)
async def exit_plan_mode(
    data: ExitPlanModeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanResponse:
    """
    Exit Plan Mode for a conversation.

    Optionally approves the plan and returns to Build Mode.

    Args:
        data: Plan mode exit request with conversation_id and plan_id
        current_user: Authenticated user
        db: Database session

    Returns:
        The updated Plan document

    Raises:
        400: If not in Plan Mode
        404: If conversation or plan not found
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.exit_plan_mode_use_case()

        plan = await use_case.execute(
            conversation_id=data.conversation_id,
            plan_id=data.plan_id,
            approve=data.approve,
            summary=data.summary,
        )

        await db.commit()

        logger.info(
            f"User {current_user.id} exited Plan Mode for conversation {data.conversation_id}, "
            f"approved={data.approve}"
        )

        return PlanResponse(
            id=plan.id,
            conversation_id=plan.conversation_id,
            title=plan.title,
            content=plan.content,
            status=plan.status.value,
            version=plan.version,
            metadata=plan.metadata,
            created_at=plan.created_at.isoformat(),
            updated_at=plan.updated_at.isoformat(),
        )

    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        if "not in Plan Mode" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        logger.error(f"Error exiting Plan Mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to exit Plan Mode: {str(e)}")


@router.get("/plan/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanResponse:
    """
    Get a plan document by ID.

    Args:
        plan_id: The plan document ID
        current_user: Authenticated user
        db: Database session

    Returns:
        The Plan document

    Raises:
        404: If plan not found
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.get_plan_use_case()

        plan = await use_case.execute(plan_id=plan_id)

        return PlanResponse(
            id=plan.id,
            conversation_id=plan.conversation_id,
            title=plan.title,
            content=plan.content,
            status=plan.status.value,
            version=plan.version,
            metadata=plan.metadata,
            created_at=plan.created_at.isoformat(),
            updated_at=plan.updated_at.isoformat(),
        )

    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        logger.error(f"Error getting plan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get plan: {str(e)}")


@router.get("/conversations/{conversation_id}/plans", response_model=list[PlanResponse])
async def list_conversation_plans(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> list[PlanResponse]:
    """
    List all plans for a conversation.

    Args:
        conversation_id: The conversation ID
        current_user: Authenticated user
        db: Database session

    Returns:
        List of Plan documents

    Raises:
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.get_plan_use_case()

        plans = await use_case.get_by_conversation(conversation_id=conversation_id)

        return [
            PlanResponse(
                id=plan.id,
                conversation_id=plan.conversation_id,
                title=plan.title,
                content=plan.content,
                status=plan.status.value,
                version=plan.version,
                metadata=plan.metadata,
                created_at=plan.created_at.isoformat(),
                updated_at=plan.updated_at.isoformat(),
            )
            for plan in plans
        ]

    except Exception as e:
        logger.error(f"Error listing plans: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list plans: {str(e)}")


@router.put("/plan/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: str,
    data: UpdatePlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanResponse:
    """
    Update a plan document.

    Args:
        plan_id: The plan document ID
        data: Update request with content and/or metadata
        current_user: Authenticated user
        db: Database session

    Returns:
        The updated Plan document

    Raises:
        400: If plan is not editable
        404: If plan not found
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.update_plan_use_case()

        plan = await use_case.execute(
            plan_id=plan_id,
            content=data.content,
            title=data.title,
            explored_files=data.explored_files,
            critical_files=data.critical_files,
            metadata=data.metadata,
        )

        await db.commit()

        logger.info(f"User {current_user.id} updated plan {plan_id}")

        return PlanResponse(
            id=plan.id,
            conversation_id=plan.conversation_id,
            title=plan.title,
            content=plan.content,
            status=plan.status.value,
            version=plan.version,
            metadata=plan.metadata,
            created_at=plan.created_at.isoformat(),
            updated_at=plan.updated_at.isoformat(),
        )

    except Exception as e:
        await db.rollback()
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        if "cannot" in str(e).lower() or "invalid" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        logger.error(f"Error updating plan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update plan: {str(e)}")


@router.get("/conversations/{conversation_id}/plan-mode", response_model=PlanModeStatusResponse)
async def get_plan_mode_status(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanModeStatusResponse:
    """
    Get the Plan Mode status for a conversation.

    Args:
        conversation_id: The conversation ID
        current_user: Authenticated user
        db: Database session

    Returns:
        Plan mode status including current mode and active plan if any

    Raises:
        404: If conversation not found
        500: For server errors
    """
    try:
        container = get_container_with_db(request, db)
        conversation_repo = container.conversation_repository()

        conversation = await conversation_repo.find_by_id(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get active plan if in Plan Mode
        plan_response = None
        if conversation.is_in_plan_mode and conversation.current_plan_id:
            plan_use_case = container.get_plan_use_case()
            try:
                plan = await plan_use_case.execute(plan_id=conversation.current_plan_id)
                plan_response = PlanResponse(
                    id=plan.id,
                    conversation_id=plan.conversation_id,
                    title=plan.title,
                    content=plan.content,
                    status=plan.status.value,
                    version=plan.version,
                    metadata=plan.metadata,
                    created_at=plan.created_at.isoformat(),
                    updated_at=plan.updated_at.isoformat(),
                )
            except Exception:
                pass  # Plan might have been deleted

        return PlanModeStatusResponse(
            is_in_plan_mode=conversation.is_in_plan_mode,
            current_mode=conversation.current_mode.value,
            current_plan_id=conversation.current_plan_id,
            plan=plan_response,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plan mode status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get plan mode status: {str(e)}")


# === Event Replay and Execution Status Endpoints ===


class EventReplayResponse(BaseModel):
    """Response with replay events."""

    events: list[dict]
    has_more: bool


class RecoveryInfo(BaseModel):
    """Information needed for event stream recovery."""

    can_recover: bool = False
    stream_exists: bool = False
    recovery_source: str = "none"  # "stream", "database", or "none"
    missed_events_count: int = 0


class ExecutionStatusResponse(BaseModel):
    """Response with execution status and optional recovery information."""

    is_running: bool
    last_sequence: int
    current_message_id: Optional[str] = None
    conversation_id: str
    recovery: Optional[RecoveryInfo] = None


class WorkflowStatusResponse(BaseModel):
    """Response with Temporal workflow status."""

    workflow_id: str
    run_id: Optional[str] = None
    status: str  # RUNNING, COMPLETED, FAILED, CANCELED, etc.
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    error: Optional[str] = None


@router.get("/conversations/{conversation_id}/events", response_model=EventReplayResponse)
async def get_conversation_events(
    conversation_id: str,
    from_sequence: int = Query(0, ge=0, description="Starting sequence number"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum events to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> EventReplayResponse:
    """
    Get SSE events for a conversation, used for replaying execution state.

    This endpoint returns persisted SSE events starting from a given sequence number,
    allowing clients to replay the execution timeline when reconnecting or switching
    between conversations.

    Args:
        conversation_id: The conversation ID
        from_sequence: Starting sequence number (inclusive)
        limit: Maximum number of events to return
        current_user: Authenticated user
        db: Database session

    Returns:
        List of events in sequence order and whether more events exist
    """
    try:
        container = get_container_with_db(request, db)
        event_repo = container.agent_execution_event_repository()

        if not event_repo:
            # Event replay not configured
            return EventReplayResponse(events=[], has_more=False)

        events = await event_repo.get_events(
            conversation_id=conversation_id,
            from_sequence=from_sequence,
            limit=limit,
        )

        # Convert events to SSE format
        event_dicts = [event.to_sse_format() for event in events]

        return EventReplayResponse(
            events=event_dicts,
            has_more=len(events) == limit,
        )

    except Exception as e:
        logger.error(f"Error getting conversation events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get events: {str(e)}")


@router.get(
    "/conversations/{conversation_id}/execution-status", response_model=ExecutionStatusResponse
)
async def get_execution_status(
    conversation_id: str,
    include_recovery: bool = Query(
        False, description="Include recovery information for stream resumption"
    ),
    from_sequence: int = Query(
        0, description="Client's last known sequence (for recovery calculation)"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ExecutionStatusResponse:
    """
    Get the current execution status of a conversation with optional recovery info.

    This endpoint provides information about whether an agent is currently
    executing for this conversation, the last event sequence number, and
    the current message being processed.

    When include_recovery=true, also returns information needed to
    recover event stream after page refresh:
    - can_recover: Whether recovery is possible
    - stream_exists: Whether Redis Stream exists
    - recovery_source: "stream", "database", or "none"
    - missed_events_count: Events missed since from_sequence

    Args:
        conversation_id: The conversation ID
        include_recovery: Include recovery information
        from_sequence: Client's last known sequence (for missed_events calculation)
        current_user: Authenticated user
        db: Database session

    Returns:
        Execution status information with optional recovery details
    """
    try:
        container = get_container_with_db(request, db)
        event_repo = container.agent_execution_event_repository()
        redis_client = container.redis()

        if not event_repo:
            # Event replay not configured
            return ExecutionStatusResponse(
                is_running=False,
                last_sequence=0,
                current_message_id=None,
                conversation_id=conversation_id,
            )

        # Get last sequence number
        last_sequence = await event_repo.get_last_sequence(conversation_id)

        # Check Redis for active execution
        is_running = False
        current_message_id = None

        if redis_client:
            running_key = f"agent:running:{conversation_id}"
            running_message_id = await redis_client.get(running_key)
            # DEBUG: Log the running state check
            logger.warning(
                f"[ExecutionStatus] Redis check for {running_key}: "
                f"value={running_message_id}, is_running={bool(running_message_id)}"
            )
            if running_message_id:
                is_running = True
                current_message_id = (
                    running_message_id.decode()
                    if isinstance(running_message_id, bytes)
                    else running_message_id
                )

        # If not running from Redis check, get current message ID from last event
        if not current_message_id and last_sequence > 0:
            events = await event_repo.get_events(
                conversation_id=conversation_id,
                from_sequence=max(0, last_sequence - 1),
                limit=1,
            )
            if events:
                current_message_id = events[-1].message_id

        # Build response
        response = ExecutionStatusResponse(
            is_running=is_running,
            last_sequence=last_sequence,
            current_message_id=current_message_id,
            conversation_id=conversation_id,
        )

        # Include recovery info if requested
        if include_recovery:
            recovery_info = RecoveryInfo(
                can_recover=last_sequence > from_sequence,
                recovery_source="database" if last_sequence > 0 else "none",
                missed_events_count=max(0, last_sequence - from_sequence),
            )

            # Check Redis Stream for live events
            if redis_client and current_message_id:
                import redis.asyncio as redis

                if isinstance(redis_client, redis.Redis):
                    stream_key = f"agent:events:{conversation_id}"
                    try:
                        # Check if stream exists
                        stream_info = await redis_client.xinfo_stream(stream_key)
                        if stream_info:
                            recovery_info.stream_exists = True
                            recovery_info.recovery_source = "stream"
                            # Get last entry to find last sequence
                            last_entry = await redis_client.xrevrange(stream_key, count=1)
                            if last_entry:
                                _, fields = last_entry[0]
                                seq_raw = fields.get(b"seq") or fields.get("seq")
                                if seq_raw:
                                    stream_seq = int(seq_raw)
                                    if stream_seq > last_sequence:
                                        recovery_info.missed_events_count = max(
                                            0, stream_seq - from_sequence
                                        )
                                        recovery_info.can_recover = True
                    except redis.ResponseError:
                        # Stream doesn't exist
                        pass

            response.recovery = recovery_info

        return response

    except Exception as e:
        logger.error(f"Error getting execution status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get execution status: {str(e)}")


@router.post("/conversations/{conversation_id}/resume", status_code=202)
async def resume_execution(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """
    Resume agent execution from the last checkpoint.

    This endpoint retrieves the latest checkpoint for a conversation and
    resumes the agent execution from that point. If no checkpoint exists,
    returns 404.

    Args:
        conversation_id: The conversation ID
        current_user: Authenticated user
        db: Database session

    Returns:
        202 Accepted if resumption started, 404 if no checkpoint found
    """
    try:
        container = get_container_with_db(request, db)
        checkpoint_repo = container.execution_checkpoint_repository()

        if not checkpoint_repo:
            raise HTTPException(status_code=501, detail="Execution checkpoint not configured")

        # Get latest checkpoint
        checkpoint = await checkpoint_repo.get_latest(conversation_id)

        if not checkpoint:
            raise HTTPException(status_code=404, detail="No checkpoint found for this conversation")

        # TODO: Implement actual resumption logic
        # This would involve:
        # 1. Create a new ReActAgent instance
        # 2. Restore state from checkpoint.execution_state
        # 3. Continue execution from the checkpoint point
        # For now, we just return the checkpoint info

        return {
            "status": "resuming",
            "checkpoint_id": checkpoint.id,
            "checkpoint_type": checkpoint.checkpoint_type,
            "step_number": checkpoint.step_number,
            "message": f"Resuming from {checkpoint.checkpoint_type} checkpoint at step {checkpoint.step_number}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to resume execution: {str(e)}")


@router.get(
    "/conversations/{conversation_id}/workflow-status", response_model=WorkflowStatusResponse
)
async def get_workflow_status(
    conversation_id: str,
    message_id: Optional[str] = Query(None, description="Message ID to get workflow status for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> WorkflowStatusResponse:
    """
    Get the Temporal workflow status for an agent execution.

    This endpoint queries the Temporal server for the current status of the
    agent execution workflow, including whether it's running, completed, or failed.

    Args:
        conversation_id: The conversation ID
        message_id: Optional message ID (defaults to latest)
        current_user: Authenticated user
        db: Database session
        request: FastAPI request

    Returns:
        Workflow status information from Temporal
    """
    try:
        container = get_container_with_db(request, db)

        # Get Temporal client (if available)
        temporal_client = await container.temporal_client()
        if not temporal_client:
            raise HTTPException(status_code=501, detail="Temporal workflow engine not configured")

        # Determine workflow ID from message_id or conversation
        workflow_id = f"agent-exec-{conversation_id}"
        if message_id:
            workflow_id = f"agent-exec-{conversation_id}-{message_id}"

        # Query Temporal for workflow status
        try:
            handle = temporal_client.get_workflow_handle(workflow_id)
            desc = await handle.describe()

            # Map Temporal status to string
            status_map = {
                "RUNNING": "RUNNING",
                "COMPLETED": "COMPLETED",
                "FAILED": "FAILED",
                "CANCELED": "CANCELED",
                "TERMINATED": "TERMINATED",
                "TIMED_OUT": "TIMED_OUT",
            }
            status = status_map.get(str(desc.status), "UNKNOWN")

            return WorkflowStatusResponse(
                workflow_id=workflow_id,
                run_id=desc.run_id,
                status=status,
                started_at=desc.start_time,
                completed_at=desc.close_time,
            )

        except Exception as e:
            # Workflow not found or other Temporal error
            if "not found" in str(e).lower() or "workflow not found" in str(e).lower():
                raise HTTPException(
                    status_code=404, detail=f"No workflow found for conversation {conversation_id}"
                )
            raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workflow status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get workflow status: {str(e)}")
