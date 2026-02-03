"""Shared utilities for MCP API.

Contains dependency functions and helper utilities.
"""

import logging

from fastapi import HTTPException, Request, status
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
        mcp_temporal_adapter=app_container._mcp_temporal_adapter,
    )


async def get_mcp_temporal_adapter(request: Request):
    """Get MCPTemporalAdapter from DI container."""
    container = request.app.state.container
    adapter = await container.mcp_temporal_adapter()
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal service is not available. MCP Temporal features require Temporal server.",
        )
    return adapter
