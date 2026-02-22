"""Unit tests for channel reload planning."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.infrastructure.adapters.primary.web.startup.channel_reload import (
    build_channel_reload_plan,
)


def _config(config_id: str, *, updated_at: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(id=config_id, updated_at=updated_at)


def _connection(last_heartbeat: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(last_heartbeat=last_heartbeat)


@pytest.mark.unit
def test_build_channel_reload_plan_add_remove_restart_and_unchanged() -> None:
    """Plan should identify add/remove/restart/unchanged connection sets."""
    now = datetime.now(timezone.utc)

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
    now = datetime.now(timezone.utc)

    plan = build_channel_reload_plan(
        enabled_configs=[_config("cfg-1", updated_at=now)],
        current_connections={"cfg-1": _connection(None)},
    )

    assert plan.to_restart == ()
    assert plan.unchanged == ("cfg-1",)
