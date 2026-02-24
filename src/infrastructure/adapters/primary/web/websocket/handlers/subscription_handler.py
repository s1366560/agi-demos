"""
Subscription Handlers for WebSocket

Handles subscribe and unsubscribe message types for conversation events.
"""

import logging
from typing import Any

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext

logger = logging.getLogger(__name__)


class SubscribeHandler(WebSocketMessageHandler):
    """Handle subscribe: Subscribe to a conversation's events."""

    @property
    def message_type(self) -> str:
        return "subscribe"

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
            await context.send_ack("subscribe", conversation_id=conversation_id)

        except Exception as e:
            logger.error(f"[WS] Error subscribing: {e}", exc_info=True)
            await context.send_error(str(e), conversation_id=conversation_id)


class UnsubscribeHandler(WebSocketMessageHandler):
    """Handle unsubscribe: Stop receiving events from a conversation."""

    @property
    def message_type(self) -> str:
        return "unsubscribe"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle unsubscribe: Stop receiving events from a conversation."""
        conversation_id = message.get("conversation_id")

        if not conversation_id:
            await context.send_error("Missing conversation_id")
            return

        await context.connection_manager.unsubscribe(context.session_id, conversation_id)
        await context.send_ack("unsubscribe", conversation_id=conversation_id)
