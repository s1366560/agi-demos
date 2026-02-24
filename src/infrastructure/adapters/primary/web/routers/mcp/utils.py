"""Shared utilities for MCP API.

Contains dependency functions and helper utilities.
"""

import logging
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.models import Project

logger = logging.getLogger(__name__)


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.
    """
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
    )


async def get_sandbox_mcp_server_manager(request: Request, db: AsyncSession) -> Any:
    """Get SandboxMCPServerManager from DI container.

    Creates a fresh container with the current DB session to ensure
    proper transaction scoping.
    """
    container = get_container_with_db(request, db)
    return container.sandbox_mcp_server_manager()


async def ensure_project_access(db: AsyncSession, project_id: str, tenant_id: str) -> None:
    """Ensure project belongs to the requesting tenant."""
    result = await db.execute(
        select(Project.id).where(
            Project.id == project_id,
            Project.tenant_id == tenant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
