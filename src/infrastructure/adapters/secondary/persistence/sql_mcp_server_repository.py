"""
SQLAlchemy implementation of MCPServerRepository.

Provides persistence for MCP server configurations with tenant-level scoping.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.mcp_server_repository import MCPServerRepositoryPort

logger = logging.getLogger(__name__)


class SQLMCPServerRepository(MCPServerRepositoryPort):
    """
    SQLAlchemy implementation of MCPServerRepository.

    Uses JSON columns to store transport configuration and discovered tools.
    Implements tenant-level scoping.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        tenant_id: str,
        name: str,
        description: Optional[str],
        server_type: str,
        transport_config: dict,
        enabled: bool = True,
    ) -> str:
        """Create a new MCP server configuration."""
        from src.infrastructure.adapters.secondary.persistence.models import MCPServer

        server_id = str(uuid.uuid4())

        db_server = MCPServer(
            id=server_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            server_type=server_type,
            transport_config=transport_config,
            enabled=enabled,
            discovered_tools=[],
            last_sync_at=None,
        )

        self._session.add(db_server)
        await self._session.flush()

        logger.info(f"Created MCP server: {server_id} (name={name}, tenant={tenant_id})")
        return server_id

    async def get_by_id(self, server_id: str) -> Optional[dict]:
        """Get an MCP server by its ID."""
        from src.infrastructure.adapters.secondary.persistence.models import MCPServer

        result = await self._session.execute(select(MCPServer).where(MCPServer.id == server_id))
        db_server = result.scalar_one_or_none()

        return self._to_dict(db_server) if db_server else None

    async def get_by_name(self, tenant_id: str, name: str) -> Optional[dict]:
        """Get an MCP server by name within a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import MCPServer

        result = await self._session.execute(
            select(MCPServer).where(MCPServer.tenant_id == tenant_id).where(MCPServer.name == name)
        )

        db_server = result.scalar_one_or_none()
        return self._to_dict(db_server) if db_server else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> List[dict]:
        """List all MCP servers for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import MCPServer

        query = select(MCPServer).where(MCPServer.tenant_id == tenant_id)

        if enabled_only:
            query = query.where(MCPServer.enabled.is_(True))

        result = await self._session.execute(query.order_by(MCPServer.created_at.desc()))
        db_servers = result.scalars().all()

        return [self._to_dict(server) for server in db_servers]

    async def update(
        self,
        server_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        server_type: Optional[str] = None,
        transport_config: Optional[dict] = None,
        enabled: Optional[bool] = None,
    ) -> bool:
        """Update an MCP server configuration."""
        from src.infrastructure.adapters.secondary.persistence.models import MCPServer

        result = await self._session.execute(select(MCPServer).where(MCPServer.id == server_id))
        db_server = result.scalar_one_or_none()

        if not db_server:
            logger.warning(f"MCP server not found: {server_id}")
            return False

        # Update fields if provided
        if name is not None:
            db_server.name = name
        if description is not None:
            db_server.description = description
        if server_type is not None:
            db_server.server_type = server_type
        if transport_config is not None:
            db_server.transport_config = transport_config
        if enabled is not None:
            db_server.enabled = enabled

        db_server.updated_at = datetime.utcnow()
        await self._session.flush()

        logger.info(f"Updated MCP server: {server_id}")
        return True

    async def update_discovered_tools(
        self,
        server_id: str,
        tools: List[dict],
        last_sync_at: datetime,
    ) -> bool:
        """Update the discovered tools for an MCP server."""
        from src.infrastructure.adapters.secondary.persistence.models import MCPServer

        result = await self._session.execute(select(MCPServer).where(MCPServer.id == server_id))
        db_server = result.scalar_one_or_none()

        if not db_server:
            logger.warning(f"MCP server not found: {server_id}")
            return False

        db_server.discovered_tools = tools
        db_server.last_sync_at = last_sync_at
        db_server.updated_at = datetime.utcnow()

        await self._session.flush()

        logger.info(f"Updated tools for MCP server {server_id}: {len(tools)} tools")
        return True

    async def delete(self, server_id: str) -> bool:
        """Delete an MCP server."""
        from src.infrastructure.adapters.secondary.persistence.models import MCPServer

        result = await self._session.execute(delete(MCPServer).where(MCPServer.id == server_id))

        if result.rowcount == 0:
            logger.warning(f"MCP server not found: {server_id}")
            return False

        logger.info(f"Deleted MCP server: {server_id}")
        return True

    async def get_enabled_servers(self, tenant_id: str) -> List[dict]:
        """Get all enabled MCP servers for a tenant."""
        return await self.list_by_tenant(tenant_id, enabled_only=True)

    def _to_dict(self, db_server) -> dict:
        """Convert database model to dictionary."""
        return {
            "id": db_server.id,
            "tenant_id": db_server.tenant_id,
            "name": db_server.name,
            "description": db_server.description,
            "server_type": db_server.server_type,
            "transport_config": db_server.transport_config,
            "enabled": db_server.enabled,
            "discovered_tools": db_server.discovered_tools,
            "last_sync_at": db_server.last_sync_at,
            "created_at": db_server.created_at,
            "updated_at": db_server.updated_at,
        }
