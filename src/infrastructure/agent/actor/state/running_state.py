"""Redis-backed running state tracking for Actor-based agent execution."""

from __future__ import annotations

import logging

from src.infrastructure.agent.state.agent_worker_state import (
    get_redis_client,
)

logger = logging.getLogger(__name__)

AGENT_FINISHED_TTL_SECONDS = 1800


def _decode_redis_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


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


async def mark_agent_finished(
    conversation_id: str,
    message_id: str,
    ttl_seconds: int = AGENT_FINISHED_TTL_SECONDS,
) -> None:
    """Record that an actor execution exited for a bounded recovery window."""
    if not conversation_id or not message_id:
        return
    redis_client = await get_redis_client()
    key = f"agent:finished:{conversation_id}"
    await redis_client.setex(key, ttl_seconds, message_id)
    logger.info(
        "Marked agent finished state: %s -> %s (TTL=%ss)",
        key,
        message_id,
        ttl_seconds,
    )


async def clear_agent_running(conversation_id: str, message_id: str | None = None) -> None:
    """Clear an agent running state in Redis."""
    redis_client = await get_redis_client()
    key = f"agent:running:{conversation_id}"
    stored_message_id = _decode_redis_value(await redis_client.get(key))
    await redis_client.delete(key)
    finished_message_id = message_id or stored_message_id
    if finished_message_id:
        await redis_client.setex(
            f"agent:finished:{conversation_id}",
            AGENT_FINISHED_TTL_SECONDS,
            finished_message_id,
        )
    logger.info("Cleared agent running state: %s", key)


async def refresh_agent_running_ttl(conversation_id: str, ttl_seconds: int = 300) -> None:
    """Refresh the running state TTL while execution continues."""
    redis_client = await get_redis_client()
    key = f"agent:running:{conversation_id}"
    await redis_client.expire(key, ttl_seconds)
    logger.debug("Refreshed agent running TTL: %s (TTL=%ss)", key, ttl_seconds)
