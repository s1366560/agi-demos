"""DI Container initialization for startup."""

import logging
from typing import Any, Optional

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

logger = logging.getLogger(__name__)


def initialize_container(
    graph_service: Any,
    redis_client: Optional[object],
    workflow_engine: Optional[Any],
    temporal_client: Optional[Any],
    mcp_temporal_adapter: Optional[Any],
) -> DIContainer:
    """
    Initialize the DI container with all services.

    Args:
        graph_service: The NativeGraphAdapter instance.
        redis_client: The Redis client instance.
        workflow_engine: The Temporal workflow engine.
        temporal_client: The Temporal client.
        mcp_temporal_adapter: The MCP Temporal adapter.

    Returns:
        Configured DIContainer instance.
    """
    logger.info("Initializing DI container...")
    container = DIContainer(
        session_factory=async_session_factory,
        graph_service=graph_service,
        redis_client=redis_client,
        workflow_engine=workflow_engine,
        temporal_client=temporal_client if workflow_engine else None,
        mcp_temporal_adapter=mcp_temporal_adapter,
    )
    logger.info("DI container initialized")
    return container
