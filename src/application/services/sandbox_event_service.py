"""Sandbox Event Publisher Service.

Publishes sandbox lifecycle and status events to Redis streams.
"""

import logging
from typing import Any, Optional

from src.domain.events.agent_events import (
    AgentDesktopStartedEvent,
    AgentDesktopStoppedEvent,
    AgentDesktopStatusEvent,
    AgentSandboxCreatedEvent,
    AgentSandboxStatusEvent,
    AgentSandboxTerminatedEvent,
    AgentTerminalStartedEvent,
    AgentTerminalStoppedEvent,
    AgentTerminalStatusEvent,
)

logger = logging.getLogger(__name__)


class SandboxEventPublisher:
    """Publishes sandbox events to Redis streams."""

    def __init__(self, event_bus: Optional[Any] = None):
        """
        Initialize publisher.

        Args:
            event_bus: RedisEventBusAdapter instance (optional for testing)
        """
        self._event_bus = event_bus

    async def publish_sandbox_created(
        self,
        project_id: str,
        sandbox_id: str,
        status: str,
        endpoint: Optional[str] = None,
        websocket_url: Optional[str] = None,
    ) -> str:
        """Emit sandbox_created event."""
        event = AgentSandboxCreatedEvent(
            sandbox_id=sandbox_id,
            project_id=project_id,
            status=status,
            endpoint=endpoint,
            websocket_url=websocket_url,
        )
        return await self._publish(project_id, event)

    async def publish_sandbox_terminated(
        self,
        project_id: str,
        sandbox_id: str,
    ) -> str:
        """Emit sandbox_terminated event."""
        event = AgentSandboxTerminatedEvent(sandbox_id=sandbox_id)
        return await self._publish(project_id, event)

    async def publish_sandbox_status(
        self,
        project_id: str,
        sandbox_id: str,
        status: str,
    ) -> str:
        """Emit sandbox_status event."""
        event = AgentSandboxStatusEvent(
            sandbox_id=sandbox_id,
            status=status,
        )
        return await self._publish(project_id, event)

    async def publish_desktop_started(
        self,
        project_id: str,
        sandbox_id: str,
        url: Optional[str] = None,
        display: str = ":1",
        resolution: str = "1280x720",
        port: int = 6080,
    ) -> str:
        """Emit desktop_started event."""
        event = AgentDesktopStartedEvent(
            sandbox_id=sandbox_id,
            url=url,
            display=display,
            resolution=resolution,
            port=port,
        )
        return await self._publish(project_id, event)

    async def publish_desktop_stopped(
        self,
        project_id: str,
        sandbox_id: str,
    ) -> str:
        """Emit desktop_stopped event."""
        event = AgentDesktopStoppedEvent(sandbox_id=sandbox_id)
        return await self._publish(project_id, event)

    async def publish_desktop_status(
        self,
        project_id: str,
        sandbox_id: str,
        running: bool,
        url: Optional[str] = None,
        display: str = "",
        resolution: str = "",
        port: int = 0,
    ) -> str:
        """Emit desktop_status event."""
        event = AgentDesktopStatusEvent(
            sandbox_id=sandbox_id,
            running=running,
            url=url,
            display=display,
            resolution=resolution,
            port=port,
        )
        return await self._publish(project_id, event)

    async def publish_terminal_started(
        self,
        project_id: str,
        sandbox_id: str,
        url: Optional[str] = None,
        port: int = 7681,
        session_id: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> str:
        """Emit terminal_started event."""
        event = AgentTerminalStartedEvent(
            sandbox_id=sandbox_id,
            url=url,
            port=port,
            session_id=session_id,
            pid=pid,
        )
        return await self._publish(project_id, event)

    async def publish_terminal_stopped(
        self,
        project_id: str,
        sandbox_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        """Emit terminal_stopped event."""
        event = AgentTerminalStoppedEvent(
            sandbox_id=sandbox_id,
            session_id=session_id,
        )
        return await self._publish(project_id, event)

    async def publish_terminal_status(
        self,
        project_id: str,
        sandbox_id: str,
        running: bool,
        url: Optional[str] = None,
        port: int = 0,
        session_id: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> str:
        """Emit terminal_status event."""
        event = AgentTerminalStatusEvent(
            sandbox_id=sandbox_id,
            running=running,
            url=url,
            port=port,
            session_id=session_id,
            pid=pid,
        )
        return await self._publish(project_id, event)

    async def _publish(self, project_id: str, event) -> str:
        """Publish event to project-level Redis stream."""
        if not self._event_bus:
            logger.warning("Event bus not available, skipping sandbox event")
            return ""

        stream_key = f"sandbox:events:{project_id}"
        event_dict = event.to_event_dict()

        # Add project_id for routing
        event_dict["project_id"] = project_id

        # Publish to stream (persistent) with trim
        message_id = await self._event_bus.stream_add(
            stream_key,
            event_dict,
            maxlen=1000
        )

        # Also publish to Pub/Sub for real-time
        await self._event_bus.publish(stream_key, event_dict)

        logger.info(
            f"[SandboxEvent] Published {event.event_type.value} "
            f"to {stream_key} (msg_id={message_id})"
        )
        return message_id
