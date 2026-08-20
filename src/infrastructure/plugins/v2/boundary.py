"""Generation pinning for HTTP, Agent-turn, and background-operation boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from typing import Any, Protocol

from starlette.types import ASGIApp, Receive, Scope, Send

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .builtin_modules import RUNTIME_BOUNDARY_SERVICE_V2, RuntimeBoundaryServiceV2
from .runtime import GenerationLeaseV2, RuntimeGenerationV2, RuntimeV2Error

_generation_context: ContextVar[RuntimeGenerationV2 | None] = ContextVar(
    "platform_plugin_generation_v2",
    default=None,
)


class GenerationHostV2(Protocol):
    async def acquire(self) -> GenerationLeaseV2: ...


type HostProviderV2 = Callable[[Scope], GenerationHostV2]


def current_generation_v2() -> RuntimeGenerationV2:
    """Return the generation pinned to the current data-plane boundary."""
    generation = _generation_context.get()
    if generation is None:
        raise RuntimeV2Error(
            "generation_not_pinned",
            "plugin generation is not pinned to the current operation",
        )
    return generation


@asynccontextmanager
async def pin_generation_v2(host: GenerationHostV2) -> AsyncIterator[RuntimeGenerationV2]:
    """Pin one acquired generation until the complete operation finishes."""
    lease = await host.acquire()
    generation = await lease.__aenter__()
    token: Token[RuntimeGenerationV2 | None] = _generation_context.set(generation)
    try:
        yield generation
    finally:
        _generation_context.reset(token)
        await lease.__aexit__(None, None, None)


class PluginGenerationMiddlewareV2:
    """Pure ASGI middleware that retains a lease through streaming completion."""

    def __init__(self, app: ASGIApp, *, host_provider: HostProviderV2) -> None:
        self._app = app
        self._host_provider = host_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        async with pin_generation_v2(self._host_provider(scope)) as generation:
            boundary = generation.resolve(
                RUNTIME_BOUNDARY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            if not isinstance(boundary, RuntimeBoundaryServiceV2):
                raise RuntimeV2Error(
                    "invalid_boundary_service",
                    "active generation has an invalid runtime boundary service",
                )
            state: dict[str, Any] = scope.setdefault("state", {})
            state["plugin_generation_v2"] = generation
            state["plugin_generation_digest_v2"] = generation.digest
            await self._app(scope, receive, send)
