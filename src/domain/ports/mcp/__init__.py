"""
MCP Port Definitions.

This package defines the abstract interfaces (ports) for MCP functionality,
following hexagonal architecture principles. Implementations are provided
by infrastructure adapters.
"""

from src.domain.ports.mcp.app_repository_port import MCPAppRepositoryPort
from src.domain.ports.mcp.client_port import MCPClientPort
from src.domain.ports.mcp.registry_port import MCPRegistryPort
from src.domain.ports.mcp.tool_port import MCPToolExecutorPort
from src.domain.ports.mcp.transport_port import MCPTransportPort

__all__ = [
    "MCPAppRepositoryPort",
    "MCPClientPort",
    "MCPRegistryPort",
    "MCPToolExecutorPort",
    "MCPTransportPort",
]
