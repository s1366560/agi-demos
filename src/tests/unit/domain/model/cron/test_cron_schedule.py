"""Unit tests for cron schedule value object normalization."""

from __future__ import annotations

import pytest

from src.domain.model.cron.value_objects import CronSchedule, ScheduleType

pytestmark = pytest.mark.unit


def test_every_schedule_accepts_split_interval_fields() -> None:
    schedule = CronSchedule(
        kind=ScheduleType.EVERY,
        config={"hours": 1, "minutes": 2, "seconds": 3},
    )

    assert schedule.config == {"interval_seconds": 3723}


def test_cron_schedule_accepts_expression_alias() -> None:
    schedule = CronSchedule(
        kind=ScheduleType.CRON,
        config={"expression": " 0 * * * * ", "timezone": "Asia/Shanghai"},
    )

    assert schedule.config == {"expr": "0 * * * *", "timezone": "Asia/Shanghai"}


def test_at_schedule_accepts_target_time_alias() -> None:
    schedule = CronSchedule(
        kind=ScheduleType.AT,
        config={"target_time": "2026-04-27T09:00:00Z"},
    )

    assert schedule.config == {"run_at": "2026-04-27T09:00:00Z"}


def test_every_schedule_rejects_zero_interval() -> None:
    with pytest.raises(ValueError, match="every schedule requires interval_seconds"):
        CronSchedule(
            kind=ScheduleType.EVERY,
            config={"hours": 0, "minutes": 0, "seconds": 0},
        )


def test_to_dict_returns_canonical_config() -> None:
    schedule = CronSchedule(
        kind=ScheduleType.CRON,
        config={"expression": "0 0 * * *"},
    )

    assert schedule.to_dict() == {"kind": "cron", "expr": "0 0 * * *"}
