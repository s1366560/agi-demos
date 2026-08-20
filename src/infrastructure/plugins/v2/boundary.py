"""Generation pinning for HTTP, Agent-turn, and background-operation boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from typing import Any, Protocol

from starlette.types import ASGIApp, Receive, Scope, Send

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .builtin_modules import RUNTIME_BOUNDARY_SERVICE_V2, RuntimeBoundaryServiceV2
from .runtime import (
    GenerationLeaseV2,
    OperationContextV2,
    RuntimeGenerationV2,
    RuntimeV2Error,
)

_generation_context: ContextVar[RuntimeGenerationV2 | None] = ContextVar(
    "platform_plugin_generation_v2",
    default=None,
)
_operation_context: ContextVar[OperationContextV2 | None] = ContextVar(
    "platform_plugin_operation_v2",
    default=None,
)

OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"
OPERATION_METADATA_SERVICE_V2 = "service:operation.metadata"
OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2 = "service:operation.plugin-distribution"
OPERATION_VAULT_LEASE_SERVICE_V2 = "service:operation.vault-lease"


class GenerationHostV2(Protocol):
    async def acquire(self) -> GenerationLeaseV2: ...


type HostProviderV2 = Callable[[Scope], GenerationHostV2]


class GenerationDescriptorCarrierV2(Protocol):
    plugin_generation: PluginGenerationDescriptorV2 | None


def current_generation_v2() -> RuntimeGenerationV2:
    """Return the generation pinned to the current data-plane boundary."""
    generation = _generation_context.get()
    if generation is None:
        raise RuntimeV2Error(
            "generation_not_pinned",
            "plugin generation is not pinned to the current operation",
        )
    return generation


def current_generation_descriptor_v2() -> PluginGenerationDescriptorV2:
    """Return only the process-safe identity of the currently pinned generation."""
    return current_generation_v2().descriptor


def current_operation_context_v2() -> OperationContextV2:
    """Return the scoped operation overlay active on the current async task."""
    operation = _operation_context.get()
    if operation is None:
        raise RuntimeV2Error(
            "operation_context_not_pinned",
            "plugin operation context is not pinned to the current operation",
        )
    return operation


def attach_current_generation_v2(carrier: GenerationDescriptorCarrierV2) -> None:
    """Attach only the serializable descriptor to a RunContext-like carrier."""
    operation = _operation_context.get()
    generation = _generation_context.get()
    descriptor = operation.descriptor if operation is not None else None
    if descriptor is None and generation is not None:
        descriptor = generation.descriptor
    if descriptor is None:
        return
    if carrier.plugin_generation is not None and carrier.plugin_generation != descriptor:
        raise RuntimeV2Error(
            "generation_descriptor_mismatch",
            "run context generation does not match the pinned operation",
        )
    carrier.plugin_generation = descriptor


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


@asynccontextmanager
async def pin_operation_context_v2(
    host: GenerationHostV2,
    *,
    operation_id: str,
    scope: ScopeV2,
    services: Mapping[str, object] | None = None,
) -> AsyncIterator[OperationContextV2]:
    """Pin one generation and its isolated scoped service overlay as a unit."""
    async with pin_generation_v2(host) as generation:
        operation = OperationContextV2(
            generation=generation,
            operation_id=operation_id,
            scope=scope,
        )
        await operation.__aenter__()
        for service, value in (services or {}).items():
            operation.provide(service, value)
        token: Token[OperationContextV2 | None] = _operation_context.set(operation)
        try:
            yield operation
        finally:
            await operation.dispose()
            _operation_context.reset(token)


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
            state["plugin_generation_v2"] = generation.descriptor
            state["plugin_generation_digest_v2"] = generation.digest
            await self._app(scope, receive, send)
