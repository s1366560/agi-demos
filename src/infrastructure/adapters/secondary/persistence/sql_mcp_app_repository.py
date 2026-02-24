"""
SQLAlchemy implementation of MCPAppRepository.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.mcp.app import (
    MCPApp,
    MCPAppResource,
    MCPAppSource,
    MCPAppStatus,
    MCPAppUIMetadata,
)
from src.domain.ports.mcp.app_repository_port import MCPAppRepositoryPort
from src.infrastructure.adapters.secondary.persistence.models import MCPAppModel

logger = logging.getLogger(__name__)


class SqlMCPAppRepository(MCPAppRepositoryPort):
    """SQLAlchemy implementation of MCPAppRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, app: MCPApp) -> MCPApp:
        """Save or update an MCP App."""
        result = await self._session.execute(select(MCPAppModel).where(MCPAppModel.id == app.id))
        db_app = result.scalar_one_or_none()

        if db_app:
            self._update_fields(db_app, app)
        else:
            db_app = self._to_db(app)
            self._session.add(db_app)

        await self._session.flush()
        logger.info(
            "Saved MCP App: %s (server=%s, tool=%s)", app.id, app.server_name, app.tool_name
        )
        return app

    async def find_by_id(self, app_id: str) -> MCPApp | None:
        """Find an MCP App by its ID."""
        result = await self._session.execute(select(MCPAppModel).where(MCPAppModel.id == app_id))
        db_app = result.scalar_one_or_none()
        return self._to_domain(db_app) if db_app else None

    async def find_by_server_and_tool(self, server_id: str, tool_name: str) -> MCPApp | None:
        """Find an MCP App by server and tool name."""
        result = await self._session.execute(
            select(MCPAppModel).where(
                MCPAppModel.server_id == server_id,
                MCPAppModel.tool_name == tool_name,
            )
        )
        db_app = result.scalar_one_or_none()
        return self._to_domain(db_app) if db_app else None

    async def find_by_server_name_and_tool(self, server_name: str, tool_name: str) -> MCPApp | None:
        """Find an MCP App by server name and tool name."""
        result = await self._session.execute(
            select(MCPAppModel).where(
                MCPAppModel.server_name == server_name,
                MCPAppModel.tool_name == tool_name,
            )
        )
        db_app = result.scalar_one_or_none()
        return self._to_domain(db_app) if db_app else None

    async def find_by_project(
        self, project_id: str, include_disabled: bool = False
    ) -> list[MCPApp]:
        """Find all MCP Apps for a project."""
        query = select(MCPAppModel).where(MCPAppModel.project_id == project_id)
        if not include_disabled:
            query = query.where(MCPAppModel.status != MCPAppStatus.DISABLED.value)
        query = query.order_by(MCPAppModel.created_at.desc())

        result = await self._session.execute(query)
        return [self._to_domain(db) for db in result.scalars().all()]

    async def find_ready_by_project(self, project_id: str) -> list[MCPApp]:
        """Find all ready MCP Apps for a project."""
        result = await self._session.execute(
            select(MCPAppModel)
            .where(
                MCPAppModel.project_id == project_id,
                MCPAppModel.status == MCPAppStatus.READY.value,
            )
            .order_by(MCPAppModel.created_at.desc())
        )
        return [self._to_domain(db) for db in result.scalars().all()]

    async def find_by_tenant(self, tenant_id: str, include_disabled: bool = False) -> list[MCPApp]:
        """Find all MCP Apps for a tenant (across all projects)."""
        query = select(MCPAppModel).where(MCPAppModel.tenant_id == tenant_id)
        if not include_disabled:
            query = query.where(MCPAppModel.status != MCPAppStatus.DISABLED.value)
        query = query.order_by(MCPAppModel.created_at.desc())

        result = await self._session.execute(query)
        return [self._to_domain(db) for db in result.scalars().all()]

    async def delete(self, app_id: str) -> bool:
        """Delete an MCP App."""
        result = await self._session.execute(delete(MCPAppModel).where(MCPAppModel.id == app_id))
        if result.rowcount == 0:
            return False
        logger.info("Deleted MCP App: %s", app_id)
        return True

    async def delete_by_server(self, server_id: str) -> int:
        """Delete all MCP Apps for a server."""
        result = await self._session.execute(
            delete(MCPAppModel).where(MCPAppModel.server_id == server_id)
        )
        count = result.rowcount
        if count > 0:
            logger.info("Deleted %d MCP Apps for server %s", count, server_id)
        return count

    async def disable_by_server(self, server_id: str) -> int:
        """Disable all MCP Apps for a server."""
        from sqlalchemy import update

        result = await self._session.execute(
            update(MCPAppModel)
            .where(
                MCPAppModel.server_id == server_id,
                MCPAppModel.status != MCPAppStatus.DISABLED.value,
            )
            .values(
                status=MCPAppStatus.DISABLED.value,
                updated_at=datetime.now(UTC),
            )
        )
        count = result.rowcount
        if count > 0:
            logger.info("Disabled %d MCP Apps for server %s", count, server_id)
        return count

    async def update_lifecycle_metadata(self, app_id: str, metadata: dict[str, Any]) -> bool:
        """Merge lifecycle metadata into existing app metadata."""
        result = await self._session.execute(select(MCPAppModel).where(MCPAppModel.id == app_id))
        db_app = result.scalar_one_or_none()
        if not db_app:
            return False
        existing = db_app.lifecycle_metadata or {}
        db_app.lifecycle_metadata = {**existing, **(metadata or {})}
        db_app.updated_at = datetime.now(UTC)
        await self._session.flush()
        return True

    def _to_domain(self, db: MCPAppModel) -> MCPApp:
        """Convert DB model to domain entity."""
        ui_metadata = MCPAppUIMetadata.from_dict(db.ui_metadata or {})

        resource = None
        if db.resource_html and db.resource_uri:
            resource = MCPAppResource(
                uri=db.resource_uri,
                html_content=db.resource_html,
                mime_type=db.resource_mime_type or "text/html;profile=mcp-app",
                resolved_at=db.resource_resolved_at or db.created_at,
                size_bytes=db.resource_size_bytes or 0,
            )

        return MCPApp(
            id=db.id,
            project_id=db.project_id,
            tenant_id=db.tenant_id,
            server_id=db.server_id,
            server_name=db.server_name,
            tool_name=db.tool_name,
            ui_metadata=ui_metadata,
            resource=resource,
            source=MCPAppSource(db.source),
            status=MCPAppStatus(db.status),
            error_message=db.error_message,
            lifecycle_metadata=db.lifecycle_metadata or {},
            created_at=db.created_at,
            updated_at=db.updated_at,
        )

    def _to_db(self, app: MCPApp) -> MCPAppModel:
        """Convert domain entity to DB model."""
        db = MCPAppModel(
            id=app.id,
            project_id=app.project_id,
            tenant_id=app.tenant_id,
            server_id=app.server_id,
            server_name=app.server_name,
            tool_name=app.tool_name,
            ui_metadata=app.ui_metadata.to_dict(),
            source=app.source.value,
            status=app.status.value,
            lifecycle_metadata=app.lifecycle_metadata or {},
            error_message=app.error_message,
        )
        if app.resource:
            db.resource_html = app.resource.html_content
            db.resource_uri = app.resource.uri
            db.resource_mime_type = app.resource.mime_type
            db.resource_size_bytes = app.resource.size_bytes
            db.resource_resolved_at = app.resource.resolved_at
        return db

    def _update_fields(self, db: MCPAppModel, app: MCPApp) -> None:
        """Update DB model fields from domain entity."""
        db.ui_metadata = app.ui_metadata.to_dict()
        db.status = app.status.value
        db.error_message = app.error_message
        db.source = app.source.value
        db.lifecycle_metadata = app.lifecycle_metadata or {}
        db.updated_at = datetime.now(UTC)

        if app.resource:
            db.resource_html = app.resource.html_content
            db.resource_uri = app.resource.uri
            db.resource_mime_type = app.resource.mime_type
            db.resource_size_bytes = app.resource.size_bytes
            db.resource_resolved_at = app.resource.resolved_at
