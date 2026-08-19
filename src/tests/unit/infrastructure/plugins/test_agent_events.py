"""Contract tests for the always-on typed agent event dispatcher."""

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.infrastructure.agent.plugins.registry import HookDispatchResult
from src.infrastructure.agent.processor.processor import ToolDefinition
from src.infrastructure.plugins.agent_events import AgentPluginEventDispatcher
from src.infrastructure.plugins.events import PluginEventBus


class LegacyRegistry:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def apply_hook(
        self,
        hook_name: str,
        *,
        payload: dict[str, Any],
        runtime_overrides: list[dict[str, Any]] | None = None,
    ) -> HookDispatchResult:
        self.calls.append(hook_name)
        updated = {**payload, "legacy": True}
        return HookDispatchResult(payload=updated, diagnostics=[])


@pytest.mark.unit
async def test_mapped_hook_flows_through_typed_bus_with_legacy_adaptation() -> None:
    registry = LegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(legacy_registry=registry)

    result = await dispatcher.dispatch("before_response", {"value": 1})

    assert result.payload == {"value": 1, "legacy": True}
    assert registry.calls == ["before_response"]


@pytest.mark.unit
async def test_unmapped_hook_dispatches_through_legacy_registry() -> None:
    registry = LegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(legacy_registry=registry)

    result = await dispatcher.dispatch("on_session_start", {"value": 1})

    assert result.payload == {"value": 1, "legacy": True}
    assert registry.calls == ["on_session_start"]


@pytest.mark.unit
async def test_typed_listener_runs_ahead_of_the_legacy_adapter() -> None:
    registry = LegacyRegistry()
    bus = PluginEventBus()

    async def typed_listener(payload: Mapping[str, Any]) -> dict[str, Any]:
        downstream = cast(dict[str, Any], await payload["next"]())
        return {**downstream, "typed": True}

    bus.subscribe("agent.before_request", "typed-plugin", typed_listener)
    dispatcher = AgentPluginEventDispatcher(legacy_registry=registry, event_bus=bus)

    result = await dispatcher.dispatch("before_response", {"value": 1})

    assert result.payload == {"value": 1, "legacy": True, "typed": True}
    assert registry.calls == ["before_response"]


@pytest.mark.unit
async def test_mapped_hook_without_registry_passes_payload_through() -> None:
    dispatcher = AgentPluginEventDispatcher(legacy_registry=None)

    result = await dispatcher.dispatch("before_response", {"value": 1})

    assert result.payload == {"value": 1}
    assert result.diagnostics == ()


@pytest.mark.unit
async def test_processor_uses_injected_event_dispatcher() -> None:
    from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor

    async def tool_execute(**_kwargs: Any) -> str:
        return "ok"

    registry = LegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(legacy_registry=registry)
    processor = SessionProcessor(
        config=ProcessorConfig(
            model="test-model",
            plugin_registry=registry,
            plugin_event_dispatcher=dispatcher,
        ),
        tools=cast(
            list[ToolDefinition],
            [
                SimpleNamespace(
                    name="demo",
                    description="Demo",
                    parameters={},
                    execute=tool_execute,
                )
            ],
        ),
    )

    payload = await processor._notify_plugin_hook("before_response", {"value": 2})

    assert payload == {"value": 2, "legacy": True}
