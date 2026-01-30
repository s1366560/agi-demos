"""
WebSocket Router for Agent Chat

Replaces SSE-based chat with bidirectional WebSocket communication.
Supports:
- Real-time message streaming
- Active stop/cancel signals
- Multi-conversation subscriptions
- Heartbeat/keepalive
- Multiple browser tabs per user (via session_id)
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Set

import orjson
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.auth_service_v2 import AuthService
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import UserTenant
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAlchemyAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlAlchemyUserRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent-websocket"])


class ConnectionManager:
    """
    Manages WebSocket connections for agent chat.

    Features:
    - Session-based connection management (supports multiple tabs per user)
    - User -> Sessions mapping for broadcasting
    - Subscription management (session -> conversation_ids)
    - Event routing by conversation_id
    - Project-scoped lifecycle state subscriptions
    """

    def __init__(self):
        # session_id -> WebSocket connection (supports multiple connections per user)
        self.active_connections: Dict[str, WebSocket] = {}
        # session_id -> user_id (reverse lookup)
        self.session_users: Dict[str, str] = {}
        # user_id -> set of session_ids (for sending to all user's sessions)
        self.user_sessions: Dict[str, Set[str]] = {}
        # session_id -> set of subscribed conversation_ids
        self.subscriptions: Dict[str, Set[str]] = {}
        # conversation_id -> set of session_ids (reverse index for broadcasting)
        self.conversation_subscribers: Dict[str, Set[str]] = {}
        # session_id -> {conversation_id -> asyncio.Task} (bridge tasks)
        self.bridge_tasks: Dict[str, Dict[str, asyncio.Task]] = {}
        # session_id -> {project_id -> asyncio.Task} (status monitoring tasks)
        self.status_tasks: Dict[str, Dict[str, asyncio.Task]] = {}
        # session_id -> set of subscribed project_ids for status updates
        self.status_subscriptions: Dict[str, Set[str]] = {}
        # tenant_id -> project_id -> set of session_ids (lifecycle state subscriptions)
        self.project_subscriptions: Dict[str, Dict[str, Set[str]]] = {}
        # session_id -> set of subscribed project_ids for lifecycle state
        self.session_project_subscriptions: Dict[str, Set[str]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, session_id: str, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection for a session."""
        await websocket.accept()
        async with self._lock:
            # Register the new session connection
            self.active_connections[session_id] = websocket
            self.session_users[session_id] = user_id
            self.subscriptions[session_id] = set()
            self.bridge_tasks[session_id] = {}

            # Track user's sessions
            if user_id not in self.user_sessions:
                self.user_sessions[user_id] = set()
            self.user_sessions[user_id].add(session_id)

        total_sessions = len(self.active_connections)
        user_session_count = len(self.user_sessions.get(user_id, set()))
        logger.info(
            f"[WS] User {user_id} session {session_id[:8]}... connected. "
            f"User sessions: {user_session_count}, Total: {total_sessions}"
        )

    async def disconnect(self, session_id: str) -> None:
        """Remove a WebSocket connection and clean up subscriptions for a session."""
        async with self._lock:
            user_id = self.session_users.get(session_id)

            # Cancel all bridge tasks for this session
            if session_id in self.bridge_tasks:
                for task in self.bridge_tasks[session_id].values():
                    task.cancel()
                del self.bridge_tasks[session_id]

            # Remove from conversation subscribers
            if session_id in self.subscriptions:
                for conv_id in self.subscriptions[session_id]:
                    if conv_id in self.conversation_subscribers:
                        self.conversation_subscribers[conv_id].discard(session_id)
                        if not self.conversation_subscribers[conv_id]:
                            del self.conversation_subscribers[conv_id]
                del self.subscriptions[session_id]

            # Remove session from user's session set
            if user_id and user_id in self.user_sessions:
                self.user_sessions[user_id].discard(session_id)
                if not self.user_sessions[user_id]:
                    del self.user_sessions[user_id]

            # Remove connection and session mappings
            self.active_connections.pop(session_id, None)
            self.session_users.pop(session_id, None)

        total_sessions = len(self.active_connections)
        logger.info(f"[WS] Session {session_id[:8]}... disconnected. Total: {total_sessions}")

    async def subscribe(self, session_id: str, conversation_id: str) -> None:
        """Subscribe a session to a conversation's events."""
        async with self._lock:
            if session_id not in self.subscriptions:
                self.subscriptions[session_id] = set()
            self.subscriptions[session_id].add(conversation_id)

            if conversation_id not in self.conversation_subscribers:
                self.conversation_subscribers[conversation_id] = set()
            self.conversation_subscribers[conversation_id].add(session_id)

        logger.debug(
            f"[WS] Session {session_id[:8]}... subscribed to conversation {conversation_id}"
        )

    async def unsubscribe(self, session_id: str, conversation_id: str) -> None:
        """Unsubscribe a session from a conversation's events."""
        async with self._lock:
            if session_id in self.subscriptions:
                self.subscriptions[session_id].discard(conversation_id)

            if conversation_id in self.conversation_subscribers:
                self.conversation_subscribers[conversation_id].discard(session_id)
                if not self.conversation_subscribers[conversation_id]:
                    del self.conversation_subscribers[conversation_id]

            # Cancel bridge task if exists
            if session_id in self.bridge_tasks and conversation_id in self.bridge_tasks[session_id]:
                self.bridge_tasks[session_id][conversation_id].cancel()
                del self.bridge_tasks[session_id][conversation_id]

        logger.debug(
            f"[WS] Session {session_id[:8]}... unsubscribed from conversation {conversation_id}"
        )

    def is_subscribed(self, session_id: str, conversation_id: str) -> bool:
        """Check if a session is subscribed to a conversation."""
        return conversation_id in self.subscriptions.get(session_id, set())

    async def send_to_session(self, session_id: str, message: Dict[str, Any]) -> bool:
        """Send a message to a specific session."""
        ws = self.active_connections.get(session_id)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.warning(f"[WS] Failed to send to session {session_id[:8]}...: {e}")
                return False
        return False

    async def send_to_user(self, user_id: str, message: Dict[str, Any]) -> int:
        """Send a message to all sessions of a specific user."""
        session_ids = self.user_sessions.get(user_id, set())
        sent_count = 0
        for session_id in session_ids:
            if await self.send_to_session(session_id, message):
                sent_count += 1
        return sent_count

    async def broadcast_to_conversation(self, conversation_id: str, message: Dict[str, Any]) -> int:
        """Broadcast a message to all sessions subscribed to a conversation."""
        subscribers = self.conversation_subscribers.get(conversation_id, set())
        sent_count = 0
        for session_id in subscribers:
            if await self.send_to_session(session_id, message):
                sent_count += 1
        return sent_count

    def get_connection(self, session_id: str) -> Optional[WebSocket]:
        """Get the WebSocket connection for a session."""
        return self.active_connections.get(session_id)

    def add_bridge_task(self, session_id: str, conversation_id: str, task: asyncio.Task) -> None:
        """Register a bridge task for a session's conversation."""
        if session_id not in self.bridge_tasks:
            self.bridge_tasks[session_id] = {}
        self.bridge_tasks[session_id][conversation_id] = task

    def get_user_id(self, session_id: str) -> Optional[str]:
        """Get the user_id for a session."""
        return self.session_users.get(session_id)

    async def subscribe_status(self, session_id: str, project_id: str, task: asyncio.Task) -> None:
        """Subscribe a session to status updates for a project."""
        async with self._lock:
            if session_id not in self.status_subscriptions:
                self.status_subscriptions[session_id] = set()
            self.status_subscriptions[session_id].add(project_id)
            
            if session_id not in self.status_tasks:
                self.status_tasks[session_id] = {}
            self.status_tasks[session_id][project_id] = task
        
        logger.debug(f"[WS] Session {session_id[:8]}... subscribed to status for project {project_id}")

    async def unsubscribe_status(self, session_id: str, project_id: str) -> None:
        """Unsubscribe a session from status updates for a project."""
        async with self._lock:
            if session_id in self.status_subscriptions:
                self.status_subscriptions[session_id].discard(project_id)

            if session_id in self.status_tasks and project_id in self.status_tasks[session_id]:
                self.status_tasks[session_id][project_id].cancel()
                del self.status_tasks[session_id][project_id]

        logger.debug(f"[WS] Session {session_id[:8]}... unsubscribed from status for project {project_id}")

    async def subscribe_lifecycle_state(
        self, session_id: str, tenant_id: str, project_id: str
    ) -> None:
        """Subscribe a session to lifecycle state updates for a project."""
        async with self._lock:
            # Initialize tenant dict if needed
            if tenant_id not in self.project_subscriptions:
                self.project_subscriptions[tenant_id] = {}

            # Initialize project set if needed
            if project_id not in self.project_subscriptions[tenant_id]:
                self.project_subscriptions[tenant_id][project_id] = set()

            # Add session to project subscriptions
            self.project_subscriptions[tenant_id][project_id].add(session_id)

            # Track session's project subscriptions
            if session_id not in self.session_project_subscriptions:
                self.session_project_subscriptions[session_id] = set()
            self.session_project_subscriptions[session_id].add((tenant_id, project_id))

        logger.debug(
            f"[WS] Session {session_id[:8]}... subscribed to lifecycle state "
            f"for tenant {tenant_id}, project {project_id}"
        )

    async def unsubscribe_lifecycle_state(
        self, session_id: str, tenant_id: str, project_id: str
    ) -> None:
        """Unsubscribe a session from lifecycle state updates for a project."""
        async with self._lock:
            # Remove from tenant/project subscriptions
            if (
                tenant_id in self.project_subscriptions
                and project_id in self.project_subscriptions[tenant_id]
            ):
                self.project_subscriptions[tenant_id][project_id].discard(session_id)
                if not self.project_subscriptions[tenant_id][project_id]:
                    del self.project_subscriptions[tenant_id][project_id]
                if not self.project_subscriptions[tenant_id]:
                    del self.project_subscriptions[tenant_id]

            # Remove from session's project subscriptions
            if session_id in self.session_project_subscriptions:
                self.session_project_subscriptions[session_id].discard(
                    (tenant_id, project_id)
                )
                if not self.session_project_subscriptions[session_id]:
                    del self.session_project_subscriptions[session_id]

        logger.debug(
            f"[WS] Session {session_id[:8]}... unsubscribed from lifecycle state "
            f"for tenant {tenant_id}, project {project_id}"
        )

    async def broadcast_to_project(
        self, tenant_id: str, project_id: str, message: Dict[str, Any]
    ) -> int:
        """
        Broadcast a message to all sessions subscribed to a project's lifecycle state.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier
            message: Message to broadcast

        Returns:
            Number of sessions notified
        """
        async with self._lock:
            subscribers = self.project_subscriptions.get(tenant_id, {}).get(
                project_id, set()
            ).copy()

        sent_count = 0
        for session_id in subscribers:
            if await self.send_to_session(session_id, message):
                sent_count += 1

        return sent_count

    async def disconnect(self, session_id: str) -> None:
        """Remove a WebSocket connection and clean up subscriptions for a session."""
        async with self._lock:
            user_id = self.session_users.get(session_id)

            # Cancel all bridge tasks for this session
            if session_id in self.bridge_tasks:
                for task in self.bridge_tasks[session_id].values():
                    task.cancel()
                del self.bridge_tasks[session_id]

            # Cancel all status monitoring tasks for this session
            if session_id in self.status_tasks:
                for task in self.status_tasks[session_id].values():
                    task.cancel()
                del self.status_tasks[session_id]

            # Remove status subscriptions
            if session_id in self.status_subscriptions:
                del self.status_subscriptions[session_id]

            # Remove lifecycle state subscriptions
            if session_id in self.session_project_subscriptions:
                for tenant_id, project_id in self.session_project_subscriptions[
                    session_id
                ]:
                    if (
                        tenant_id in self.project_subscriptions
                        and project_id in self.project_subscriptions[tenant_id]
                    ):
                        self.project_subscriptions[tenant_id][project_id].discard(
                            session_id
                        )
                        if not self.project_subscriptions[tenant_id][project_id]:
                            del self.project_subscriptions[tenant_id][project_id]
                        if not self.project_subscriptions[tenant_id]:
                            del self.project_subscriptions[tenant_id]
                del self.session_project_subscriptions[session_id]

            # Remove from conversation subscribers
            if session_id in self.subscriptions:
                for conv_id in self.subscriptions[session_id]:
                    if conv_id in self.conversation_subscribers:
                        self.conversation_subscribers[conv_id].discard(session_id)
                        if not self.conversation_subscribers[conv_id]:
                            del self.conversation_subscribers[conv_id]
                del self.subscriptions[session_id]

            # Remove session from user's session set
            if user_id and user_id in self.user_sessions:
                self.user_sessions[user_id].discard(session_id)
                if not self.user_sessions[user_id]:
                    del self.user_sessions[user_id]

            # Remove connection and session mappings
            self.active_connections.pop(session_id, None)
            self.session_users.pop(session_id, None)

        total_sessions = len(self.active_connections)
        logger.info(f"[WS] Session {session_id[:8]}... disconnected. Total: {total_sessions}")


