"""Redis-backed running state tracking for Actor-based agent execution."""

from __future__ import annotations

import logging

from src.infrastructure.agent.state.agent_worker_state import (
    get_redis_client,
)

logger = logging.getLogger(__name__)


async def set_agent_running(
    conversation_id: str,
    message_id: str,
    ttl_seconds: int = 300,
) -> None:
    """Mark an agent execution as running in Redis."""
    redis_client = await get_redis_client()
    key = f"agent:running:{conversation_id}"
    await redis_client.setex(key, ttl_seconds, message_id)
    logger.info(
        "Set agent running state: %s -> %s (TTL=%ss)",
        key,
        message_id,
        ttl_seconds,
    )


async def clear_agent_running(conversation_id: str) -> None:
    """Clear an agent running state in Redis."""
    redis_client = await get_redis_client()
    key = f"agent:running:{conversation_id}"
    await redis_client.delete(key)
    logger.info("Cleared agent running state: %s", key)


async def refresh_agent_running_ttl(conversation_id: str, ttl_seconds: int = 300) -> None:
    """Refresh the running state TTL while execution continues."""
    redis_client = await get_redis_client()
    key = f"agent:running:{conversation_id}"
    await redis_client.expire(key, ttl_seconds)
    logger.debug("Refreshed agent running TTL: %s (TTL=%ss)", key, ttl_seconds)
