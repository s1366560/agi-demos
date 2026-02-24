"""
Sandbox Subscription Handlers for WebSocket

Handles sandbox event subscriptions via unified WebSocket.
Migrates from SSE endpoint to WebSocket for unified event delivery.

Topic Format: sandbox:{project_id}
"""

import asyncio
import logging
from typing import Any

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
    get_connection_manager,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.primary.web.websocket.topics import TopicType, get_topic_manager

logger = logging.getLogger(__name__)


class SubscribeSandboxHandler(WebSocketMessageHandler):
    """
    Handle subscribe_sandbox: Subscribe to sandbox lifecycle events.

    Message format:
    {
        "type": "subscribe_sandbox",
        "project_id": "proj-123"
    }
    """

    @property
    def message_type(self) -> str:
        return "subscribe_sandbox"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle sandbox subscription request."""
        project_id = message.get("project_id")

        if not project_id:
            await context.send_error("Missing project_id")
            return

        try:
            # Build topic key
            topic = f"{TopicType.SANDBOX.value}:{project_id}"

            # Subscribe via topic manager
            topic_manager = get_topic_manager()
            success = await topic_manager.subscribe(context.session_id, topic)

            if success:
                # Start bridge task to forward Redis events to WebSocket
                await self._start_sandbox_bridge(context, project_id)

                await context.send_ack("subscribe_sandbox", project_id=project_id)
                logger.info(
                    f"[WS] Session {context.session_id[:8]}... subscribed to sandbox:{project_id}"
                )
            else:
                # Already subscribed
                await context.send_ack(
                    "subscribe_sandbox",
                    project_id=project_id,
                    message="Already subscribed",
                )

        except Exception as e:
            logger.error(f"[WS] Error subscribing to sandbox: {e}", exc_info=True)
            await context.send_error(str(e), project_id=project_id)

    async def _start_sandbox_bridge(self, context: MessageContext, project_id: str) -> None:
        """Start background task to bridge Redis sandbox events to WebSocket."""
        container = context.get_scoped_container()

        # Get event publisher (which has Redis event bus access)
        try:
            event_publisher: SandboxEventPublisher | None = container.sandbox_event_publisher()
        except Exception:
            event_publisher = None

        if not event_publisher or not event_publisher._event_bus:
            logger.warning(f"[WS] Sandbox event bus not available for project {project_id}")
            return

        # Create bridge task
        task = asyncio.create_task(self._sandbox_bridge_loop(context, project_id, event_publisher))

        # Store task for cleanup (using status_tasks as sandbox_tasks)
        manager = get_connection_manager()
        if context.session_id not in manager.status_tasks:
            manager.status_tasks[context.session_id] = {}
        manager.status_tasks[context.session_id][f"sandbox:{project_id}"] = task

    async def _sandbox_bridge_loop(
        self,
        context: MessageContext,
        project_id: str,
        event_publisher: SandboxEventPublisher,
    ) -> None:
        """
        Bridge loop that reads from Redis Stream and forwards to WebSocket.

        This runs until the client disconnects or unsubscribes.
        """
        stream_key = f"sandbox:events:{project_id}"
        event_bus = event_publisher._event_bus
        last_id = "0"

        logger.debug(f"[WS] Starting sandbox bridge for {stream_key}")

        try:
            while True:
                # Check if still connected
                ws = get_connection_manager().get_connection(context.session_id)
                if not ws:
                    break

                # Read from Redis Stream
                async for message in event_bus.stream_read(
                    stream_key=stream_key,
                    last_id=last_id,
                    count=100,
                    block_ms=5000,
                ):
                    # Update last_id for next iteration
                    last_id = message.get("id", last_id)
                    event_data = message.get("data", {})

                    # Forward to WebSocket with routing key
                    await context.send_json(
                        {
                            "type": "sandbox_event",
                            "routing_key": f"sandbox:{project_id}",
                            "project_id": project_id,
                            "data": event_data,
                            "event_id": last_id,
                        }
                    )

        except asyncio.CancelledError:
            logger.debug(f"[WS] Sandbox bridge cancelled for {stream_key}")
        except Exception as e:
            logger.error(f"[WS] Sandbox bridge error for {stream_key}: {e}")


class UnsubscribeSandboxHandler(WebSocketMessageHandler):
    """
    Handle unsubscribe_sandbox: Stop receiving sandbox events.

    Message format:
    {
        "type": "unsubscribe_sandbox",
        "project_id": "proj-123"
    }
    """

    @property
    def message_type(self) -> str:
        return "unsubscribe_sandbox"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle sandbox unsubscription request."""
        project_id = message.get("project_id")

        if not project_id:
            await context.send_error("Missing project_id")
            return

        try:
            # Build topic key
            topic = f"{TopicType.SANDBOX.value}:{project_id}"

            # Unsubscribe via topic manager
            topic_manager = get_topic_manager()
            await topic_manager.unsubscribe(context.session_id, topic)

            # Cancel bridge task
            manager = get_connection_manager()
            task_key = f"sandbox:{project_id}"
            if (
                context.session_id in manager.status_tasks
                and task_key in manager.status_tasks[context.session_id]
            ):
                manager.status_tasks[context.session_id][task_key].cancel()
                del manager.status_tasks[context.session_id][task_key]

            await context.send_ack("unsubscribe_sandbox", project_id=project_id)
            logger.info(
                f"[WS] Session {context.session_id[:8]}... unsubscribed from sandbox:{project_id}"
            )

        except Exception as e:
            logger.error(f"[WS] Error unsubscribing from sandbox: {e}", exc_info=True)
            await context.send_error(str(e), project_id=project_id)