# Global connection manager instance
manager = ConnectionManager()


async def authenticate_websocket(token: str, db: AsyncSession) -> Optional[tuple[str, str]]:
    """
    Authenticate WebSocket connection using API key.

    Args:
        token: API key token (format: ms_sk_xxx)
        db: Database session

    Returns:
        Tuple of (user_id, tenant_id) if authenticated, None otherwise
    """
    try:
        # Create AuthService with repositories
        auth_service = AuthService(
            user_repository=SqlAlchemyUserRepository(db),
            api_key_repository=SqlAlchemyAPIKeyRepository(db),
        )

        # Verify API key
        api_key = await auth_service.verify_api_key(token)
        if not api_key:
            return None

        # Get user
        user = await auth_service.get_user_by_id(api_key.user_id)
        if not user:
            return None

        # Get tenant_id from UserTenant table
        result = await db.execute(
            select(UserTenant.tenant_id).where(UserTenant.user_id == user.id).limit(1)
        )
        tenant_id = result.scalar_one_or_none()

        if not tenant_id:
            logger.warning(f"[WS] User {user.id} does not belong to any tenant")
            return None

        return (user.id, tenant_id)
    except Exception as e:
        logger.warning(f"[WS] Authentication failed: {e}")
        return None


def get_container_from_app(websocket: WebSocket) -> DIContainer:
    """Get the DI container from the FastAPI app state."""
    return websocket.app.state.container


