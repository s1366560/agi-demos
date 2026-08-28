"""Generation-visible projection of the process-owned Redis client."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

REDIS_RUNTIME_MODULE_V2 = "builtin://memstack/runtime/redis-client"
REDIS_RUNTIME_SERVICE_V2 = "service:runtime.redis-client"
type RedisRuntimeFactoryV2 = Callable[[], object | None | Awaitable[object | None]]


@dataclass(frozen=True, kw_only=True)
class RedisRuntimeServiceV2:
    """Immutable generation projection; ``None`` is an explicit unavailable state."""

    client: object | None


async def _apply_redis_runtime_v2(
    context: ContextV2,
    config: Mapping[str, Any],
    *,
    redis_client: object | None = None,
    factory: RedisRuntimeFactoryV2 | None = None,
) -> EffectResultV2:
    if config.get("strategy") != "host-resource":
        raise ValueError("Redis runtime requires strategy host-resource")
    if redis_client is not None and factory is not None:
        raise RuntimeV2Error(
            "redis_runtime_source_conflict",
            "Redis runtime accepts either a projected client or an owned factory, not both",
        )

    client = redis_client
    owned_close: Callable[[], object] | None = None
    if factory is not None:
        client = factory()
        if inspect.isawaitable(client):
            client = await client
        if client is not None:
            close = getattr(client, "aclose", None)
            if not callable(close):
                raise RuntimeV2Error(
                    "invalid_owned_redis_client",
                    "generation-owned Redis clients must expose aclose()",
                )
            owned_close = close

    _ = context.provide(
        REDIS_RUNTIME_SERVICE_V2,
        RedisRuntimeServiceV2(client=client),
        label="redis-runtime",
    )
    if owned_close is None:
        return None

    async def dispose() -> None:
        result = owned_close()
        if inspect.isawaitable(result):
            await result

    return dispose


def redis_runtime_definition_v2(
    redis_client: object | None = None,
    *,
    factory: RedisRuntimeFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Project a host resource or own one factory-created client per generation."""

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        return await _apply_redis_runtime_v2(
            context,
            config,
            redis_client=redis_client,
            factory=factory,
        )

    return PluginDefinitionV2(
        module_ref=REDIS_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(REDIS_RUNTIME_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "REDIS_RUNTIME_MODULE_V2",
    "REDIS_RUNTIME_SERVICE_V2",
    "RedisRuntimeFactoryV2",
    "RedisRuntimeServiceV2",
    "redis_runtime_definition_v2",
]
