"""Redis client initialization for startup."""

import logging
from typing import Optional

from src.configuration.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def initialize_redis_client() -> Optional[object]:
    """
    Initialize Redis client for event bus and caching.

    Also cleans up stale agent running states from previous sessions.

    Returns:
        The Redis client, or None if initialization fails.
    """
    redis_client = None
    try:
        import redis.asyncio as redis

        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        logger.info("Redis client initialized for event bus")

        # Clean up stale agent running states on startup
        # This handles cases where the server was restarted while agents were running
        try:
            stale_keys = []
            async for key in redis_client.scan_iter(match="agent:running:*"):
                stale_keys.append(key)
            if stale_keys:
                await redis_client.delete(*stale_keys)
                logger.info(
                    f"Cleaned up {len(stale_keys)} stale agent running states from previous session"
                )
        except Exception as cleanup_error:
            logger.warning(f"Failed to clean up stale agent running states: {cleanup_error}")

    except Exception as e:
        logger.warning(f"Failed to initialize Redis client: {e}")

    return redis_client
