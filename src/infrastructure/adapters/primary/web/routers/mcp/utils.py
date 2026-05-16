"""Shared utilities for MCP API.

Contains dependency functions and helper utilities.
"""

import logging
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Project
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.
    """
    app_container: DIContainer = request.app.state.container
    return app_container.with_db(db)


async def get_sandbox_mcp_server_manager(request: Request, db: AsyncSession) -> Any:
    """Get SandboxMCPServerManager from DI container.

    Creates a fresh container with the current DB session to ensure
    proper transaction scoping.
    """
    container = get_container_with_db(request, db)
    return container.sandbox_mcp_server_manager()


async def ensure_project_access(db: AsyncSession, project_id: str, tenant_id: str) -> None:
    """Ensure project belongs to the requesting tenant.

    NOTE (M12 audit): This single-field existence check uses raw SQLAlchemy
    deliberately.  It lives in the infrastructure/router layer (not domain or
    application) and mirrors identical patterns in projects.py and memories.py.
    Creating a dedicated repository method for a one-off access guard would
    add unnecessary abstraction.
    """
    result = await db.execute(
        refresh_select_statement(select(Project.id).where(
            Project.id == project_id,
            Project.tenant_id == tenant_id,
        ))
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        )
