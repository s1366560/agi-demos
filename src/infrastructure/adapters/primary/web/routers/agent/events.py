"""Event replay and execution status endpoints for Agent API.

Provides endpoints for event management and execution monitoring:
- get_conversation_events: Get SSE events for replay
- get_execution_status: Get current execution status
- resume_execution: Resume from checkpoint
- get_workflow_status: Get Ray Actor status
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .schemas import (
    EventReplayResponse,
    ExecutionStatusResponse,
    RecoveryInfo,
    WorkflowStatusResponse,
)
from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/conversations/{conversation_id}/events", response_model=EventReplayResponse)
async def get_conversation_events(
    conversation_id: str,
    from_time_us: int = Query(0, ge=0, description="Starting event_time_us"),
    from_counter: int = Query(0, ge=0, description="Starting event_counter"),
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
    """
    try:
        container = get_container_with_db(request, db)
        event_repo = container.agent_execution_event_repository()

        if not event_repo:
            # Event replay not configured
            return EventReplayResponse(events=[], has_more=False)

        events = await event_repo.get_events(
            conversation_id=conversation_id,
            from_time_us=from_time_us,
            from_counter=from_counter,
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
    from_time_us: int = Query(
        0, description="Client's last known event_time_us (for recovery calculation)"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ExecutionStatusResponse:
    """
    Get the current execution status of a conversation with optional recovery info.

    When include_recovery=true, also returns information needed to
    recover event stream after page refresh:
    - can_recover: Whether recovery is possible
    - stream_exists: Whether Redis Stream exists
    - recovery_source: "stream", "database", or "none"
    - missed_events_count: Events missed since from_time_us
    """
    try:
        container = get_container_with_db(request, db)
        event_repo = container.agent_execution_event_repository()
        redis_client = container.redis()

        if not event_repo:
            # Event replay not configured
            return ExecutionStatusResponse(
                is_running=False,
                last_event_time_us=0,
                last_event_counter=0,
                current_message_id=None,
                conversation_id=conversation_id,
            )

        # Get last event time
        last_event_time_us, last_event_counter = await event_repo.get_last_event_time(
            conversation_id
        )

        # Check Redis for active execution
        is_running = False
        current_message_id = None

        if redis_client:
            running_key = f"agent:running:{conversation_id}"
            running_message_id = await redis_client.get(running_key)
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
        if not current_message_id and last_event_time_us > 0:
            events = await event_repo.get_events(
                conversation_id=conversation_id,
                limit=1,
            )
            if events:
                current_message_id = events[-1].message_id

        # Build response
        response = ExecutionStatusResponse(
            is_running=is_running,
            last_event_time_us=last_event_time_us,
            last_event_counter=last_event_counter,
            current_message_id=current_message_id,
            conversation_id=conversation_id,
        )

        # Include recovery info if requested
        if include_recovery:
            recovery_info = RecoveryInfo(
                can_recover=last_event_time_us > from_time_us,
                recovery_source="database" if last_event_time_us > 0 else "none",
                missed_events_count=0,  # Cannot compute count from time comparison
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
                            # Get last entry to find last event time
                            last_entry = await redis_client.xrevrange(stream_key, count=1)
                            if last_entry:
                                _, fields = last_entry[0]
                                time_us_raw = (
                                    fields.get(b"event_time_us")
                                    or fields.get("event_time_us")
                                )
                                if time_us_raw:
                                    stream_time_us = int(time_us_raw)
                                    if stream_time_us > last_event_time_us:
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
    Get the Ray Actor status for an agent execution.
    """
    try:
        from src.infrastructure.adapters.secondary.ray.client import await_ray
        from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )

        conversation_repo = SqlConversationRepository(db)
        conversation = await conversation_repo.find_by_id(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

        if conversation.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Access denied to this conversation")

        actor = await get_actor_if_exists(
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            agent_mode="default",
        )
        if not actor:
            raise HTTPException(
                status_code=404,
                detail=f"No actor found for conversation {conversation_id}",
            )

        status = await await_ray(actor.status.remote())
        status_text = "RUNNING" if status.is_executing else "IDLE" if status.is_initialized else "UNINITIALIZED"

        started_at = None
        if status.created_at:
            try:
                started_at = datetime.fromisoformat(status.created_at)
            except Exception:
                started_at = None

        return WorkflowStatusResponse(
            workflow_id=status.actor_id,
            run_id=None,
            status=status_text,
            started_at=started_at,
            completed_at=None,
            current_step=None,
            total_steps=None,
            error=None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workflow status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get workflow status: {str(e)}")
