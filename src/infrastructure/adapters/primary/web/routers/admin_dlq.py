"""DLQ Admin API Router.

Provides administrative endpoints for managing the Dead Letter Queue:
- View failed messages
- Retry failed messages (single and batch)
- Discard messages
- View DLQ statistics
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from src.domain.model.auth.user import User
from src.domain.ports.services.dead_letter_queue_port import (
    DeadLetterMessage,
    DeadLetterQueuePort,
    DLQMessageNotFoundError,
    DLQMessageStatus,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/dlq",
    tags=["admin", "dlq"],
)


# =============================================================================
# Request/Response Models
# =============================================================================


class DLQMessageResponse(BaseModel):
    """Response model for a DLQ message."""
    
    id: str
    event_id: str
    event_type: str
    event_data: str
    routing_key: str
    error: str
    error_type: str
    error_traceback: Optional[str] = None
    retry_count: int
    max_retries: int
    first_failed_at: datetime
    last_failed_at: datetime
    next_retry_at: Optional[datetime] = None
    status: str
    metadata: dict
    can_retry: bool
    age_seconds: float

    @classmethod
    def from_domain(cls, msg: DeadLetterMessage) -> "DLQMessageResponse":
        return cls(
            id=msg.id,
            event_id=msg.event_id,
            event_type=msg.event_type,
            event_data=msg.event_data,
            routing_key=msg.routing_key,
            error=msg.error,
            error_type=msg.error_type,
            error_traceback=msg.error_traceback,
            retry_count=msg.retry_count,
            max_retries=msg.max_retries,
            first_failed_at=msg.first_failed_at,
            last_failed_at=msg.last_failed_at,
            next_retry_at=msg.next_retry_at,
            status=msg.status.value,
            metadata=msg.metadata,
            can_retry=msg.can_retry,
            age_seconds=msg.age_seconds,
        )


class DLQListResponse(BaseModel):
    """Response model for listing DLQ messages."""
    
    messages: List[DLQMessageResponse]
    total: int
    limit: int
    offset: int


class DLQStatsResponse(BaseModel):
    """Response model for DLQ statistics."""
    
    total_messages: int
    pending_count: int
    retrying_count: int
    discarded_count: int
    expired_count: int
    resolved_count: int
    oldest_message_age_seconds: float
    error_type_counts: dict
    event_type_counts: dict


class RetryRequest(BaseModel):
    """Request model for retrying messages."""
    
    message_ids: List[str] = Field(min_length=1, max_length=100)


class RetryResponse(BaseModel):
    """Response model for retry operation."""
    
    results: dict  # message_id -> success (bool)
    success_count: int
    failure_count: int


class DiscardRequest(BaseModel):
    """Request model for discarding messages."""
    
    message_ids: List[str] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)


class DiscardResponse(BaseModel):
    """Response model for discard operation."""
    
    results: dict  # message_id -> success (bool)
    success_count: int
    failure_count: int


class CleanupResponse(BaseModel):
    """Response model for cleanup operation."""
    
    cleaned_count: int


# =============================================================================
# Dependencies
# =============================================================================


async def get_dlq(request: Request) -> DeadLetterQueuePort:
    """Get the DLQ port from DI container."""
    try:
        container = request.app.state.container
        dlq = container.get(DeadLetterQueuePort)
        if dlq is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DLQ service not available",
            )
        return dlq
    except AttributeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application container not initialized",
        )


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require admin role for endpoint access."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/messages", response_model=DLQListResponse)
async def list_messages(
    filter_status: Optional[str] = Query(None, alias="status", description="Filter by status (pending, retrying, discarded, expired, resolved)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    error_type: Optional[str] = Query(None, description="Filter by error type"),
    routing_key: Optional[str] = Query(None, description="Filter by routing key pattern"),
    limit: int = Query(50, ge=1, le=100, description="Maximum messages to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> DLQListResponse:
    """List DLQ messages with optional filtering.
    
    Admin only endpoint for viewing failed events in the dead letter queue.
    """
    # Parse status filter
    status_filter = None
    if filter_status:
        try:
            status_filter = DLQMessageStatus(filter_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {filter_status}. Valid values: {[s.value for s in DLQMessageStatus]}",
            )
    
    messages = await dlq.get_messages(
        status=status_filter,
        event_type=event_type,
        error_type=error_type,
        routing_key_pattern=routing_key,
        limit=limit,
        offset=offset,
    )
    
    return DLQListResponse(
        messages=[DLQMessageResponse.from_domain(m) for m in messages],
        total=len(messages),  # TODO: Add total count to port
        limit=limit,
        offset=offset,
    )


@router.get("/messages/{message_id}", response_model=DLQMessageResponse)
async def get_message(
    message_id: str,
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> DLQMessageResponse:
    """Get a specific DLQ message by ID.
    
    Admin only endpoint for viewing detailed information about a failed event.
    """
    message = await dlq.get_message(message_id)
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DLQ message not found: {message_id}",
        )
    
    return DLQMessageResponse.from_domain(message)


@router.post("/messages/{message_id}/retry")
async def retry_message(
    message_id: str,
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> dict:
    """Retry a single DLQ message.
    
    Admin only endpoint for retrying a failed event.
    """
    try:
        success = await dlq.retry_message(message_id)
        return {
            "message_id": message_id,
            "success": success,
            "message": "Retry initiated" if success else "Retry failed",
        }
    except DLQMessageNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DLQ message not found: {message_id}",
        )


@router.post("/messages/retry", response_model=RetryResponse)
async def retry_messages(
    request: RetryRequest,
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> RetryResponse:
    """Retry multiple DLQ messages in batch.
    
    Admin only endpoint for batch retrying failed events.
    Maximum 100 messages per request.
    """
    results = await dlq.retry_batch(request.message_ids)
    
    success_count = sum(1 for v in results.values() if v)
    failure_count = len(results) - success_count
    
    return RetryResponse(
        results=results,
        success_count=success_count,
        failure_count=failure_count,
    )


@router.delete("/messages/{message_id}")
async def discard_message(
    message_id: str,
    reason: str = Query(..., min_length=1, max_length=500, description="Reason for discarding"),
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> dict:
    """Discard a single DLQ message.
    
    Admin only endpoint for permanently discarding a failed event.
    """
    try:
        success = await dlq.discard_message(message_id, reason)
        return {
            "message_id": message_id,
            "success": success,
            "message": "Message discarded" if success else "Discard failed",
        }
    except DLQMessageNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DLQ message not found: {message_id}",
        )


@router.post("/messages/discard", response_model=DiscardResponse)
async def discard_messages(
    request: DiscardRequest,
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> DiscardResponse:
    """Discard multiple DLQ messages in batch.
    
    Admin only endpoint for batch discarding failed events.
    Maximum 100 messages per request.
    """
    results = await dlq.discard_batch(request.message_ids, request.reason)
    
    success_count = sum(1 for v in results.values() if v)
    failure_count = len(results) - success_count
    
    return DiscardResponse(
        results=results,
        success_count=success_count,
        failure_count=failure_count,
    )


@router.get("/stats", response_model=DLQStatsResponse)
async def get_stats(
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> DLQStatsResponse:
    """Get DLQ statistics.
    
    Admin only endpoint for viewing queue health metrics.
    """
    stats = await dlq.get_stats()
    
    return DLQStatsResponse(
        total_messages=stats.total_messages,
        pending_count=stats.pending_count,
        retrying_count=stats.retrying_count,
        discarded_count=stats.discarded_count,
        expired_count=stats.expired_count,
        resolved_count=stats.resolved_count,
        oldest_message_age_seconds=stats.oldest_message_age,
        error_type_counts=stats.error_type_counts,
        event_type_counts=stats.event_type_counts,
    )


@router.post("/cleanup/expired", response_model=CleanupResponse)
async def cleanup_expired(
    older_than_hours: int = Query(168, ge=1, le=720, description="Clean messages older than this (hours)"),
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> CleanupResponse:
    """Clean up expired DLQ messages.
    
    Admin only endpoint for removing old expired messages.
    Default: messages older than 168 hours (1 week).
    """
    cleaned = await dlq.cleanup_expired(older_than_hours)
    
    logger.info(f"Cleaned up {cleaned} expired DLQ messages older than {older_than_hours} hours")
    
    return CleanupResponse(cleaned_count=cleaned)


@router.post("/cleanup/resolved", response_model=CleanupResponse)
async def cleanup_resolved(
    older_than_hours: int = Query(24, ge=1, le=168, description="Clean resolved messages older than this (hours)"),
    dlq: DeadLetterQueuePort = Depends(get_dlq),
    _user: User = Depends(require_admin),
) -> CleanupResponse:
    """Clean up resolved DLQ messages.
    
    Admin only endpoint for removing old successfully retried messages.
    Default: messages older than 24 hours.
    """
    cleaned = await dlq.cleanup_resolved(older_than_hours)
    
    logger.info(f"Cleaned up {cleaned} resolved DLQ messages older than {older_than_hours} hours")
    
    return CleanupResponse(cleaned_count=cleaned)
