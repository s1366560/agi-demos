"""Docker Event Monitor - Real-time container status monitoring.

Listens to Docker daemon events and publishes sandbox status changes
to the event bus for real-time frontend updates.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import docker
from docker.errors import DockerException

logger = logging.getLogger(__name__)

# Container labels used to identify our sandbox containers
SANDBOX_LABEL_KEY = "memstack.sandbox"
PROJECT_LABEL_KEY = "memstack.project_id"
TENANT_LABEL_KEY = "memstack.tenant_id"

# Docker events we care about
CONTAINER_EVENTS = {
    "start": "running",
    "stop": "stopped",
    "die": "stopped",
    "kill": "stopped",
    "oom": "error",
    "pause": "stopped",
    "unpause": "running",
    "restart": "running",
    "destroy": "terminated",
}


class DockerEventMonitor:
    """Monitor Docker daemon events for sandbox container status changes.

    Uses Docker Events API to receive real-time notifications when containers
    change state (start, stop, die, kill, oom, etc.).

    When a sandbox container status changes:
    1. Updates the database record
    2. Publishes SSE event for frontend real-time update
    """

    def __init__(
        self,
        on_status_change: Callable[[str, str, str, str], Awaitable[bool]] | None = None,
        docker_client: docker.DockerClient | None = None,
    ) -> None:
        """Initialize the monitor.

        Args:
            on_status_change: Async callback(project_id, sandbox_id, new_status, event_type)
            docker_client: Optional Docker client (for testing)
        """
        self._on_status_change = on_status_change
        self._docker = docker_client
        self._running = False
        self._monitor_task: asyncio.Task[None] | None = None
        self._tracked_containers: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None  # Store main event loop

    async def start(self) -> None:
        """Start monitoring Docker events."""
        if self._running:
            logger.warning("[DockerEventMonitor] Already running")
            return

        # Capture the main event loop for use in thread pool callbacks
        self._loop = asyncio.get_running_loop()

        # Initialize Docker client
        if not self._docker:
            try:
                self._docker = docker.from_env()
                logger.info("[DockerEventMonitor] Docker client initialized")
            except DockerException as e:
                logger.error(f"[DockerEventMonitor] Failed to connect to Docker: {e}")
                return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("[DockerEventMonitor] Started monitoring Docker events")

    async def stop(self) -> None:
        """Stop monitoring Docker events."""
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

        logger.info("[DockerEventMonitor] Stopped monitoring Docker events")

    def is_running(self) -> bool:
        """Check if monitor is running."""
        return self._running

    async def _monitor_loop(self) -> None:
        """Main monitoring loop - listens to Docker events."""
        while self._running:
            try:
                # Run blocking Docker events in thread pool
                await asyncio.get_event_loop().run_in_executor(None, self._process_events)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DockerEventMonitor] Error in monitor loop: {e}")
                # Wait before retry
                await asyncio.sleep(5)

    def _process_events(self) -> None:
        """Process Docker events (runs in thread pool)."""
        if not self._docker:
            return

        try:
            # Listen for container events
            events = self._docker.events(
                decode=True,
                filters={
                    "type": "container",
                    "event": list(CONTAINER_EVENTS.keys()),
                },
            )

            for event in events:
                if not self._running:
                    break

                self._handle_event(event)

        except Exception as e:
            if self._running:
                logger.error(f"[DockerEventMonitor] Events stream error: {e}")

    def _handle_event(self, event: dict[str, Any]) -> None:
        """Handle a single Docker event."""
        action = event.get("Action", "")
        actor = event.get("Actor", {})
        container_id = actor.get("ID", "")[:12]
        attributes = actor.get("Attributes", {})

        # Check if this is a sandbox container
        if SANDBOX_LABEL_KEY not in attributes:
            return

        project_id = attributes.get(PROJECT_LABEL_KEY, "")
        # tenant_id = attributes.get(TENANT_LABEL_KEY, "")  # Reserved for future multi-tenant filtering
        sandbox_id = attributes.get("name", container_id)

        new_status = CONTAINER_EVENTS.get(action)
        if not new_status:
            return

        logger.info(
            f"[DockerEventMonitor] Container event: {action} -> {new_status} "
            f"(sandbox={sandbox_id}, project={project_id})"
        )

        # Schedule async callback using the captured main event loop
        if self._on_status_change and project_id and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._on_status_change(project_id, sandbox_id, new_status, action), self._loop  # type: ignore[arg-type]
                )
            except Exception as e:
                logger.error(f"[DockerEventMonitor] Callback error: {e}")

    async def sync_current_state(self) -> dict[str, str]:
        """Sync current state of all sandbox containers.

        Returns:
            Dict mapping container_id to current status
        """
        if not self._docker:
            return {}

        result = {}

        try:
            containers = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._docker.containers.list(  # type: ignore[union-attr]
                    all=True, filters={"label": SANDBOX_LABEL_KEY}
                ),
            )

            for container in containers:
                container_id = container.short_id
                status_map = {
                    "running": "running",
                    "paused": "stopped",
                    "exited": "stopped",
                    "created": "creating",
                    "restarting": "running",
                    "removing": "terminated",
                    "dead": "error",
                }
                result[container_id] = status_map.get(container.status, "unknown")

            logger.info(f"[DockerEventMonitor] Synced {len(result)} sandbox containers")

        except Exception as e:
            logger.error(f"[DockerEventMonitor] Sync error: {e}")

        return result


# Global monitor instance
_monitor: DockerEventMonitor | None = None


def get_docker_event_monitor() -> DockerEventMonitor | None:
    """Get the global Docker event monitor instance."""
    return _monitor


async def start_docker_event_monitor(
    on_status_change: Callable[[str, str, str, str], Awaitable[bool]],
) -> DockerEventMonitor:
    """Start the global Docker event monitor.

    Args:
        on_status_change: Async callback(project_id, sandbox_id, new_status, event_type)

    Returns:
        DockerEventMonitor instance
    """
    global _monitor

    if _monitor and _monitor.is_running():
        logger.warning("[DockerEventMonitor] Monitor already running")
        return _monitor

    _monitor = DockerEventMonitor(on_status_change=on_status_change)
    await _monitor.start()

    return _monitor


async def stop_docker_event_monitor() -> None:
    """Stop the global Docker event monitor."""
    global _monitor

    if _monitor:
        await _monitor.stop()
        _monitor = None
