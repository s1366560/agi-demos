"""MCP Transport Clients.

This module provides MCP protocol client implementations used by
sandbox adapters and MCP tool factories.

Components:
- MCPSubprocessClient: LOCAL (stdio) transport client
- MCPHttpClient: Remote (HTTP/SSE) transport client
- MCPWebSocketClient: WebSocket transport client for sandbox connections
- GlobalConnectionLimiter: Process-wide connection limit for MCP pools
"""

from src.infrastructure.mcp.clients.global_connection_limiter import (
    GlobalConnectionLimiter,
    get_global_limiter,
)
from src.infrastructure.mcp.clients.http_client import MCPHttpClient
from src.infrastructure.mcp.clients.subprocess_client import MCPSubprocessClient
from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

__all__ = [
    "GlobalConnectionLimiter",
    "MCPHttpClient",
    "MCPSubprocessClient",
    "MCPWebSocketClient",
    "get_global_limiter",
]
