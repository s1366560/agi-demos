"""SSE event streaming endpoints for Sandbox API.

Provides Server-Sent Events for sandbox lifecycle and service events.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_from_header_or_query,
    get_db,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _

from .utils import assert_caller_owns_project, get_event_publisher

logger = logging.getLogger(__name__)

router = APIRouter()


async def sandbox_event_stream(
    project_id: str,
    last_id: str = "0",
    event_publisher: SandboxEventPublisher | None = None,
) -> AsyncIterator[dict[str, Any]]:
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
            block_ms=5000,
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
    event_publisher: SandboxEventPublisher | None = None,
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


@router.get("/events/{project_id}", response_class=StreamingResponse, response_model=None)
async def subscribe_sandbox_events(
    project_id: str,
    last_id: str = Query("0", description="Last event ID for resuming stream"),
    current_user: User = Depends(get_current_user_from_header_or_query),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    SSE endpoint for sandbox events.

    **DEPRECATED**: This SSE endpoint is deprecated. Please migrate to WebSocket.
    Use the unified WebSocket endpoint at `/api/v1/agent/ws` with message type
    `subscribe_sandbox` for sandbox event subscriptions.

    Migration example:
    ```javascript
    // Old SSE approach is deprecated; do not create new query-token clients.
    const es = new EventSource('/api/v1/sandbox/events/proj-123');

    // New WebSocket approach (recommended)
    ws.send(JSON.stringify({ type: 'subscribe_sandbox', project_id: 'proj-123' }));
    // Events arrive as: { type: 'sandbox_event', routing_key: 'sandbox:proj-123', data: {...} }
    ```

    Subscribes to sandbox lifecycle events (created, terminated, status)
    and service events (desktop_started, desktop_stopped, terminal_started, etc.).

    Query Parameters:
    - token: Legacy query-token authentication for existing SSE clients only
    - last_id: Last received event ID for resuming (default: "0")

    SSE Format:
    - Event type: "sandbox"
    - Data: JSON with "type", "data", "timestamp" fields
    - ID: Redis Stream message ID for reconnection resume

    Reconnection:
    - Save the last received `id` value
    - Reconnect with `last_id=<saved_id>` to resume from that point
    """
    # Authorize: caller must be a member of the project they want to stream.
    await assert_caller_owns_project(project_id=project_id, user=current_user, db=db)

    # Check if event bus is available before starting SSE stream
    if not event_publisher or not event_publisher._event_bus:
        logger.warning("[SandboxSSE] Event bus not available, returning 503")
        raise HTTPException(
            status_code=503,
            detail=_("Event streaming service temporarily unavailable. Redis event bus not configured."),
        )

    return StreamingResponse(
        sse_generator(project_id, last_id, event_publisher),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Deprecation": "true",
            "Sunset": "2026-06-01",
            "Link": '</api/v1/agent/ws>; rel="successor-version"',
        },
    )
