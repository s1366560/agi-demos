"""Redis implementation of AgentNamespacePort for per-agent state isolation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Key pattern: agent:ns:{project_id}:{agent_id}:{key}
_KEY_PREFIX = "agent:ns"
_DEFAULT_TTL_SECONDS = 86400


def _build_key(project_id: str, agent_id: str, key: str) -> str:
    return f"{_KEY_PREFIX}:{project_id}:{agent_id}:{key}"


def _build_namespace_prefix(project_id: str, agent_id: str) -> str:
    return f"{_KEY_PREFIX}:{project_id}:{agent_id}:"


def _strip_prefix(full_key: str, prefix: str) -> str:
    if full_key.startswith(prefix):
        return full_key[len(prefix) :]
    return full_key


class RedisAgentNamespaceAdapter:
    """Redis-backed per-agent namespace isolation.

    Implements AgentNamespacePort using Redis with isolated key prefixes
    per project/agent pair. Keys follow the pattern:
        agent:ns:{project_id}:{agent_id}:{key}
    """

    def __init__(
        self,
        redis: Redis,
        default_ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._default_ttl = default_ttl_seconds

    async def get_key(
        self,
        project_id: str,
        agent_id: str,
        key: str,
    ) -> str | None:
        full_key = _build_key(project_id, agent_id, key)
        result = await self._redis.get(full_key)
        if result is None:
            return None
        return str(result)

    async def set_key(
        self,
        project_id: str,
        agent_id: str,
        key: str,
        value: str,
        ttl_seconds: int | None = None,
    ) -> None:
        full_key = _build_key(project_id, agent_id, key)
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        await self._redis.set(full_key, value, ex=effective_ttl)

    async def delete_key(
        self,
        project_id: str,
        agent_id: str,
        key: str,
    ) -> bool:
        full_key = _build_key(project_id, agent_id, key)
        deleted = await self._redis.delete(full_key)
        return int(deleted) > 0

    async def list_keys(
        self,
        project_id: str,
        agent_id: str,
        pattern: str = "*",
    ) -> list[str]:
        prefix = _build_namespace_prefix(project_id, agent_id)
        scan_pattern = f"{prefix}{pattern}"
        keys: list[str] = []
        async for raw_key in self._redis.scan_iter(match=scan_pattern, count=100):
            keys.append(_strip_prefix(str(raw_key), prefix))
        return keys

    async def clear_namespace(
        self,
        project_id: str,
        agent_id: str,
    ) -> int:
        prefix = _build_namespace_prefix(project_id, agent_id)
        scan_pattern = f"{prefix}*"
        count = 0
        batch: list[str] = []
        async for raw_key in self._redis.scan_iter(match=scan_pattern, count=100):
            batch.append(str(raw_key))
            if len(batch) >= 100:
                deleted = await self._redis.delete(*batch)
                count += int(deleted)
                batch.clear()
        if batch:
            deleted = await self._redis.delete(*batch)
            count += int(deleted)
        return count

    async def get_many(
        self,
        project_id: str,
        agent_id: str,
        keys: list[str],
    ) -> dict[str, str | None]:
        if not keys:
            return {}
        full_keys = [_build_key(project_id, agent_id, k) for k in keys]
        values = await self._redis.mget(full_keys)
        result: dict[str, str | None] = {}
        for key, value in zip(keys, values):
            result[key] = str(value) if value is not None else None
        return result

    async def set_many(
        self,
        project_id: str,
        agent_id: str,
        mapping: dict[str, str],
        ttl_seconds: int | None = None,
    ) -> None:
        if not mapping:
            return
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        pipe = self._redis.pipeline()
        for key, value in mapping.items():
            full_key = _build_key(project_id, agent_id, key)
            pipe.set(full_key, value, ex=effective_ttl)
        await pipe.execute()
