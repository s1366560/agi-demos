"""Redis implementation of AgentCredentialScopePort for per-agent credential isolation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.infrastructure.security.encryption_service import EncryptionService

logger = logging.getLogger(__name__)

_KEY_PREFIX = "agent:cred"
_DEFAULT_TTL_SECONDS = 86400


def _build_key(project_id: str, agent_id: str, credential_key: str) -> str:
    return f"{_KEY_PREFIX}:{project_id}:{agent_id}:{credential_key}"


def _build_scope_prefix(project_id: str, agent_id: str) -> str:
    return f"{_KEY_PREFIX}:{project_id}:{agent_id}:"


def _strip_prefix(full_key: str, prefix: str) -> str:
    if full_key.startswith(prefix):
        return full_key[len(prefix) :]
    return full_key


class RedisAgentCredentialScopeAdapter:
    """Redis-backed per-agent credential scope with AES-256-GCM encryption.

    Implements AgentCredentialScopePort using Redis with isolated key prefixes
    per project/agent pair. All credential values are encrypted at rest via
    EncryptionService. Keys follow the pattern:
        agent:cred:{project_id}:{agent_id}:{credential_key}
    """

    def __init__(
        self,
        redis: Redis,
        encryption_service: EncryptionService,
        default_ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._encryption = encryption_service
        self._default_ttl = default_ttl_seconds

    async def get_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
    ) -> str | None:
        full_key = _build_key(project_id, agent_id, credential_key)
        encrypted = await self._redis.get(full_key)
        if encrypted is None:
            return None
        return self._encryption.decrypt(str(encrypted))

    async def set_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
        credential_value: str,
        ttl_seconds: int | None = None,
    ) -> None:
        full_key = _build_key(project_id, agent_id, credential_key)
        encrypted = self._encryption.encrypt(credential_value)
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        await self._redis.set(full_key, encrypted, ex=effective_ttl)

    async def delete_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
    ) -> bool:
        full_key = _build_key(project_id, agent_id, credential_key)
        deleted = await self._redis.delete(full_key)
        return int(deleted) > 0

    async def list_credential_keys(
        self,
        project_id: str,
        agent_id: str,
    ) -> list[str]:
        prefix = _build_scope_prefix(project_id, agent_id)
        scan_pattern = f"{prefix}*"
        keys: list[str] = []
        async for raw_key in self._redis.scan_iter(match=scan_pattern, count=100):
            keys.append(_strip_prefix(str(raw_key), prefix))
        return keys

    async def has_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
    ) -> bool:
        full_key = _build_key(project_id, agent_id, credential_key)
        return bool(await self._redis.exists(full_key))

    async def clear_credentials(
        self,
        project_id: str,
        agent_id: str,
    ) -> int:
        prefix = _build_scope_prefix(project_id, agent_id)
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
