"""Project-scoped event subscription handlers for unified WebSocket."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import redis.asyncio as redis
from sqlalchemy import and_, select

from src.domain.ports.services.unified_event_bus_port import SubscriptionOptions
from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.primary.web.websocket.topics import TopicType, get_topic_manager
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)
from src.infrastructure.adapters.secondary.persistence.models import UserProject

logger = logging.getLogger(__name__)


async def _has_project_member(context: MessageContext, project_id: str) -> bool:
    result = await context.db.execute(
        refresh_select_statement(
            select(UserProject).where(
                and_(
                    UserProject.user_id == context.user_id,
                    UserProject.project_id == project_id,
                )
            )
        )
    )
    return result.scalar_one_or_none() is not None


async def _ensure_project_member(context: MessageContext, project_id: str) -> bool:
    if await _has_project_member(context, project_id):
        return True
    await context.send_error("Project membership required", code="project_access_denied")
    return False


class SubscribeProjectEventsHandler(WebSocketMessageHandler):
    """Subscribe to project-scoped events (e.g., reflection_complete, conversation_created)."""

    @property
    def message_type(self) -> str:
        return "subscribe_project_events"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        project_id = message.get("project_id")
        if not project_id:
            await context.send_error("Missing project_id")
            return
        if not await _ensure_project_member(context, project_id):
            return

        topic = f"{TopicType.PROJECT.value}:{project_id}"
        topic_manager = get_topic_manager()
        success = await topic_manager.subscribe(context.session_id, topic)
        if success:
            from_sequence = message.get("from_sequence")
            if not isinstance(from_sequence, str):
                from_sequence = None
            await self._start_project_bridge(context, project_id, from_sequence)
        await context.send_ack("subscribe_project_events", project_id=project_id)

    async def _start_project_bridge(
        self,
        context: MessageContext,
        project_id: str,
        from_sequence: str | None,
    ) -> None:
        container = context.get_scoped_container()
        redis_client = container.redis()
        if redis_client is None:
            return
        task = asyncio.create_task(
            self._project_bridge_loop(context, project_id, redis_client, from_sequence)
        )
        manager = context.connection_manager
        if context.session_id not in manager.status_tasks:
            manager.status_tasks[context.session_id] = {}
        manager.status_tasks[context.session_id][f"project:{project_id}"] = task

    async def _project_bridge_loop(
        self,
        context: MessageContext,
        project_id: str,
        redis_client: redis.Redis,
        from_sequence: str | None,
    ) -> None:
        bus = RedisUnifiedEventBusAdapter(redis_client)
        pattern = f"project:{project_id}:*"
        topic = f"{TopicType.PROJECT.value}:{project_id}"
        task_key = f"project:{project_id}"
        routing_key = f"project:{project_id}:reflection_complete"

        try:
            if from_sequence:
                events = await bus.get_events(
                    routing_key,
                    from_sequence=from_sequence,
                    max_count=500,
                )
                for event in events:
                    if event.sequence_id == from_sequence:
                        continue
                    if not await _has_project_member(context, project_id):
                        await context.send_error(
                            "Project membership required",
                            code="project_access_denied",
                        )
                        return
                    await context.send_json(
                        {
                            "type": event.envelope.event_type,
                            "routing_key": event.routing_key,
                            "project_id": project_id,
                            "data": event.envelope.payload,
                            "event_id": event.envelope.event_id,
                            "sequence_id": event.sequence_id,
                            "timestamp": event.envelope.timestamp,
                        }
                    )

            async for event in bus.subscribe(
                pattern,
                SubscriptionOptions(block_ms=1000, batch_size=100),
            ):
                if not await _has_project_member(context, project_id):
                    await context.send_error(
                        "Project membership required",
                        code="project_access_denied",
                    )
                    break
                await context.send_json(
                    {
                        "type": event.envelope.event_type,
                        "routing_key": event.routing_key,
                        "project_id": project_id,
                        "data": event.envelope.payload,
                        "event_id": event.envelope.event_id,
                        "sequence_id": event.sequence_id,
                        "timestamp": event.envelope.timestamp,
                    }
                )
        except asyncio.CancelledError:
            logger.debug("[WS] project bridge cancelled", extra={"project_id": project_id})
        except Exception as exc:
            logger.warning("[WS] project bridge error: %s", exc)
        finally:
            await get_topic_manager().unsubscribe(context.session_id, topic)
            manager = context.connection_manager
            if context.session_id in manager.status_tasks:
                manager.status_tasks[context.session_id].pop(task_key, None)


class UnsubscribeProjectEventsHandler(WebSocketMessageHandler):
    """Unsubscribe from project-scoped realtime events."""

    @property
    def message_type(self) -> str:
        return "unsubscribe_project_events"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        project_id = message.get("project_id")
        if not project_id:
            await context.send_error("Missing project_id")
            return
        topic = f"{TopicType.PROJECT.value}:{project_id}"
        await get_topic_manager().unsubscribe(context.session_id, topic)
        manager = context.connection_manager
        task_key = f"project:{project_id}"
        if (
            context.session_id in manager.status_tasks
            and task_key in manager.status_tasks[context.session_id]
        ):
            manager.status_tasks[context.session_id][task_key].cancel()
            del manager.status_tasks[context.session_id][task_key]
        await context.send_ack("unsubscribe_project_events", project_id=project_id)


__all__ = ["SubscribeProjectEventsHandler", "UnsubscribeProjectEventsHandler"]
