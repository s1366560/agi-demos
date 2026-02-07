"""Common utilities for Agent API endpoints."""

import logging

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer

logger = logging.getLogger(__name__)


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.

    This creates a new container with the request's db session while preserving
    the graph_service and redis_client from the app state container.
    """
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
    )
