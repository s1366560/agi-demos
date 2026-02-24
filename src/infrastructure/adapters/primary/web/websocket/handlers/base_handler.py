"""
Base Handler for WebSocket Messages

Defines the abstract interface for WebSocket message handlers.
"""

from abc import ABC, abstractmethod
from typing import Any

from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext


class WebSocketMessageHandler(ABC):
    """
    Abstract base class for WebSocket message handlers.

    Each handler is responsible for processing a specific message type.

    Usage:
        class MyHandler(WebSocketMessageHandler):
            @property
            def message_type(self) -> str:
                return "my_message"

            async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
                # Process the message
                pass
    """

    @property
    @abstractmethod
    def message_type(self) -> str:
        """
        The message type this handler processes.

        Returns:
            The message type string (e.g., 'send_message', 'subscribe')
        """
        pass

    @abstractmethod
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """
        Handle the message.

        Args:
            context: Message context with access to websocket, db, container, etc.
            message: The raw message dict received from the client

        Raises:
            Any exception will be caught by the router and sent as an error to the client.
        """
        pass
