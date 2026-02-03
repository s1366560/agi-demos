"""
MCP (Model Context Protocol) Domain Models.

This module defines the core domain entities and value objects for MCP,
providing a unified model across the entire system.

Key entities:
- MCPServer: MCP server configuration and status
- MCPTool: Tool definition and execution result
- Transport: Transport protocol configuration
- Connection: Connection state management
"""

from src.domain.model.mcp.connection import ConnectionInfo, ConnectionState
from src.domain.model.mcp.server import MCPServer, MCPServerConfig, MCPServerStatus
from src.domain.model.mcp.tool import MCPTool, MCPToolResult, MCPToolSchema
from src.domain.model.mcp.transport import TransportConfig, TransportType

__all__ = [
    # Server
    "MCPServer",
    "MCPServerConfig",
    "MCPServerStatus",
    # Tool
    "MCPTool",
    "MCPToolSchema",
    "MCPToolResult",
    # Transport
    "TransportType",
    "TransportConfig",
    # Connection
    "ConnectionState",
    "ConnectionInfo",
]
