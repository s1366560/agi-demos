"""DI Container initialization for startup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_app_container: DIContainer | None = None


def get_app_container() -> DIContainer | None:
    """Get the initialized application DI container."""
    return _app_container


def initialize_container(
    redis_client: object | None,
) -> DIContainer:
    """
    Initialize the DI container with all services.

    Args:
        redis_client: The Redis client instance.

    Returns:
        Configured DIContainer instance.
    """
    global _app_container
    logger.info("Initializing DI container...")
    typed_redis_client = cast("Redis | None", redis_client)
    container = DIContainer(
        session_factory=async_session_factory,
        redis_client=typed_redis_client,
    )
    _app_container = container
    logger.info("DI container initialized")
    return container
