"""Helpers for publishing project-scoped conversation lifecycle events."""

from __future__ import annotations

import logging

import redis.asyncio as redis

from src.domain.events.envelope import EventEnvelope
from src.domain.model.agent import Conversation
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)

logger = logging.getLogger(__name__)


def build_conversation_created_payload(conversation: Conversation) -> dict[str, object]:
    """Create a stable payload shape for ``conversation_created`` events."""
    return {
        "conversation_id": conversation.id,
        "project_id": conversation.project_id,
        "tenant_id": conversation.tenant_id,
        "title": conversation.title,
        "status": conversation.status.value,
        "created_at": conversation.created_at.isoformat(),
    }


async def publish_conversation_created(
    *,
    redis_client: redis.Redis,
    conversation: Conversation,
) -> None:
    """Publish ``conversation_created`` to the project event stream.

    Routing key convention: ``project:{project_id}:conversation_created``.
    """
    payload = build_conversation_created_payload(conversation)
    envelope = EventEnvelope(event_type="conversation_created", payload=payload)
    routing_key = f"project:{conversation.project_id}:conversation_created"
    try:
        bus = RedisUnifiedEventBusAdapter(redis_client)
        await bus.publish(envelope, routing_key)
    except Exception:
        logger.exception(
            "Failed to publish conversation_created",
            extra={
                "conversation_id": conversation.id,
                "project_id": conversation.project_id,
            },
        )


__all__ = [
    "build_conversation_created_payload",
    "publish_conversation_created",
]
