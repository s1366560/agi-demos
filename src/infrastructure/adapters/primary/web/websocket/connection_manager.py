"""
WebSocket Connection Manager

Manages WebSocket connections for agent chat with support for:
- Session-based connection management (multiple tabs per user)
- User -> Sessions mapping for broadcasting
- Subscription management (session -> conversation_ids)
- Event routing by conversation_id
- Project-scoped lifecycle state subscriptions
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from src.infrastructure.adapters.primary.web.routers.event_dispatcher import (
    DispatcherManager,
    get_dispatcher_manager,
)

logger = logging.getLogger(__name__)


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

    def __init__(self, dispatcher_manager: DispatcherManager | None = None) -> None:
        # session_id -> WebSocket connection (supports multiple connections per user)
        self.active_connections: dict[str, WebSocket] = {}
        # session_id -> user_id (reverse lookup)
        self.session_users: dict[str, str] = {}
        # user_id -> set of session_ids (for sending to all user's sessions)
        self.user_sessions: dict[str, set[str]] = {}
        # session_id -> set of subscribed conversation_ids
        self.subscriptions: dict[str, set[str]] = {}
        # conversation_id -> set of session_ids (reverse index for broadcasting)
        self.conversation_subscribers: dict[str, set[str]] = {}
        # session_id -> {conversation_id -> asyncio.Task} (bridge tasks)
        self.bridge_tasks: dict[str, dict[str, asyncio.Task[None]]] = {}
        # session_id -> {project_id -> asyncio.Task} (status monitoring tasks)
        self.status_tasks: dict[str, dict[str, asyncio.Task[None]]] = {}
        # session_id -> set of subscribed project_ids for status updates
        self.status_subscriptions: dict[str, set[str]] = {}
        # tenant_id -> project_id -> set of session_ids (lifecycle state subscriptions)
        self.project_subscriptions: dict[str, dict[str, set[str]]] = {}
        # session_id -> set of subscribed project_ids for lifecycle state
        self.session_project_subscriptions: dict[str, set[tuple[str, str]]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
        # Strong references to in-flight cleanup tasks scheduled from sync
        # paths (e.g. ``send_to_session`` failure). Without this set the
        # tasks could be garbage-collected mid-execution.
        self._pending_cleanup_tasks: set[asyncio.Task[None]] = set()
        # Event dispatcher manager for async event delivery
        self.dispatcher_manager: DispatcherManager = dispatcher_manager or get_dispatcher_manager()

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
        """Clean up a disconnected session."""
        # Cancel and collect tasks under the lock, then await them outside
        # the lock so that bridge/status coroutines can run their cleanup
        # (which may need to acquire `_lock`) without deadlocking.
        async with self._lock:
            user_id = self.session_users.get(session_id)
            cancelled_tasks = self._cancel_session_tasks(session_id)
            self.status_subscriptions.pop(session_id, None)
            self._remove_project_subscriptions(session_id)
            self._remove_conversation_subscriptions(session_id)
            self._remove_user_session(user_id, session_id)
            self.active_connections.pop(session_id, None)
            self.session_users.pop(session_id, None)

        # Await cancellation outside the lock. ``return_exceptions=True``
        # ensures one misbehaving task does not break cleanup of others;
        # CancelledError is the normal outcome here and is suppressed.
        if cancelled_tasks:
            try:
                await asyncio.gather(*cancelled_tasks, return_exceptions=True)
            except Exception:
                logger.exception(
                    "[WS] Error awaiting cancelled tasks during disconnect",
                    extra={"session_id": session_id},
                )

        await self.dispatcher_manager.cleanup_session(session_id)
        total_sessions = len(self.active_connections)
        logger.info(f"[WS] Session {session_id[:8]}... disconnected. Total: {total_sessions}")

    def _cancel_session_tasks(self, session_id: str) -> list[asyncio.Task[None]]:
        """Cancel bridge and status monitoring tasks for a session.

        Returns the list of cancelled tasks so the caller can await them
        outside the lock.
        """
        cancelled: list[asyncio.Task[None]] = []
        for task_dict_name in ("bridge_tasks", "status_tasks"):
            task_dict = getattr(self, task_dict_name)
            if session_id in task_dict:
                for task in task_dict[session_id].values():
                    if not task.done():
                        task.cancel()
                        cancelled.append(task)
                del task_dict[session_id]
        return cancelled

    def _remove_project_subscriptions(self, session_id: str) -> None:
        """Remove lifecycle state subscriptions for a session."""
        subscriptions = self.session_project_subscriptions.pop(session_id, set())
        if not subscriptions:
            return
        for tenant_id, project_id in subscriptions:
            tenant_subs = self.project_subscriptions.get(tenant_id, {})
            if project_id in tenant_subs:
                tenant_subs[project_id].discard(session_id)
                if not tenant_subs[project_id]:
                    del tenant_subs[project_id]
                if not tenant_subs:
                    self.project_subscriptions.pop(tenant_id, None)

    def _remove_conversation_subscriptions(self, session_id: str) -> None:
        """Remove conversation subscriptions for a session."""
        subscriptions = self.subscriptions.pop(session_id, set())
        if not subscriptions:
            return
        for conv_id in subscriptions:
            if conv_id in self.conversation_subscribers:
                self.conversation_subscribers[conv_id].discard(session_id)
                if not self.conversation_subscribers[conv_id]:
                    del self.conversation_subscribers[conv_id]

    def _remove_user_session(self, user_id: str | None, session_id: str) -> None:
        """Remove session from user's session set."""
        if not user_id or user_id not in self.user_sessions:
            return
        self.user_sessions[user_id].discard(session_id)
        if not self.user_sessions[user_id]:
            del self.user_sessions[user_id]

    # ==========================================================================
    # Conversation Subscriptions
    # ==========================================================================

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

    # ==========================================================================
    # Message Sending
    # ==========================================================================

    async def send_to_session(self, session_id: str, message: dict[str, Any]) -> bool:
        """Send a message to a specific session.

        On send failure the dead session is scheduled for cleanup so we don't
        accumulate stale entries in ``active_connections`` / subscriptions.
        """
        ws = self.active_connections.get(session_id)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.warning(f"[WS] Failed to send to session {session_id[:8]}...: {e}")
                # Schedule async cleanup; do not block caller and do not raise.
                # Store reference to the cleanup task so it doesn't get GC'd
                # mid-execution. We intentionally don't await it.
                try:
                    cleanup_task = asyncio.create_task(self.disconnect(session_id))
                    self._pending_cleanup_tasks.add(cleanup_task)
                    cleanup_task.add_done_callback(self._pending_cleanup_tasks.discard)
                except RuntimeError:
                    # No running loop (e.g. shutdown) — best-effort silent drop.
                    pass
                return False
        return False

    async def send_to_user(self, user_id: str, message: dict[str, Any]) -> int:
        """Send a message to all sessions of a specific user."""
        async with self._lock:
            session_ids = list(self.user_sessions.get(user_id, set()))
        sent_count = 0
        for session_id in session_ids:
            if await self.send_to_session(session_id, message):
                sent_count += 1
        return sent_count

    async def broadcast_to_conversation(self, conversation_id: str, message: dict[str, Any]) -> int:
        """
        Broadcast a message to all sessions subscribed to a conversation.

        Uses EventDispatcher for async, non-blocking event delivery with
        backpressure handling and priority queuing.
        """
        # Snapshot subscriber set + their websockets under the lock to avoid
        # "set changed size during iteration" when concurrent disconnect /
        # unsubscribe mutate ``conversation_subscribers``.
        async with self._lock:
            subscribers = list(self.conversation_subscribers.get(conversation_id, set()))
            ws_by_session = {
                sid: self.active_connections.get(sid)
                for sid in subscribers
                if sid in self.active_connections
            }

        enqueued_count = 0
        for session_id, ws in ws_by_session.items():
            if ws is None:
                continue
            dispatcher = await self.dispatcher_manager.get_dispatcher(session_id, ws)
            if await dispatcher.enqueue(message):
                enqueued_count += 1

        return enqueued_count

    # ==========================================================================
    # Lifecycle State Subscriptions
    # ==========================================================================

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
                self.session_project_subscriptions[session_id].discard((tenant_id, project_id))
                if not self.session_project_subscriptions[session_id]:
                    del self.session_project_subscriptions[session_id]

        logger.debug(
            f"[WS] Session {session_id[:8]}... unsubscribed from lifecycle state "
            f"for tenant {tenant_id}, project {project_id}"
        )

    async def broadcast_to_project(
        self, tenant_id: str, project_id: str, message: dict[str, Any]
    ) -> int:
        """Broadcast a message to all sessions subscribed to a project's lifecycle state."""
        async with self._lock:
            subscribers = (
                self.project_subscriptions.get(tenant_id, {}).get(project_id, set()).copy()
            )

        sent_count = 0
        for session_id in subscribers:
            if await self.send_to_session(session_id, message):
                sent_count += 1

        return sent_count

    async def broadcast_lifecycle_state(
        self, tenant_id: str, project_id: str, state: dict[str, Any]
    ) -> int:
        """Broadcast lifecycle state change to all sessions subscribed to a project."""
        message = {
            "type": "lifecycle_state_change",
            "project_id": project_id,
            "data": state,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return await self.broadcast_to_project(tenant_id, project_id, message)

    async def broadcast_sandbox_state(
        self, tenant_id: str, project_id: str, state: dict[str, Any]
    ) -> int:
        """Broadcast sandbox state change to all sessions subscribed to a project."""
        message = {
            "type": "sandbox_state_change",
            "project_id": project_id,
            "data": state,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return await self.broadcast_to_project(tenant_id, project_id, message)

    # ==========================================================================
    # Status Subscriptions
    # ==========================================================================

    async def subscribe_status(
        self, session_id: str, project_id: str, task: asyncio.Task[None]
    ) -> None:
        """Subscribe a session to status updates for a project."""
        async with self._lock:
            if session_id not in self.status_subscriptions:
                self.status_subscriptions[session_id] = set()
            self.status_subscriptions[session_id].add(project_id)

            if session_id not in self.status_tasks:
                self.status_tasks[session_id] = {}
            self.status_tasks[session_id][project_id] = task

        logger.debug(
            f"[WS] Session {session_id[:8]}... subscribed to status for project {project_id}"
        )

    async def unsubscribe_status(self, session_id: str, project_id: str) -> None:
        """Unsubscribe a session from status updates for a project."""
        async with self._lock:
            if session_id in self.status_subscriptions:
                self.status_subscriptions[session_id].discard(project_id)

            if session_id in self.status_tasks and project_id in self.status_tasks[session_id]:
                self.status_tasks[session_id][project_id].cancel()
                del self.status_tasks[session_id][project_id]

        logger.debug(
            f"[WS] Session {session_id[:8]}... unsubscribed from status for project {project_id}"
        )

    # ==========================================================================
    # Bridge Task Management
    # ==========================================================================

    def get_connection(self, session_id: str) -> WebSocket | None:
        """Get the WebSocket connection for a session."""
        return self.active_connections.get(session_id)

    def add_bridge_task(
        self, session_id: str, conversation_id: str, task: asyncio.Task[None]
    ) -> None:
        """Register a bridge task for a session's conversation."""
        if session_id not in self.bridge_tasks:
            self.bridge_tasks[session_id] = {}

        # Cancel existing task if present
        existing_task = self.bridge_tasks[session_id].get(conversation_id)
        if existing_task and not existing_task.done():
            logger.info(
                f"[WS] Cancelling existing bridge task for session {session_id[:8]}... "
                f"conversation {conversation_id}"
            )
            existing_task.cancel()

        self.bridge_tasks[session_id][conversation_id] = task

    async def try_start_bridge_task(
        self,
        session_id: str,
        conversation_id: str,
        task_factory: Callable[[], asyncio.Task[None]],
        *,
        bridge_message_id: str | None = None,
    ) -> bool:
        """Atomically start/register bridge task when no compatible active bridge exists."""
        async with self._lock:
            # Session may have disconnected between subscribe and recovery bridge startup.
            if session_id not in self.active_connections:
                return False
            if conversation_id not in self.subscriptions.get(session_id, set()):
                return False

            for existing_session_id, task_map in self.bridge_tasks.items():
                task = task_map.get(conversation_id)
                if not task or task.done():
                    continue
                existing_message_id = getattr(task, "_bridge_message_id", None)
                if (
                    bridge_message_id
                    and isinstance(existing_message_id, str)
                    and existing_message_id != bridge_message_id
                ):
                    logger.info(
                        f"[WS] Replacing stale bridge task for conversation {conversation_id}: "
                        f"old_session={existing_session_id[:8]}..., "
                        f"old_message_id={existing_message_id}, "
                        f"new_message_id={bridge_message_id}"
                    )
                    task.cancel()
                    del task_map[conversation_id]
                    continue
                return False

            if session_id not in self.bridge_tasks:
                self.bridge_tasks[session_id] = {}

            existing_task = self.bridge_tasks[session_id].get(conversation_id)
            if existing_task and not existing_task.done():
                logger.info(
                    f"[WS] Cancelling existing bridge task for session {session_id[:8]}... "
                    f"conversation {conversation_id}"
                )
                existing_task.cancel()

            new_task = task_factory()
            if bridge_message_id:
                new_task._bridge_message_id = bridge_message_id  # type: ignore[attr-defined]
            self.bridge_tasks[session_id][conversation_id] = new_task
            return True

    def get_user_id(self, session_id: str) -> str | None:
        """Get the user_id for a session."""
        return self.session_users.get(session_id)


# Global connection manager instance
_connection_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager
