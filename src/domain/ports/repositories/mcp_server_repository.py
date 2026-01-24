"""
MCPServerRepository port for MCP server persistence.

Repository interface for persisting and retrieving MCP servers,
following the Repository pattern.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional


class MCPServerRepositoryPort(ABC):
    """
    Repository port for MCP server persistence.

    Provides CRUD operations for MCP servers with tenant-level
    scoping. MCP servers are shared across projects within a tenant
    but isolated between tenants.
    """

    @abstractmethod
    async def create(
        self,
        tenant_id: str,
        name: str,
        description: Optional[str],
        server_type: str,
        transport_config: dict,
        enabled: bool = True,
    ) -> str:
        """
        Create a new MCP server configuration.

        Args:
            tenant_id: Tenant ID
            name: Server name
            description: Optional server description
            server_type: Transport protocol type (stdio, http, sse, websocket)
            transport_config: Transport configuration dictionary
            enabled: Whether server is enabled

        Returns:
            Created server ID

        Raises:
            ValueError: If server data is invalid
        """
        pass

    @abstractmethod
    async def get_by_id(self, server_id: str) -> Optional[dict]:
        """
        Get an MCP server by its ID.

        Args:
            server_id: Server ID

        Returns:
            Server data dictionary if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_name(self, tenant_id: str, name: str) -> Optional[dict]:
        """
        Get an MCP server by name within a tenant.

        Args:
            tenant_id: Tenant ID
            name: Server name

        Returns:
            Server data dictionary if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> List[dict]:
        """
        List all MCP servers for a tenant.

        Args:
            tenant_id: Tenant ID
            enabled_only: If True, only return enabled servers

        Returns:
            List of server data dictionaries
        """
        pass

    @abstractmethod
    async def update(
        self,
        server_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        server_type: Optional[str] = None,
        transport_config: Optional[dict] = None,
        enabled: Optional[bool] = None,
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

        Raises:
            ValueError: If update data is invalid
        """
        pass

    @abstractmethod
    async def update_discovered_tools(
        self,
        server_id: str,
        tools: List[dict],
        last_sync_at: datetime,
    ) -> bool:
        """
        Update the discovered tools for an MCP server.

        Args:
            server_id: Server ID
            tools: List of tool definitions
            last_sync_at: Timestamp of last sync

        Returns:
            True if updated successfully, False if server not found
        """
        pass

    @abstractmethod
    async def delete(self, server_id: str) -> bool:
        """
        Delete an MCP server.

        Args:
            server_id: Server ID

        Returns:
            True if deleted successfully, False if server not found
        """
        pass

    @abstractmethod
    async def get_enabled_servers(self, tenant_id: str) -> List[dict]:
        """
        Get all enabled MCP servers for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            List of enabled server data dictionaries
        """
        pass
