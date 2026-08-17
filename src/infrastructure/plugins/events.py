"""Typed platform event dispatch with explicit mode semantics."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.domain.model.plugins import (
    PLATFORM_PLUGIN_EVENTS,
    EventDefinition,
    MissingNextPolicy,
    PluginEventMode,
)

EventHandler = Callable[[Mapping[str, Any]], Any]
NextHandler = Callable[[], Any]
Disposable = Callable[[], None]


@dataclass(frozen=True)
class EventDiagnostic:
    """One contained plugin event failure."""

    plugin_id: str
    event: str
    code: str
    message: str


@dataclass(frozen=True)
class EventAuditEntry:
    """Observable record for one listener invocation."""

    plugin_id: str
    event: str
    mode: PluginEventMode
    latency_us: int
    diagnostic_codes: tuple[str, ...] = ()


ObserverResult = tuple[list[EventDiagnostic], list[EventAuditEntry]]


@dataclass(frozen=True)
class EventDispatchResult:
    """Outcome of one event dispatch."""

    payload: Mapping[str, Any]
    diagnostics: tuple[EventDiagnostic, ...] = ()
    audit: tuple[EventAuditEntry, ...] = ()
    denied: bool = False


@dataclass
class _Listener:
    plugin_id: str
    handler: EventHandler


class PluginEventBus:
    """Dispatch typed plugin events without letting one plugin break the host."""

    def __init__(
        self,
        definitions: Mapping[str, EventDefinition] | None = None,
    ) -> None:
        source = tuple(definitions.values()) if definitions else tuple(PLATFORM_PLUGIN_EVENTS)
        self._definitions = {definition.name: definition for definition in source}
        self._listeners: dict[str, list[_Listener]] = {}
        self._background_tasks: set[asyncio.Task[ObserverResult]] = set()

    def subscribe(
        self,
        event_name: str,
        plugin_id: str,
        handler: EventHandler,
        *,
        overwrite: bool = False,
    ) -> Disposable:
        """Subscribe one plugin handler and return its disposer."""
        if event_name not in self._definitions:
            raise ValueError(f"unknown platform plugin event: {event_name}")
        if not plugin_id.strip():
            raise ValueError("plugin_id must be non-empty")
        if self._definitions[event_name].mode == PluginEventMode.WATERFALL:
            if not inspect.iscoroutinefunction(handler):
                raise ValueError(f"waterfall event {event_name} requires an async handler")

        listeners = self._listeners.setdefault(event_name, [])
        if any(listener.plugin_id == plugin_id for listener in listeners):
            if not overwrite:
                raise ValueError(f"event {event_name} already has listener {plugin_id}")
            listeners[:] = [listener for listener in listeners if listener.plugin_id != plugin_id]
        listeners.append(_Listener(plugin_id=plugin_id, handler=handler))

        def dispose() -> None:
            remaining = self._listeners.get(event_name, [])
            remaining[:] = [listener for listener in remaining if listener.plugin_id != plugin_id]

        return dispose

    def definition(self, event_name: str) -> EventDefinition:
        """Return one event contract."""
        try:
            return self._definitions[event_name]
        except KeyError as exc:
            raise ValueError(f"unknown platform plugin event: {event_name}") from exc

    def list_listeners(self, event_name: str) -> tuple[str, ...]:
        """Return deterministic plugin ids listening to one event."""
        return tuple(listener.plugin_id for listener in self._listeners.get(event_name, ()))

    async def emit(self, event_name: str, payload: Mapping[str, Any]) -> EventDispatchResult:
        """Dispatch an emit event without awaiting listeners."""
        definition = self._require_mode(event_name, PluginEventMode.EMIT)
        diagnostics: list[EventDiagnostic] = []
        audit: list[EventAuditEntry] = []
        for listener in tuple(self._listeners.get(event_name, ())):
            started = time.perf_counter_ns()
            task = asyncio.create_task(
                self._invoke_observer(event_name, definition, listener, payload)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            audit.append(
                EventAuditEntry(
                    plugin_id=listener.plugin_id,
                    event=event_name,
                    mode=definition.mode,
                    latency_us=(time.perf_counter_ns() - started) // 1000,
                    diagnostic_codes=(),
                )
            )
        return EventDispatchResult(
            payload=payload,
            diagnostics=tuple(diagnostics),
            audit=tuple(audit),
        )

    async def parallel(self, event_name: str, payload: Mapping[str, Any]) -> EventDispatchResult:
        """Dispatch observers in parallel and await all listener promises."""
        definition = self._require_mode(event_name, PluginEventMode.PARALLEL)
        listeners = tuple(self._listeners.get(event_name, ()))
        results = await asyncio.gather(
            *(
                self._invoke_observer(event_name, definition, listener, payload)
                for listener in listeners
            )
        )
        diagnostics = [item for result in results for item in result[0]]
        audit = [item for result in results for item in result[1]]
        return EventDispatchResult(
            payload=payload, diagnostics=tuple(diagnostics), audit=tuple(audit)
        )

    async def serial(self, event_name: str, payload: Mapping[str, Any]) -> EventDispatchResult:
        """Dispatch mutating observers in registration order."""
        definition = self._require_mode(event_name, PluginEventMode.SERIAL)
        current = dict(payload)
        diagnostics: list[EventDiagnostic] = []
        audit: list[EventAuditEntry] = []
        for listener in tuple(self._listeners.get(event_name, ())):
            result, listener_diagnostics, listener_audit = await self._invoke_mutating(
                event_name,
                definition,
                listener,
                current,
            )
            diagnostics.extend(listener_diagnostics)
            audit.extend(listener_audit)
            if isinstance(result, Mapping):
                current = dict(result)
        return EventDispatchResult(
            payload=current,
            diagnostics=tuple(diagnostics),
            audit=tuple(audit),
        )

    async def waterfall(
        self,
        event_name: str,
        payload: Mapping[str, Any],
    ) -> EventDispatchResult:
        """Dispatch a cooperative waterfall and retain the final payload."""
        definition = self._require_mode(event_name, PluginEventMode.WATERFALL)
        listeners = tuple(self._listeners.get(event_name, ()))
        diagnostics: list[EventDiagnostic] = []
        audit: list[EventAuditEntry] = []

        async def call_next(index: int = 0, current: Mapping[str, Any] = payload) -> object:
            if index >= len(listeners):
                return current
            listener = listeners[index]
            next_called = False
            handler_payload = dict(current)

            async def next_handler() -> object:
                nonlocal next_called
                next_called = True
                return await call_next(index + 1, handler_payload)

            handler_payload["next"] = next_handler

            started = time.perf_counter_ns()
            local_codes: list[str] = []
            try:
                result = await listener.handler(handler_payload)
            except Exception as exc:
                local_codes.append("listener_failed")
                diagnostics.append(
                    EventDiagnostic(
                        plugin_id=listener.plugin_id,
                        event=event_name,
                        code="listener_failed",
                        message=str(exc),
                    )
                )
                audit.append(
                    EventAuditEntry(
                        plugin_id=listener.plugin_id,
                        event=event_name,
                        mode=definition.mode,
                        latency_us=(time.perf_counter_ns() - started) // 1000,
                        diagnostic_codes=tuple(local_codes),
                    )
                )
                handler_payload.pop("next", None)
                return current

            if not next_called:
                if definition.missing_next_policy == MissingNextPolicy.DENY:
                    local_codes.append("missing_next_denied")
                    diagnostics.append(
                        EventDiagnostic(
                            plugin_id=listener.plugin_id,
                            event=event_name,
                            code="missing_next_denied",
                            message=f"{listener.plugin_id} returned without calling next",
                        )
                    )
                    audit.append(
                        EventAuditEntry(
                            plugin_id=listener.plugin_id,
                            event=event_name,
                            mode=definition.mode,
                            latency_us=(time.perf_counter_ns() - started) // 1000,
                            diagnostic_codes=tuple(local_codes),
                        )
                    )
                    return _DeniedPayload(current)
                if definition.missing_next_policy == MissingNextPolicy.CONTINUE:
                    local_codes.append("missing_next_continued")
                    result = await next_handler()

            audit.append(
                EventAuditEntry(
                    plugin_id=listener.plugin_id,
                    event=event_name,
                    mode=definition.mode,
                    latency_us=(time.perf_counter_ns() - started) // 1000,
                    diagnostic_codes=tuple(local_codes),
                )
            )
            handler_payload.pop("next", None)
            return result

        final = await call_next()
        denied = isinstance(final, _DeniedPayload)
        final_payload = final.payload if isinstance(final, _DeniedPayload) else final
        return EventDispatchResult(
            payload=final_payload if isinstance(final_payload, Mapping) else payload,
            diagnostics=tuple(diagnostics),
            audit=tuple(audit),
            denied=denied,
        )

    async def close(self) -> None:
        """Await and contain emitted background listeners."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

    def _require_mode(self, event_name: str, expected: PluginEventMode) -> EventDefinition:
        definition = self.definition(event_name)
        if definition.mode != expected:
            raise ValueError(
                f"event {event_name} requires {definition.mode.value}, not {expected.value}"
            )
        return definition

    async def _invoke_observer(
        self,
        event_name: str,
        definition: EventDefinition,
        listener: _Listener,
        payload: Mapping[str, Any],
    ) -> tuple[list[EventDiagnostic], list[EventAuditEntry]]:
        started = time.perf_counter_ns()
        diagnostics: list[EventDiagnostic] = []
        code = ""
        try:
            result = listener.handler(dict(payload))
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            code = "listener_failed"
            diagnostics.append(
                EventDiagnostic(
                    plugin_id=listener.plugin_id,
                    event=event_name,
                    code=code,
                    message=str(exc),
                )
            )
        return diagnostics, [
            EventAuditEntry(
                plugin_id=listener.plugin_id,
                event=event_name,
                mode=definition.mode,
                latency_us=(time.perf_counter_ns() - started) // 1000,
                diagnostic_codes=(code,) if code else (),
            )
        ]

    async def _invoke_mutating(
        self,
        event_name: str,
        definition: EventDefinition,
        listener: _Listener,
        payload: Mapping[str, Any],
    ) -> tuple[Any, list[EventDiagnostic], list[EventAuditEntry]]:
        started = time.perf_counter_ns()
        diagnostics: list[EventDiagnostic] = []
        code = ""
        try:
            result = listener.handler(dict(payload))
            if inspect.isawaitable(result):
                result = await result
            return (
                result,
                diagnostics,
                [
                    EventAuditEntry(
                        plugin_id=listener.plugin_id,
                        event=event_name,
                        mode=definition.mode,
                        latency_us=(time.perf_counter_ns() - started) // 1000,
                        diagnostic_codes=(),
                    )
                ],
            )
        except Exception as exc:
            code = "listener_failed"
            diagnostics.append(
                EventDiagnostic(
                    plugin_id=listener.plugin_id,
                    event=event_name,
                    code=code,
                    message=str(exc),
                )
            )
            return (
                payload,
                diagnostics,
                [
                    EventAuditEntry(
                        plugin_id=listener.plugin_id,
                        event=event_name,
                        mode=definition.mode,
                        latency_us=(time.perf_counter_ns() - started) // 1000,
                        diagnostic_codes=(code,),
                    )
                ],
            )


