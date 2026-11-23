"""Redis connections for cloud identity flows and worker infrastructure."""

from redis.asyncio import ConnectionPool, Redis

from src.configuration.config import get_settings

_pool: ConnectionPool | None = None


async def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            get_settings().redis_url, decode_responses=True, max_connections=50
        )
    return _pool


async def get_redis_client() -> Redis:
    return Redis(connection_pool=await get_redis_pool())


async def close_redis_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
