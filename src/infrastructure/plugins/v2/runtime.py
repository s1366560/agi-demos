"""Context, Fiber, effect, loader, and generation semantics for plugin runtime v2."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import (
    AsyncIterable,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
    ScopeV2,
)

type AsyncDisposerV2 = Callable[[], None | Awaitable[None]]
type EffectResultV2 = (
    None | AsyncDisposerV2 | Iterable[AsyncDisposerV2] | AsyncIterable[AsyncDisposerV2]
)
type PluginApplyV2 = Callable[
    ["ContextV2", Mapping[str, Any]],
    EffectResultV2 | Awaitable[EffectResultV2],
]


class RuntimeV2Error(RuntimeError):
    """A stable runtime error with a machine-readable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FiberPhaseV2(StrEnum):
    """Valid states for one plugin entry activation."""

    PENDING = "pending"
    LOADING = "loading"
    ACTIVE = "active"
    UNLOADING = "unloading"
    DISPOSED = "disposed"
    FAILED = "failed"


@dataclass(frozen=True, kw_only=True)
class PluginDefinitionV2:
    """A trusted module catalog entry and its statically declared services."""

    module_ref: str
    apply: PluginApplyV2
    provides: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class EffectDiagnosticV2:
    label: str
    error: str | None = None


@dataclass(frozen=True, kw_only=True)
class FiberDiagnosticV2:
    entry_id: str
    phase: FiberPhaseV2
    effects: tuple[EffectDiagnosticV2, ...]
    error: str | None


@dataclass
class _EffectRecord:
    label: str
    disposer: AsyncDisposerV2
    active: bool = True
    error: str | None = None

    async def dispose(self) -> None:
        if not self.active:
            return
        self.active = False
        try:
            result = self.disposer()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"


class _EffectStack:
    def __init__(self, phase: Callable[[], FiberPhaseV2]) -> None:
        self._phase = phase
        self._records: list[_EffectRecord] = []

    def add(self, disposer: AsyncDisposerV2, *, label: str) -> AsyncDisposerV2:
        self._ensure_active()
        record = _EffectRecord(label=label, disposer=disposer)
        self._records.append(record)
        return record.dispose

    async def add_result(self, result: EffectResultV2, *, label: str) -> None:
        self._ensure_active()
        if result is None:
            return
        if callable(result):
            self.add(result, label=label)
            return
        if isinstance(result, AsyncIterable):
            index = 0
            async for disposer in result:
                if not callable(disposer):
                    raise RuntimeV2Error("invalid_effect", f"{label}[{index}] is not callable")
                self.add(disposer, label=f"{label}[{index}]")
                index += 1
            return
        if isinstance(result, Iterable) and not isinstance(result, (str, bytes, Mapping)):
            for index, disposer in enumerate(result):
                if not callable(disposer):
                    raise RuntimeV2Error("invalid_effect", f"{label}[{index}] is not callable")
                self.add(disposer, label=f"{label}[{index}]")
            return
        raise RuntimeV2Error("invalid_effect", f"{label} returned an unsupported effect")

    async def dispose(self) -> None:
        for record in reversed(self._records):
            await record.dispose()

    def diagnostics(self) -> tuple[EffectDiagnosticV2, ...]:
        return tuple(
            EffectDiagnosticV2(label=item.label, error=item.error) for item in self._records
        )

    def _ensure_active(self) -> None:
        if self._phase() not in {FiberPhaseV2.LOADING, FiberPhaseV2.ACTIVE}:
            raise RuntimeV2Error("inactive_effect", "inactive context cannot register an effect")


@dataclass(frozen=True)
class _ProviderRecord:
    service: str
    value: object
    scope: ScopeV2
    isolation: str | None
    owner_entry_id: str


class _ProviderStore:
    def __init__(self) -> None:
        self._records: list[_ProviderRecord] = []

    def add(self, record: _ProviderRecord) -> AsyncDisposerV2:
        if any(
            item.service == record.service
            and item.scope == record.scope
            and item.isolation == record.isolation
            for item in self._records
        ):
            raise RuntimeV2Error(
                "service_conflict",
                f"service {record.service} already has a provider in this scope and isolation",
            )
        self._records.append(record)

        async def dispose() -> None:
            if record in self._records:
                self._records.remove(record)

        return dispose

    def resolve(self, service: str, scope: ScopeV2, isolation: str | None) -> object:
        candidates = [
            item
            for item in self._records
            if item.service == service
            and item.isolation == isolation
            and _scope_contains(item.scope, scope)
        ]
        if not candidates:
            raise RuntimeV2Error(
                "missing_service",
                f"service {service} is unavailable for scope {scope.kind.value}",
            )
        candidates.sort(key=lambda item: _scope_rank(item.scope), reverse=True)
        top_rank = _scope_rank(candidates[0].scope)
        if sum(_scope_rank(item.scope) == top_rank for item in candidates) > 1:
            raise RuntimeV2Error(
                "ambiguous_service",
                f"service {service} has multiple nearest providers",
            )
        return candidates[0].value


