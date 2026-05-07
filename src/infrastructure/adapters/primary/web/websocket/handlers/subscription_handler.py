"""
Subscription Handlers for WebSocket

Handles subscribe and unsubscribe message types for conversation events.
"""

import asyncio
import logging
from typing import Any, override

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    stream_hitl_response_to_websocket,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext

logger = logging.getLogger(__name__)


def _is_valid_int_cursor(value: object) -> bool:
    """True only for real integers (exclude bool)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_terminal_event_type(event_type: object) -> bool:
    """Return True when event type is a terminal agent event."""
    if isinstance(event_type, str):
        return event_type in {"complete", "error", "cancelled"}
    enum_value = getattr(event_type, "value", None)
    return isinstance(enum_value, str) and enum_value in {"complete", "error", "cancelled"}


async def _resolve_recovery_cursor(
    context: MessageContext,
    conversation_id: str,
    running_message_id: str,
    requested_time_us: int | None,
    requested_counter: int | None,
) -> tuple[int | None, int | None]:
    """Resolve recovery cursor using client hint and latest persisted running-message event."""
    cursor_time_us = requested_time_us
    cursor_counter = requested_counter
    if cursor_time_us is not None and cursor_counter is None:
        cursor_counter = 0
    if cursor_time_us is not None:
        return cursor_time_us, cursor_counter

    container = context.get_scoped_container()
    event_repo = container.agent_execution_event_repository()
    if not event_repo:
        return cursor_time_us, cursor_counter

    message_events = await event_repo.get_events_by_message(conversation_id, running_message_id)
    db_time_us = 0
    db_counter = 0
    for event in message_events:
        if event.event_time_us > db_time_us or (
            event.event_time_us == db_time_us and event.event_counter > db_counter
        ):
            db_time_us = event.event_time_us
            db_counter = event.event_counter

    if db_time_us == 0 and db_counter == 0:
        return cursor_time_us, cursor_counter

    return db_time_us, db_counter


async def _is_active_running_message(
    context: MessageContext,
    conversation_id: str,
    message_id: str,
) -> bool:
    """Validate Redis running message id against persisted terminal events."""
    container = context.get_scoped_container()
    event_repo = container.agent_execution_event_repository()
    if not event_repo:
        return True

    try:
        events = await event_repo.get_events_by_message(conversation_id, message_id)
    except Exception:
        logger.exception(
            "[WS] Failed to validate running message state: conv=%s message_id=%s",
            conversation_id,
            message_id,
        )
        return False

    for event in reversed(events):
        if _is_terminal_event_type(event.event_type):
            logger.info(
                "[WS] Skip recovery bridge for stale running key: conv=%s message_id=%s "
                "(terminal event=%s)",
                conversation_id,
                message_id,
                event.event_type,
            )
            return False
    return True


async def _maybe_start_recovery_bridge(
    context: MessageContext,
    conversation_id: str,
    message: dict[str, Any],
) -> None:
    """Start a recovery bridge on subscribe when execution is still running."""
    try:
        container = context.get_scoped_container()
        redis_client = container.redis()
        running_message_id: str | None = None
        if redis_client:
            running_raw = await redis_client.get(f"agent:running:{conversation_id}")
            if isinstance(running_raw, bytes):
                running_message_id = running_raw.decode("utf-8")
            elif isinstance(running_raw, str):
                running_message_id = running_raw

        if not running_message_id:
            return

        if not await _is_active_running_message(context, conversation_id, running_message_id):
            return

        from_time_raw = message.get("from_time_us")
        from_counter_raw = message.get("from_counter")
        from_time_us = from_time_raw if _is_valid_int_cursor(from_time_raw) else None
        from_counter = from_counter_raw if _is_valid_int_cursor(from_counter_raw) else None

        cursor_time_us, cursor_counter = await _resolve_recovery_cursor(
            context=context,
            conversation_id=conversation_id,
            running_message_id=running_message_id,
            requested_time_us=from_time_us,
            requested_counter=from_counter,
        )

        async def _run_recovery_stream() -> None:
            from src.configuration.factories import create_llm_client

            llm = await create_llm_client(context.tenant_id)
            agent_service = container.agent_service(llm)
            await stream_hitl_response_to_websocket(
                agent_service=agent_service,
                session_id=context.session_id,
                conversation_id=conversation_id,
                message_id=running_message_id,
                replay_from_db=False,
                from_time_us=cursor_time_us,
                from_counter=cursor_counter,
            )

        started = await context.connection_manager.try_start_bridge_task(
            session_id=context.session_id,
            conversation_id=conversation_id,
            bridge_message_id=running_message_id,
            task_factory=lambda: asyncio.create_task(_run_recovery_stream()),
        )
        if started:
            logger.info(
                "[WS] Started recovery bridge on subscribe: conv=%s session=%s message_id=%s",
                conversation_id,
                context.session_id[:8],
                running_message_id,
            )
    except Exception:
        logger.exception(
            "[WS] Failed to start recovery bridge for conversation %s",
            conversation_id,
        )


class SubscribeHandler(WebSocketMessageHandler):
    """Handle subscribe: Subscribe to a conversation's events."""

    @property
    @override
    def message_type(self) -> str:
        return "subscribe"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle subscribe: Subscribe to a conversation's events."""
        conversation_id = message.get("conversation_id")

        if not conversation_id:
            await context.send_error("Missing conversation_id")
            return

        try:
            # Verify conversation ownership
            container = context.get_scoped_container()
            conversation_repo = container.conversation_repository()
            conversation = await conversation_repo.find_by_id(conversation_id)

            if not conversation:
                await context.send_error("Conversation not found", conversation_id=conversation_id)
                return

            if conversation.user_id != context.user_id:
                await context.send_error(
                    "You do not have permission to access this conversation",
                    conversation_id=conversation_id,
                )
                return

            await context.connection_manager.subscribe(context.session_id, conversation_id)
            await _maybe_start_recovery_bridge(
                context=context,
                conversation_id=conversation_id,
                message=message,
            )
            await context.send_ack("subscribe", conversation_id=conversation_id)

        except Exception:
            logger.exception(
                "[WS] Error subscribing",
                extra={
                    "session_id": context.session_id,
                    "conversation_id": conversation_id,
                    "user_id": context.user_id,
                },
            )
            await context.send_error(
                "Failed to subscribe (see server logs)",
                conversation_id=conversation_id,
            )


class UnsubscribeHandler(WebSocketMessageHandler):
    """Handle unsubscribe: Stop receiving events from a conversation."""

    @property
    @override
    def message_type(self) -> str:
        return "unsubscribe"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle unsubscribe: Stop receiving events from a conversation."""
        conversation_id = message.get("conversation_id")

        if not conversation_id:
            await context.send_error("Missing conversation_id")
            return

        await context.connection_manager.unsubscribe(context.session_id, conversation_id)
        await context.send_ack("unsubscribe", conversation_id=conversation_id)
