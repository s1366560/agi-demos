"""Shared utilities for MCP API.

Contains dependency functions and helper utilities.
"""

import logging

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer

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


async def get_sandbox_mcp_server_manager(request: Request, db: AsyncSession):
    """Get SandboxMCPServerManager from DI container.

    Creates a fresh container with the current DB session to ensure
    proper transaction scoping.
    """
    container = get_container_with_db(request, db)
    return container.sandbox_mcp_server_manager()
