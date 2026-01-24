"""MCP Temporal Integration.

This module provides Temporal-based MCP server management, separating
MCP subprocess lifecycle from the API service for better scalability
and fault tolerance.

Components:
- MCPTemporalAdapter: API-side adapter for MCP operations via Temporal
- MCPServerWorkflow: Long-running workflow managing MCP server lifecycle
- MCP Activities: Activities for starting/calling/stopping MCP servers
- MCPSubprocessClient: LOCAL (stdio) transport client
- MCPHttpClient: Remote (HTTP/SSE) transport client
- MCPWebSocketClient: WebSocket transport client for sandbox connections
"""

from src.infrastructure.adapters.secondary.temporal.mcp.adapter import MCPTemporalAdapter
from src.infrastructure.adapters.secondary.temporal.mcp.http_client import MCPHttpClient
from src.infrastructure.adapters.secondary.temporal.mcp.subprocess_client import MCPSubprocessClient
from src.infrastructure.adapters.secondary.temporal.mcp.websocket_client import MCPWebSocketClient

__all__ = [
    "MCPTemporalAdapter",
    "MCPSubprocessClient",
    "MCPHttpClient",
    "MCPWebSocketClient",
]
