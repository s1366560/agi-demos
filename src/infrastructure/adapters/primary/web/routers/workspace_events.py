"""Workspace event publishing helpers."""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as redis

from src.domain.events.envelope import EventEnvelope
from src.domain.events.types import AgentEventType
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)

logger = logging.getLogger(__name__)


def build_workspace_routing_key(workspace_id: str, event_name: str) -> str:
    """Build workspace routing key using colon convention."""
    return f"workspace:{workspace_id}:{event_name}"


async def publish_workspace_event(
    redis_client: redis.Redis | None,
    *,
    workspace_id: str,
    event_type: AgentEventType,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> None:
    """Publish workspace-scoped event to unified Redis event bus."""
    if redis_client is None:
        return

    envelope = EventEnvelope.wrap(
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id or workspace_id,
        metadata=metadata or {},
    )
    routing_key = build_workspace_routing_key(workspace_id, event_type.value)
    bus = RedisUnifiedEventBusAdapter(redis_client)
    await bus.publish(envelope, routing_key)
    logger.debug(
        "[WorkspaceEvents] published event",
        extra={"workspace_id": workspace_id, "event_type": event_type.value, "routing_key": routing_key},
    )