@router.websocket("/ws")
async def agent_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="API key for authentication"),
    session_id: Optional[str] = Query(None, description="Client session ID for multi-tab support"),
    db: AsyncSession = Depends(get_db),
):
    """
    WebSocket endpoint for agent chat.

    Query Parameters:
    - token: API key for authentication (required)
    - session_id: Client-generated session ID for multi-tab support (optional, auto-generated if not provided)

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

    Server -> Client messages:
    - ack: Acknowledgment of client action
      {type: 'ack', action: str, conversation_id: str, ...}
    - pong: Response to heartbeat
      {type: 'pong', timestamp: str}
    - message: User/assistant message
      {type: 'message', conversation_id: str, data: {...}}
    - thought: Agent thinking
      {type: 'thought', conversation_id: str, data: {...}}
    - text_delta: Streaming text
      {type: 'text_delta', conversation_id: str, data: {...}}
    - ... (all SSE event types)
    - error: Error message
      {type: 'error', conversation_id: str, data: {message: str}}
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

    # Connect with session_id
    await manager.connect(user_id, session_id, websocket)

    try:
        # Send connection confirmation with session_id
        await websocket.send_json(
            {
                "type": "connected",
                "data": {
                    "user_id": user_id,
                    "session_id": session_id,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            }
        )

        # Message handling loop
        while True:
            try:
                data = await websocket.receive_json()
                await handle_client_message(
                    websocket=websocket,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    message=data,
                    db=db,
                )
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


async def handle_client_message(
    websocket: WebSocket,
    user_id: str,
    tenant_id: str,
    session_id: str,
    message: Dict[str, Any],
    db: AsyncSession,
) -> None:
    """
    Handle incoming client messages.

    Args:
        websocket: The WebSocket connection
        user_id: Authenticated user ID
        tenant_id: User's tenant ID
        session_id: Client session ID
        message: The received message
        db: Database session
    """
    msg_type = message.get("type")

    if msg_type == "heartbeat":
        await websocket.send_json(
            {
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    elif msg_type == "send_message":
        await handle_send_message(websocket, user_id, tenant_id, session_id, message, db)

    elif msg_type == "stop_session":
        await handle_stop_session(websocket, user_id, session_id, message, db)

    elif msg_type == "subscribe":
        await handle_subscribe(websocket, user_id, session_id, message, db)

    elif msg_type == "unsubscribe":
        await handle_unsubscribe(websocket, user_id, session_id, message)

    elif msg_type == "subscribe_status":
        await handle_subscribe_status(websocket, user_id, tenant_id, session_id, message)

    elif msg_type == "unsubscribe_status":
        await handle_unsubscribe_status(websocket, session_id, message)

    elif msg_type == "subscribe_lifecycle_state":
        await handle_subscribe_lifecycle_state(
            websocket, user_id, tenant_id, session_id, message
        )

    elif msg_type == "unsubscribe_lifecycle_state":
        await handle_unsubscribe_lifecycle_state(
            websocket, tenant_id, session_id, message
        )

    else:
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": f"Unknown message type: {msg_type}"},
            }
        )


async def handle_send_message(
    websocket: WebSocket,
    user_id: str,
    tenant_id: str,
    session_id: str,
    message: Dict[str, Any],
    db: AsyncSession,
) -> None:
    """
    Handle send_message: Start agent execution.

    This replaces the SSE POST /chat endpoint.
    """
    conversation_id = message.get("conversation_id")
    user_message = message.get("message")
    project_id = message.get("project_id")

    if not all([conversation_id, user_message, project_id]):
        await websocket.send_json(
            {
                "type": "error",
                "data": {
                    "message": "Missing required fields: conversation_id, message, project_id"
                },
            }
        )
        return

    try:
        base_container = get_container_from_app(websocket)
        container = base_container.with_db(db)

        # Verify conversation ownership
        conversation_repo = container.conversation_repository()
        conversation = await conversation_repo.find_by_id(conversation_id)

        if not conversation:
            await websocket.send_json(
                {
                    "type": "error",
                    "conversation_id": conversation_id,
                    "data": {"message": "Conversation not found"},
                }
            )
            return

        if conversation.user_id != user_id:
            await websocket.send_json(
                {
                    "type": "error",
                    "conversation_id": conversation_id,
                    "data": {"message": "You do not have permission to access this conversation"},
                }
            )
            return

        # Auto-subscribe this session to this conversation
        await manager.subscribe(session_id, conversation_id)

        # Create LLM and agent service
        from src.configuration.factories import create_langchain_llm

        llm = create_langchain_llm(tenant_id)
        agent_service = container.agent_service(llm)

        # Send acknowledgment
        await websocket.send_json(
            {
                "type": "ack",
                "action": "send_message",
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        # Start streaming in background task
        task = asyncio.create_task(
            stream_agent_to_websocket(
                agent_service=agent_service,
                websocket=websocket,
                user_id=user_id,
                session_id=session_id,
                conversation_id=conversation_id,
                user_message=user_message,
                project_id=project_id,
                tenant_id=tenant_id,
            )
        )
        manager.add_bridge_task(session_id, conversation_id, task)

    except Exception as e:
        logger.error(f"[WS] Error handling send_message: {e}", exc_info=True)
        await websocket.send_json(
            {
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": str(e)},
            }
        )


async def stream_agent_to_websocket(
    agent_service,
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    conversation_id: str,
    user_message: str,
    project_id: str,
    tenant_id: str,
) -> None:
    """
    Stream agent events to WebSocket.

    This is the bridge between the agent service and WebSocket.
    Events are broadcast to ALL sessions subscribed to this conversation,
    allowing multiple browser tabs to receive the same messages in real-time.
    """
    event_count = 0
    try:
        async for event in agent_service.stream_chat_v2(
            conversation_id=conversation_id,
            user_message=user_message,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ):
            event_count += 1
            event_type = event.get("type", "unknown")
            event_data = event.get("data", {})

            # DEBUG: Log every event received from agent_service
            logger.warning(
                f"[WS Bridge] Event #{event_count}: type={event_type}, conv={conversation_id}"
            )

            # Check if session is still subscribed
            if not manager.is_subscribed(session_id, conversation_id):
                logger.info(f"[WS] Session {session_id[:8]}... unsubscribed, stopping stream")
                break

            # Add conversation_id to event for routing
            ws_event = {
                "type": event.get("type"),
                "conversation_id": conversation_id,
                "data": event_data,
                "seq": event.get("id"),
                "timestamp": event.get("timestamp", datetime.utcnow().isoformat()),
            }

            # Broadcast to ALL sessions subscribed to this conversation
            # This enables multiple browser tabs to receive the same messages
            await manager.broadcast_to_conversation(conversation_id, ws_event)

    except asyncio.CancelledError:
        logger.info(f"[WS] Stream cancelled for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"[WS] Error streaming to websocket: {e}", exc_info=True)
        # Send error only to the initiating session
        await manager.send_to_session(
            session_id,
            {
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": str(e)},
            },
        )


async def handle_stop_session(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    message: Dict[str, Any],
    db: AsyncSession,
) -> None:
    """
    Handle stop_session: Cancel ongoing agent execution.

    This is a key advantage of WebSocket over SSE - bidirectional communication.
    """
    conversation_id = message.get("conversation_id")

    if not conversation_id:
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": "Missing conversation_id"},
            }
        )
        return

    try:
        # Cancel the bridge task if exists for this session
        if (
            session_id in manager.bridge_tasks
            and conversation_id in manager.bridge_tasks[session_id]
        ):
            task = manager.bridge_tasks[session_id][conversation_id]
            task.cancel()
            del manager.bridge_tasks[session_id][conversation_id]
            logger.info(f"[WS] Cancelled stream task for conversation {conversation_id}")

        # Cancel Temporal workflow
        try:
            from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory

            client = await TemporalClientFactory.get_client()

            # Find and cancel the running workflow
            # Workflow ID pattern: agent-execution-{conversation_id}-{message_id}
            # We need to find the most recent one
            async for workflow in client.list_workflows(
                query=f'WorkflowId STARTS_WITH "agent-execution-{conversation_id}-" AND ExecutionStatus = "Running"'
            ):
                await client.get_workflow_handle(workflow.id).cancel()
                logger.info(f"[WS] Cancelled Temporal workflow {workflow.id}")
                break
        except Exception as e:
            logger.warning(f"[WS] Failed to cancel Temporal workflow: {e}")

        # Send acknowledgment
        await websocket.send_json(
            {
                "type": "ack",
                "action": "stop_session",
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"[WS] Error stopping session: {e}", exc_info=True)
        await websocket.send_json(
            {
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": str(e)},
            }
        )


async def handle_subscribe(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    message: Dict[str, Any],
    db: AsyncSession,
) -> None:
    """
    Handle subscribe: Subscribe to a conversation's events.

    Useful for receiving events from conversations started elsewhere.
    """
    conversation_id = message.get("conversation_id")

    if not conversation_id:
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": "Missing conversation_id"},
            }
        )
        return

    try:
        # Verify conversation ownership
        base_container = get_container_from_app(websocket)
        container = base_container.with_db(db)
        conversation_repo = container.conversation_repository()
        conversation = await conversation_repo.find_by_id(conversation_id)

        if not conversation:
            await websocket.send_json(
                {
                    "type": "error",
                    "conversation_id": conversation_id,
                    "data": {"message": "Conversation not found"},
                }
            )
            return

        if conversation.user_id != user_id:
            await websocket.send_json(
                {
                    "type": "error",
                    "conversation_id": conversation_id,
                    "data": {"message": "You do not have permission to access this conversation"},
                }
            )
            return

        await manager.subscribe(session_id, conversation_id)

        await websocket.send_json(
            {
                "type": "ack",
                "action": "subscribe",
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"[WS] Error subscribing: {e}", exc_info=True)
        await websocket.send_json(
            {
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": str(e)},
            }
        )


async def handle_unsubscribe(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    message: Dict[str, Any],
) -> None:
    """Handle unsubscribe: Stop receiving events from a conversation."""
    conversation_id = message.get("conversation_id")

    if not conversation_id:
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": "Missing conversation_id"},
            }
        )
        return

    await manager.unsubscribe(session_id, conversation_id)

    await websocket.send_json(
        {
            "type": "ack",
            "action": "unsubscribe",
            "conversation_id": conversation_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


# Export manager for use in other modules
def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance."""
    return manager


