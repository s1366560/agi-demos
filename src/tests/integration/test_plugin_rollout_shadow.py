"""Rollout parity evidence for typed agent events and tool generations."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.plugins import PluginEventMode
from src.infrastructure.agent.plugins.registry import HookDispatchResult
from src.infrastructure.plugins.agent_events import AgentPluginEventDispatcher
from src.infrastructure.plugins.agent_tools import AgentToolSetService
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.events import PluginEventBus


class ParityLegacyRegistry:
    """Apply one deterministic, mode-compatible transformation per hook."""

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
        if hook_name in {"before_prompt_build", "before_response", "before_tool_execution"}:
            return HookDispatchResult(payload={**payload, "rollout": "parity"}, diagnostics=[])
        if hook_name == "after_tool_execution":
            return HookDispatchResult(payload={**payload, "rollout": "parity"}, diagnostics=[])
        return HookDispatchResult(payload=dict(payload), diagnostics=[])


def parity_event_bus() -> PluginEventBus:
    bus = PluginEventBus()
    definitions = {
        name: bus.definition(name)
        for name in (
            "agent.before_step",
            "agent.before_request",
            "tools.before_execute",
            "tools.after_execute",
            "agent.after_turn",
        )
    }

    async def waterfall(payload: dict[str, Any]) -> dict[str, Any]:
        downstream = await payload["next"]()
        return {**downstream, "rollout": "parity"}

    async def serial(payload: dict[str, Any]) -> dict[str, Any]:
        return {**payload, "rollout": "parity"}

    async def observer(payload: dict[str, Any]) -> None:
        _ = payload

    for definition in definitions.values():
        handler = (
            waterfall
            if definition.mode == PluginEventMode.WATERFALL
            else serial
            if definition.mode == PluginEventMode.SERIAL
            else observer
        )
        bus.subscribe(definition.name, "typed-parity", handler)
    return bus


@pytest.mark.integration
async def test_all_migrated_agent_events_have_zero_shadow_diff() -> None:
    registry = ParityLegacyRegistry()
    cases = {
        "before_prompt_build": {"input": "goal"},
        "before_response": {"model": "demo"},
        "before_tool_execution": {"tool": "demo"},
        "after_tool_execution": {"result": "ok"},
        "after_turn_complete": {"turn": 3},
    }
    dispatcher = AgentPluginEventDispatcher(
        legacy_registry=registry,
        event_bus=parity_event_bus(),
        shadow_enabled=True,
    )

    results = [
        await dispatcher.dispatch(hook_name, payload) for hook_name, payload in cases.items()
    ]

    assert all(result.shadow_diff is not None for result in results)
    assert all(result.shadow_diff.equal for result in results)  # type: ignore[union-attr]
    assert all(result.payload["rollout"] == "parity" for result in results[:4])
    assert registry.calls == list(cases)


@pytest.mark.integration
async def test_v2_event_adapter_preserves_legacy_payload() -> None:
    registry = ParityLegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(
        legacy_registry=registry,
        event_bus=PluginEventBus(),
        v2_enabled=True,
    )

    result = await dispatcher.dispatch("before_response", {"model": "demo"})

    assert result.payload == {"model": "demo", "rollout": "parity"}
    assert result.shadow_diff is None
    assert registry.calls == ["before_response"]


@pytest.mark.integration
def test_agent_tool_shadow_generation_has_zero_diff_until_inventory_changes() -> None:
    tool = SimpleNamespace(
        name="demo",
        description="Demo",
        parameters={"type": "object"},
    )
    changed = SimpleNamespace(
        name="demo",
        description="Changed",
        parameters={"type": "object"},
    )
    scope = PluginScopeContext(tenant_id="tenant", project_id="project")
    service = AgentToolSetService(profile_digest="rollout-profile")
    service.publish(scope, {"demo": tool}, profile_digest="rollout-profile")

    assert service.shadow_diff(scope, {"demo": tool}) is False
    assert service.shadow_diff(scope, {"demo": changed}) is True
