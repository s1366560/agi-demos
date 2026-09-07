"""Generation-owned opaque registry for sandbox HTTP service records."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Protocol, cast, runtime_checkable

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .runtime import (
    AsyncDisposerV2,
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SANDBOX_HTTP_SERVICE_REGISTRY_MODULE_V2 = "builtin://memstack/sandbox/http-service-registry"
SANDBOX_HTTP_SERVICE_REGISTRY_SERVICE_V2 = "service:sandbox.http-service-registry"

logger = logging.getLogger(__name__)


class _RedisHashClientProtocolV2(Protocol):
    async def hget(self, key: str, field: str) -> object: ...

    async def hset(self, key: str, field: str, value: str) -> object: ...

    async def hgetall(self, key: str) -> Mapping[object, object]: ...

    async def eval(
        self,
        script: str,
        key_count: int,
        key: str,
        field: str,
    ) -> object: ...


@runtime_checkable
class SandboxHttpServiceRegistryProtocolV2(Protocol):
    """Consumer seam for opaque project-scoped HTTP service payloads."""

    async def upsert_payload(
        self,
        project_id: str,
        service_id: str,
        payload: str,
    ) -> bool: ...

    async def list_payloads(self, project_id: str) -> dict[str, str]: ...

    async def get_payload(self, project_id: str, service_id: str) -> str | None: ...

    async def pop_payload(self, project_id: str, service_id: str) -> str | None: ...


class SandboxHttpServiceRegistryV2:
    """Own the mutable HTTP-service cache for one exact generation."""

    def __init__(self, *, redis_client: object | None = None) -> None:
        super().__init__()
        self._redis = cast("_RedisHashClientProtocolV2 | None", redis_client)
        self._services: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()
        self._disposed = False

    async def upsert_payload(
        self,
        project_id: str,
        service_id: str,
        payload: str,
    ) -> bool:
        """Insert or replace one payload and report whether it already existed."""
        self._ensure_active()
        if self._redis is not None:
            try:
                key = _registry_redis_key_v2(project_id)
                existing = await self._redis.hget(key, service_id)
                _ = await self._redis.hset(key, service_id, payload)
                async with self._lock:
                    self._ensure_active()
                    self._services.setdefault(project_id, {})[service_id] = payload
                return existing is not None
            except Exception as exc:
                _log_redis_failure_v2("upsert", exc)

        async with self._lock:
            self._ensure_active()
            project_services = self._services.setdefault(project_id, {})
            existed = service_id in project_services
            project_services[service_id] = payload
            return existed

    async def list_payloads(self, project_id: str) -> dict[str, str]:
        """Return a copy of every payload for a project."""
        self._ensure_active()
        if self._redis is not None:
            try:
                raw_payloads = await self._redis.hgetall(_registry_redis_key_v2(project_id))
                payloads = {
                    _decode_redis_text_v2(raw_service_id): _decode_redis_text_v2(raw_payload)
                    for raw_service_id, raw_payload in raw_payloads.items()
                }
                async with self._lock:
                    self._ensure_active()
                    if payloads:
                        self._services[project_id] = dict(payloads)
                    else:
                        _ = self._services.pop(project_id, None)
                return payloads
            except Exception as exc:
                _log_redis_failure_v2("list", exc)

        async with self._lock:
            self._ensure_active()
            return dict(self._services.get(project_id, {}))

    async def get_payload(self, project_id: str, service_id: str) -> str | None:
        """Resolve one payload, refreshing the generation cache from Redis."""
        self._ensure_active()
        if self._redis is not None:
            try:
                payload = await self._redis.hget(_registry_redis_key_v2(project_id), service_id)
                if payload is None:
                    await self._drop_from_memory(project_id, service_id)
                    return None
                serialized = _decode_redis_text_v2(payload)
                async with self._lock:
                    self._ensure_active()
                    self._services.setdefault(project_id, {})[service_id] = serialized
                return serialized
            except Exception as exc:
                _log_redis_failure_v2("get", exc)

        async with self._lock:
            self._ensure_active()
            return self._services.get(project_id, {}).get(service_id)

    async def pop_payload(self, project_id: str, service_id: str) -> str | None:
        """Atomically remove one Redis payload, with memory-only fallback."""
        self._ensure_active()
        if self._redis is not None:
            try:
                redis_payload = await self._redis.eval(
                    (
                        "local value = redis.call('HGET', KEYS[1], ARGV[1]); "
                        "if value then redis.call('HDEL', KEYS[1], ARGV[1]); end; "
                        "return value"
                    ),
                    1,
                    _registry_redis_key_v2(project_id),
                    service_id,
                )
                await self._drop_from_memory(project_id, service_id)
                return None if redis_payload is None else _decode_redis_text_v2(redis_payload)
            except Exception as exc:
                _log_redis_failure_v2("pop", exc)

        async with self._lock:
            self._ensure_active()
            project_services = self._services.get(project_id, {})
            memory_payload = project_services.pop(service_id, None)
            if not project_services:
                _ = self._services.pop(project_id, None)
            return memory_payload

    async def dispose(self) -> None:
        """Release all generation-local state after the final lease exits."""
        async with self._lock:
            self._services.clear()
            self._disposed = True

    async def _drop_from_memory(self, project_id: str, service_id: str) -> None:
        async with self._lock:
            self._ensure_active()
            project_services = self._services.get(project_id, {})
            _ = project_services.pop(service_id, None)
            if not project_services:
                _ = self._services.pop(project_id, None)

    def _ensure_active(self) -> None:
        if self._disposed:
            raise RuntimeV2Error(
                "sandbox_http_service_registry_disposed",
                "sandbox HTTP service registry generation has been disposed",
            )


def sandbox_http_service_registry_definition_v2(
    *,
    redis_client: object | None = None,
) -> PluginDefinitionV2:
    """Build the generation-owned HTTP service registry Provider."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> AsyncDisposerV2:
        if config.get("strategy") != "generation-owned-registry":
            raise ValueError(
                "sandbox HTTP service registry requires strategy generation-owned-registry"
            )
        registry = SandboxHttpServiceRegistryV2(redis_client=redis_client)
        _ = context.provide(
            SANDBOX_HTTP_SERVICE_REGISTRY_SERVICE_V2,
            registry,
            label="sandbox-http-service-registry",
        )
        return registry.dispose

    return PluginDefinitionV2(
        module_ref=SANDBOX_HTTP_SERVICE_REGISTRY_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SANDBOX_HTTP_SERVICE_REGISTRY_MODULE_V2),
        apply=apply,
    )


