"""Dispatch agent hooks through the typed platform event bus.

The typed bus is the only dispatch path for hooks with a typed event mapping.
Handlers registered through the legacy ``AgentPluginRegistry`` facade are
adapted into typed listeners on first use, so existing plugin code keeps
working while dispatch gains explicit event-mode semantics. Hooks without a
typed mapping continue to dispatch through the legacy registry directly.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from src.domain.model.plugins import PluginEventMode

from .events import EventDispatchResult, PluginEventBus

logger = logging.getLogger(__name__)


@dataclass
class AgentEventDispatchResult:
    """Effective payload plus contained plugin diagnostics."""

    payload: dict[str, Any]
    diagnostics: tuple[object, ...] = ()
    denied: bool = False


@dataclass(kw_only=True)
class AgentPluginEventDispatcher:
    """Dispatch hooks through the typed event bus with legacy adaptation."""

    legacy_registry: Any | None
    event_bus: PluginEventBus = field(default_factory=PluginEventBus)
    runtime_hook_overrides: list[dict[str, Any]] = field(default_factory=list)
    _subscribed_events: set[str] = field(default_factory=set, init=False)

    async def dispatch(
        self,
        hook_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        runtime_hook_overrides: list[dict[str, Any]] | None = None,
    ) -> AgentEventDispatchResult:
        """Dispatch one hook through its typed event or the legacy registry."""
        effective_payload = dict(payload or {})
        event_name = _TYPED_EVENT_BY_HOOK.get(hook_name)
        if self.legacy_registry is None or event_name is None:
            return await self._dispatch_legacy(
                hook_name,
                effective_payload,
                runtime_hook_overrides or list(self.runtime_hook_overrides),
            )

        self._ensure_legacy_adapter(hook_name, event_name)
        typed = await self._dispatch_typed(event_name, effective_payload)
        return AgentEventDispatchResult(
            payload=typed.payload,
            diagnostics=typed.diagnostics,
            denied=typed.denied,
        )

    async def _dispatch_typed(
        self,
        event_name: str,
        payload: dict[str, Any],
    ) -> AgentEventDispatchResult:
        definition = self.event_bus.definition(event_name)
        result: EventDispatchResult
        if definition.mode == PluginEventMode.WATERFALL:
            result = await self.event_bus.waterfall(event_name, payload)
        elif definition.mode == PluginEventMode.SERIAL:
            result = await self.event_bus.serial(event_name, payload)
        elif definition.mode == PluginEventMode.PARALLEL:
            result = await self.event_bus.parallel(event_name, payload)
        else:
            result = await self.event_bus.emit(event_name, payload)
        return AgentEventDispatchResult(
            payload=_drop_typed_keys(result.payload),
            diagnostics=result.diagnostics,
            denied=result.denied,
        )

    async def _dispatch_legacy(
        self,
        hook_name: str,
        payload: dict[str, Any],
        runtime_overrides: list[dict[str, Any]],
    ) -> AgentEventDispatchResult:
        if self.legacy_registry is None:
            return AgentEventDispatchResult(payload=payload)
        result = await self.legacy_registry.apply_hook(
            hook_name,
            payload=payload,
            runtime_overrides=runtime_overrides,
        )
        return AgentEventDispatchResult(
            payload=dict(result.payload),
            diagnostics=tuple(result.diagnostics),
        )

    def _ensure_legacy_adapter(self, hook_name: str, event_name: str) -> None:
        if event_name in self._subscribed_events:
            return
        definition = self.event_bus.definition(event_name)
        registry = self.legacy_registry
        if registry is None:
            raise ValueError("legacy registry is required for adapter dispatch")

        if definition.mode == PluginEventMode.WATERFALL:

            async def waterfall_adapter(payload: Mapping[str, Any]) -> Mapping[str, Any]:
                downstream = await payload["next"]()
                result = await registry.apply_hook(
                    hook_name,
                    payload=dict(downstream),
                    runtime_overrides=self.runtime_hook_overrides,
                )
                return cast(Mapping[str, Any], result.payload)

            _ = self.event_bus.subscribe(event_name, "legacy-adapter", waterfall_adapter)
        elif definition.mode in {PluginEventMode.SERIAL, PluginEventMode.PARALLEL}:

            async def mutating_adapter(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
                result = await registry.apply_hook(
                    hook_name,
                    payload=dict(payload),
                    runtime_overrides=self.runtime_hook_overrides,
                )
                return cast(Mapping[str, Any] | None, result.payload)

            _ = self.event_bus.subscribe(event_name, "legacy-adapter", mutating_adapter)
        else:

            async def emit_adapter(payload: Mapping[str, Any]) -> None:
                result = await registry.apply_hook(
                    hook_name,
                    payload=dict(payload),
                    runtime_overrides=self.runtime_hook_overrides,
                )
                if result.diagnostics:
                    logger.warning(
                        "Legacy adapter for %s reported %d diagnostics",
                        hook_name,
                        len(result.diagnostics),
                    )

            _ = self.event_bus.subscribe(event_name, "legacy-adapter", emit_adapter)
        self._subscribed_events.add(event_name)


_TYPED_EVENT_BY_HOOK: Mapping[str, str] = {
    "before_prompt_build": "agent.before_step",
    "before_response": "agent.before_request",
    "before_tool_execution": "tools.before_execute",
    "after_tool_execution": "tools.after_execute",
    "after_turn_complete": "agent.after_turn",
}


def _drop_typed_keys(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "next"}


def create_agent_plugin_event_dispatcher(
    legacy_registry: object | None,
    runtime_hook_overrides: list[dict[str, Any]] | None = None,
) -> AgentPluginEventDispatcher:
    """Create the always-on dispatcher bridging legacy hooks to typed events."""
    return AgentPluginEventDispatcher(
        legacy_registry=legacy_registry,
        runtime_hook_overrides=runtime_hook_overrides or [],
    )
