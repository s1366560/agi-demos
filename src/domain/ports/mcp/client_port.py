"""
MCPClientPort - Abstract interface for MCP client operations.

This port defines the contract for MCP client implementations,
allowing different transport mechanisms (stdio, HTTP, SSE, WebSocket)
to be used interchangeably.
"""

from abc import abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from src.domain.model.mcp.connection import ConnectionInfo
from src.domain.model.mcp.server import MCPServerConfig
from src.domain.model.mcp.tool import MCPToolCallRequest, MCPToolResult, MCPToolSchema


@runtime_checkable
class MCPClientPort(Protocol):
    """
    Abstract interface for MCP client operations.

    This port defines the contract for connecting to MCP servers,
    discovering tools, and executing tool calls.
    """

    @abstractmethod
    async def connect(
        self,
        config: MCPServerConfig,
        timeout: float | None = None,
    ) -> ConnectionInfo:
        """
        Connect to an MCP server.

        Args:
            config: Server configuration including transport settings.
            timeout: Optional connection timeout in seconds.

        Returns:
            ConnectionInfo with connection state and server information.

        Raises:
            MCPConnectionError: If connection fails.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Disconnect from the current MCP server.

        Should be idempotent - calling on disconnected client is safe.
        """
        ...

    @abstractmethod
    async def list_tools(self) -> list[MCPToolSchema]:
        """
        List available tools from the connected server.

        Returns:
            List of tool schemas describing available tools.

        Raises:
            MCPNotConnectedError: If not connected to a server.
        """
        ...

    @abstractmethod
    async def call_tool(
        self,
        request: MCPToolCallRequest,
        timeout: float | None = None,
    ) -> MCPToolResult:
        """
        Execute a tool call on the connected server.

        Args:
            request: Tool call request with name and arguments.
            timeout: Optional execution timeout in seconds.

        Returns:
            MCPToolResult with tool execution output.

        Raises:
            MCPNotConnectedError: If not connected to a server.
            MCPToolExecutionError: If tool execution fails.
        """
        ...

    @abstractmethod
    async def call_tool_streaming(
        self,
        request: MCPToolCallRequest,
        timeout: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute a tool call with streaming output.

        Args:
            request: Tool call request with name and arguments.
            timeout: Optional execution timeout in seconds.

        Yields:
            Streaming content chunks from tool execution.

        Raises:
            MCPNotConnectedError: If not connected to a server.
            MCPToolExecutionError: If tool execution fails.
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if currently connected to a server."""
        ...

    @property
    @abstractmethod
    def connection_info(self) -> ConnectionInfo | None:
        """Get current connection information."""
        ...

    @abstractmethod
    async def ping(self) -> bool:
        """
        Send a ping to check server health.

        Returns:
            True if server responds, False otherwise.
        """
        ...


@runtime_checkable
class MCPClientFactoryPort(Protocol):
    """
    Factory interface for creating MCP clients.

    This allows different client implementations to be used
    based on transport type or other criteria.
    """

    @abstractmethod
    def create_client(
        self,
        config: MCPServerConfig,
    ) -> MCPClientPort:
        """
        Create an MCP client for the given configuration.

        Args:
            config: Server configuration specifying transport type.

        Returns:
            MCPClientPort implementation appropriate for the transport.
        """
        ...
