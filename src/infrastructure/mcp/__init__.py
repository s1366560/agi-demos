"""
MCP (Model Context Protocol) Infrastructure Layer.

This module provides MCP tool integration for the MemStack Agent system.
MCP servers are managed via Ray Actors (or local fallback) for horizontal scaling.

Architecture:
- MCPConfig: Configuration models for local/remote MCP servers
- MCPToolAdapter: Adapts MCP tools to AgentTool interface
- MCPToolLoader: Loads tools from MCP servers
- MCPRayAdapter: Ray Actor-based MCP server management
- MCPLocalFallback: In-process fallback when Ray is unavailable
- Transport: Protocol implementations (stdio, http, websocket)
- Tools: Unified tool adapter interfaces

Server configurations are stored in database (tenant-scoped).
Tools are loaded dynamically from running MCP server actors.

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
from src.infrastructure.mcp.tool_adapter import MCPToolAdapter
from src.infrastructure.mcp.tool_loader import MCPToolLoader

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

# Backward compatibility aliases
MCPTemporalToolAdapter = MCPToolAdapter
MCPTemporalToolLoader = MCPToolLoader

__all__ = [
    # Legacy config (to be migrated to domain models)
    "McpConfig",
    "McpLocalConfig",
    "McpOAuthConfig",
    "McpRemoteConfig",
    "MCPStatus",
    # MCP integration (Ray / Local Fallback)
    "MCPToolAdapter",
    "MCPToolLoader",
    # Backward compatibility aliases
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
