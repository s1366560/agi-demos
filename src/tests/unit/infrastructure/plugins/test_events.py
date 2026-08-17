import pytest

from src.infrastructure.plugins.events import LegacyHookEventAdapter, PluginEventBus


@pytest.mark.unit
async def test_waterfall_delegates_and_rewrites_payload() -> None:
    bus = PluginEventBus()

    async def first(payload):
        payload["value"] += 1
        return await payload["next"]()

    async def second(payload):
        payload["value"] *= 3
        return payload

    bus.subscribe("llm.request", "first-plugin", first)
    bus.subscribe("llm.request", "second-plugin", second)

    result = await bus.waterfall("llm.request", {"value": 2})

    assert result.payload["value"] == 9
    assert not result.diagnostics
    assert [entry.plugin_id for entry in result.audit] == [
        "second-plugin",
        "first-plugin",
    ]


@pytest.mark.unit
async def test_policy_waterfall_missing_next_denies() -> None:
    bus = PluginEventBus()

    async def policy(_payload):
        return {"decision": "short-circuit"}

    bus.subscribe("tools.before_execute", "policy-plugin", policy)

    result = await bus.waterfall("tools.before_execute", {"tool": "bash"})

    assert result.denied
    assert any(item.code == "missing_next_denied" for item in result.diagnostics)


@pytest.mark.unit
async def test_event_mode_mismatch_fails_loud() -> None:
    bus = PluginEventBus()

    with pytest.raises(ValueError, match="requires serial"):
        await bus.emit("agent.after_step", {})


@pytest.mark.unit
async def test_emit_listener_is_scheduled_and_audited() -> None:
    bus = PluginEventBus()
    bus.subscribe("agent.after_turn", "observer", lambda _payload: None)

    result = await bus.emit("agent.after_turn", {"ok": True})
    await bus.close()

    assert result.audit[0].plugin_id == "observer"
    assert result.audit[0].mode.value == "emit"


@pytest.mark.unit
async def test_listener_exception_is_contained_and_audited() -> None:
    bus = PluginEventBus()

    async def failing(_payload):
        raise RuntimeError("boom")

    bus.subscribe("tools.after_execute", "bad-plugin", failing)
    result = await bus.serial("tools.after_execute", {"value": 1})

    assert result.payload == {"value": 1}
    assert result.diagnostics[0].plugin_id == "bad-plugin"
    assert result.audit[0].diagnostic_codes == ("listener_failed",)


@pytest.mark.unit
async def test_legacy_hook_adapter_maps_before_tool_hook() -> None:
    adapter = LegacyHookEventAdapter(PluginEventBus())

    assert adapter.event_name("before_tool_execution") == "tools.before_execute"


@pytest.mark.unit
async def test_subscription_is_reversible() -> None:
    bus = PluginEventBus()
    dispose = bus.subscribe(
        "agent.after_turn",
        "observer",
        lambda _payload: None,
    )
    assert bus.list_listeners("agent.after_turn") == ("observer",)

    dispose()
    assert bus.list_listeners("agent.after_turn") == ()
