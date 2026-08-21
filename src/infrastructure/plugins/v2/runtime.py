"""Fiber, loader, operation, and generation semantics for plugin runtime v2."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    EventContractV2,
    PluginContractV2,
    PluginModuleV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
    ScopeKindV2,
    ScopeV2,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .runtime_context import (
    AsyncDisposerV2,
    ContextV2,
    EffectDiagnosticV2,
    EffectResultV2,
    FiberDiagnosticV2,
    FiberPhaseV2,
    RuntimeV2Error,
    _EffectStack,
    _EventBusV2,
    _ProviderStore,
)
from .runtime_contracts import (
    entry_order_v2,
    event_contract_catalog_v2,
    generated_contract_digest_v2,
    generated_target_catalog_v2,
    preflight_entries_v2,
    validate_contract_digests_v2,
)

type PluginApplyV2 = Callable[
    [ContextV2, Mapping[str, Any]],
    EffectResultV2 | Awaitable[EffectResultV2],
]


@dataclass(frozen=True, kw_only=True)
class PluginDefinitionV2:
    """A trusted runtime entry bound to one exact generated contract digest."""

    module_ref: str
    contract_digest: str
    apply: PluginApplyV2


class FiberV2:
    """One entry activation with explicit state and asynchronous LIFO cleanup."""

    def __init__(
        self,
        *,
        entry: ProfileEntryV2,
        definition: PluginDefinitionV2,
        contract: PluginContractV2,
        event_contracts: Mapping[str, EventContractV2],
        providers: _ProviderStore,
        events: _EventBusV2,
    ) -> None:
        self.entry = entry
        self.definition = definition
        self.contract = contract
        self.phase = FiberPhaseV2.PENDING
        self.error: BaseException | None = None
        self._effects = _EffectStack(lambda: self.phase)
        self.context = ContextV2(
            entry_id=entry.entry_id,
            scope=entry.scope,
            providers=providers,
            events=events,
            effects=self._effects,
            contract=contract,
            event_contracts=event_contracts,
            inject=entry.inject,
            isolation=entry.isolate,
        )

    async def start(self) -> None:
        if self.phase != FiberPhaseV2.PENDING:
            raise RuntimeV2Error("invalid_fiber_transition", f"cannot start from {self.phase}")
        self.phase = FiberPhaseV2.LOADING
        try:
            result = self.definition.apply(self.context, self.entry.config)
            if inspect.isawaitable(result):
                result = await result
            await self._effects.add_result(result, label="apply")
            self.phase = FiberPhaseV2.ACTIVE
        except Exception as exc:
            self.error = exc
            self.phase = FiberPhaseV2.FAILED
            await self._effects.dispose()
            raise

    async def dispose(self) -> None:
        if self.phase == FiberPhaseV2.DISPOSED:
            return
        if self.phase == FiberPhaseV2.PENDING:
            self.phase = FiberPhaseV2.DISPOSED
            return
        if self.phase == FiberPhaseV2.UNLOADING:
            return
        self.phase = FiberPhaseV2.UNLOADING
        await self._effects.dispose()
        self.phase = FiberPhaseV2.DISPOSED

    def diagnostics(self) -> FiberDiagnosticV2:
        return FiberDiagnosticV2(
            entry_id=self.entry.entry_id,
            phase=self.phase,
            effects=self._effects.diagnostics(),
            error=None if self.error is None else f"{type(self.error).__name__}: {self.error}",
        )


class RuntimeGenerationV2:
    """An immutable published entry set; mutable state is private lifecycle metadata."""

    def __init__(
        self,
        *,
        snapshot: ProfileSnapshotV2,
        fibers: Sequence[FiberV2],
        providers: _ProviderStore,
        events: _EventBusV2,
        event_contracts: Mapping[str, EventContractV2],
    ) -> None:
        self.snapshot = snapshot
        self.fibers = tuple(fibers)
        self._providers = providers
        self._events = events
        self._event_contracts = MappingProxyType(dict(event_contracts))
        self._lease_count = 0
        self._retired = False
        self._disposed = False

    @property
    def generation(self) -> int:
        return self.snapshot.generation

    @property
    def digest(self) -> str:
        return self.snapshot.digest

    @property
    def descriptor(self) -> PluginGenerationDescriptorV2:
        return PluginGenerationDescriptorV2(
            profile_id=self.snapshot.profile_id,
            generation=self.snapshot.generation,
            digest=self.snapshot.digest,
        )

    def resolve(
        self,
        service: str,
        scope: ScopeV2,
        *,
        version: str = "1.0.0",
        isolation: str | None = None,
    ) -> object:
        if self._disposed:
            raise RuntimeV2Error("disposed_generation", "generation is disposed")
        return self._providers.resolve(service, version, scope, isolation)

    async def dispose(self) -> None:
        if self._disposed:
            return
        for fiber in reversed(self.fibers):
            await fiber.dispose()
        self._disposed = True


class OperationContextV2:
    """An isolated, disposable service overlay for one request, turn, or operation."""

    def __init__(
        self,
        *,
        generation: RuntimeGenerationV2,
        operation_id: str,
        scope: ScopeV2,
    ) -> None:
        self.generation = generation
        self.operation_id = operation_id
        self.phase = FiberPhaseV2.PENDING
        self._effects = _EffectStack(lambda: self.phase)
        providers = _ProviderStore(generation._providers)
        events = _EventBusV2(generation._events)
        root = ContextV2(
            entry_id=f"operation:{operation_id}",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
            providers=providers,
            events=events,
            effects=self._effects,
            event_contracts=generation._event_contracts,
            privileged=True,
        )
        contexts = [root]
        for child_scope in _operation_scope_chain(scope)[1:]:
            contexts.append(contexts[-1].extend(scope=child_scope))
        self.contexts = tuple(contexts)
        self.context = self.contexts[-1]

    @property
    def descriptor(self) -> PluginGenerationDescriptorV2:
        return self.generation.descriptor

    async def __aenter__(self) -> OperationContextV2:
        if self.phase is not FiberPhaseV2.PENDING:
            raise RuntimeV2Error(
                "invalid_operation_transition",
                f"cannot start operation from {self.phase}",
            )
        self.phase = FiberPhaseV2.LOADING
        self.phase = FiberPhaseV2.ACTIVE
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.dispose()

    def provide(
        self,
        service: str,
        value: object,
        *,
        version: str = "1.0.0",
        label: str | None = None,
    ) -> AsyncDisposerV2:
        return self.context.provide(service, value, version=version, label=label)

    def require(self, service: str, *, version: str = "1.0.0") -> object:
        return self.context.require(service, version=version)

    async def dispatch(self, event: str, payload: object) -> object:
        return await self.context.dispatch(event, payload)

    async def effect(
        self,
        setup: Callable[[], EffectResultV2 | Awaitable[EffectResultV2]],
        *,
        label: str,
    ) -> None:
        await self.context.effect(setup, label=label)

    async def dispose(self) -> None:
        if self.phase is FiberPhaseV2.DISPOSED:
            return
        if self.phase is FiberPhaseV2.PENDING:
            self.phase = FiberPhaseV2.DISPOSED
            return
        self.phase = FiberPhaseV2.UNLOADING
        await self._effects.dispose()
        self.phase = FiberPhaseV2.DISPOSED


class LoaderV2:
    """Stages a complete generation from a strict snapshot and trusted module catalog."""

    def __init__(
        self,
        definitions: Sequence[PluginDefinitionV2] = (),
        *,
        target: DataPlaneTargetV2 = DataPlaneTargetV2.PYTHON,
        target_catalog: Mapping[str, str] | None = None,
    ) -> None:
        self._definitions: dict[str, PluginDefinitionV2] = {}
        self._target = target
        catalog = generated_target_catalog_v2(target) if target_catalog is None else target_catalog
        self._target_catalog = MappingProxyType(dict(catalog))
        for definition in definitions:
            self.register_module(definition)

    def register_module(self, definition: PluginDefinitionV2) -> None:
        if definition.module_ref in self._definitions:
            raise RuntimeV2Error(
                "duplicate_module_definition",
                f"module {definition.module_ref} is already registered",
            )
        self._definitions[definition.module_ref] = definition

    async def stage(self, snapshot: ProfileSnapshotV2) -> RuntimeGenerationV2:
        modules_by_key = {
            (manifest.plugin_id, module.module_ref): module
            for manifest in snapshot.manifests
            for module in manifest.modules
        }
        for module in modules_by_key.values():
            if self._target not in module.targets:
                continue
            catalog_digest = self._target_catalog.get(module.module_ref)
            if catalog_digest is None:
                raise RuntimeV2Error(
                    "missing_target_catalog",
                    f"module {module.module_ref} is absent from {self._target.value} catalog",
                )
            validate_contract_digests_v2(module, catalog_digest=catalog_digest)

        enabled = {
            entry.entry_id: entry
            for entry in project_snapshot_entries_v2(snapshot, self._target)
            if entry.enabled
        }
        definitions: dict[str, PluginDefinitionV2] = {}
        modules: dict[str, PluginModuleV2] = {}
        for entry in enabled.values():
            definition = self._definitions.get(entry.module_ref)
            if definition is None:
                raise RuntimeV2Error(
                    "missing_module_definition",
                    f"entry {entry.entry_id} module {entry.module_ref} is unavailable",
                )
            module = modules_by_key[(entry.plugin_ref, entry.module_ref)]
            if definition.contract_digest != module.contract_digest:
                raise RuntimeV2Error(
                    "contract_digest_mismatch",
                    f"runtime module {entry.module_ref} contract digest differs from manifest",
                )
            definitions[entry.entry_id] = definition
            modules[entry.entry_id] = module
            if entry.parent_entry_id is not None and entry.parent_entry_id not in enabled:
                raise RuntimeV2Error(
                    "inactive_parent_entry",
                    f"entry {entry.entry_id} parent is disabled",
                )

        preflight_entries_v2(enabled, modules)
        order = entry_order_v2(enabled, modules)
        event_contracts = event_contract_catalog_v2(modules.values())
        providers = _ProviderStore()
        events = _EventBusV2()
        fibers: list[FiberV2] = []
        try:
            for entry_id in order:
                fiber = FiberV2(
                    entry=enabled[entry_id],
                    definition=definitions[entry_id],
                    contract=modules[entry_id].contract,
                    event_contracts=event_contracts,
                    providers=providers,
                    events=events,
                )
                fibers.append(fiber)
                await fiber.start()
        except Exception:
            for fiber in reversed(fibers):
                await fiber.dispose()
            raise
        return RuntimeGenerationV2(
            snapshot=snapshot,
            fibers=fibers,
            providers=providers,
            events=events,
            event_contracts=event_contracts,
        )


def project_snapshot_entries_v2(
    snapshot: ProfileSnapshotV2,
    target: DataPlaneTargetV2,
) -> tuple[ProfileEntryV2, ...]:
    """Project a fully validated snapshot onto one data plane without mutating it."""
    module_targets = {
        (manifest.plugin_id, module.module_ref): module.targets
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    return tuple(
        entry
        for entry in snapshot.entries
        if target in module_targets[(entry.plugin_ref, entry.module_ref)]
    )


class GenerationLeaseV2:
    def __init__(self, manager: GenerationManagerV2, generation: RuntimeGenerationV2) -> None:
        self._manager = manager
        self.generation = generation
        self._released = False

    async def __aenter__(self) -> RuntimeGenerationV2:
        return self.generation

    async def __aexit__(self, *_args: object) -> None:
        await self.release()

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._manager._release(self.generation)


class GenerationManagerV2:
    """Atomically publishes generations and drains retired generations after leases."""

    def __init__(self) -> None:
        self._current: RuntimeGenerationV2 | None = None
        self._lock = asyncio.Lock()

    @property
    def current(self) -> RuntimeGenerationV2 | None:
        return self._current

    async def publish(
        self,
        generation: RuntimeGenerationV2,
        *,
        commit: Callable[[], None] | None = None,
    ) -> RuntimeGenerationV2 | None:
        """Publish one generation with an optional no-await companion commit."""
        dispose: RuntimeGenerationV2 | None = None
        async with self._lock:
            if commit is not None:
                commit()
            previous = self._current
            self._current = generation
            if previous is not None:
                previous._retired = True
                if previous._lease_count == 0:
                    dispose = previous
        if dispose is not None:
            await dispose.dispose()
        return previous

    async def acquire(self) -> GenerationLeaseV2:
        async with self._lock:
            generation = self._current
            if generation is None:
                raise RuntimeV2Error("generation_unavailable", "no generation is published")
            generation._lease_count += 1
        return GenerationLeaseV2(self, generation)

    async def close(self) -> None:
        dispose: RuntimeGenerationV2 | None = None
        async with self._lock:
            current = self._current
            self._current = None
            if current is not None:
                current._retired = True
                if current._lease_count == 0:
                    dispose = current
        if dispose is not None:
            await dispose.dispose()

    async def _release(self, generation: RuntimeGenerationV2) -> None:
        dispose = False
        async with self._lock:
            generation._lease_count -= 1
            if generation._lease_count < 0:
                raise RuntimeV2Error("lease_underflow", "generation lease count underflow")
            dispose = generation._retired and generation._lease_count == 0
        if dispose:
            await generation.dispose()


def _operation_scope_chain(scope: ScopeV2) -> tuple[ScopeV2, ...]:
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    if scope.kind is ScopeKindV2.ROOT:
        return (root,)
    if scope.tenant_id is None:
        raise RuntimeV2Error("invalid_operation_scope", "tenant scope identifier is required")
    tenant = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=scope.tenant_id)
    if scope.kind is ScopeKindV2.TENANT:
        return root, tenant
    if scope.project_id is None:
        raise RuntimeV2Error("invalid_operation_scope", "project scope identifier is required")
    project = ScopeV2(
        kind=ScopeKindV2.PROJECT,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
    )
    if scope.kind is ScopeKindV2.PROJECT:
        return root, tenant, project
    if scope.session_id is None:
        raise RuntimeV2Error("invalid_operation_scope", "session scope identifier is required")
    session = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        session_id=scope.session_id,
    )
    return root, tenant, project, session


class SupportsApplyV2(Protocol):
    def __call__(
        self,
        context: ContextV2,
        config: Mapping[str, Any],
    ) -> EffectResultV2 | Awaitable[EffectResultV2]: ...


__all__ = [
    "AsyncDisposerV2",
    "ContextV2",
    "EffectDiagnosticV2",
    "EffectResultV2",
    "FiberDiagnosticV2",
    "FiberPhaseV2",
    "FiberV2",
    "GenerationLeaseV2",
    "GenerationManagerV2",
    "LoaderV2",
    "OperationContextV2",
    "PluginDefinitionV2",
    "RuntimeGenerationV2",
    "RuntimeV2Error",
    "generated_contract_digest_v2",
    "project_snapshot_entries_v2",
]
