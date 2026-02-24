"""
MCPRegistryPort - Abstract interface for MCP server registry operations.

This port defines the contract for managing MCP server registrations,
including CRUD operations and status queries.
"""

from abc import abstractmethod
from typing import Protocol, runtime_checkable

from src.domain.model.mcp.server import MCPServer, MCPServerConfig, MCPServerStatus
from src.domain.model.mcp.tool import MCPTool


@runtime_checkable
class MCPRegistryPort(Protocol):
    """
    Abstract interface for MCP server registry.

    This port defines the contract for registering, managing, and
    querying MCP servers in the system.
    """

    @abstractmethod
    async def register_server(
        self,
        config: MCPServerConfig,
    ) -> MCPServer:
        """
        Register a new MCP server.

        Args:
            config: Server configuration including name, transport, etc.

        Returns:
            The registered MCPServer entity with assigned ID.

        Raises:
            MCPServerAlreadyExistsError: If server with same name exists.
        """
        ...

    @abstractmethod
    async def unregister_server(
        self,
        server_id: str,
        tenant_id: str,
    ) -> None:
        """
        Unregister an MCP server.

        Args:
            server_id: Unique identifier of the server.
            tenant_id: Tenant ID for access control.

        Raises:
            MCPServerNotFoundError: If server doesn't exist.
        """
        ...

    @abstractmethod
    async def get_server(
        self,
        server_id: str,
        tenant_id: str,
    ) -> MCPServer | None:
        """
        Get a server by ID.

        Args:
            server_id: Unique identifier of the server.
            tenant_id: Tenant ID for access control.

        Returns:
            MCPServer if found, None otherwise.
        """
        ...

    @abstractmethod
    async def get_server_by_name(
        self,
        name: str,
        tenant_id: str,
    ) -> MCPServer | None:
        """
        Get a server by name within a tenant.

        Args:
            name: Server name.
            tenant_id: Tenant ID for scoping.

        Returns:
            MCPServer if found, None otherwise.
        """
        ...

    @abstractmethod
    async def list_servers(
        self,
        tenant_id: str,
        connected_only: bool = False,
    ) -> list[MCPServer]:
        """
        List all servers for a tenant.

        Args:
            tenant_id: Tenant ID for filtering.
            connected_only: If True, only return connected servers.

        Returns:
            List of MCPServer entities.
        """
        ...

    @abstractmethod
    async def update_server_status(
        self,
        server_id: str,
        tenant_id: str,
        status: MCPServerStatus,
    ) -> None:
        """
        Update server connection status.

        Args:
            server_id: Unique identifier of the server.
            tenant_id: Tenant ID for access control.
            status: New server status.

        Raises:
            MCPServerNotFoundError: If server doesn't exist.
        """
        ...

    @abstractmethod
    async def get_all_tools(
        self,
        tenant_id: str,
    ) -> list[MCPTool]:
        """
        Get all tools from all connected servers for a tenant.

        Args:
            tenant_id: Tenant ID for filtering.

        Returns:
            List of MCPTool entities from all servers.
        """
        ...

    @abstractmethod
    async def get_tool_by_name(
        self,
        full_name: str,
        tenant_id: str,
    ) -> MCPTool | None:
        """
        Get a specific tool by its full name.

        Args:
            full_name: Full tool name (e.g., "mcp__filesystem__read_file").
            tenant_id: Tenant ID for access control.

        Returns:
            MCPTool if found, None otherwise.
        """
        ...

    @abstractmethod
    async def find_server_for_tool(
        self,
        tool_name: str,
        tenant_id: str,
    ) -> MCPServer | None:
        """
        Find the server that provides a specific tool.

        Args:
            tool_name: Tool name (local or full name).
            tenant_id: Tenant ID for access control.

        Returns:
            MCPServer that provides the tool, or None.
        """
        ...


@runtime_checkable
class MCPServerRepositoryPort(Protocol):
    """
    Repository interface for persisting MCP server configurations.

    This is a lower-level interface for database operations,
    used by the registry implementation.
    """

    @abstractmethod
    async def save(self, server: MCPServer) -> None:
        """Save a server to persistent storage."""
        ...

    @abstractmethod
    async def delete(self, server_id: str, tenant_id: str) -> None:
        """Delete a server from persistent storage."""
        ...

    @abstractmethod
    async def find_by_id(
        self,
        server_id: str,
        tenant_id: str,
    ) -> MCPServer | None:
        """Find a server by ID."""
        ...

    @abstractmethod
    async def find_by_name(
        self,
        name: str,
        tenant_id: str,
    ) -> MCPServer | None:
        """Find a server by name."""
        ...

    @abstractmethod
    async def find_all(
        self,
        tenant_id: str,
    ) -> list[MCPServer]:
        """Find all servers for a tenant."""
        ...