async def handle_subscribe_status(
    websocket: WebSocket,
    user_id: str,
    tenant_id: str,
    session_id: str,
    message: Dict[str, Any],
) -> None:
    """
    Handle subscribe_status: Subscribe to Agent Session status updates.
    
    This enables real-time status bar updates via WebSocket.
    """
    project_id = message.get("project_id")
    polling_interval = message.get("polling_interval", 3000)  # Default 3 seconds

    if not project_id:
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": "Missing project_id"},
            }
        )
        return

    try:
        # Start status monitoring task
        task = asyncio.create_task(
            monitor_agent_status(
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                project_id=project_id,
                polling_interval_ms=polling_interval,
            )
        )
        
        await manager.subscribe_status(session_id, project_id, task)

        await websocket.send_json(
            {
                "type": "ack",
                "action": "subscribe_status",
                "project_id": project_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"[WS] Error subscribing to status: {e}", exc_info=True)
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": str(e)},
            }
        )


async def handle_unsubscribe_status(
    websocket: WebSocket,
    session_id: str,
    message: Dict[str, Any],
) -> None:
    """Handle unsubscribe_status: Stop receiving status updates for a project."""
    project_id = message.get("project_id")

    if not project_id:
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": "Missing project_id"},
            }
        )
        return

    await manager.unsubscribe_status(session_id, project_id)

    await websocket.send_json(
        {
            "type": "ack",
            "action": "unsubscribe_status",
            "project_id": project_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


async def handle_subscribe_lifecycle_state(
    websocket: WebSocket,
    user_id: str,
    tenant_id: str,
    session_id: str,
    message: Dict[str, Any],
) -> None:
    """
    Handle subscribe_lifecycle_state: Subscribe to agent lifecycle state updates.

    This enables real-time lifecycle state bar updates via WebSocket.
    """
    project_id = message.get("project_id")

    if not project_id:
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": "Missing project_id"},
            }
        )
        return

    try:
        # Subscribe to lifecycle state updates for this project
        await manager.subscribe_lifecycle_state(session_id, tenant_id, project_id)

        await websocket.send_json(
            {
                "type": "ack",
                "action": "subscribe_lifecycle_state",
                "project_id": project_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"[WS] Error subscribing to lifecycle state: {e}", exc_info=True)
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": str(e)},
            }
        )


