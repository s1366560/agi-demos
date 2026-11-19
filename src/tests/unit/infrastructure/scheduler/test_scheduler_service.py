"""Unit tests for APScheduler registration config normalization."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import pytest

from src.infrastructure.scheduler import scheduler_service

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def open_registration(monkeypatch):
    # These cases exercise trigger normalization, not the durable cutover boundary.
    @asynccontextmanager
    async def allow():
        yield

    monkeypatch.setattr(scheduler_service, "_require_cron_registration_open", allow)


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


async def test_register_job_rejects_invalid_schedule_without_queueing(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_service, "_scheduler", fake_scheduler)
    caplog.set_level(logging.ERROR, logger=scheduler_service.logger.name)

    with pytest.raises(scheduler_service.CronScheduleRejected):
        await scheduler_service.register_job(
            job_id="job-2",
            schedule_type="every",
            schedule_config={"hours": 0, "minutes": 0, "seconds": 0},
        )

    assert fake_scheduler.schedules == []
    assert "Invalid schedule config for job job-2 (every)" in caplog.text


async def test_accepted_schedule_does_not_execute_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler()
    executions: list[dict[str, object]] = []

    async def execute_cron_job(**kwargs: object) -> None:
        executions.append(kwargs)

    monkeypatch.setattr(scheduler_service, "_scheduler", fake_scheduler)
    monkeypatch.setattr(
        "src.infrastructure.scheduler.job_executor.execute_cron_job",
        execute_cron_job,
    )

    await scheduler_service.register_job(
        job_id="job-3",
        schedule_type="every",
        schedule_config={"interval_seconds": 3600},
    )

    assert len(fake_scheduler.schedules) == 1
    assert executions == []
