"""Private Redis records shared by API processes and agent workers.

Only host-issued request IDs travel on the control stream. Invocation arguments
and media live in scoped, bounded records, never in an event or log payload.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import WatchError

PREFIX = "memstack:computer-use:v2"
LEASE_SECONDS = 45
REQUEST_SECONDS = 7 * 24 * 3600
MEDIA_SECONDS = 3600


class DeviceBridgeError(Exception):
    """A protocol code with no untrusted payload in its representation."""


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def string(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise DeviceBridgeError("computer_use_invalid_record")


def identifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise DeviceBridgeError("computer_use_invalid_identifier")
    return value


def record(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(string(value))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise DeviceBridgeError("computer_use_invalid_record") from exc
    if not isinstance(parsed, dict):
        raise DeviceBridgeError("computer_use_invalid_record")
    return parsed


def scope_key(*, user_id: str, tenant_id: str, project_id: str) -> str:
    return digest([identifier(user_id), identifier(tenant_id), identifier(project_id)])


class BridgeStore:
    """Optimistic transactions keep claims and chunk offsets atomic."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def read(self, key: str) -> dict[str, Any] | None:
        return record(await self.redis.get(key))

    async def members(self, key: str) -> set[str]:
        values = await cast(Awaitable[set[bytes | str]], self.redis.smembers(key))
        return {string(value) for value in values}

    async def remove_member(self, key: str, member: str) -> None:
        await cast(Awaitable[int], self.redis.srem(key, member))

    async def update(
        self,
        key: str,
        change: Callable[[dict[str, Any] | None], dict[str, Any]],
        *,
        ttl: int = REQUEST_SECONDS,
        extra: Callable[[Any, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        for _attempt in range(8):
            async with self.redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    updated = change(record(await pipe.get(key)))
                    cast(Callable[[], object], pipe.multi)()
                    pipe.set(key, encoded(updated), ex=ttl)
                    if extra is not None:
                        extra(pipe, updated)
                    await pipe.execute()
                    return updated
                except WatchError:
                    continue
        raise DeviceBridgeError("computer_use_concurrent_update")


def request_key(request_id: str) -> str:
    return f"{PREFIX}:request:{identifier(request_id)}"


def control_key(connection_id: str) -> str:
    return f"{PREFIX}:control:{identifier(connection_id)}"


def run_key(user_id: str, tenant_id: str, project_id: str, run_id: str) -> str:
    return f"{PREFIX}:run:{digest([user_id, tenant_id, project_id, identifier(run_id)])}"


def conversation_key(user_id: str, tenant_id: str, project_id: str, conversation_id: str) -> str:
    return f"{PREFIX}:conversation:{digest([user_id, tenant_id, project_id, identifier(conversation_id)])}"
