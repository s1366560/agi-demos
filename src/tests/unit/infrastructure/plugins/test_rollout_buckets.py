"""Staged plugin rollout bucket selection tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.infrastructure.plugins.agent_events import create_agent_plugin_event_dispatcher
from src.infrastructure.plugins.rollout_buckets import (
    is_scope_selected,
    parse_rollout_allowlist,
    rollout_bucket,
    settings_allowlist,
    settings_percentage,
)
from src.infrastructure.plugins.shadow_rollout import (
    queued_event_count,
    reset_shadow_rollout_queue_for_test,
)


def settings(
    *,
    events_shadow: bool = True,
    events_percent: int = 100,
    allowlist: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        platform_plugin_agent_events_v2=False,
        platform_plugin_agent_events_shadow=events_shadow,
        platform_plugin_agent_events_shadow_percent=events_percent,
        platform_plugin_agent_tools_v2=False,
        platform_plugin_agent_tools_shadow=False,
        platform_plugin_agent_tools_shadow_percent=events_percent,
        platform_plugin_shadow_scope_allowlist=allowlist,
    )


@pytest.mark.unit
def test_rollout_bucket_is_stable_and_thresholds_are_nested() -> None:
    first = rollout_bucket("agent_events", "tenant-1")
    second = rollout_bucket("agent_events", "tenant-1")
    threshold_percent = first // 100 + 1

    assert first == second
    assert threshold_percent <= 100
    assert is_scope_selected(
        capability="agent_events",
        scope_id="tenant-1",
        percentage=threshold_percent,
    )
    if threshold_percent > 1:
        assert not is_scope_selected(
            capability="agent_events",
            scope_id="tenant-1",
            percentage=threshold_percent - 1,
        )


@pytest.mark.unit
def test_zero_and_full_percent_bound_the_staged_cohort() -> None:
    scopes = [f"scope-{index}" for index in range(1_000)]

    assert not any(
        is_scope_selected(capability="agent_events", scope_id=scope, percentage=0)
        for scope in scopes
    )
    assert all(
        is_scope_selected(capability="agent_events", scope_id=scope, percentage=100)
        for scope in scopes
    )


@pytest.mark.unit
def test_staged_cohorts_are_nested_for_one_ten_and_fifty_percent() -> None:
    scopes = [f"tenant-{index}" for index in range(10_000)]
    one_percent = {
        scope
        for scope in scopes
        if is_scope_selected(capability="agent_events", scope_id=scope, percentage=1)
    }
    ten_percent = {
        scope
        for scope in scopes
        if is_scope_selected(capability="agent_events", scope_id=scope, percentage=10)
    }
    fifty_percent = {
        scope
        for scope in scopes
        if is_scope_selected(capability="agent_events", scope_id=scope, percentage=50)
    }

    assert one_percent < ten_percent < fifty_percent
    assert 50 <= len(one_percent) <= 150
    assert 950 <= len(ten_percent) <= 1_050
    assert 4_950 <= len(fifty_percent) <= 5_050


@pytest.mark.unit
def test_allowlist_overrides_percentage_and_helpers_normalize_settings() -> None:
    value = settings(events_percent=0, allowlist=" tenant-a , ,tenant-b ")

    assert settings_percentage(value, "platform_plugin_agent_events_shadow_percent") == 0
    assert settings_allowlist(
        value,
        "platform_plugin_shadow_scope_allowlist",
    ) == frozenset({"tenant-a", "tenant-b"})
    assert parse_rollout_allowlist(None) == frozenset()
    assert is_scope_selected(
        capability="agent_events",
        scope_id="tenant-a",
        percentage=0,
        allowlist={"tenant-a"},
    )


@pytest.mark.unit
def test_event_dispatcher_respects_zero_full_and_allowlist_cohorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: settings(events_percent=0),
    )
    assert create_agent_plugin_event_dispatcher(object(), tenant_id="tenant-1") is None

    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: settings(events_percent=100),
    )
    dispatcher = create_agent_plugin_event_dispatcher(object(), tenant_id="tenant-1")
    assert dispatcher is not None
    assert dispatcher.scope_type == "tenant"
    assert dispatcher.scope_id == "tenant-1"

    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: settings(events_percent=0, allowlist="tenant-1"),
    )
    allowlisted = create_agent_plugin_event_dispatcher(object(), tenant_id="tenant-1")
    assert allowlisted is not None


@pytest.mark.unit
def test_tool_generation_shadow_respects_percentage_and_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.state.agent_worker_state import (
        _publish_scoped_tool_generation,
    )

    class ToolService:
        def __init__(self) -> None:
            self.calls = 0

        def shadow_comparison(
            self,
            scope: object,
            tools: dict[str, object],
        ) -> tuple[dict[str, str], dict[str, str], bool]:
            self.calls += 1
            inventory = {"demo": "Demo:Demo"}
            return inventory, dict(inventory), False

        def publish(self, scope: object, tools: dict[str, object]) -> object:
            return object()

    service = ToolService()

    def fail_service() -> ToolService:
        raise AssertionError("zero-percent cohort must not construct the tool service")

    zero_settings = SimpleNamespace(
        platform_plugin_agent_tools_v2=False,
        platform_plugin_agent_tools_shadow=True,
        platform_plugin_agent_tools_shadow_percent=0,
        platform_plugin_shadow_scope_allowlist=None,
    )
    monkeypatch.setattr("src.configuration.config.get_settings", lambda: zero_settings)
    monkeypatch.setattr(
        "src.infrastructure.plugins.agent_tools.get_agent_tool_set_service",
        fail_service,
    )
    _publish_scoped_tool_generation("project-zero", {"demo": object()})

    full_settings = SimpleNamespace(
        platform_plugin_agent_tools_v2=False,
        platform_plugin_agent_tools_shadow=True,
        platform_plugin_agent_tools_shadow_percent=100,
        platform_plugin_shadow_scope_allowlist=None,
    )
    monkeypatch.setattr("src.configuration.config.get_settings", lambda: full_settings)
    monkeypatch.setattr(
        "src.infrastructure.plugins.agent_tools.get_agent_tool_set_service",
        lambda: service,
    )
    reset_shadow_rollout_queue_for_test()
    _publish_scoped_tool_generation(
        "project-selected",
        {"demo": SimpleNamespace(name="demo", description="Demo", parameters={})},
    )

    allowlist_settings = SimpleNamespace(
        platform_plugin_agent_tools_v2=False,
        platform_plugin_agent_tools_shadow=True,
        platform_plugin_agent_tools_shadow_percent=0,
        platform_plugin_shadow_scope_allowlist="project-zero",
    )
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: allowlist_settings,
    )
    _publish_scoped_tool_generation(
        "project-zero",
        {"demo": SimpleNamespace(name="demo", description="Demo", parameters={})},
    )

    assert service.calls == 2
    assert queued_event_count() == 2
    reset_shadow_rollout_queue_for_test()
