"""SSE event streaming endpoints for Sandbox API.

Provides Server-Sent Events for sandbox lifecycle and service events.
"""

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_from_header_or_query,
)
from src.infrastructure.adapters.secondary.persistence.models import User

from .utils import get_event_publisher

logger = logging.getLogger(__name__)

router = APIRouter()


async def sandbox_event_stream(
    project_id: str,
    last_id: str = "0",
    event_publisher: Optional[SandboxEventPublisher] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Stream sandbox events from Redis Stream.

    Args:
        project_id: Project ID to stream events for
        last_id: Last received event ID for resuming (default: "0")
        event_publisher: Event publisher with Redis event bus

    Yields:
        Event dictionaries from Redis Stream
    """
    if not event_publisher or not event_publisher._event_bus:
        logger.warning("[SandboxSSE] Event bus not available")
        return

    stream_key = f"sandbox:events:{project_id}"
    event_bus = event_publisher._event_bus

    logger.info(f"[SandboxSSE] Starting stream for {stream_key} from {last_id}")

    try:
        async for message in event_bus.stream_read(
            stream_key=stream_key,
            last_id=last_id,
            count=100,
            block_ms=5000,  # Block for 5 seconds waiting for new events
        ):
            # Yield the event data with the message ID
            yield {
                "id": message.get("id", ""),
                "data": message.get("data", {}),
            }
    except asyncio.CancelledError:
        logger.info(f"[SandboxSSE] Stream cancelled for {stream_key}")
    except Exception as e:
        logger.error(f"[SandboxSSE] Stream error for {stream_key}: {e}")


async def sse_generator(
    project_id: str,
    last_id: str = "0",
    event_publisher: Optional[SandboxEventPublisher] = None,
) -> AsyncIterator[str]:
    """
    SSE response generator.

    Formats events as SSE messages:
    event: sandbox
    data: {"type": "...", "data": {...}, "timestamp": "..."}
    id: 1234567890-0

    Args:
        project_id: Project ID to stream events for
        last_id: Last received event ID for resuming
        event_publisher: Event publisher with Redis event bus

    Yields:
        SSE formatted strings
    """
    async for message in sandbox_event_stream(project_id, last_id, event_publisher):
        event_data = message.get("data", {})
        event_id = message.get("id", "")

        # Format as SSE
        sse_message = f"event: sandbox\ndata: {json.dumps(event_data)}\nid: {event_id}\n\n"
        yield sse_message


@router.get("/events/{project_id}")
async def subscribe_sandbox_events(
    project_id: str,
    last_id: str = Query("0", description="Last event ID for resuming stream"),
    _current_user: User = Depends(get_current_user_from_header_or_query),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    SSE endpoint for sandbox events.

    Subscribes to sandbox lifecycle events (created, terminated, status)
    and service events (desktop_started, desktop_stopped, terminal_started, etc.).

    Query Parameters:
    - token: API key for authentication (required for SSE since EventSource cannot set headers)
    - last_id: Last received event ID for resuming (default: "0")

    SSE Format:
    - Event type: "sandbox"
    - Data: JSON with "type", "data", "timestamp" fields
    - ID: Redis Stream message ID for reconnection resume

    Reconnection:
    - Save the last received `id` value
    - Reconnect with `last_id=<saved_id>` to resume from that point
    """
    # Check if event bus is available before starting SSE stream
    if not event_publisher or not event_publisher._event_bus:
        logger.warning("[SandboxSSE] Event bus not available, returning 503")
        raise HTTPException(
            status_code=503,
            detail="Event streaming service temporarily unavailable. Redis event bus not configured.",
        )

    return StreamingResponse(
        sse_generator(project_id, last_id, event_publisher),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