@dataclass(frozen=True)
class _ListenerRecord:
    event: str
    handler: Callable[..., Any]
    scope: ScopeV2
    owner_entry_id: str


class _EventBusV2:
    def __init__(self) -> None:
        self._listeners: list[_ListenerRecord] = []

    def add(self, record: _ListenerRecord) -> AsyncDisposerV2:
        self._listeners.append(record)

        async def dispose() -> None:
            if record in self._listeners:
                self._listeners.remove(record)

        return dispose

    def listeners(self, event: str, scope: ScopeV2) -> tuple[_ListenerRecord, ...]:
        return tuple(
            item
            for item in self._listeners
            if item.event == event and _scope_contains(item.scope, scope)
        )


class ContextV2:
    """The only API through which a v2 plugin can contribute or consume state."""

    def __init__(
        self,
        *,
        entry_id: str,
        scope: ScopeV2,
        providers: _ProviderStore,
        events: _EventBusV2,
        effects: _EffectStack,
        inject: Mapping[str, str] | None = None,
        isolation: Mapping[str, str] | None = None,
        interceptors: Mapping[str, Sequence[Callable[[object], object]]] | None = None,
        privileged: bool = False,
    ) -> None:
        self.entry_id = entry_id
        self.scope = scope
        self._providers = providers
        self._events = events
        self._effects = effects
        self._inject = MappingProxyType(dict(inject or {}))
        self._isolation = MappingProxyType(dict(isolation or {}))
        self._interceptors = {key: tuple(value) for key, value in (interceptors or {}).items()}
        self._privileged = privileged

    def extend(
        self,
        *,
        entry_id: str | None = None,
        scope: ScopeV2 | None = None,
        inject: Mapping[str, str] | None = None,
    ) -> ContextV2:
        return ContextV2(
            entry_id=entry_id or self.entry_id,
            scope=scope or self.scope,
            providers=self._providers,
            events=self._events,
            effects=self._effects,
            inject=self._inject if inject is None else inject,
            isolation=self._isolation,
            interceptors=self._interceptors,
            privileged=self._privileged,
        )

    def isolate(self, service: str, *, label: str) -> ContextV2:
        isolation = {**self._isolation, service: label}
        return self._copy(isolation=isolation)

    def intercept(self, service: str, interceptor: Callable[[object], object]) -> ContextV2:
        interceptors = dict(self._interceptors)
        interceptors[service] = (*interceptors.get(service, ()), interceptor)
        return self._copy(interceptors=interceptors)

    def provide(self, service: str, value: object, *, label: str | None = None) -> AsyncDisposerV2:
        self._effects._ensure_active()
        disposer = self._providers.add(
            _ProviderRecord(
                service=service,
                value=value,
                scope=self.scope,
                isolation=self._isolation.get(service),
                owner_entry_id=self.entry_id,
            )
        )
        return self._effects.add(disposer, label=label or f"provide:{service}")

    def get(self, service_or_alias: str, default: object = None) -> object:
        try:
            service = self._resolve_injected_service(service_or_alias)
            value = self._providers.resolve(
                service,
                self.scope,
                self._isolation.get(service),
            )
            for interceptor in self._interceptors.get(service, ()):
                value = interceptor(value)
            return value
        except RuntimeV2Error as exc:
            if exc.code == "missing_service":
                return default
            raise

    def require(self, service_or_alias: str) -> object:
        service = self._resolve_injected_service(service_or_alias)
        value = self._providers.resolve(service, self.scope, self._isolation.get(service))
        for interceptor in self._interceptors.get(service, ()):
            value = interceptor(value)
        return value

    async def effect(
        self,
        setup: Callable[[], EffectResultV2 | Awaitable[EffectResultV2]],
        *,
        label: str,
    ) -> None:
        self._effects._ensure_active()
        result = setup()
        if inspect.isawaitable(result):
            result = await result
        await self._effects.add_result(result, label=label)

    def on(self, event: str, handler: Callable[..., Any]) -> AsyncDisposerV2:
        self._effects._ensure_active()
        disposer = self._events.add(
            _ListenerRecord(
                event=event,
                handler=handler,
                scope=self.scope,
                owner_entry_id=self.entry_id,
            )
        )
        return self._effects.add(disposer, label=f"event:{event}")

    async def emit(self, event: str, payload: object) -> tuple[object, ...]:
        listeners = self._events.listeners(event, self.scope)
        return tuple(await asyncio.gather(*[_invoke(item.handler, payload) for item in listeners]))

    async def serial(self, event: str, payload: object) -> tuple[object, ...]:
        results: list[object] = []
        for item in self._events.listeners(event, self.scope):
            results.append(await _invoke(item.handler, payload))
        return tuple(results)

    async def bail(self, event: str, payload: object) -> object | None:
        for item in self._events.listeners(event, self.scope):
            result = await _invoke(item.handler, payload)
            if result is not None:
                return result
        return None

    async def waterfall(self, event: str, payload: object) -> object:
        listeners = self._events.listeners(event, self.scope)

        async def dispatch(index: int, current: object) -> object:
            if index >= len(listeners):
                return current
            called = False

            async def next_(next_value: object = current) -> object:
                nonlocal called
                if called:
                    raise RuntimeV2Error("waterfall_next_reused", "waterfall next() called twice")
                called = True
                return await dispatch(index + 1, next_value)

            return await _invoke(listeners[index].handler, current, next_)

        return await dispatch(0, payload)

    def _resolve_injected_service(self, service_or_alias: str) -> str:
        if self._privileged:
            return self._inject.get(service_or_alias, service_or_alias)
        service = self._inject.get(service_or_alias)
        if service is None:
            raise RuntimeV2Error(
                "undeclared_inject",
                f"entry {self.entry_id} did not inject {service_or_alias}",
            )
        return service

    def _copy(
        self,
        *,
        isolation: Mapping[str, str] | None = None,
        interceptors: Mapping[str, Sequence[Callable[[object], object]]] | None = None,
    ) -> ContextV2:
        return ContextV2(
            entry_id=self.entry_id,
            scope=self.scope,
            providers=self._providers,
            events=self._events,
            effects=self._effects,
            inject=self._inject,
            isolation=isolation or self._isolation,
            interceptors=interceptors or self._interceptors,
            privileged=self._privileged,
        )


