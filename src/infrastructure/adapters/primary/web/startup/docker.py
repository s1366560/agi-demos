"""Docker services initialization for startup."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.sandbox.docker_event_monitor import (
        DockerEventMonitor,
    )

logger = logging.getLogger(__name__)

# Module-level reference for shutdown
_docker_event_monitor: DockerEventMonitor | None = None


async def initialize_docker_services() -> DockerEventMonitor | None:
    """
    Initialize the Docker event monitor.

    Returns:
        The Docker event monitor instance, or None if initialization fails.
    """
    global _docker_event_monitor

    docker_services_enabled = os.getenv(
        "SANDBOX_DOCKER_SERVICES_ENABLED", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not docker_services_enabled:
        logger.info("Docker sandbox services disabled by SANDBOX_DOCKER_SERVICES_ENABLED")
        return None

    # Start Docker event monitor for real-time container status updates
    try:
        from contextlib import asynccontextmanager

        from src.application.services.sandbox_status_sync_service import SandboxStatusSyncService
        from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
            SqlProjectSandboxRepository,
        )
        from src.infrastructure.adapters.secondary.sandbox.docker_event_monitor import (
            start_docker_event_monitor,
        )

        # Create a repository factory that yields ProjectSandboxRepository instances
        @asynccontextmanager
        async def sandbox_repository_factory() -> AsyncGenerator[Any, None]:
            async with async_session_factory() as session:
                yield SqlProjectSandboxRepository(session)

        async def handle_status_change(
            project_id: str,
            sandbox_id: str,
            new_status: str,
            event_type: str,
        ) -> bool:
            from src.infrastructure.plugins.v2.boundary import (
                current_process_generation_host_v2,
                pin_generation_v2,
            )
            from src.infrastructure.plugins.v2.sandbox_projection import (
                current_sandbox_application_services_v2,
            )

            async with pin_generation_v2(current_process_generation_host_v2()):
                sync_service = SandboxStatusSyncService(
                    repository_factory=sandbox_repository_factory,
                    event_publisher=(current_sandbox_application_services_v2().event_publisher),
                )
                return await sync_service.handle_status_change(
                    project_id,
                    sandbox_id,
                    new_status,
                    event_type,
                )

        # Start monitor with sync service callback
        _docker_event_monitor = await start_docker_event_monitor(
            on_status_change=handle_status_change
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
