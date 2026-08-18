"""Bridge legacy agent hooks to the typed platform event bus."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from src.domain.model.plugins import PluginEventMode

from .events import EventDiagnostic, EventDispatchResult, PluginEventBus
from .rollout_buckets import (
    is_scope_selected,
    settings_allowlist,
    settings_percentage,
)
from .shadow_rollout import enqueue_shadow_rollout_event, make_shadow_rollout_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventShadowDiff:
    """Structured comparison between legacy and typed dispatch payloads."""

    hook_name: str
    event_name: str
    equal: bool
    legacy_payload: dict[str, Any]
    typed_payload: dict[str, Any]


@dataclass
class AgentEventDispatchResult:
    """Effective payload plus optional shadow-diff evidence."""

    payload: dict[str, Any]
    diagnostics: tuple[object, ...] = ()
    shadow_diff: EventShadowDiff | None = None
    denied: bool = False


@dataclass(kw_only=True)
class AgentPluginEventDispatcher:
    """Dispatch legacy hooks, typed events, or both under rollout flags."""

    legacy_registry: Any | None
    event_bus: PluginEventBus = field(default_factory=PluginEventBus)
    v2_enabled: bool = False
    remove_legacy_fallback: bool = False
    shadow_enabled: bool = False
    max_shadow_diffs: int = 100
    runtime_hook_overrides: list[dict[str, Any]] = field(default_factory=list)
    scope_type: str = "global"
    scope_id: str = "global"
    _subscribed_events: set[str] = field(default_factory=set, init=False)
    _shadow_diffs: list[EventShadowDiff] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.remove_legacy_fallback and not self.v2_enabled:
            raise ValueError("legacy event removal requires agent events V2")

    async def dispatch(
        self,
        hook_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        runtime_hook_overrides: list[dict[str, Any]] | None = None,
    ) -> AgentEventDispatchResult:
        """Dispatch one legacy hook name under the configured rollout mode."""
        effective_payload = dict(payload or {})
        event_name = _TYPED_EVENT_BY_HOOK.get(hook_name)
        if self.legacy_registry is None or event_name is None or not self._rollout_enabled:
            return await self._dispatch_legacy(
                hook_name,
                effective_payload,
                runtime_hook_overrides or list(self.runtime_hook_overrides),
            )

        if self.v2_enabled and not self.remove_legacy_fallback:
            self._ensure_legacy_adapter(hook_name, event_name)
        legacy = None
        if not self.v2_enabled:
            legacy = await self._dispatch_legacy(
                hook_name,
                effective_payload,
                runtime_hook_overrides or list(self.runtime_hook_overrides),
            )
        typed = await self._dispatch_typed(event_name, effective_payload)
        if self.shadow_enabled and not self.v2_enabled:
            assert legacy is not None
            diff = _shadow_diff(
                hook_name,
                event_name,
                legacy.payload,
                typed.payload,
            )
            self._record_shadow_diff(diff)
            return AgentEventDispatchResult(
                payload=legacy.payload,
                diagnostics=(*legacy.diagnostics, *typed.diagnostics),
                shadow_diff=diff,
                denied=typed.denied,
            )
        if self.v2_enabled:
            diagnostics = typed.diagnostics
            if self.remove_legacy_fallback and not self.event_bus.list_listeners(event_name):
                diagnostics = (
                    *diagnostics,
                    EventDiagnostic(
                        plugin_id="platform-plugin-kernel",
                        event=event_name,
                        code="legacy_fallback_removed",
                        message=(f"legacy hook {hook_name} has no typed listener for {event_name}"),
                    ),
                )
            return AgentEventDispatchResult(
                payload=typed.payload,
                diagnostics=diagnostics,
                denied=typed.denied,
            )
        assert legacy is not None
        return legacy

    def shadow_diffs(self) -> tuple[EventShadowDiff, ...]:
        """Return retained shadow-mode evidence."""
        return tuple(self._shadow_diffs)

    @property
    def _rollout_enabled(self) -> bool:
        return self.v2_enabled or self.shadow_enabled

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

    def _record_shadow_diff(self, diff: EventShadowDiff) -> None:
        self._shadow_diffs.append(diff)
        if len(self._shadow_diffs) > self.max_shadow_diffs:
            del self._shadow_diffs[0]
        enqueue_shadow_rollout_event(
            make_shadow_rollout_event(
                capability="agent_events",
                event_name=diff.event_name,
                hook_name=diff.hook_name,
                scope_type=self.scope_type,
                scope_id=self.scope_id,
                equal=diff.equal,
                legacy_payload=diff.legacy_payload,
                typed_payload=diff.typed_payload,
            )
        )


_TYPED_EVENT_BY_HOOK: Mapping[str, str] = {
    "before_prompt_build": "agent.before_step",
    "before_response": "agent.before_request",
    "before_tool_execution": "tools.before_execute",
    "after_tool_execution": "tools.after_execute",
    "after_turn_complete": "agent.after_turn",
}


def _shadow_diff(
    hook_name: str,
    event_name: str,
    legacy: Mapping[str, Any],
    typed: Mapping[str, Any],
) -> EventShadowDiff:
    comparable_typed = _drop_typed_keys(typed)
    comparable_legacy = _drop_typed_keys(legacy)
    return EventShadowDiff(
        hook_name=hook_name,
        event_name=event_name,
        equal=comparable_legacy == comparable_typed,
        legacy_payload=comparable_legacy,
        typed_payload=comparable_typed,
    )


def _drop_typed_keys(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "next"}


def create_agent_plugin_event_dispatcher(
    legacy_registry: object | None,
    runtime_hook_overrides: list[dict[str, Any]] | None = None,
    *,
    tenant_id: str | None = None,
) -> AgentPluginEventDispatcher | None:
    """Create the rollout dispatcher only when a rollout flag is enabled."""
    from src.configuration.config import get_settings

    settings = get_settings()
    if not (
        settings.platform_plugin_agent_events_v2 or settings.platform_plugin_agent_events_shadow
    ):
        return None
    remove_legacy = getattr(settings, "platform_plugin_agent_events_remove_legacy", False)
    if remove_legacy and not settings.platform_plugin_agent_events_v2:
        raise ValueError("PLATFORM_PLUGIN_AGENT_EVENTS_REMOVE_LEGACY requires agent events V2")
    normalized_tenant_id = (tenant_id or "").strip()
    shadow_selected = settings.platform_plugin_agent_events_v2 or (
        settings.platform_plugin_agent_events_shadow
        and is_scope_selected(
            capability="agent_events",
            scope_id=normalized_tenant_id or None,
            percentage=settings_percentage(
                settings,
                "platform_plugin_agent_events_shadow_percent",
            ),
            allowlist=settings_allowlist(
                settings,
                "platform_plugin_shadow_scope_allowlist",
            ),
        )
    )
    if not shadow_selected:
        return None
    return AgentPluginEventDispatcher(
        legacy_registry=legacy_registry,
        v2_enabled=settings.platform_plugin_agent_events_v2,
        remove_legacy_fallback=remove_legacy,
        shadow_enabled=settings.platform_plugin_agent_events_shadow,
        runtime_hook_overrides=runtime_hook_overrides or [],
        scope_type="tenant" if normalized_tenant_id else "global",
        scope_id=normalized_tenant_id or "global",
    )