@dataclass(frozen=True)
class _DeniedPayload:
    payload: Mapping[str, Any]


LEGACY_HOOK_EVENT_MAP: Mapping[str, str] = {
    "before_prompt_build": "agent.before_step",
    "before_response": "agent.before_request",
    "before_tool_execution": "tools.before_execute",
    "after_tool_execution": "tools.after_execute",
    "after_turn_complete": "agent.after_turn",
}


class LegacyHookEventAdapter:
    """Translate legacy hook names onto typed events."""

    def __init__(self, bus: PluginEventBus) -> None:
        self._bus = bus

    def event_name(self, legacy_hook: str) -> str:
        """Return the typed event corresponding to a legacy hook."""
        try:
            return LEGACY_HOOK_EVENT_MAP[legacy_hook]
        except KeyError as exc:
            raise ValueError(f"legacy hook {legacy_hook} has no typed event") from exc

    async def dispatch(
        self,
        legacy_hook: str,
        payload: Mapping[str, Any],
    ) -> EventDispatchResult:
        """Dispatch through the typed event contract."""
        event_name = self.event_name(legacy_hook)
        definition = self._bus.definition(event_name)
        if definition.mode == PluginEventMode.WATERFALL:
            return await self._bus.waterfall(event_name, payload)
        if definition.mode == PluginEventMode.SERIAL:
            return await self._bus.serial(event_name, payload)
        return await self._bus.emit(event_name, payload)
