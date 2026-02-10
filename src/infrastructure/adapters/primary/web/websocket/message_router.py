"""
WebSocket Message Router

Routes incoming WebSocket messages to appropriate handlers based on message type.
Uses the handler pattern for clean separation of concerns.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext

logger = logging.getLogger(__name__)


class MessageRouter:
    """
    Routes WebSocket messages to registered handlers.

    Usage:
        router = MessageRouter()
        router.register(SendMessageHandler())
        router.register(SubscribeHandler())

        # In WebSocket endpoint
        await router.route(context, message)
    """

    def __init__(self):
        self._handlers: Dict[str, WebSocketMessageHandler] = {}

    def register(self, handler: WebSocketMessageHandler) -> "MessageRouter":
        """
        Register a message handler.

        Args:
            handler: The handler to register

        Returns:
            Self for chaining
        """
        self._handlers[handler.message_type] = handler
        logger.debug(f"[WS Router] Registered handler for message type: {handler.message_type}")
        return self

    def register_all(self, handlers: list[WebSocketMessageHandler]) -> "MessageRouter":
        """
        Register multiple handlers.

        Args:
            handlers: List of handlers to register

        Returns:
            Self for chaining
        """
        for handler in handlers:
            self.register(handler)
        return self

    async def route(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """
        Route a message to the appropriate handler.

        Args:
            context: Message context
            message: The raw message dict
        """
        msg_type = message.get("type")

        if not msg_type:
            await context.send_error("Missing message type")
            return

        # Handle heartbeat directly (no handler needed)
        if msg_type == "heartbeat":
            await context.send_json(
                {
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            return

        # Find and execute handler
        handler = self._handlers.get(msg_type)
        if handler:
            try:
                await handler.handle(context, message)
            except Exception as e:
                logger.error(
                    f"[WS Router] Error in handler for {msg_type}: {e}", exc_info=True
                )
                await context.send_error(f"Handler error: {str(e)}")
        else:
            await context.send_error(f"Unknown message type: {msg_type}")

    @property
    def registered_types(self) -> list[str]:
        """Get list of registered message types."""
        return list(self._handlers.keys())


# Global router instance with default handlers
_message_router: Optional[MessageRouter] = None


def get_message_router() -> MessageRouter:
    """
    Get the global message router with all handlers registered.

    Returns:
        Configured MessageRouter instance
    """
    global _message_router
    if _message_router is None:
        from src.infrastructure.adapters.primary.web.websocket.handlers import (
            ClarificationRespondHandler,
            DecisionRespondHandler,
            EnvVarRespondHandler,
            PermissionRespondHandler,
            RestartAgentHandler,
            SendMessageHandler,
            StartAgentHandler,
            StopAgentHandler,
            StopSessionHandler,
            SubscribeHandler,
            SubscribeLifecycleStateHandler,
            SubscribeSandboxHandler,
            SubscribeStatusHandler,
            UnsubscribeHandler,
            UnsubscribeLifecycleStateHandler,
            UnsubscribeSandboxHandler,
            UnsubscribeStatusHandler,
        )

        _message_router = MessageRouter()
        _message_router.register_all(
            [
                # Chat
                SendMessageHandler(),
                StopSessionHandler(),
                # Subscription
                SubscribeHandler(),
                UnsubscribeHandler(),
                # Status
                SubscribeStatusHandler(),
                UnsubscribeStatusHandler(),
                # Lifecycle
                SubscribeLifecycleStateHandler(),
                UnsubscribeLifecycleStateHandler(),
                StartAgentHandler(),
                StopAgentHandler(),
                RestartAgentHandler(),
                # Sandbox
                SubscribeSandboxHandler(),
                UnsubscribeSandboxHandler(),
                # HITL
                ClarificationRespondHandler(),
                DecisionRespondHandler(),
                EnvVarRespondHandler(),
                PermissionRespondHandler(),
            ]
        )
        logger.info(
            f"[WS Router] Initialized with {len(_message_router.registered_types)} handlers: "
            f"{_message_router.registered_types}"
        )

    return _message_router