class FiberV2:
    """One entry activation with explicit state and asynchronous LIFO cleanup."""

    def __init__(
        self,
        *,
        entry: ProfileEntryV2,
        definition: PluginDefinitionV2,
        providers: _ProviderStore,
        events: _EventBusV2,
    ) -> None:
        self.entry = entry
        self.definition = definition
        self.phase = FiberPhaseV2.PENDING
        self.error: BaseException | None = None
        self._effects = _EffectStack(lambda: self.phase)
        self.context = ContextV2(
            entry_id=entry.entry_id,
            scope=entry.scope,
            providers=providers,
            events=events,
            effects=self._effects,
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
    ) -> None:
        self.snapshot = snapshot
        self.fibers = tuple(fibers)
        self._providers = providers
        self._lease_count = 0
        self._retired = False
        self._disposed = False

    @property
    def generation(self) -> int:
        return self.snapshot.generation

    @property
    def digest(self) -> str:
        return self.snapshot.digest

    def resolve(self, service: str, scope: ScopeV2, *, isolation: str | None = None) -> object:
        if self._disposed:
            raise RuntimeV2Error("disposed_generation", "generation is disposed")
        return self._providers.resolve(service, scope, isolation)

    async def dispose(self) -> None:
        if self._disposed:
            return
        for fiber in reversed(self.fibers):
            await fiber.dispose()
        self._disposed = True


