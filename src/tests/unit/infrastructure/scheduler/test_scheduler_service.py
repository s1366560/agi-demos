"""Unit tests for APScheduler registration config normalization."""

from __future__ import annotations

import logging

import pytest

from src.infrastructure.scheduler import scheduler_service

pytestmark = pytest.mark.unit


class FakeScheduler:
    def __init__(self) -> None:
        self.schedules: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def add_schedule(self, *args: object, **kwargs: object) -> str:
        self.schedules.append((args, kwargs))
        return "schedule-id"


async def test_register_job_accepts_legacy_every_config(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_service, "_scheduler", fake_scheduler)

    await scheduler_service.register_job(
        job_id="job-1",
        schedule_type="every",
        schedule_config={"hours": 0, "minutes": 5, "seconds": 0},
    )

    assert len(fake_scheduler.schedules) == 1
    args, kwargs = fake_scheduler.schedules[0]
    assert args[1].__class__.__name__ == "IntervalTrigger"
    assert kwargs["id"] == "job-1"
    assert kwargs["kwargs"] == {"job_id": "job-1"}


async def test_register_job_logs_invalid_schedule_without_raising(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_service, "_scheduler", fake_scheduler)
    caplog.set_level(logging.ERROR, logger=scheduler_service.logger.name)

    await scheduler_service.register_job(
        job_id="job-2",
        schedule_type="every",
        schedule_config={"hours": 0, "minutes": 0, "seconds": 0},
    )

    assert fake_scheduler.schedules == []
    assert "Invalid schedule config for job job-2 (every)" in caplog.text
