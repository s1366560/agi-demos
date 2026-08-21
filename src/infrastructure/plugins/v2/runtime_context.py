"""Scoped services, events, and reversible effects for plugin runtime v2."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

import jsonschema

from src.domain.model.plugins.generated_v2 import (
    EventContractV2,
    EventModeV2,
    PluginContractV2,
    ScopeV2,
)

type AsyncDisposerV2 = Callable[[], None | Awaitable[None]]
type EffectResultV2 = (
    None | AsyncDisposerV2 | Iterable[AsyncDisposerV2] | AsyncIterable[AsyncDisposerV2]
)


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
    version: str
    value: object
    scope: ScopeV2
    isolation: str | None
    owner_entry_id: str


class _ProviderStore:
    def __init__(self, parent: _ProviderStore | None = None) -> None:
        self._records: list[_ProviderRecord] = []
        self._parent = parent

    def add(self, record: _ProviderRecord) -> AsyncDisposerV2:
        if any(
            item.service == record.service
            and item.version == record.version
            and item.scope == record.scope
            and item.isolation == record.isolation
            for item in self._records
        ):
            raise RuntimeV2Error(
                "service_conflict",
                f"service {record.service}@{record.version} already has a provider "
                "in this scope and isolation",
            )
        self._records.append(record)

        async def dispose() -> None:
            if record in self._records:
                self._records.remove(record)

        return dispose

    def resolve(
        self,
        service: str,
        version: str,
        scope: ScopeV2,
        isolation: str | None,
    ) -> object:
        candidates = self._candidates(service, version, scope, isolation)
        if self._parent is not None:
            candidates.extend(self._parent._candidates(service, version, scope, isolation))
        if not candidates:
            raise RuntimeV2Error(
                "missing_service",
                f"service {service}@{version} is unavailable for scope {scope.kind.value}",
            )
        candidates.sort(key=lambda item: scope_rank_v2(item.scope), reverse=True)
        top_rank = scope_rank_v2(candidates[0].scope)
        if sum(scope_rank_v2(item.scope) == top_rank for item in candidates) > 1:
            raise RuntimeV2Error(
                "ambiguous_service",
                f"service {service} has multiple nearest providers",
            )
        return candidates[0].value

    def _candidates(
        self,
        service: str,
        version: str,
        scope: ScopeV2,
        isolation: str | None,
    ) -> list[_ProviderRecord]:
        return [
            item
            for item in self._records
            if item.service == service
            and item.version == version
            and item.isolation == isolation
            and scope_contains_v2(item.scope, scope)
        ]


@dataclass(frozen=True)
class _ListenerRecord:
    event: str
    handler: Callable[..., Any]
    scope: ScopeV2
    owner_entry_id: str


class _EventBusV2:
    def __init__(self, parent: _EventBusV2 | None = None) -> None:
        self._listeners: list[_ListenerRecord] = []
        self._parent = parent

    def add(self, record: _ListenerRecord) -> AsyncDisposerV2:
        self._listeners.append(record)

        async def dispose() -> None:
            if record in self._listeners:
                self._listeners.remove(record)

        return dispose

    def listeners(self, event: str, scope: ScopeV2) -> tuple[_ListenerRecord, ...]:
        inherited = () if self._parent is None else self._parent.listeners(event, scope)
        local = tuple(
            item
            for item in self._listeners
            if item.event == event and scope_contains_v2(item.scope, scope)
        )
        return (*inherited, *local)


async def _invoke(handler: Callable[..., Any], *args: object) -> object:
    result = handler(*args)
    if inspect.isawaitable(result):
        return await result
    return result


def scope_rank_v2(scope: ScopeV2) -> int:
    return {"root": 0, "tenant": 1, "project": 2, "session": 3}[scope.kind.value]


def scope_contains_v2(parent: ScopeV2, child: ScopeV2) -> bool:
    if scope_rank_v2(parent) > scope_rank_v2(child):
        return False
    for name in ("tenant_id", "project_id", "session_id"):
        parent_value = getattr(parent, name)
        if parent_value is not None and parent_value != getattr(child, name):
            return False
    return True


def _validate_event_value(
    schema: Mapping[str, Any],
    value: object,
    *,
    code: str,
    event: str,
) -> None:
    try:
        jsonschema.Draft202012Validator(cast(Any, schema)).validate(cast(Any, value))
    except jsonschema.ValidationError as exc:
        raise RuntimeV2Error(code, f"event {event}: {exc.message}") from exc


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
        contract: PluginContractV2 | None = None,
        event_contracts: Mapping[str, EventContractV2] | None = None,
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
        self._contract = contract
        self._event_contracts = MappingProxyType(dict(event_contracts or {}))
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
            contract=self._contract,
            event_contracts=self._event_contracts,
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

    def provide(
        self,
        service: str,
        value: object,
        *,
        version: str | None = None,
        label: str | None = None,
    ) -> AsyncDisposerV2:
        self._effects._ensure_active()
        resolved_version = version or "1.0.0"
        if not self._privileged:
            provision = next(
                (
                    item
                    for item in self._required_contract().services.provides
                    if item.service == service
                ),
                None,
            )
            if provision is None:
                raise RuntimeV2Error(
                    "undeclared_provide",
                    f"entry {self.entry_id} did not declare provide {service}",
                )
            if version is not None and version != provision.version:
                raise RuntimeV2Error(
                    "provide_version_mismatch",
                    f"entry {self.entry_id} declared {service}@{provision.version}",
                )
            resolved_version = provision.version
        disposer = self._providers.add(
            _ProviderRecord(
                service=service,
                version=resolved_version,
                value=value,
                scope=self.scope,
                isolation=self._isolation.get(service),
                owner_entry_id=self.entry_id,
            )
        )
        return self._effects.add(disposer, label=label or f"provide:{service}")

    def require(self, service_or_alias: str, *, version: str | None = None) -> object:
        service, resolved_version = self._resolve_injected_service(
            service_or_alias, version=version
        )
        value = self._providers.resolve(
            service,
            resolved_version,
            self.scope,
            self._isolation.get(service),
        )
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
        if not self._privileged and not any(
            item.event == event for item in self._required_contract().events.handles
        ):
            raise RuntimeV2Error(
                "undeclared_event_handler",
                f"entry {self.entry_id} did not declare handler {event}",
            )
        disposer = self._events.add(
            _ListenerRecord(
                event=event,
                handler=handler,
                scope=self.scope,
                owner_entry_id=self.entry_id,
            )
        )
        return self._effects.add(disposer, label=f"event:{event}")

    async def dispatch(self, event: str, payload: object) -> object:
        declaration = self._dispatch_contract(event)
        _validate_event_value(
            declaration.payload_schema,
            payload,
            code="invalid_event_payload",
            event=event,
        )
        listeners = self._events.listeners(event, self.scope)

        if declaration.mode is EventModeV2.EMIT:
            emitted_results = tuple(
                await asyncio.gather(*[_invoke(item.handler, payload) for item in listeners])
            )
            for emitted_result in emitted_results:
                _validate_event_value(
                    declaration.result_schema,
                    emitted_result,
                    code="invalid_event_result",
                    event=event,
                )
            return emitted_results
        if declaration.mode is EventModeV2.SERIAL:
            serial_results: list[object] = []
            for item in listeners:
                serial_result = await _invoke(item.handler, payload)
                _validate_event_value(
                    declaration.result_schema,
                    serial_result,
                    code="invalid_event_result",
                    event=event,
                )
                serial_results.append(serial_result)
            return tuple(serial_results)
        if declaration.mode is EventModeV2.BAIL:
            bail_result: object = None
            for item in listeners:
                bail_result = await _invoke(item.handler, payload)
                if bail_result is not None:
                    break
            _validate_event_value(
                declaration.result_schema,
                bail_result,
                code="invalid_event_result",
                event=event,
            )
            return bail_result

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

        result = await dispatch(0, payload)
        _validate_event_value(
            declaration.result_schema,
            result,
            code="invalid_event_result",
            event=event,
        )
        return result

    def _resolve_injected_service(
        self,
        service_or_alias: str,
        *,
        version: str | None,
    ) -> tuple[str, str]:
        if self._privileged:
            return self._inject.get(service_or_alias, service_or_alias), version or "1.0.0"
        requirement = next(
            (
                item
                for item in self._required_contract().services.requires
                if item.alias == service_or_alias
            ),
            None,
        )
        if requirement is None:
            raise RuntimeV2Error(
                "undeclared_require",
                f"entry {self.entry_id} did not declare require {service_or_alias}",
            )
        if version is not None and version != requirement.version:
            raise RuntimeV2Error(
                "require_version_mismatch",
                f"entry {self.entry_id} declared {requirement.service}@{requirement.version}",
            )
        service = self._inject.get(service_or_alias)
        if service is None:
            raise RuntimeV2Error(
                "missing_required_inject",
                f"entry {self.entry_id} did not inject {service_or_alias}",
            )
        return service, requirement.version

    def _required_contract(self) -> PluginContractV2:
        if self._contract is None:
            raise RuntimeV2Error("missing_module_contract", "plugin context has no contract")
        return self._contract

    def _dispatch_contract(self, event: str) -> EventContractV2:
        if self._privileged:
            declaration = self._event_contracts.get(event)
        else:
            declaration = next(
                (item for item in self._required_contract().events.emits if item.event == event),
                None,
            )
        if declaration is None:
            raise RuntimeV2Error(
                "undeclared_event_dispatch",
                f"entry {self.entry_id} did not declare dispatch {event}",
            )
        return declaration

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
            contract=self._contract,
            event_contracts=self._event_contracts,
            inject=self._inject,
            isolation=isolation or self._isolation,
            interceptors=interceptors or self._interceptors,
            privileged=self._privileged,
        )


__all__ = [
    "AsyncDisposerV2",
    "ContextV2",
    "EffectDiagnosticV2",
    "EffectResultV2",
    "FiberDiagnosticV2",
    "FiberPhaseV2",
    "RuntimeV2Error",
]
