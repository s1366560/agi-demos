"""
V2 SQLAlchemy implementation of MCPServerRepository using BaseRepository.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.mcp.server import MCPServer
from src.domain.ports.repositories.mcp_server_repository import MCPServerRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import MCPServer as DBMCPServer

logger = logging.getLogger(__name__)


class SqlMCPServerRepository(BaseRepository[MCPServer, DBMCPServer], MCPServerRepositoryPort):
    """
    V2 SQLAlchemy implementation of MCPServerRepository using BaseRepository.
    """

    _model_class = DBMCPServer

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)

    # === Interface implementation ===

    async def create(
        self,
        tenant_id: str,
        project_id: str,
        name: str,
        description: str | None,
        server_type: str,
        transport_config: dict[str, Any],
        enabled: bool = True,
    ) -> str:
        """Create a new MCP server configuration."""
        server_id = str(uuid.uuid4())

        db_server = DBMCPServer(
            id=server_id,
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            description=description,
            server_type=server_type,
            transport_config=transport_config,
            enabled=enabled,
            runtime_status="pending_start" if enabled else "disabled",
            runtime_metadata={},
            discovered_tools=[],
            last_sync_at=None,
        )

        self._session.add(db_server)
        await self._session.flush()

        logger.info(
            f"Created MCP server: {server_id} "
            f"(name={name}, project={project_id}, tenant={tenant_id})"
        )
        return server_id

    async def get_by_id(self, server_id: str) -> MCPServer | None:
        """Get an MCP server by its ID."""
        query = select(DBMCPServer).where(DBMCPServer.id == server_id)
        result = await self._session.execute(query)
        db_server = result.scalar_one_or_none()

        return self._to_domain(db_server) if db_server else None

    async def get_by_name(self, project_id: str, name: str) -> MCPServer | None:
        """Get an MCP server by name within a project."""
        query = select(DBMCPServer).where(
            DBMCPServer.project_id == project_id,
            DBMCPServer.name == name,
        )

        result = await self._session.execute(query)
        db_server = result.scalar_one_or_none()
        return self._to_domain(db_server) if db_server else None

    async def list_by_project(
        self,
        project_id: str,
        enabled_only: bool = False,
    ) -> list[MCPServer]:
        """List all MCP servers for a project."""
        query = select(DBMCPServer).where(DBMCPServer.project_id == project_id)

        if enabled_only:
            query = query.where(DBMCPServer.enabled.is_(True))

        result = await self._session.execute(query.order_by(DBMCPServer.created_at.desc()))
        db_servers = result.scalars().all()

        return [d for server in db_servers if (d := self._to_domain(server)) is not None]

    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> list[MCPServer]:
        """List all MCP servers for a tenant (across all projects)."""
        query = select(DBMCPServer).where(DBMCPServer.tenant_id == tenant_id)

        if enabled_only:
            query = query.where(DBMCPServer.enabled.is_(True))

        result = await self._session.execute(query.order_by(DBMCPServer.created_at.desc()))
        db_servers = result.scalars().all()

        return [d for server in db_servers if (d := self._to_domain(server)) is not None]

    async def update(
        self,
        server_id: str,
        name: str | None = None,
        description: str | None = None,
        server_type: str | None = None,
        transport_config: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> bool:
        """Update an MCP server configuration."""
        result = await self._session.execute(select(DBMCPServer).where(DBMCPServer.id == server_id))
        db_server = result.scalar_one_or_none()

        if not db_server:
            logger.warning(f"MCP server not found: {server_id}")
            return False

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

        db_server.updated_at = datetime.now(UTC)
        await self._session.flush()

        logger.info(f"Updated MCP server: {server_id}")
        return True

    async def update_discovered_tools(
        self,
        server_id: str,
        tools: list[dict[str, Any]],
        last_sync_at: datetime,
        sync_error: str | None = None,
    ) -> bool:
        """Update the discovered tools for an MCP server."""
        result = await self._session.execute(select(DBMCPServer).where(DBMCPServer.id == server_id))
        db_server = result.scalar_one_or_none()

        if not db_server:
            logger.warning(f"MCP server not found: {server_id}")
            return False

        db_server.discovered_tools = tools
        db_server.sync_error = sync_error
        db_server.last_sync_at = last_sync_at
        db_server.updated_at = datetime.now(UTC)

        await self._session.flush()

        logger.info(f"Updated tools for MCP server {server_id}: {len(tools)} tools")
        return True

    async def update_runtime_metadata(
        self,
        server_id: str,
        runtime_status: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update runtime status/metadata for MCP server lifecycle tracking."""
        result = await self._session.execute(select(DBMCPServer).where(DBMCPServer.id == server_id))
        db_server = result.scalar_one_or_none()

        if not db_server:
            logger.warning(f"MCP server not found: {server_id}")
            return False

        if runtime_status is not None:
            db_server.runtime_status = runtime_status
        if runtime_metadata is not None:
            existing = db_server.runtime_metadata or {}
            db_server.runtime_metadata = {**existing, **runtime_metadata}
        db_server.updated_at = datetime.now(UTC)
        await self._session.flush()
        return True

    async def delete(self, server_id: str) -> bool:
        """Delete an MCP server."""
        result = await self._session.execute(delete(DBMCPServer).where(DBMCPServer.id == server_id))

        if result.rowcount == 0:
            logger.warning(f"MCP server not found: {server_id}")
            return False

        logger.info(f"Deleted MCP server: {server_id}")
        return True

    async def get_enabled_servers(
        self,
        tenant_id: str,
        project_id: str | None = None,
    ) -> list[MCPServer]:
        """Get all enabled MCP servers, optionally filtered by project."""
        if project_id:
            return await self.list_by_project(project_id, enabled_only=True)
        return await self.list_by_tenant(tenant_id, enabled_only=True)

    # === Conversion methods ===

    def _to_domain(self, db_server: DBMCPServer | None) -> MCPServer | None:
        """Convert database model to MCPServer domain entity."""
        if db_server is None:
            return None

        return MCPServer(
            id=db_server.id,
            tenant_id=db_server.tenant_id,
            project_id=db_server.project_id,
            name=db_server.name,
            description=db_server.description,
            server_type=db_server.server_type,
            transport_config=db_server.transport_config,
            enabled=db_server.enabled,
            runtime_status=db_server.runtime_status or "unknown",
            runtime_metadata=db_server.runtime_metadata or {},
            discovered_tools=db_server.discovered_tools or [],
            sync_error=db_server.sync_error,
            last_sync_at=db_server.last_sync_at,
            created_at=db_server.created_at,
            updated_at=db_server.updated_at,
        )

    def _to_db(self, entity: MCPServer) -> DBMCPServer:
        """Convert MCPServer domain entity to database model."""
        return DBMCPServer(
            id=entity.id,
            tenant_id=entity.tenant_id,
            project_id=entity.project_id,
            name=entity.name,
            description=entity.description,
            server_type=entity.server_type,
            transport_config=entity.transport_config or {},
            enabled=entity.enabled,
            runtime_status=entity.runtime_status,
            runtime_metadata=entity.runtime_metadata or {},
            discovered_tools=entity.discovered_tools or [],
            last_sync_at=entity.last_sync_at,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    def _update_fields(self, db_model: DBMCPServer, entity: MCPServer) -> None:
        """Update database model fields from MCPServer entity."""
        db_model.name = entity.name
        db_model.description = entity.description
        if entity.server_type is not None:
            db_model.server_type = entity.server_type
        if entity.transport_config is not None:
            db_model.transport_config = entity.transport_config
        db_model.enabled = entity.enabled
        if entity.runtime_status:
            db_model.runtime_status = entity.runtime_status
        if entity.runtime_metadata:
            db_model.runtime_metadata = entity.runtime_metadata
        db_model.discovered_tools = entity.discovered_tools
        if entity.last_sync_at is not None:
            db_model.last_sync_at = entity.last_sync_at
