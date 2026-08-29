# pyright: reportImportCycles=false
"""Generation pinning for HTTP, Agent-turn, and background-operation boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from contextvars import Context, ContextVar, Token, copy_context
from copy import deepcopy
from dataclasses import dataclass
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

    async def acquire_exact(
        self,
        generation: RuntimeGenerationV2,
        descriptor: PluginGenerationDescriptorV2,
    ) -> GenerationLeaseV2: ...


_generation_host_context: ContextVar[GenerationHostV2 | None] = ContextVar(
    "platform_plugin_generation_host_v2",
    default=None,
)


type HostProviderV2 = Callable[[Scope], GenerationHostV2]

_process_generation_host_v2: DistributionGenerationHostV2 | None = None


class GenerationDescriptorCarrierV2(Protocol):
    plugin_generation: PluginGenerationDescriptorV2 | None


def current_generation_v2() -> RuntimeGenerationV2:
    """Return the generation pinned to the current data-plane boundary."""
    generation = _generation_context.get()
    if generation is None or generation._disposed:
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
    if operation is None or operation.phase is not FiberPhaseV2.ACTIVE:
        raise RuntimeV2Error(
            "operation_context_not_pinned",
            "plugin operation context is not pinned to the current operation",
        )
    return operation


@contextmanager
def bind_operation_context_v2(
    operation: OperationContextV2,
) -> Iterator[OperationContextV2]:
    """Bind an already-active operation without acquiring another generation lease."""
    if operation.phase is not FiberPhaseV2.ACTIVE:
        raise RuntimeV2Error(
            "inactive_operation",
            "only an active plugin operation can be bound to the current task",
        )
    token: Token[OperationContextV2 | None] = _operation_context.set(operation)
    try:
        yield operation
    finally:
        _operation_context.reset(token)


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
    async with _pin_reserved_generation_v2(host, lease) as generation:
        yield generation


@asynccontextmanager
async def _pin_reserved_generation_v2(
    host: GenerationHostV2,
    lease: GenerationLeaseV2,
) -> AsyncIterator[RuntimeGenerationV2]:
    """Activate an already-acquired lease without reacquiring the current generation."""
    generation = await lease.__aenter__()
    generation_token: Token[RuntimeGenerationV2 | None] = _generation_context.set(generation)
    host_token: Token[GenerationHostV2 | None] = _generation_host_context.set(host)
    try:
        yield generation
    finally:
        try:
            _generation_host_context.reset(host_token)
            _generation_context.reset(generation_token)
        finally:
            await lease.__aexit__(None, None, None)


@dataclass(kw_only=True)
class ForkedAgentOperationV2:
    """One-shot reservation for a detached operation on an exact generation."""

    host: DistributionGenerationHostV2
    lease: GenerationLeaseV2
    generation: RuntimeGenerationV2
    scope: ScopeV2
    parent_operation_id: str
    identity: dict[str, str]
    distribution: dict[str, Any]
    _claimed: bool = False
    _released: bool = False

    @property
    def descriptor(self) -> PluginGenerationDescriptorV2:
        return self.generation.descriptor

    @asynccontextmanager
    async def admit(
        self,
        *,
        operation_id: str,
        metadata: Mapping[str, object],
        services: Mapping[str, object] | None = None,
    ) -> AsyncIterator[OperationContextV2]:
        """Activate the reserved lease as a new isolated operation exactly once."""
        if self._claimed or self._released:
            raise RuntimeV2Error(
                "forked_operation_consumed",
                "forked plugin operation reservation has already been consumed",
            )
        extra_services = dict(services or {})
        unsupported = set(extra_services) - {OPERATION_DB_SESSION_SERVICE_V2}
        if unsupported:
            raise RuntimeV2Error(
                "unsafe_forked_operation_service",
                "forked plugin operation received an unclassified service",
            )
        child_metadata = deepcopy(dict(metadata))
        child_metadata["parent_operation_id"] = self.parent_operation_id
        operation_services: dict[str, object] = {
            OPERATION_IDENTITY_SERVICE_V2: dict(self.identity),
            OPERATION_METADATA_SERVICE_V2: child_metadata,
            OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2: deepcopy(self.distribution),
            **extra_services,
        }
        self._claimed = True
        try:
            async with (
                _pin_reserved_generation_v2(self.host, self.lease) as generation,
                _pin_agent_turn_on_generation_v2(
                    generation,
                    operation_id=operation_id,
                    scope=self.scope,
                    services=operation_services,
                    parent=None,
                ) as operation,
            ):
                yield operation
        finally:
            await self.lease.release()
            self._released = True

    async def release(self) -> None:
        """Release an unclaimed reservation after task creation or admission failure."""
        if self._released:
            return
        if self._claimed:
            raise RuntimeV2Error(
                "forked_operation_active",
                "active forked plugin operation must exit before release",
            )
        await self.lease.release()
        self._released = True


@dataclass(kw_only=True)
class ReservedGenerationV2:
    """One-shot exact-generation reservation for a detached operation boundary."""

    host: DistributionGenerationHostV2
    lease: GenerationLeaseV2
    generation: RuntimeGenerationV2
    _claimed: bool = False
    _released: bool = False

    @property
    def descriptor(self) -> PluginGenerationDescriptorV2:
        return self.generation.descriptor

    @asynccontextmanager
    async def admit(self) -> AsyncIterator[RuntimeGenerationV2]:
        """Activate the reserved generation once from a context-clean detached task."""
        if self._claimed or self._released:
            raise RuntimeV2Error(
                "reserved_generation_consumed",
                "reserved plugin generation has already been consumed",
            )
        if (
            _generation_context.get() is not None
            or _operation_context.get() is not None
            or _generation_host_context.get() is not None
        ):
            raise RuntimeV2Error(
                "detached_generation_context_not_clean",
                "reserved plugin generation requires a detached task context",
            )
        self._claimed = True
        try:
            async with _pin_reserved_generation_v2(
                self.host,
                self.lease,
            ) as generation:
                yield generation
        finally:
            await self.lease.release()
            self._released = True

    async def release(self) -> None:
        """Release an unclaimed reservation after detached task creation fails."""
        if self._released:
            return
        if self._claimed:
            raise RuntimeV2Error(
                "reserved_generation_active",
                "active reserved plugin generation must exit before release",
            )
        await self.lease.release()
        self._released = True


async def fork_current_agent_operation_v2() -> ForkedAgentOperationV2:
    """Reserve the exact active generation for one detached Agent operation."""
    operation = current_operation_context_v2()
    generation = current_generation_v2()
    if operation.generation is not generation:
        raise RuntimeV2Error(
            "generation_descriptor_mismatch",
            "operation and generation contexts do not reference the same generation",
        )
    host = _generation_host_context.get()
    if (
        host is None
        or not hasattr(host, "acquire_exact")
        or not hasattr(host, "distribution_for_generation")
    ):
        raise RuntimeV2Error(
            "exact_generation_host_unavailable",
            "active generation host cannot reserve an exact detached operation",
        )
    exact_host = cast(DistributionGenerationHostV2, host)
    identity = _forked_operation_identity_v2(operation)
    lease = await exact_host.acquire_exact(generation, operation.descriptor)
    try:
        distribution = exact_host.distribution_for_generation(generation).to_payload()
        if distribution.get("descriptor") != operation.descriptor.to_payload():
            raise RuntimeV2Error(
                "generation_descriptor_mismatch",
                "forked plugin distribution does not match its exact generation",
            )
        return ForkedAgentOperationV2(
            host=exact_host,
            lease=lease,
            generation=generation,
            scope=operation.context.scope,
            parent_operation_id=operation.operation_id,
            identity=identity,
            distribution=deepcopy(distribution),
        )
    except BaseException:
        await lease.release()
        raise


async def reserve_current_generation_v2() -> ReservedGenerationV2:
    """Retain the exact boundary generation before launching a detached task."""
    generation = current_generation_v2()
    host = _generation_host_context.get()
    if (
        host is None
        or not hasattr(host, "acquire_exact")
        or not hasattr(host, "distribution_for_generation")
    ):
        raise RuntimeV2Error(
            "exact_generation_host_unavailable",
            "active generation host cannot reserve an exact detached boundary",
        )
    exact_host = cast(DistributionGenerationHostV2, host)
    lease = await exact_host.acquire_exact(generation, generation.descriptor)
    return ReservedGenerationV2(
        host=exact_host,
        lease=lease,
        generation=generation,
    )


def detached_operation_task_context_v2() -> Context:
    """Copy tracing context while removing parent plugin operation authority."""
    context = copy_context()

    def clear_plugin_context() -> None:
        _generation_context.set(None)
        _operation_context.set(None)
        _generation_host_context.set(None)

    context.run(clear_plugin_context)
    return context


def _forked_operation_identity_v2(operation: OperationContextV2) -> dict[str, str]:
    raw_identity = operation.require(OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(raw_identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "parent operation identity must be an object",
        )
    scope = operation.context.scope
    identity: dict[str, str] = {}
    for key, scope_value in (
        ("tenant_id", scope.tenant_id),
        ("project_id", scope.project_id),
    ):
        raw_value = raw_identity.get(key)
        if raw_value is None:
            continue
        if not isinstance(raw_value, str) or not raw_value:
            raise RuntimeV2Error(
                "invalid_operation_identity",
                "parent operation scope identity must be a non-empty string",
            )
        if scope_value is not None and raw_value != scope_value:
            raise RuntimeV2Error(
                "operation_identity_scope_mismatch",
                "parent operation identity does not match its scope",
            )
        identity[key] = raw_value
    user_id = raw_identity.get("user_id")
    if user_id is not None:
        if not isinstance(user_id, str) or not user_id:
            raise RuntimeV2Error(
                "invalid_operation_identity",
                "parent operation user identity must be a non-empty string",
            )
        identity["user_id"] = user_id
    return identity


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
            try:
                await operation.dispose()
            finally:
                _operation_context.reset(token)


@asynccontextmanager
async def pin_agent_turn_operation_v2(
    *,
    operation_id: str,
    tenant_id: str,
    project_id: str,
    session_id: str,
    services: Mapping[str, object] | None = None,
    force_process_host_lease: bool = False,
) -> AsyncIterator[OperationContextV2]:
    """Pin one complete session-scoped V2 operation for an agent turn.

    Background tasks can inherit an HTTP generation through ``ContextVar`` even
    though the request lease ends before the task consumes it.  Such callers
    must force an independent process-host lease instead of reusing that copied
    generation or operation context.
    """
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=tenant_id,
        project_id=project_id,
        session_id=session_id,
    )
    if force_process_host_lease:
        host = current_process_generation_host_v2()
        async with (
            pin_generation_v2(host) as leased_generation,
            _pin_agent_turn_on_generation_v2(
                leased_generation,
                operation_id=operation_id,
                scope=scope,
                services=services,
                parent=None,
            ) as operation,
        ):
            yield operation
        return

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
        try:
            await operation.dispose()
        finally:
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
    """Retain one generation through an HTTP response or WebSocket connection."""

    def __init__(self, app: ASGIApp, *, host_provider: HostProviderV2) -> None:
        self._app = app
        self._host_provider = host_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
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
