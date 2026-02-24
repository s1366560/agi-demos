"""
Status Handlers for WebSocket

Handles subscribe_status and unsubscribe_status for agent status polling.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext

logger = logging.getLogger(__name__)


class SubscribeStatusHandler(WebSocketMessageHandler):
    """Handle subscribe_status: Subscribe to Agent Session status updates."""

    @property
    def message_type(self) -> str:
        return "subscribe_status"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle subscribe_status: Subscribe to Agent Session status updates."""
        project_id = message.get("project_id")
        polling_interval = message.get("polling_interval", 3000)  # Default 3 seconds

        if not project_id:
            await context.send_error("Missing project_id")
            return

        try:
            # Start status monitoring task
            task = asyncio.create_task(
                monitor_agent_status(
                    session_id=context.session_id,
                    user_id=context.user_id,
                    tenant_id=context.tenant_id,
                    project_id=project_id,
                    polling_interval_ms=polling_interval,
                )
            )

            await context.connection_manager.subscribe_status(
                context.session_id, project_id, task
            )
            await context.send_ack("subscribe_status", project_id=project_id)

        except Exception as e:
            logger.error(f"[WS] Error subscribing to status: {e}", exc_info=True)
            await context.send_error(str(e))


class UnsubscribeStatusHandler(WebSocketMessageHandler):
    """Handle unsubscribe_status: Stop receiving status updates for a project."""

    @property
    def message_type(self) -> str:
        return "unsubscribe_status"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle unsubscribe_status: Stop receiving status updates."""
        project_id = message.get("project_id")

        if not project_id:
            await context.send_error("Missing project_id")
            return

        await context.connection_manager.unsubscribe_status(context.session_id, project_id)
        await context.send_ack("unsubscribe_status", project_id=project_id)


# =============================================================================
# Helper Functions
# =============================================================================


async def monitor_agent_status(
    session_id: str,
    user_id: str,
    tenant_id: str,
    project_id: str,
    polling_interval_ms: int = 3000,
) -> None:
    """
    Monitor Agent Session status and push updates via WebSocket.

    Runs as a background task and periodically queries the Ray Actor
    status, sending updates to the client when status changes.
    """
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        get_connection_manager,
    )
    from src.infrastructure.adapters.secondary.ray.client import await_ray
    from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists

    manager = get_connection_manager()

    last_status = None

    try:
        while True:
            try:
                # Check if still subscribed
                if session_id not in manager.status_subscriptions:
                    logger.debug(
                        f"[WS Status] Session {session_id[:8]}... not in status_subscriptions"
                    )
                    break
                if project_id not in manager.status_subscriptions.get(session_id, set()):
                    logger.debug(
                        f"[WS Status] Project {project_id} not in session "
                        f"{session_id[:8]}... subscriptions"
                    )
                    break

                status_data = {
                    "is_initialized": False,
                    "is_active": False,
                    "total_chats": 0,
                    "active_chats": 0,
                    "tool_count": 0,
                    "workflow_id": "",
                }

                actor = await get_actor_if_exists(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    agent_mode="default",
                )
                if actor:
                    try:
                        status = await await_ray(actor.status.remote())
                        status_data = {
                            "is_initialized": status.is_initialized,
                            "is_active": status.is_active,
                            "total_chats": status.total_chats,
                            "active_chats": status.active_chats,
                            "tool_count": status.tool_count,
                            "cached_since": status.created_at,
                            "workflow_id": status.actor_id,
                        }
                    except Exception:
                        # Actor not reachable, return default
                        pass

                # Only send if status changed
                if status_data != last_status:
                    await manager.send_to_session(
                        session_id,
                        {
                            "type": "status_update",
                            "project_id": project_id,
                            "data": status_data,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    )
                    last_status = status_data

            except Exception as e:
                logger.warning(f"[WS Status] Error monitoring status: {e}")

            # Wait before next poll
            await asyncio.sleep(polling_interval_ms / 1000)

    except asyncio.CancelledError:
        logger.debug(f"[WS Status] Monitor cancelled for project {project_id}")
    except Exception as e:
        logger.error(f"[WS Status] Unexpected error: {e}", exc_info=True)
