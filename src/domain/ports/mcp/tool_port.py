"""
MCPToolExecutorPort - Abstract interface for MCP tool execution.

This port defines the contract for executing MCP tools, abstracting
away the underlying transport and server management.
"""

from abc import abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from src.domain.model.mcp.tool import MCPTool, MCPToolResult


@runtime_checkable
class MCPToolExecutorPort(Protocol):
    """
    Abstract interface for MCP tool execution.

    This port provides a high-level interface for executing MCP tools,
    handling server connections, retries, and error handling internally.
    """

    @abstractmethod
    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        timeout: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MCPToolResult:
        """
        Execute an MCP tool by name.

        Args:
            tool_name: Full tool name (e.g., "mcp__filesystem__read_file")
                       or short name if unambiguous.
            arguments: Tool arguments as key-value pairs.
            tenant_id: Tenant ID for server lookup.
            timeout: Optional execution timeout in seconds.
            metadata: Optional metadata for logging/tracing.

        Returns:
            MCPToolResult with execution output.

        Raises:
            MCPToolNotFoundError: If tool doesn't exist.
            MCPServerNotConnectedError: If server is not connected.
            MCPToolExecutionError: If execution fails.
        """
        ...

    @abstractmethod
    async def execute_streaming(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        timeout: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute an MCP tool with streaming output.

        Args:
            tool_name: Full tool name or short name.
            arguments: Tool arguments.
            tenant_id: Tenant ID for server lookup.
            timeout: Optional execution timeout.
            metadata: Optional metadata for logging/tracing.

        Yields:
            Streaming content chunks from tool execution.

        Raises:
            MCPToolNotFoundError: If tool doesn't exist.
            MCPServerNotConnectedError: If server is not connected.
            MCPToolExecutionError: If execution fails.
        """
        ...

    @abstractmethod
    async def list_available_tools(
        self,
        tenant_id: str,
        server_name: str | None = None,
    ) -> list[MCPTool]:
        """
        List all available MCP tools.

        Args:
            tenant_id: Tenant ID for filtering.
            server_name: Optional server name to filter tools.

        Returns:
            List of available MCPTool entities.
        """
        ...

    @abstractmethod
    async def get_tool_schema(
        self,
        tool_name: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        """
        Get the JSON schema for a tool's input.

        Args:
            tool_name: Full tool name or short name.
            tenant_id: Tenant ID for server lookup.

        Returns:
            JSON schema dict if found, None otherwise.
        """
        ...


@runtime_checkable
class MCPToolAdapterPort(Protocol):
    """
    Adapter interface for integrating MCP tools with the agent system.

    This port bridges MCP tools with the agent's tool execution framework.
    """

    @abstractmethod
    def get_tool_definitions(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get tool definitions in agent-compatible format.

        Args:
            tenant_id: Tenant ID for filtering.

        Returns:
            List of tool definitions for the agent.
        """
        ...

    @abstractmethod
    async def execute_tool(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        Execute a tool call from the agent.

        Args:
            tool_call_id: Unique ID for this tool call.
            tool_name: Full MCP tool name.
            arguments: Tool arguments.
            tenant_id: Tenant ID.

        Returns:
            Tool result in agent-compatible format.
        """
        ...

    @abstractmethod
    def is_mcp_tool(self, tool_name: str) -> bool:
        """
        Check if a tool name is an MCP tool.

        Args:
            tool_name: Tool name to check.

        Returns:
            True if this is an MCP tool.
        """
        ...

    @abstractmethod
    def parse_tool_name(
        self,
        full_name: str,
    ) -> tuple[str, str]:
        """
        Parse a full MCP tool name into server and tool components.

        Args:
            full_name: Full tool name (e.g., "mcp__filesystem__read_file").

        Returns:
            Tuple of (server_name, tool_name).

        Raises:
            ValueError: If name format is invalid.
        """
        ...
