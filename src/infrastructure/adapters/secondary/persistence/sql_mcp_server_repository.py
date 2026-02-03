"""
V2 SQLAlchemy implementation of MCPServerRepository using BaseRepository.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.mcp_server_repository import MCPServerRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import MCPServer as DBMCPServer

logger = logging.getLogger(__name__)


class SqlMCPServerRepository(BaseRepository[dict, DBMCPServer], MCPServerRepositoryPort):
    """
    V2 SQLAlchemy implementation of MCPServerRepository using BaseRepository.

    Note: This repository uses dict as the domain type since MCPServer
    is represented as a dictionary in the current architecture.
    """

    _model_class = DBMCPServer

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)

    # === Interface implementation ===

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
        server_id = str(uuid.uuid4())

        db_server = DBMCPServer(
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
        query = select(DBMCPServer).where(DBMCPServer.id == server_id)
        result = await self._session.execute(query)
        db_server = result.scalar_one_or_none()

        return self._to_domain(db_server) if db_server else None

    async def get_by_name(self, tenant_id: str, name: str) -> Optional[dict]:
        """Get an MCP server by name within a tenant."""
        query = select(DBMCPServer).where(
            DBMCPServer.tenant_id == tenant_id,
            DBMCPServer.name == name,
        )

        result = await self._session.execute(query)
        db_server = result.scalar_one_or_none()
        return self._to_domain(db_server) if db_server else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> List[dict]:
        """List all MCP servers for a tenant."""
        query = select(DBMCPServer).where(DBMCPServer.tenant_id == tenant_id)

        if enabled_only:
            query = query.where(DBMCPServer.enabled.is_(True))

        result = await self._session.execute(query.order_by(DBMCPServer.created_at.desc()))
        db_servers = result.scalars().all()

        return [self._to_domain(server) for server in db_servers]

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
        result = await self._session.execute(select(DBMCPServer).where(DBMCPServer.id == server_id))
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
        result = await self._session.execute(select(DBMCPServer).where(DBMCPServer.id == server_id))
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
        result = await self._session.execute(delete(DBMCPServer).where(DBMCPServer.id == server_id))

        if result.rowcount == 0:
            logger.warning(f"MCP server not found: {server_id}")
            return False

        logger.info(f"Deleted MCP server: {server_id}")
        return True

    async def get_enabled_servers(self, tenant_id: str) -> List[dict]:
        """Get all enabled MCP servers for a tenant."""
        return await self.list_by_tenant(tenant_id, enabled_only=True)

    # === Conversion methods ===

    def _to_domain(self, db_server: Optional[DBMCPServer]) -> Optional[dict]:
        """Convert database model to dictionary."""
        if db_server is None:
            return None

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

    def _to_db(self, domain_entity: dict) -> DBMCPServer:
        """Convert dictionary to database model."""
        return DBMCPServer(
            id=domain_entity.get("id"),
            tenant_id=domain_entity.get("tenant_id"),
            name=domain_entity.get("name"),
            description=domain_entity.get("description"),
            server_type=domain_entity.get("server_type"),
            transport_config=domain_entity.get("transport_config", {}),
            enabled=domain_entity.get("enabled", True),
            discovered_tools=domain_entity.get("discovered_tools", []),
            last_sync_at=domain_entity.get("last_sync_at"),
            created_at=domain_entity.get("created_at"),
            updated_at=domain_entity.get("updated_at"),
        )

    def _update_fields(self, db_model: DBMCPServer, domain_entity: dict) -> None:
        """Update database model fields from dictionary."""
        if "name" in domain_entity:
            db_model.name = domain_entity["name"]
        if "description" in domain_entity:
            db_model.description = domain_entity["description"]
        if "server_type" in domain_entity:
            db_model.server_type = domain_entity["server_type"]
        if "transport_config" in domain_entity:
            db_model.transport_config = domain_entity["transport_config"]
        if "enabled" in domain_entity:
            db_model.enabled = domain_entity["enabled"]
        if "discovered_tools" in domain_entity:
            db_model.discovered_tools = domain_entity["discovered_tools"]
        if "last_sync_at" in domain_entity:
            db_model.last_sync_at = domain_entity["last_sync_at"]
