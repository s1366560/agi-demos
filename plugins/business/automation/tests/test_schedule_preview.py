"""The local preview uses canonical forms without scheduling a job."""

import pytest

from plugins.business.automation.triggers import next_scheduled_run

pytestmark = pytest.mark.unit


def test_preview_uses_cron_timezone_and_discards_expired_one_off() -> None:
    start = "2026-07-10T04:00:00+00:00"
    assert next_scheduled_run(
        {
            "kind": "cron",
            "start": start,
            "timezone": "Asia/Shanghai",
            "config": {"expr": "0 9 * * *"},
        }
    ) == {"next_run_at": "2026-07-11T09:00:00+08:00"}
    assert next_scheduled_run(
        {"kind": "at", "start": start, "config": {"run_at": "2026-07-09T15:00:00+00:00"}}
    ) == {"next_run_at": None}


def test_preview_rejects_naive_start_and_empty_interval() -> None:
    args = {"kind": "every", "config": {"interval_seconds": 0}}
    with pytest.raises(ValueError, match="time zone"):
        next_scheduled_run({**args, "start": "2026-07-01T00:00:00"})
    with pytest.raises(ValueError, match="positive"):
        next_scheduled_run({**args, "start": "2026-07-01T00:00:00Z"})
