"""Docker services initialization for startup."""

import logging
from typing import Any, Optional

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

logger = logging.getLogger(__name__)

# Module-level reference for shutdown
_docker_event_monitor: Optional[Any] = None


async def initialize_docker_services(container: DIContainer) -> Optional[Any]:
    """
    Initialize Docker-related services including sandbox sync and event monitor.

    Args:
        container: The DI container for getting services.

    Returns:
        The Docker event monitor instance, or None if initialization fails.
    """
    global _docker_event_monitor

    # Sync existing sandbox containers from Docker
    logger.info("Syncing existing sandbox containers from Docker...")
    try:
        from src.infrastructure.adapters.primary.web.routers.sandbox import (
            ensure_sandbox_sync,
        )

        await ensure_sandbox_sync()
    except Exception as e:
        logger.warning(f"Failed to sync sandbox containers from Docker: {e}")

    # Start Docker event monitor for real-time container status updates
    try:
        from src.application.services.sandbox_status_sync_service import SandboxStatusSyncService
        from src.infrastructure.adapters.secondary.sandbox.docker_event_monitor import (
            start_docker_event_monitor,
        )

        # Get event publisher from container (already configured with Redis event bus)
        event_publisher = container.sandbox_event_publisher()

        # Create a repository factory that yields ProjectSandboxRepository instances
        from contextlib import asynccontextmanager

        from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
            SqlProjectSandboxRepository,
        )

        @asynccontextmanager
        async def sandbox_repository_factory():
            async with async_session_factory() as session:
                yield SqlProjectSandboxRepository(session)

        # Create status sync service
        sync_service = SandboxStatusSyncService(
            repository_factory=sandbox_repository_factory,
            event_publisher=event_publisher,
        )

        # Start monitor with sync service callback
        _docker_event_monitor = await start_docker_event_monitor(
            on_status_change=sync_service.handle_status_change
        )
        logger.info("Docker event monitor started for real-time container status updates")
        return _docker_event_monitor
    except Exception as e:
        logger.warning(f"Failed to start Docker event monitor: {e}")
        return None


async def shutdown_docker_services() -> None:
    """Stop Docker event monitor."""
    global _docker_event_monitor

    if _docker_event_monitor:
        try:
            from src.infrastructure.adapters.secondary.sandbox.docker_event_monitor import (
                stop_docker_event_monitor,
            )

            await stop_docker_event_monitor()
            logger.info("Docker event monitor stopped")
        except Exception as e:
            logger.warning(f"Error stopping Docker event monitor: {e}")