async def handle_unsubscribe_lifecycle_state(
    websocket: WebSocket,
    tenant_id: str,
    session_id: str,
    message: Dict[str, Any],
) -> None:
    """Handle unsubscribe_lifecycle_state: Stop receiving lifecycle state updates."""
    project_id = message.get("project_id")

    if not project_id:
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": "Missing project_id"},
            }
        )
        return

    await manager.unsubscribe_lifecycle_state(session_id, tenant_id, project_id)

    await websocket.send_json(
        {
            "type": "ack",
            "action": "unsubscribe_lifecycle_state",
            "project_id": project_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


async def monitor_agent_status(
    session_id: str,
    user_id: str,
    tenant_id: str,
    project_id: str,
    polling_interval_ms: int = 3000,
) -> None:
    """
    Monitor Agent Session status and push updates via WebSocket.
    
    This runs as a background task and periodically queries the Temporal
    workflow status, sending updates to the client when status changes.
    """
    from src.infrastructure.adapters.secondary.temporal.client import (
        TemporalClientFactory,
    )
    from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
        AgentSessionStatus,
        get_agent_session_workflow_id,
    )

    workflow_id = get_agent_session_workflow_id(
        tenant_id=tenant_id,
        project_id=project_id,
        agent_mode="default",
    )

    last_status = None
    
    try:
        while True:
            try:
                # Check if still subscribed
                if session_id not in manager.status_subscriptions:
                    logger.debug(f"[WS Status] Session {session_id[:8]}... not in status_subscriptions")
                    break
                if project_id not in manager.status_subscriptions.get(session_id, set()):
                    logger.debug(f"[WS Status] Project {project_id} not in session {session_id[:8]}... subscriptions")
                    break

                # Query Temporal for status
                temporal_client = await TemporalClientFactory.get_client()
                status_data = {
                    "is_initialized": False,
                    "is_active": False,
                    "total_chats": 0,
                    "active_chats": 0,
                    "tool_count": 0,
                    "workflow_id": workflow_id,
                }

                if temporal_client:
                    try:
                        handle = temporal_client.get_workflow_handle(workflow_id)
                        status: AgentSessionStatus = await handle.query("get_status")
                        status_data = {
                            "is_initialized": status.is_initialized,
                            "is_active": status.is_active,
                            "total_chats": status.total_chats,
                            "active_chats": status.active_chats,
                            "tool_count": status.tool_count,
                            "cached_since": status.cached_since,
                            "workflow_id": workflow_id,
                        }
                    except Exception:
                        # Workflow not found, return default (uninitialized) status
                        pass

                # Only send if status changed
                if status_data != last_status:
                    await manager.send_to_session(
                        session_id,
                        {
                            "type": "status_update",
                            "project_id": project_id,
                            "data": status_data,
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )
                    last_status = status_data

            except Exception as e:
                logger.warning(f"[WS Status] Error monitoring status: {e}")

            # Wait before next poll
            await asyncio.sleep(polling_interval_ms / 1000)

    except asyncio.CancelledError:
        logger.debug(f"[WS Status] Monitor cancelled for project {project_id}")
    except Exception as e:
        logger.error(f"[WS Status] Unexpected error: {e}", exc_info=True)
