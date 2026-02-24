"""
WebSocket Router for Agent Chat

Main FastAPI router for WebSocket connections.
Replaces SSE-based chat with bidirectional WebSocket communication.

Features:
- Real-time message streaming
- Active stop/cancel signals
- Multi-conversation subscriptions
- Heartbeat/keepalive
- Multiple browser tabs per user (via session_id)
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import orjson
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.routers.event_dispatcher import (
    get_dispatcher_manager,
)
from src.infrastructure.adapters.primary.web.websocket.auth import authenticate_websocket
from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
    get_connection_manager,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.primary.web.websocket.message_router import get_message_router
from src.infrastructure.adapters.secondary.persistence.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent-websocket"])


def get_container_from_app(websocket: WebSocket) -> DIContainer:
    """Get the DI container from the FastAPI app state."""
    return websocket.app.state.container


@router.websocket("/ws")
async def agent_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="API key for authentication"),
    session_id: str | None = Query(
        None, description="Client session ID for multi-tab support"
    ),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    WebSocket endpoint for agent chat.

    Query Parameters:
    - token: API key for authentication (required)
    - session_id: Client-generated session ID for multi-tab support
      (optional, auto-generated if not provided)

    Protocol:

    Client -> Server messages:
    - send_message: Start a new agent execution
      {type: 'send_message', conversation_id: str, message: str, project_id: str}
    - stop_session: Stop an ongoing agent execution
      {type: 'stop_session', conversation_id: str}
    - subscribe: Subscribe to a conversation's events
      {type: 'subscribe', conversation_id: str}
    - unsubscribe: Unsubscribe from a conversation
      {type: 'unsubscribe', conversation_id: str}
    - heartbeat: Keep connection alive
      {type: 'heartbeat'}
    - subscribe_status: Subscribe to agent status updates
      {type: 'subscribe_status', project_id: str}
    - unsubscribe_status: Unsubscribe from status updates
      {type: 'unsubscribe_status', project_id: str}
    - subscribe_lifecycle_state: Subscribe to lifecycle state
      {type: 'subscribe_lifecycle_state', project_id: str}
    - unsubscribe_lifecycle_state: Unsubscribe from lifecycle state
      {type: 'unsubscribe_lifecycle_state', project_id: str}
    - subscribe_sandbox: Subscribe to sandbox events (unified WebSocket)
      {type: 'subscribe_sandbox', project_id: str}
    - unsubscribe_sandbox: Unsubscribe from sandbox events
      {type: 'unsubscribe_sandbox', project_id: str}
    - start_agent: Start agent workflow
      {type: 'start_agent', project_id: str}
    - stop_agent: Stop agent workflow
      {type: 'stop_agent', project_id: str}
    - restart_agent: Restart agent workflow
      {type: 'restart_agent', project_id: str}
    - clarification_respond: Respond to clarification request
      {type: 'clarification_respond', request_id: str, answer: str}
    - decision_respond: Respond to decision request
      {type: 'decision_respond', request_id: str, decision: str}
    - env_var_respond: Provide environment variable values
      {type: 'env_var_respond', request_id: str, values: dict}

    Server -> Client messages:
    - connected: Connection confirmation
      {type: 'connected', data: {user_id, session_id, timestamp}}
    - ack: Acknowledgment of client action
      {type: 'ack', action: str, ...}
    - pong: Response to heartbeat
      {type: 'pong', timestamp: str}
    - message: User/assistant message
      {type: 'message', conversation_id: str, data: {...}}
    - thought: Agent thinking
      {type: 'thought', conversation_id: str, data: {...}}
    - text_delta: Streaming text
      {type: 'text_delta', conversation_id: str, data: {...}}
    - error: Error message
      {type: 'error', data: {message: str}}
    - status_update: Agent status update
      {type: 'status_update', project_id: str, data: {...}}
    - lifecycle_state_change: Agent lifecycle state change
      {type: 'lifecycle_state_change', project_id: str, data: {...}}
    - agent_lifecycle_ack: Agent lifecycle action acknowledgment
      {type: 'agent_lifecycle_ack', action: str, project_id: str, status: str}
    - sandbox_event: Sandbox lifecycle/service event (unified WebSocket)
      {type: 'sandbox_event', routing_key: str, project_id: str, data: {...}}
    """
    # Authenticate
    auth_result = await authenticate_websocket(token, db)
    if not auth_result:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    user_id, tenant_id = auth_result

    # Generate session_id if not provided (for backward compatibility)
    if not session_id:
        session_id = str(uuid.uuid4())

    # Get connection manager and message router
    manager = get_connection_manager()
    message_router = get_message_router()

    # Connect with session_id
    await manager.connect(user_id, session_id, websocket)

    # Get DI container
    base_container = get_container_from_app(websocket)
    container = base_container.with_db(db)

    try:
        # Send connection confirmation with session_id
        await websocket.send_json(
            {
                "type": "connected",
                "data": {
                    "user_id": user_id,
                    "session_id": session_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            }
        )

        # Create message context
        context = MessageContext(
            websocket=websocket,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            db=db,
            container=container,
        )

        # Message handling loop
        while True:
            try:
                data = await websocket.receive_json()
                await message_router.route(context, data)
            except orjson.JSONDecodeError as e:
                logger.warning(f"[WS] Invalid JSON from session {session_id[:8]}...: {e}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {"message": "Invalid JSON format"},
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"[WS] Session {session_id[:8]}... disconnected normally")
    except Exception as e:
        logger.error(f"[WS] Error for session {session_id[:8]}...: {e}", exc_info=True)
    finally:
        await manager.disconnect(session_id)


@router.get("/dispatcher-stats")
async def get_dispatcher_stats() -> dict[str, Any]:
    """
    Get event dispatcher statistics.

    Returns queue sizes, drop counts, and other metrics for monitoring
    the async event delivery system.
    """
    return get_dispatcher_manager().get_all_stats()


# =============================================================================
# Backward Compatibility Exports
# =============================================================================

# Export manager for use in other modules (e.g., websocket_notifier.py)
def get_ws_connection_manager():
    """Get the global connection manager instance for external use."""
    return get_connection_manager()