class LoaderV2:
    """Stages a complete generation from a strict snapshot and trusted module catalog."""

    def __init__(
        self,
        definitions: Sequence[PluginDefinitionV2] = (),
        *,
        target: DataPlaneTargetV2 = DataPlaneTargetV2.PYTHON,
    ) -> None:
        self._definitions = {item.module_ref: item for item in definitions}
        self._target = target

    def register_module(self, definition: PluginDefinitionV2) -> None:
        if definition.module_ref in self._definitions:
            raise RuntimeV2Error(
                "duplicate_module_definition",
                f"module {definition.module_ref} is already registered",
            )
        self._definitions[definition.module_ref] = definition

    async def stage(self, snapshot: ProfileSnapshotV2) -> RuntimeGenerationV2:
        enabled = {
            entry.entry_id: entry
            for entry in project_snapshot_entries_v2(snapshot, self._target)
            if entry.enabled
        }
        definitions: dict[str, PluginDefinitionV2] = {}
        for entry in enabled.values():
            definition = self._definitions.get(entry.module_ref)
            if definition is None:
                raise RuntimeV2Error(
                    "missing_module_definition",
                    f"entry {entry.entry_id} module {entry.module_ref} is unavailable",
                )
            definitions[entry.entry_id] = definition
            if entry.parent_entry_id is not None and entry.parent_entry_id not in enabled:
                raise RuntimeV2Error(
                    "inactive_parent_entry",
                    f"entry {entry.entry_id} parent is disabled",
                )

        order = _entry_order(enabled, definitions)
        providers = _ProviderStore()
        events = _EventBusV2()
        fibers: list[FiberV2] = []
        try:
            for entry_id in order:
                fiber = FiberV2(
                    entry=enabled[entry_id],
                    definition=definitions[entry_id],
                    providers=providers,
                    events=events,
                )
                fibers.append(fiber)
                await fiber.start()
        except Exception:
            for fiber in reversed(fibers):
                await fiber.dispose()
            raise
        return RuntimeGenerationV2(snapshot=snapshot, fibers=fibers, providers=providers)


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

    async def publish(self, generation: RuntimeGenerationV2) -> RuntimeGenerationV2 | None:
        dispose: RuntimeGenerationV2 | None = None
        async with self._lock:
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


async def _invoke(handler: Callable[..., Any], *args: object) -> object:
    result = handler(*args)
    if inspect.isawaitable(result):
        return await result
    return result


def _scope_rank(scope: ScopeV2) -> int:
    return {"root": 0, "tenant": 1, "project": 2, "session": 3}[scope.kind.value]


def _scope_contains(parent: ScopeV2, child: ScopeV2) -> bool:
    if _scope_rank(parent) > _scope_rank(child):
        return False
    for name in ("tenant_id", "project_id", "session_id"):
        parent_value = getattr(parent, name)
        if parent_value is not None and parent_value != getattr(child, name):
            return False
    return True


def _entry_order(
    entries: Mapping[str, ProfileEntryV2],
    definitions: Mapping[str, PluginDefinitionV2],
) -> tuple[str, ...]:
    dependencies: dict[str, set[str]] = {entry_id: set() for entry_id in entries}
    for entry_id, entry in entries.items():
        if entry.parent_entry_id is not None:
            dependencies[entry_id].add(entry.parent_entry_id)
        for service in entry.inject.values():
            providers = [
                provider_id
                for provider_id, definition in definitions.items()
                if service in definition.provides
                and _scope_contains(entries[provider_id].scope, entry.scope)
                and entries[provider_id].isolate.get(service) == entry.isolate.get(service)
            ]
            if not providers:
                raise RuntimeV2Error(
                    "missing_inject_provider",
                    f"entry {entry_id} injects missing service {service}",
                )
            providers.sort(key=lambda item: _scope_rank(entries[item].scope), reverse=True)
            top_rank = _scope_rank(entries[providers[0]].scope)
            nearest = [item for item in providers if _scope_rank(entries[item].scope) == top_rank]
            if len(nearest) != 1:
                raise RuntimeV2Error(
                    "ambiguous_inject_provider",
                    f"entry {entry_id} has ambiguous service {service}",
                )
            if nearest[0] != entry_id:
                dependencies[entry_id].add(nearest[0])

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(entry_id: str) -> None:
        if entry_id in visited:
            return
        if entry_id in visiting:
            raise RuntimeV2Error("entry_dependency_cycle", f"entry cycle includes {entry_id}")
        visiting.add(entry_id)
        for dependency in sorted(dependencies[entry_id]):
            visit(dependency)
        visiting.remove(entry_id)
        visited.add(entry_id)
        ordered.append(entry_id)

    for entry_id in sorted(entries):
        visit(entry_id)
    return tuple(ordered)


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
    "PluginDefinitionV2",
    "RuntimeGenerationV2",
    "RuntimeV2Error",
    "project_snapshot_entries_v2",
]
