"""Exact-generation Redis binding for the process-local HITL stream."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import cast

import redis.asyncio as aioredis

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import GenerationHostV2, pin_generation_v2
from src.infrastructure.plugins.v2.redis_runtime import (
    REDIS_RUNTIME_SERVICE_V2,
    RedisRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2, RuntimeV2Error


class LocalHITLRedisGenerationBindingV2:
    """Expose Redis only inside a current or explicitly reserved generation lease."""

    def __init__(self, *, host: GenerationHostV2) -> None:
        super().__init__()
        self._host = host
        self._redis_context: ContextVar[aioredis.Redis | None] = ContextVar(
            f"local_hitl_resume_redis_{id(self)}",
            default=None,
        )

    @asynccontextmanager
    async def lease_current(self) -> AsyncIterator[aioredis.Redis]:
        """Bind Redis while the process host's current generation remains leased."""
        async with pin_generation_v2(self._host) as generation:
            with self.bind(generation) as redis_client:
                yield redis_client

    @contextmanager
    def bind(self, generation: RuntimeGenerationV2) -> Iterator[aioredis.Redis]:
        """Bind Redis from a generation whose caller already owns a lease."""
        runtime = generation.resolve(
            REDIS_RUNTIME_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        if not isinstance(runtime, RedisRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_hitl_redis_runtime",
                "local HITL resume requires a valid generation Redis runtime",
            )
        if runtime.client is None:
            raise RuntimeV2Error(
                "hitl_redis_runtime_unavailable",
                "local HITL resume requires the generation Redis client",
            )
        redis_client = cast(aioredis.Redis, runtime.client)
        token = self._redis_context.set(redis_client)
        try:
            yield redis_client
        finally:
            self._redis_context.reset(token)

    def current(self) -> aioredis.Redis:
        """Return the exact leased Redis client or fail closed."""
        redis_client = self._redis_context.get()
        if redis_client is None:
            raise RuntimeV2Error(
                "hitl_redis_generation_not_pinned",
                "local HITL Redis access requires an active generation lease",
            )
        return redis_client


__all__ = ["LocalHITLRedisGenerationBindingV2"]
