"""
WebSocket Router for Agent Chat - Backward Compatibility Layer

This module provides backward compatibility for imports from the old location.
The actual implementation has been moved to:
    src/infrastructure/adapters/primary/web/websocket/

All imports should be updated to use the new location.
"""

# Re-export everything from the new location for backward compatibility
from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
    ConnectionManager,
    get_connection_manager,
)
from src.infrastructure.adapters.primary.web.websocket.router import (
    get_ws_connection_manager,
    router,
)

# Legacy alias: "manager" was a global instance in old code
manager = get_connection_manager()

__all__ = [
    "ConnectionManager",
    "get_connection_manager",
    "get_ws_connection_manager",
    "manager",
    "router",
]
