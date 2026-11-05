"""Redis-backed running state tracking for Actor-based agent execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

AGENT_FINISHED_TTL_SECONDS = 1800
AGENT_HEARTBEAT_INTERVAL_SECONDS = 30

_REFRESH_OWNED_RUNNING = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


def _current_redis_client_v2() -> Redis:
    from src.infrastructure.plugins.v2.agent_worker_runtime import (
        current_agent_worker_redis_client_v2,
    )

    return current_agent_worker_redis_client_v2()


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
    redis_client = _current_redis_client_v2()
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
    redis_client = _current_redis_client_v2()
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
    redis_client = _current_redis_client_v2()
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


async def refresh_agent_running_ttl(
    conversation_id: str, ttl_seconds: int = 300, *, message_id: str | None = None
) -> None:
    """Refresh the running state TTL while execution continues."""
    redis_client = _current_redis_client_v2()
    key = f"agent:running:{conversation_id}"
    if message_id is None:
        await redis_client.expire(key, ttl_seconds)
    else:
        # An old turn must never renew a newer turn's running marker.
        _ = await cast(
            Awaitable[object],
            redis_client.eval(_REFRESH_OWNED_RUNNING, 1, key, message_id, ttl_seconds),
        )
    logger.debug("Refreshed agent running TTL: %s (TTL=%ss)", key, ttl_seconds)


def start_agent_running_heartbeat(conversation_id: str, message_id: str) -> asyncio.Task[None]:
    """Renew the live turn while model, tool, and human-interaction awaits are silent."""

    async def renew() -> None:
        while True:
            await asyncio.sleep(AGENT_HEARTBEAT_INTERVAL_SECONDS)
            try:
                await refresh_agent_running_ttl(conversation_id, message_id=message_id)
            except Exception:
                logger.warning("Agent running heartbeat unavailable for %s", conversation_id)

    return asyncio.create_task(renew(), name=f"agent-running-heartbeat:{conversation_id}")


async def stop_agent_running_heartbeat(heartbeat: asyncio.Task[None]) -> None:
    """Join the heartbeat before clearing the running marker or releasing its operation."""
    _ = heartbeat.cancel()
    _ = await asyncio.gather(heartbeat, return_exceptions=True)
