"""
MCP (Model Context Protocol) Infrastructure Layer.

This module provides MCP tool integration for the MemStack Agent system.
All MCP servers are managed via Temporal Workflows for horizontal scaling.

Architecture:
- MCPConfig: Configuration models for local/remote MCP servers
- MCPTemporalToolAdapter: Adapts Temporal MCP tools to AgentTool interface
- MCPTemporalToolLoader: Loads tools from Temporal MCP servers
- Transport: Protocol implementations (stdio, http, websocket)
- Tools: Unified tool adapter interfaces

Server configurations are stored in database (tenant-scoped).
Tools are loaded dynamically from running Temporal Workflows.

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
from src.infrastructure.mcp.temporal_tool_adapter import MCPTemporalToolAdapter
from src.infrastructure.mcp.temporal_tool_loader import MCPTemporalToolLoader

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
    # Legacy config (to be migrated to domain models)
    "McpConfig",
    "McpLocalConfig",
    "McpOAuthConfig",
    "McpRemoteConfig",
    "MCPStatus",
    # Temporal integration
    "MCPTemporalToolAdapter",
    "MCPTemporalToolLoader",
    # Transport layer
    "TransportFactory",
    "StdioTransport",
    "HTTPTransport",
    "WebSocketTransport",
    # Tools layer
    "BaseMCPToolAdapter",
    "MCPToolFactory",
]
