"""WebSocket manager initialization for startup."""

import logging

logger = logging.getLogger(__name__)


def initialize_websocket_manager() -> None:
    """Register WebSocket manager for lifecycle state notifications."""
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        get_connection_manager,
    )
    from src.infrastructure.agent.core.project_react_agent import (
        register_websocket_manager,
    )

    ws_manager = get_connection_manager()
    register_websocket_manager(ws_manager)
    logger.info("WebSocket manager registered for lifecycle state notifications")