def current_sandbox_http_service_registry_v2() -> SandboxHttpServiceRegistryProtocolV2:
    """Resolve the registry from the generation pinned to this data-plane boundary."""
    from .boundary import current_generation_v2

    registry = current_generation_v2().resolve(
        SANDBOX_HTTP_SERVICE_REGISTRY_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(registry, SandboxHttpServiceRegistryProtocolV2):
        raise RuntimeV2Error(
            "invalid_sandbox_http_service_registry",
            "sandbox HTTP service registry has an invalid implementation",
        )
    return registry


def _registry_redis_key_v2(project_id: str) -> str:
    return f"project:sandbox:http-services:{project_id}"


def _decode_redis_text_v2(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _log_redis_failure_v2(operation: str, exc: Exception) -> None:
    logger.warning(
        "Sandbox HTTP service registry Redis operation failed: operation=%s error_type=%s",
        operation,
        type(exc).__name__,
    )


__all__ = [
    "SANDBOX_HTTP_SERVICE_REGISTRY_MODULE_V2",
    "SANDBOX_HTTP_SERVICE_REGISTRY_SERVICE_V2",
    "SandboxHttpServiceRegistryProtocolV2",
    "SandboxHttpServiceRegistryV2",
    "current_sandbox_http_service_registry_v2",
    "sandbox_http_service_registry_definition_v2",
]
