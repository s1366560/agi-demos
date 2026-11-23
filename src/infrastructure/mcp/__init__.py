"""
MCP (Model Context Protocol) Infrastructure Layer.

This module provides MCP tool integration for the MemStack Agent system.
MCP servers run inside project sandbox containers for security and isolation.

Architecture:
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

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools import BaseMCPToolAdapter, MCPToolFactory
    from .transport import HTTPTransport, StdioTransport, TransportFactory, WebSocketTransport

__all__ = [
    "BaseMCPToolAdapter",
    "HTTPTransport",
    "MCPToolFactory",
    "StdioTransport",
    "TransportFactory",
    "WebSocketTransport",
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(name)
    module = ".tools" if name in {"BaseMCPToolAdapter", "MCPToolFactory"} else ".transport"
    return getattr(import_module(module, __name__), name)
