"""
WebSocket Module for Agent Chat

This module provides WebSocket infrastructure for real-time agent communication:
- Connection management with multi-tab support
- Message routing via handler pattern
- Event dispatching with backpressure handling
- Authentication and authorization
"""

from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
    ConnectionManager,
    get_connection_manager,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import (
    MessageContext,
)
from src.infrastructure.adapters.primary.web.websocket.message_router import (
    MessageRouter,
    get_message_router,
)
from src.infrastructure.adapters.primary.web.websocket.router import router

__all__ = [
    "ConnectionManager",
    "MessageContext",
    "MessageRouter",
    "get_connection_manager",
    "get_message_router",
    "router",
]
