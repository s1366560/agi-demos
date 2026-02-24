"""
Base MCP Tool Adapter.

Provides abstract base class for MCP tool adapters with
common functionality for tool execution.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from src.domain.model.mcp.tool import MCPTool, MCPToolResult, MCPToolSchema

logger = logging.getLogger(__name__)


class BaseMCPToolAdapter(ABC):
    """
    Abstract base class for MCP tool adapters.

    Provides common functionality for tool execution including:
    - Argument validation
    - Error handling
    - Result formatting
    - Logging

    Subclasses implement the _execute_tool_internal method for
    transport-specific execution logic.
    """

    def __init__(self, server_name: str) -> None:
        """
        Initialize the adapter.

        Args:
            server_name: Name of the MCP server providing tools
        """
        self._server_name = server_name
        self._tools_cache: dict[str, MCPToolSchema] = {}
        self._initialized = False

    @property
    def server_name(self) -> str:
        """Get the server name."""
        return self._server_name

    @property
    def is_initialized(self) -> bool:
        """Check if adapter is initialized."""
        return self._initialized

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_ms: int | None = None,
    ) -> MCPToolResult:
        """
        Execute a tool and return the result.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            timeout_ms: Execution timeout in milliseconds

        Returns:
            MCPToolResult with execution output
        """
        try:
            logger.debug(f"Executing tool {tool_name} on server {self._server_name}")

            # Validate tool exists if cache is populated
            if self._tools_cache and tool_name not in self._tools_cache:
                return MCPToolResult.error(
                    f"Tool '{tool_name}' not found on server '{self._server_name}'"
                )

            # Execute through transport-specific implementation
            result = await self._execute_tool_internal(tool_name, arguments, timeout_ms)

            logger.debug(f"Tool {tool_name} completed: is_error={result.is_error}")
            return result

        except Exception as e:
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            return MCPToolResult.error(str(e))

    async def list_tools(self) -> list[MCPTool]:
        """
        List available tools from the server.

        Returns:
            List of MCPTool objects
        """
        schemas = await self._list_tools_internal()

        # Update cache
        self._tools_cache = {s.name: s for s in schemas}

        # Convert schemas to MCPTool entities
        return [
            MCPTool(
                server_id=self._server_name,  # Use server_name as ID
                server_name=self._server_name,
                schema=schema,
            )
            for schema in schemas
        ]

    async def initialize(self) -> None:
        """Initialize the adapter."""
        if self._initialized:
            return

        await self._initialize_internal()
        self._initialized = True

    async def close(self) -> None:
        """Close the adapter and release resources."""
        await self._close_internal()
        self._initialized = False
        self._tools_cache.clear()

    # Abstract methods for subclass implementation

    @abstractmethod
    async def _execute_tool_internal(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_ms: int | None,
    ) -> MCPToolResult:
        """
        Transport-specific tool execution.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            timeout_ms: Timeout in milliseconds

        Returns:
            MCPToolResult from execution
        """
        ...

    @abstractmethod
    async def _list_tools_internal(self) -> list[MCPToolSchema]:
        """
        Transport-specific tool listing.

        Returns:
            List of tool schemas
        """
        ...

    @abstractmethod
    async def _initialize_internal(self) -> None:
        """Transport-specific initialization."""
        ...

    @abstractmethod
    async def _close_internal(self) -> None:
        """Transport-specific cleanup."""
        ...


class LocalToolAdapter(BaseMCPToolAdapter):
    """
    Adapter for local (stdio) MCP servers.

    Delegates to subprocess-based MCP client for tool execution.
    """

    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize local tool adapter.

        Args:
            server_name: Name of the MCP server
            command: Command to start the server
            args: Command arguments
            env: Environment variables
        """
        super().__init__(server_name)
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._client = None

    async def _initialize_internal(self) -> None:
        """Initialize subprocess client."""
        from src.infrastructure.mcp.clients.subprocess_client import (
            MCPSubprocessClient,
        )

        self._client = MCPSubprocessClient(
            command=self._command,
            args=self._args,
            env=self._env,
        )
        await self._client.connect()

    async def _close_internal(self) -> None:
        """Close subprocess client."""
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def _execute_tool_internal(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_ms: int | None,
    ) -> MCPToolResult:
        """Execute tool via subprocess."""
        if not self._client:
            return MCPToolResult.error("Client not initialized")

        timeout_sec = (timeout_ms / 1000) if timeout_ms else None
        result = await self._client.call_tool(tool_name, arguments, timeout=timeout_sec)

        return MCPToolResult(
            content=result.content,
            is_error=result.isError,
            artifact=result.artifact,
        )

    async def _list_tools_internal(self) -> list[MCPToolSchema]:
        """List tools from subprocess client."""
        if not self._client:
            return []

        tools = await self._client.list_tools()
        return [
            MCPToolSchema(
                name=t.name,
                description=t.description,
                input_schema=t.inputSchema,
            )
            for t in tools
        ]


class WebSocketToolAdapter(BaseMCPToolAdapter):
    """
    Adapter for WebSocket-based MCP servers.

    Delegates to WebSocket MCP client for tool execution.
    """

    def __init__(self, server_name: str, websocket_url: str) -> None:
        """
        Initialize WebSocket tool adapter.

        Args:
            server_name: Name of the MCP server
            websocket_url: WebSocket URL to connect to
        """
        super().__init__(server_name)
        self._websocket_url = websocket_url
        self._client = None

    async def _initialize_internal(self) -> None:
        """Initialize WebSocket client."""
        from src.infrastructure.mcp.clients.websocket_client import (
            MCPWebSocketClient,
        )

        self._client = MCPWebSocketClient(self._websocket_url)
        await self._client.connect()

    async def _close_internal(self) -> None:
        """Close WebSocket client."""
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def _execute_tool_internal(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_ms: int | None,
    ) -> MCPToolResult:
        """Execute tool via WebSocket."""
        if not self._client:
            return MCPToolResult.error("Client not initialized")

        timeout_sec = (timeout_ms / 1000) if timeout_ms else None
        result = await self._client.call_tool(tool_name, arguments, timeout=timeout_sec)

        return MCPToolResult(
            content=result.get("content", []),
            is_error=result.get("isError", False),
            artifact=result.get("artifact"),
        )

    async def _list_tools_internal(self) -> list[MCPToolSchema]:
        """List tools from WebSocket client."""
        if not self._client:
            return []

        tools = await self._client.list_tools()
        return [
            MCPToolSchema(
                name=t.get("name", ""),
                description=t.get("description"),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools
        ]
