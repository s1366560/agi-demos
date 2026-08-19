"""Workspace subscription handlers for unified WebSocket."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, override

import redis.asyncio as redis

from src.domain.ports.services.unified_event_bus_port import SubscriptionOptions
from src.domain.ports.services.workspace_access_verifier_port import (
    WorkspaceAccessRequest,
    WorkspaceAccessVerifier,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.primary.web.websocket.topics import TopicType, get_topic_manager
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)

logger = logging.getLogger(__name__)

_workspace_access_verifier: WorkspaceAccessVerifier | None = None


def configure_workspace_access_verifier(verifier: WorkspaceAccessVerifier | None) -> None:
    """Configure the process-wide verifier selected by the Workspace backend."""
    global _workspace_access_verifier
    _workspace_access_verifier = verifier


async def _has_workspace_member(context: MessageContext, workspace_id: str) -> bool:
    """Check whether the current websocket user still belongs to the workspace."""
    if _workspace_access_verifier is None:
        return False
    return await _workspace_access_verifier.has_access(
        WorkspaceAccessRequest(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            workspace_id=workspace_id,
        )
    )


async def _ensure_workspace_member(context: MessageContext, workspace_id: str) -> bool:
    """Reject workspace-scoped websocket actions for non-members."""
    if await _has_workspace_member(context, workspace_id):
        return True
    await context.send_error("Workspace membership required", code="workspace_access_denied")
    return False


class SubscribeWorkspaceHandler(WebSocketMessageHandler):
    """Subscribe to workspace events."""

    @property
    def message_type(self) -> str:
        return "subscribe_workspace"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        workspace_id = message.get("workspace_id")
        if not workspace_id:
            await context.send_error("Missing workspace_id")
            return
        if not await _ensure_workspace_member(context, workspace_id):
            return

        topic = f"{TopicType.WORKSPACE.value}:{workspace_id}"
        topic_manager = get_topic_manager()
        success = await topic_manager.subscribe(context.session_id, topic)
        if success:
            await self._start_workspace_bridge(context, workspace_id)
        await context.send_ack("subscribe_workspace", workspace_id=workspace_id)

    async def _start_workspace_bridge(self, context: MessageContext, workspace_id: str) -> None:
        container = context.get_scoped_container()
        redis_client = container.redis()
        if redis_client is None:
            return
        task = asyncio.create_task(self._workspace_bridge_loop(context, workspace_id, redis_client))
        manager = context.connection_manager
        if context.session_id not in manager.status_tasks:
            manager.status_tasks[context.session_id] = {}
        manager.status_tasks[context.session_id][f"workspace:{workspace_id}"] = task

    async def _workspace_bridge_loop(
        self,
        context: MessageContext,
        workspace_id: str,
        redis_client: redis.Redis,
    ) -> None:
        bus = RedisUnifiedEventBusAdapter(redis_client)
        # Core publishes lifecycle/mutation events to the bare two-segment
        # stream (workspace:{id}) while legacy/agent publishers use
        # three-segment topics (workspace:{id}:chat etc.) — match both.
        patterns = (f"workspace:{workspace_id}", f"workspace:{workspace_id}:*")
        topic = f"{TopicType.WORKSPACE.value}:{workspace_id}"
        task_key = f"workspace:{workspace_id}"
        queue: asyncio.Queue[Any] = asyncio.Queue()
        pump_done = object()

        async def pump(pattern: str) -> None:
            try:
                async for event in bus.subscribe(
                    pattern,
                    SubscriptionOptions(block_ms=1000, batch_size=100),
                ):
                    await queue.put(event)
            finally:
                await queue.put(pump_done)

        pump_tasks = [asyncio.create_task(pump(pattern)) for pattern in patterns]
        finished_pumps = 0
        try:
            while True:
                event = await queue.get()
                if event is pump_done:
                    finished_pumps += 1
                    if finished_pumps == len(pump_tasks):
                        break
                    continue
                # workspace_deleted must bypass the membership re-check: the
                # verifier is fail-closed and the workspace no longer exists,
                # so the check would swallow exactly the event that notifies
                # the client about the deletion.
                is_deleted_event = event.envelope.event_type == "workspace_deleted"
                if not is_deleted_event and not await _has_workspace_member(context, workspace_id):
                    await context.send_error(
                        "Workspace membership required",
                        code="workspace_access_denied",
                    )
                    break
                await context.send_json(
                    {
                        "type": event.envelope.event_type,
                        "routing_key": event.routing_key,
                        "workspace_id": workspace_id,
                        "data": event.envelope.payload,
                        "event_id": event.envelope.event_id,
                        "timestamp": event.envelope.timestamp,
                    }
                )
        except asyncio.CancelledError:
            logger.debug("[WS] workspace bridge cancelled", extra={"workspace_id": workspace_id})
        except Exception as exc:
            logger.warning("[WS] workspace bridge error: %s", exc)
        finally:
            for pump_task in pump_tasks:
                pump_task.cancel()
            await get_topic_manager().unsubscribe(context.session_id, topic)
            manager = context.connection_manager
            if context.session_id in manager.status_tasks:
                manager.status_tasks[context.session_id].pop(task_key, None)


class UnsubscribeWorkspaceHandler(WebSocketMessageHandler):
    """Unsubscribe from workspace events."""

    @property
    def message_type(self) -> str:
        return "unsubscribe_workspace"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        workspace_id = message.get("workspace_id")
        if not workspace_id:
            await context.send_error("Missing workspace_id")
            return
        topic = f"{TopicType.WORKSPACE.value}:{workspace_id}"
        await get_topic_manager().unsubscribe(context.session_id, topic)
        manager = context.connection_manager
        task_key = f"workspace:{workspace_id}"
        if (
            context.session_id in manager.status_tasks
            and task_key in manager.status_tasks[context.session_id]
        ):
            manager.status_tasks[context.session_id][task_key].cancel()
            del manager.status_tasks[context.session_id][task_key]
        await context.send_ack("unsubscribe_workspace", workspace_id=workspace_id)


class WorkspacePresenceJoinHandler(WebSocketMessageHandler):
    """Handle user joining workspace presence."""

    @property
    @override
    def message_type(self) -> str:
        return "workspace_presence_join"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        workspace_id = message.get("workspace_id")
        if not workspace_id:
            await context.send_error("Missing workspace_id")
            return
        if not await _ensure_workspace_member(context, workspace_id):
            return

        display_name = message.get("display_name", "")
        if not display_name:
            await context.send_error("Missing display_name")
            return

        container = context.get_scoped_container()
        redis_client = container.redis()
        if redis_client is None:
            await context.send_error("Redis unavailable")
            return

        from src.application.services.workspace_presence_service import (
            WorkspacePresenceService,
        )

        service = WorkspacePresenceService(redis_client)
        online_users = await service.join(workspace_id, context.user_id, display_name)
        await context.send_ack(
            "workspace_presence_join",
            workspace_id=workspace_id,
            online_users=online_users,
        )


class WorkspacePresenceLeaveHandler(WebSocketMessageHandler):
    """Handle user leaving workspace presence."""

    @property
    @override
    def message_type(self) -> str:
        return "workspace_presence_leave"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        workspace_id = message.get("workspace_id")
        if not workspace_id:
            await context.send_error("Missing workspace_id")
            return

        container = context.get_scoped_container()
        redis_client = container.redis()
        if redis_client is None:
            await context.send_error("Redis unavailable")
            return

        from src.application.services.workspace_presence_service import (
            WorkspacePresenceService,
        )

        service = WorkspacePresenceService(redis_client)
        await service.leave(workspace_id, context.user_id)
        await context.send_ack("workspace_presence_leave", workspace_id=workspace_id)


class WorkspaceHeartbeatHandler(WebSocketMessageHandler):
    """Handle workspace heartbeat to keep presence alive."""

    @property
    @override
    def message_type(self) -> str:
        return "workspace_heartbeat"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        workspace_id = message.get("workspace_id")
        if not workspace_id:
            await context.send_error("Missing workspace_id")
            return
        if not await _ensure_workspace_member(context, workspace_id):
            return

        container = context.get_scoped_container()
        redis_client = container.redis()
        if redis_client is None:
            return

        from src.application.services.workspace_presence_service import (
            WorkspacePresenceService,
        )

        service = WorkspacePresenceService(redis_client)
        await service.heartbeat(workspace_id, context.user_id)
        await context.send_ack("workspace_heartbeat", workspace_id=workspace_id)
