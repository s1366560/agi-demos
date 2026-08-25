"""Generation-visible projection of the process-owned Redis client."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2

REDIS_RUNTIME_MODULE_V2 = "builtin://memstack/runtime/redis-client"
REDIS_RUNTIME_SERVICE_V2 = "service:runtime.redis-client"


@dataclass(frozen=True, kw_only=True)
class RedisRuntimeServiceV2:
    """Immutable generation projection; ``None`` is an explicit unavailable state."""

    client: object | None


def _apply_redis_runtime_v2(
    context: ContextV2,
    config: Mapping[str, Any],
    *,
    redis_client: object | None = None,
) -> None:
    if config.get("strategy") != "process-shared-projection":
        raise ValueError("Redis runtime requires strategy process-shared-projection")
    _ = context.provide(
        REDIS_RUNTIME_SERVICE_V2,
        RedisRuntimeServiceV2(client=redis_client),
        label="redis-runtime",
    )


def redis_runtime_definition_v2(
    redis_client: object | None = None,
) -> PluginDefinitionV2:
    """Project the host resource without transferring its lifecycle ownership."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        _apply_redis_runtime_v2(
            context,
            config,
            redis_client=redis_client,
        )

    return PluginDefinitionV2(
        module_ref=REDIS_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(REDIS_RUNTIME_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "REDIS_RUNTIME_MODULE_V2",
    "REDIS_RUNTIME_SERVICE_V2",
    "RedisRuntimeServiceV2",
    "redis_runtime_definition_v2",
]
