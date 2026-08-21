"""Generation pinning for HTTP, Agent-turn, and background-operation boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from typing import Any, Protocol, cast

from starlette.types import ASGIApp, Receive, Scope, Send

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .builtin_modules import RUNTIME_BOUNDARY_SERVICE_V2, RuntimeBoundaryServiceV2
from .runtime import (
    FiberPhaseV2,
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


class GenerationDistributionV2(Protocol):
    def to_payload(self) -> dict[str, Any]: ...


class DistributionGenerationHostV2(GenerationHostV2, Protocol):
    def distribution_for_generation(
        self,
        generation: RuntimeGenerationV2,
    ) -> GenerationDistributionV2: ...


type HostProviderV2 = Callable[[Scope], GenerationHostV2]

_process_generation_host_v2: DistributionGenerationHostV2 | None = None


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


def install_process_generation_host_v2(host: DistributionGenerationHostV2) -> None:
    """Publish the initialized process host used by non-ASGI operation boundaries."""
    global _process_generation_host_v2
    _process_generation_host_v2 = host


def clear_process_generation_host_v2(host: DistributionGenerationHostV2) -> None:
    """Clear the process host only when the caller still owns the active registration."""
    global _process_generation_host_v2
    if _process_generation_host_v2 is host:
        _process_generation_host_v2 = None


def current_process_generation_host_v2() -> DistributionGenerationHostV2:
    """Return the initialized process host or fail closed before admission."""
    if _process_generation_host_v2 is None:
        raise RuntimeV2Error(
            "process_generation_host_not_configured",
            "plugin generation host is not configured for this process",
        )
    return _process_generation_host_v2


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
        _ = await operation.__aenter__()
        for service, value in (services or {}).items():
            _ = operation.provide(service, value)
        token: Token[OperationContextV2 | None] = _operation_context.set(operation)
        try:
            yield operation
        finally:
            await operation.dispose()
            _operation_context.reset(token)


@asynccontextmanager
async def pin_agent_turn_operation_v2(
    *,
    operation_id: str,
    tenant_id: str,
    project_id: str,
    session_id: str,
    services: Mapping[str, object] | None = None,
) -> AsyncIterator[OperationContextV2]:
    """Pin one complete session-scoped V2 operation for an agent turn."""
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=tenant_id,
        project_id=project_id,
        session_id=session_id,
    )
    existing = _operation_context.get()
    if (
        existing is not None
        and existing.phase is FiberPhaseV2.ACTIVE
        and existing.context.scope == scope
    ):
        yield existing
        return

    generation = _generation_context.get()
    if generation is not None:
        async with _pin_agent_turn_on_generation_v2(
            generation,
            operation_id=operation_id,
            scope=scope,
            services=services,
            parent=existing,
        ) as operation:
            yield operation
        return

    host = current_process_generation_host_v2()
    async with (
        pin_generation_v2(host) as leased_generation,
        _pin_agent_turn_on_generation_v2(
            leased_generation,
            operation_id=operation_id,
            scope=scope,
            services=services,
            parent=existing,
        ) as operation,
    ):
        yield operation


@asynccontextmanager
async def _pin_agent_turn_on_generation_v2(
    generation: RuntimeGenerationV2,
    *,
    operation_id: str,
    scope: ScopeV2,
    services: Mapping[str, object] | None,
    parent: OperationContextV2 | None,
) -> AsyncIterator[OperationContextV2]:
    resolved_services = dict(services or {})
    if OPERATION_IDENTITY_SERVICE_V2 not in resolved_services:
        resolved_services[OPERATION_IDENTITY_SERVICE_V2] = {"tenant_id": scope.tenant_id}
    if OPERATION_METADATA_SERVICE_V2 not in resolved_services:
        resolved_services[OPERATION_METADATA_SERVICE_V2] = {
            "kind": "agent-turn",
            "conversation_id": scope.session_id,
        }
    if OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2 not in resolved_services:
        resolved_services[OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2] = (
            _distribution_payload_for_generation_v2(generation, parent=parent)
        )

    operation = OperationContextV2(
        generation=generation,
        operation_id=operation_id,
        scope=scope,
    )
    _ = await operation.__aenter__()
    token: Token[OperationContextV2 | None] | None = None
    try:
        for service, value in resolved_services.items():
            _ = operation.provide(service, value)
        token = _operation_context.set(operation)
        yield operation
    finally:
        await operation.dispose()
        if token is not None:
            _operation_context.reset(token)


def _distribution_payload_for_generation_v2(
    generation: RuntimeGenerationV2,
    *,
    parent: OperationContextV2 | None,
) -> dict[str, Any]:
    if parent is not None:
        try:
            value = parent.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
        except RuntimeV2Error as exc:
            if exc.code != "service_not_found":
                raise
        else:
            if not isinstance(value, dict):
                raise RuntimeV2Error(
                    "invalid_operation_distribution",
                    "parent operation plugin distribution must be an object",
                )
            object_map = cast(dict[object, object], value)
            if not all(isinstance(key, str) for key in object_map):
                raise RuntimeV2Error(
                    "invalid_operation_distribution",
                    "parent operation plugin distribution keys must be strings",
                )
            return cast(dict[str, Any], dict(object_map))

    host = current_process_generation_host_v2()
    distribution = host.distribution_for_generation(generation)
    payload = distribution.to_payload()
    if payload.get("descriptor") != generation.descriptor.to_payload():
        raise RuntimeV2Error(
            "generation_descriptor_mismatch",
            "plugin distribution does not match the leased generation",
        )
    return payload


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
