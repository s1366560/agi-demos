"""DI Container initialization for startup."""

import logging
from typing import Any, Optional

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

logger = logging.getLogger(__name__)

_app_container: Optional[DIContainer] = None


def get_app_container() -> Optional[DIContainer]:
    """Get the initialized application DI container."""
    return _app_container


def initialize_container(
    graph_service: Any,
    redis_client: Optional[object],
    workflow_engine: Optional[Any],
) -> DIContainer:
    """
    Initialize the DI container with all services.

    Args:
        graph_service: The NativeGraphAdapter instance.
        redis_client: The Redis client instance.
        workflow_engine: The workflow engine.

    Returns:
        Configured DIContainer instance.
    """
    global _app_container
    logger.info("Initializing DI container...")
    container = DIContainer(
        session_factory=async_session_factory,
        graph_service=graph_service,
        redis_client=redis_client,
        workflow_engine=workflow_engine,
    )
    _app_container = container
    logger.info("DI container initialized")
    return container
