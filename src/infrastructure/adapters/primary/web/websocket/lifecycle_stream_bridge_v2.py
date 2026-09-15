"""Authorized cross-worker Redis lifecycle stream delivery for API WebSockets."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import or_, select

from src.domain.events.envelope import EventEnvelope
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_worker_lifecycle_transport_v2 import (
    lifecycle_routing_key_v2,
)

logger = logging.getLogger(__name__)


async def lifecycle_project_access_v2(context: MessageContext, project_id: str) -> bool:
    async with context.fresh_db_context() as scoped:
        member = await scoped.db.scalar(
            select(UserProject.id)
            .join(Project, Project.id == UserProject.project_id)
            .join(UserTenant, UserTenant.tenant_id == Project.tenant_id)
            .where(
                UserProject.user_id == context.user_id,
                UserProject.project_id == project_id,
                Project.tenant_id == context.tenant_id,
                UserTenant.user_id == context.user_id,
            )
            .limit(1)
        )
    return member is not None


async def start_lifecycle_bridge_v2(context: MessageContext, project_id: str) -> None:
    """Capture the cursor before subscription ACK; no initial event can race past it."""
    client = context.get_scoped_container().redis()
    if client is None:
        raise RuntimeError("Lifecycle event transport is unavailable")
    key = "events:" + lifecycle_routing_key_v2(context.tenant_id, project_id)
    latest = await client.xrevrange(key, count=1)
    cursor = latest[0][0] if latest else "0-0"
    await stop_lifecycle_bridge_v2(context, project_id)
    task = asyncio.create_task(_relay_lifecycle_v2(context, project_id, client, key, cursor))
    context.connection_manager.status_tasks.setdefault(context.session_id, {})[
        f"lifecycle:{project_id}"
    ] = task


async def stop_lifecycle_bridge_v2(context: MessageContext, project_id: str) -> None:
    tasks = context.connection_manager.status_tasks.get(context.session_id, {})
    task = tasks.pop(f"lifecycle:{project_id}", None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _relay_lifecycle_v2(
    context: MessageContext, project_id: str, client: Redis, key: str, cursor: str | bytes
) -> None:
    try:
        while True:
            rows = await client.xread({key: cursor}, count=100, block=1000)
            if not await lifecycle_project_access_v2(context, project_id):
                await context.send_error(
                    _("Project membership required"), code="project_access_denied"
                )
                return
            for _stream, events in rows:
                for sequence_id, fields in events:
                    cursor = sequence_id
                    raw = fields.get("data", fields.get(b"data"))
                    try:
                        envelope = EventEnvelope.from_json(raw)
                    except (TypeError, ValueError, AttributeError):
                        logger.warning("Invalid worker lifecycle envelope skipped")
                        continue
                    message_value: object = envelope.payload
                    if not isinstance(message_value, dict):
                        continue
                    message = message_value
                    if (
                        envelope.metadata.get("tenant_id") != context.tenant_id
                        or envelope.metadata.get("project_id") != project_id
                        or message.get("tenant_id") != context.tenant_id
                        or message.get("project_id") != project_id
                        or message.get("type")
                        not in {"subagent_lifecycle", "agent_lifecycle", "lifecycle_state_change"}
                    ):
                        continue
                    if not await lifecycle_message_access_v2(context, project_id, message):
                        continue
                    await context.send_json(
                        {
                            **message,
                            "event_id": envelope.event_id,
                            "lifecycle_sequence_id": sequence_id.decode()
                            if isinstance(sequence_id, bytes)
                            else sequence_id,
                        }
                    )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Worker lifecycle stream bridge failed for project %s", project_id)
    finally:
        await context.connection_manager.unsubscribe_lifecycle_state(
            context.session_id, context.tenant_id, project_id
        )
        tasks = context.connection_manager.status_tasks.get(context.session_id, {})
        if tasks.get(f"lifecycle:{project_id}") is asyncio.current_task():
            tasks.pop(f"lifecycle:{project_id}", None)


async def lifecycle_message_access_v2(
    context: MessageContext, project_id: str, message: dict[str, Any]
) -> bool:
    """Project membership does not expose another member's private child task."""
    if message.get("type") == "agent_lifecycle":
        from .peer_lifecycle_access_v2 import peer_lifecycle_access_v2

        return await peer_lifecycle_access_v2(context, project_id, message)
    if message.get("type") != "subagent_lifecycle":
        return True
    event = message.get("data")
    nested = event.get("data", event) if isinstance(event, dict) else None
    if not isinstance(nested, dict):
        return False
    conversation_id = nested.get("conversation_id") or event.get("conversation_id")
    run_id = (
        nested.get("run_id")
        or nested.get("execution_id")
        or event.get("run_id")
        or event.get("execution_id")
    )
    if (
        not isinstance(conversation_id, str)
        or not conversation_id
        or not isinstance(run_id, str)
        or not run_id
    ):
        return False
    for data in (event, nested):
        if any(
            data.get(field, expected) != expected
            for field, expected in (
                ("tenant_id", context.tenant_id),
                ("project_id", project_id),
                ("conversation_id", conversation_id),
            )
        ):
            return False
    async with context.fresh_db_context() as scoped:
        row = await scoped.db.scalar(
            select(Conversation.id)
            .join(UserProject, UserProject.project_id == Conversation.project_id)
            .join(UserTenant, UserTenant.tenant_id == Conversation.tenant_id)
            .where(
                Conversation.id == conversation_id,
                Conversation.project_id == project_id,
                Conversation.tenant_id == context.tenant_id,
                UserProject.user_id == context.user_id,
                UserTenant.user_id == context.user_id,
                or_(
                    Conversation.user_id == context.user_id,
                    UserProject.role.in_(("owner", "admin")),
                    UserTenant.role.in_(("owner", "admin")),
                ),
            )
            .limit(1)
        )
    return row is not None
