"""
MCP Transport Layer.

This package provides transport implementations for MCP protocol communication,
supporting multiple protocols:
- stdio: Subprocess communication (local MCP servers)
- http: HTTP request/response
- sse: Server-Sent Events (streaming HTTP)
- websocket: WebSocket bidirectional communication

All transports implement the MCPTransportPort interface from the domain layer.
"""

from src.infrastructure.mcp.transport.base import BaseTransport
from src.infrastructure.mcp.transport.factory import TransportFactory
from src.infrastructure.mcp.transport.http import HTTPTransport
from src.infrastructure.mcp.transport.stdio import StdioTransport
from src.infrastructure.mcp.transport.websocket import WebSocketTransport

__all__ = [
    "BaseTransport",
    "TransportFactory",
    "StdioTransport",
    "HTTPTransport",
    "WebSocketTransport",
]
