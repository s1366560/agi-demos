"""Unit tests for SQL cron job repository recovery behavior."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from src.infrastructure.adapters.secondary.persistence.models import CronJobModel
from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
    SqlCronJobRepository,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 4, 27, 10, 0, tzinfo=UTC)


class FakeScalarResult:
    def __init__(self, rows: list[CronJobModel]) -> None:
        self._rows = rows

    def all(self) -> list[CronJobModel]:
        return self._rows


class FakeResult:
    def __init__(self, rows: list[CronJobModel]) -> None:
        self._rows = rows

    def scalars(self) -> FakeScalarResult:
        return FakeScalarResult(self._rows)


class FakeSession:
    def __init__(self, rows: list[CronJobModel]) -> None:
        self._rows = rows

    async def execute(self, _statement: Any) -> FakeResult:
        return FakeResult(self._rows)


def _cron_job_model(job_id: str, schedule_config: dict[str, Any]) -> CronJobModel:
    return CronJobModel(
        id=job_id,
        project_id="project-1",
        tenant_id="tenant-1",
        name=f"Job {job_id}",
        description=None,
        enabled=True,
        delete_after_run=False,
        schedule_type="every",
        schedule_config=schedule_config,
        payload_type="system_event",
        payload_config={"content": "run"},
        delivery_type="none",
        delivery_config={},
        conversation_mode="reuse",
        conversation_id=None,
        timezone="UTC",
        stagger_seconds=0,
        timeout_seconds=300,
        max_retries=3,
        state={},
        created_by=None,
        created_at=NOW,
        updated_at=None,
    )


async def test_find_due_jobs_skips_invalid_persisted_schedule(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = SqlCronJobRepository(
        FakeSession(
            [
                _cron_job_model("invalid-job", {"hours": 0, "minutes": 0, "seconds": 0}),
                _cron_job_model("valid-job", {"hours": 0, "minutes": 5, "seconds": 0}),
            ]
        )
    )
    caplog.set_level(logging.WARNING, logger="src.infrastructure.adapters.secondary.persistence")

    jobs = await repo.find_due_jobs(now=NOW)

    assert [job.id for job in jobs] == ["valid-job"]
    assert "Skipping invalid cron job invalid-job during scheduler sync" in caplog.text
