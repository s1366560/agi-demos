"""Unit tests for channel reload planning."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.adapters.primary.web.startup.channel_reload import (
    ChannelReloadPlan,
    _notify_plugin_reload_hooks,
    build_channel_reload_plan,
)
from src.infrastructure.plugins.v2.channel_adapters import CHANNEL_RUNTIME_RELOAD_EVENT_V2


def _config(config_id: str, *, updated_at: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(id=config_id, updated_at=updated_at)


def _connection(last_heartbeat: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(last_heartbeat=last_heartbeat)


@pytest.mark.unit
def test_build_channel_reload_plan_add_remove_restart_and_unchanged() -> None:
    """Plan should identify add/remove/restart/unchanged connection sets."""
    now = datetime.now(UTC)

    plan = build_channel_reload_plan(
        enabled_configs=[
            _config("cfg-add", updated_at=now),
            _config("cfg-restart", updated_at=now),
            _config("cfg-keep", updated_at=now - timedelta(minutes=1)),
        ],
        current_connections={
            "cfg-restart": _connection(now - timedelta(minutes=5)),
            "cfg-keep": _connection(now),
            "cfg-remove": _connection(now),
        },
    )

    assert plan.to_add == ("cfg-add",)
    assert plan.to_remove == ("cfg-remove",)
    assert plan.to_restart == ("cfg-restart",)
    assert plan.unchanged == ("cfg-keep",)
    assert plan.summary() == {"add": 1, "remove": 1, "restart": 1, "unchanged": 1}


@pytest.mark.unit
def test_build_channel_reload_plan_skips_restart_when_no_heartbeat() -> None:
    """Connections without heartbeat should remain unchanged in planning mode."""
    now = datetime.now(UTC)

    plan = build_channel_reload_plan(
        enabled_configs=[_config("cfg-1", updated_at=now)],
        current_connections={"cfg-1": _connection(None)},
    )

    assert plan.to_restart == ()
    assert plan.unchanged == ("cfg-1",)


@pytest.mark.unit
async def test_reload_notification_dispatches_v2_event_in_leased_operation() -> None:
    operation = SimpleNamespace(
        generation=SimpleNamespace(digest="a" * 64),
        operation_id="channel-reload:test",
        dispatch=AsyncMock(return_value=()),
    )
    observed: dict[str, object] = {}

    @asynccontextmanager
    async def _pin_operation(_host: object, **kwargs: object):
        observed.update(kwargs)
        yield operation

    with (
        patch(
            "src.infrastructure.adapters.primary.web.startup.channel_reload."
            "current_process_generation_host_v2",
            return_value=object(),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.startup.channel_reload."
            "pin_operation_context_v2",
            _pin_operation,
        ),
    ):
        await _notify_plugin_reload_hooks(
            plan=ChannelReloadPlan(to_add=("config-a",), unchanged=("config-b",)),
            dry_run=True,
        )

    assert str(observed["operation_id"]).startswith("channel-reload:")
    scope = observed["scope"]
    assert getattr(scope, "kind", None).value == "root"
    operation.dispatch.assert_awaited_once_with(
        CHANNEL_RUNTIME_RELOAD_EVENT_V2,
        {
            "dry_run": True,
            "generation_digest": "a" * 64,
            "operation_id": "channel-reload:test",
            "plan": {"add": 1, "remove": 0, "restart": 0, "unchanged": 1},
        },
    )
