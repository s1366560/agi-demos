"""Port for managing MCP servers within sandbox containers.

Defines the contract for installing, starting, stopping,
and proxying tool calls to user-configured MCP servers
running inside project sandbox containers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SandboxMCPServerStatus:
    """Status of an MCP server running in a sandbox."""

    name: str
    server_type: str
    status: str
    pid: Optional[int] = None
    port: Optional[int] = None
    tool_count: int = 0
    error: Optional[str] = None


@dataclass
class SandboxMCPToolCallResult:
    """Result of calling a tool on a sandbox-hosted MCP server."""

    content: List[Dict[str, Any]]
    is_error: bool = False
    error_message: Optional[str] = None


class SandboxMCPServerPort(ABC):
    """Port for managing MCP servers in sandbox containers.

    This port provides an abstraction for the lifecycle management
    of user-configured MCP servers running inside project sandboxes.
    """

    @abstractmethod
    async def install_and_start(
        self,
        project_id: str,
        tenant_id: str,
        server_name: str,
        server_type: str,
        transport_config: Dict[str, Any],
    ) -> SandboxMCPServerStatus:
        """Install and start an MCP server in the project's sandbox.

        Creates the sandbox if it doesn't exist.

        Args:
            project_id: Project ID.
            tenant_id: Tenant ID.
            server_name: MCP server name.
            server_type: Transport type (stdio, sse, http, websocket).
            transport_config: Transport configuration.

        Returns:
            Server status after startup.

        Raises:
            SandboxError: If sandbox creation or server start fails.
        """

    @abstractmethod
    async def stop_server(
        self,
        project_id: str,
        server_name: str,
    ) -> bool:
        """Stop an MCP server in the project's sandbox.

        Args:
            project_id: Project ID.
            server_name: MCP server name.

        Returns:
            True if stopped successfully.
        """

    @abstractmethod
    async def discover_tools(
        self,
        project_id: str,
        tenant_id: str,
        server_name: str,
        server_type: str,
        transport_config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Discover tools from an MCP server running in the sandbox.

        Installs and starts the server if not already running.

        Args:
            project_id: Project ID.
            tenant_id: Tenant ID.
            server_name: MCP server name.
            server_type: Transport type.
            transport_config: Transport configuration.

        Returns:
            List of tool definitions.
        """

    @abstractmethod
    async def call_tool(
        self,
        project_id: str,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> SandboxMCPToolCallResult:
        """Call a tool on an MCP server running in the sandbox.

        Args:
            project_id: Project ID.
            server_name: MCP server name.
            tool_name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tool call result.
        """

    @abstractmethod
    async def test_connection(
        self,
        project_id: str,
        tenant_id: str,
        server_name: str,
        server_type: str,
        transport_config: Dict[str, Any],
    ) -> SandboxMCPServerStatus:
        """Test connectivity to an MCP server by starting it in sandbox.

        Args:
            project_id: Project ID.
            tenant_id: Tenant ID.
            server_name: MCP server name.
            server_type: Transport type.
            transport_config: Transport configuration.

        Returns:
            Server status with tool count.
        """

    @abstractmethod
    async def list_servers(
        self,
        project_id: str,
    ) -> List[SandboxMCPServerStatus]:
        """List all MCP servers running in a project's sandbox.

        Args:
            project_id: Project ID.

        Returns:
            List of server statuses.
        """
