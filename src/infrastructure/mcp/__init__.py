"""
MCP (Model Context Protocol) Infrastructure Layer.

This module provides MCP tool integration for the MemStack Agent system.
MCP servers run inside project sandbox containers for security and isolation.

Architecture:
- MCPConfig: Configuration models for local/remote MCP servers
- SandboxMCPServerToolAdapter: Adapts sandbox-hosted MCP tools to AgentTool interface
- SandboxMCPServerManager: Manages MCP server lifecycle in sandbox containers
- Transport: Protocol implementations (stdio, http, websocket)
- Tools: Unified tool adapter interfaces

Server configurations are stored in database (tenant-scoped).
Tools are loaded dynamically from running MCP servers in sandbox containers.

Domain Models (src.domain.model.mcp):
- MCPServer, MCPServerConfig, MCPServerStatus
- MCPTool, MCPToolSchema, MCPToolResult
- TransportType, TransportConfig
- ConnectionState, ConnectionInfo

Ports (src.domain.ports.mcp):
- MCPClientPort, MCPClientFactoryPort
- MCPRegistryPort, MCPServerRepositoryPort
- MCPToolExecutorPort, MCPToolAdapterPort
- MCPTransportPort, MCPTransportFactoryPort
"""

from src.infrastructure.mcp.config import (
    McpConfig,
    McpLocalConfig,
    McpOAuthConfig,
    McpRemoteConfig,
    MCPStatus,
)

# Tools layer
from src.infrastructure.mcp.tools import (
    BaseMCPToolAdapter,
    MCPToolFactory,
)

# Transport layer
from src.infrastructure.mcp.transport import (
    HTTPTransport,
    StdioTransport,
    TransportFactory,
    WebSocketTransport,
)

__all__ = [
    # Config
    "McpConfig",
    "McpLocalConfig",
    "McpOAuthConfig",
    "McpRemoteConfig",
    "MCPStatus",
    # Transport layer
    "TransportFactory",
    "StdioTransport",
    "HTTPTransport",
    "WebSocketTransport",
    # Tools layer
    "BaseMCPToolAdapter",
    "MCPToolFactory",
]
