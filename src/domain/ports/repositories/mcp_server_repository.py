"""
MCPServerRepository port for MCP server persistence.

Repository interface for persisting and retrieving MCP servers,
following the Repository pattern.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.domain.model.mcp.server import MCPServer


class MCPServerRepositoryPort(ABC):
    """
    Repository port for MCP server persistence.

    Provides CRUD operations for MCP servers with project-level
    scoping. Each MCP server belongs to a specific project and
    runs inside that project's sandbox container.
    """

    @abstractmethod
    async def create(
        self,
        tenant_id: str,
        project_id: str,
        name: str,
        description: str | None,
        server_type: str,
        transport_config: dict,
        enabled: bool = True,
    ) -> str:
        """
        Create a new MCP server configuration.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID the server belongs to
            name: Server name
            description: Optional server description
            server_type: Transport protocol type (stdio, http, sse, websocket)
            transport_config: Transport configuration dictionary
            enabled: Whether server is enabled

        Returns:
            Created server ID
        """

    @abstractmethod
    async def get_by_id(self, server_id: str) -> Optional["MCPServer"]:
        """
        Get an MCP server by its ID.

        Args:
            server_id: Server ID

        Returns:
            MCPServer entity if found, None otherwise
        """

    @abstractmethod
    async def get_by_name(self, project_id: str, name: str) -> Optional["MCPServer"]:
        """
        Get an MCP server by name within a project.

        Args:
            project_id: Project ID
            name: Server name

        Returns:
            MCPServer entity if found, None otherwise
        """

    @abstractmethod
    async def list_by_project(
        self,
        project_id: str,
        enabled_only: bool = False,
    ) -> list["MCPServer"]:
        """
        List all MCP servers for a project.

        Args:
            project_id: Project ID
            enabled_only: If True, only return enabled servers

        Returns:
            List of MCPServer entities
        """

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> list["MCPServer"]:
        """
        List all MCP servers for a tenant (across all projects).

        Args:
            tenant_id: Tenant ID
            enabled_only: If True, only return enabled servers

        Returns:
            List of MCPServer entities
        """

    @abstractmethod
    async def update(
        self,
        server_id: str,
        name: str | None = None,
        description: str | None = None,
        server_type: str | None = None,
        transport_config: dict | None = None,
        enabled: bool | None = None,
    ) -> bool:
        """
        Update an MCP server configuration.

        Args:
            server_id: Server ID
            name: Optional new name
            description: Optional new description
            server_type: Optional new server type
            transport_config: Optional new transport config
            enabled: Optional new enabled status

        Returns:
            True if updated successfully, False if server not found
        """

    @abstractmethod
    async def update_discovered_tools(
        self,
        server_id: str,
        tools: list[dict],
        last_sync_at: datetime,
        sync_error: str | None = None,
    ) -> bool:
        """
        Update the discovered tools for an MCP server.

        Args:
            server_id: Server ID
            tools: List of tool definitions
            last_sync_at: Timestamp of last sync
            sync_error: Optional error message from last sync attempt

        Returns:
            True if updated successfully, False if server not found
        """

    @abstractmethod
    async def delete(self, server_id: str) -> bool:
        """
        Delete an MCP server.

        Args:
            server_id: Server ID

        Returns:
            True if deleted successfully, False if server not found
        """

    @abstractmethod
    async def get_enabled_servers(
        self,
        tenant_id: str,
        project_id: str | None = None,
    ) -> list["MCPServer"]:
        """
        Get all enabled MCP servers.

        Args:
            tenant_id: Tenant ID
            project_id: Optional project ID to filter by

        Returns:
            List of enabled MCPServer entities
        """
