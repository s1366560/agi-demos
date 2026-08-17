from types import SimpleNamespace

import pytest

from src.infrastructure.agent.plugins.registry import HookDispatchResult
from src.infrastructure.plugins.agent_events import AgentPluginEventDispatcher


class LegacyRegistry:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def apply_hook(
        self,
        hook_name: str,
        *,
        payload: dict,
        runtime_overrides: list | None = None,
    ) -> HookDispatchResult:
        self.calls.append(hook_name)
        updated = {**payload, "legacy": True}
        return HookDispatchResult(payload=updated, diagnostics=[])


@pytest.mark.unit
async def test_legacy_mode_dispatches_once_without_typed_adapter() -> None:
    registry = LegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(legacy_registry=registry)

    result = await dispatcher.dispatch("before_response", {"value": 1})

    assert result.payload == {"value": 1, "legacy": True}
    assert registry.calls == ["before_response"]
    assert result.shadow_diff is None


@pytest.mark.unit
async def test_shadow_mode_compares_typed_and_legacy_paths() -> None:
    registry = LegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(
        legacy_registry=registry,
        shadow_enabled=True,
    )

    result = await dispatcher.dispatch("before_response", {"value": 1})

    assert result.payload == {"value": 1, "legacy": True}
    assert result.shadow_diff is not None
    assert not result.shadow_diff.equal
    assert registry.calls == ["before_response"]


@pytest.mark.unit
async def test_v2_mode_adapts_legacy_handlers_into_typed_waterfall() -> None:
    registry = LegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(
        legacy_registry=registry,
        v2_enabled=True,
    )

    result = await dispatcher.dispatch("before_response", {"value": 1})

    assert result.payload == {"value": 1, "legacy": True}
    assert registry.calls == ["before_response"]
    assert result.shadow_diff is None


@pytest.mark.unit
async def test_processor_uses_injected_event_dispatcher() -> None:
    from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor

    async def tool_execute(**_kwargs):
        return "ok"

    registry = LegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(
        legacy_registry=registry,
        v2_enabled=True,
    )
    processor = SessionProcessor(
        config=ProcessorConfig(
            model="test-model",
            plugin_registry=registry,
            plugin_event_dispatcher=dispatcher,
        ),
        tools=[
            SimpleNamespace(
                name="demo",
                description="Demo",
                parameters={},
                execute=tool_execute,
            )
        ],
    )

    payload = await processor._notify_plugin_hook("before_response", {"value": 2})

    assert payload == {"value": 2, "legacy": True}
