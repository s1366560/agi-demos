from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.cron_service import (
    CronExecutionUnavailableError,
    CronJobService,
    CronMutationUnavailableError,
)
from src.domain.model.cron.value_objects import CronPayload, CronSchedule

pytestmark = pytest.mark.unit


async def test_manual_run_fails_closed_without_persisting_fake_success() -> None:
    job_repo = AsyncMock()
    job_repo.find_by_id.return_value = SimpleNamespace(
        id="job-1",
        project_id="project-1",
        conversation_id="conversation-1",
    )
    run_repo = AsyncMock()
    service = CronJobService(
        cron_job_repo=job_repo,
        cron_job_run_repo=run_repo,
    )

    with pytest.raises(CronExecutionUnavailableError, match="durable automation execution"):
        await service.trigger_manual_run("job-1")

    run_repo.save.assert_not_awaited()


@pytest.mark.parametrize("action", ["create", "update", "delete", "toggle"])
async def test_job_mutations_fail_closed_before_repository_writes(action: str) -> None:
    job_repo = AsyncMock()
    run_repo = AsyncMock()
    service = CronJobService(
        cron_job_repo=job_repo,
        cron_job_run_repo=run_repo,
    )

    with pytest.raises(CronMutationUnavailableError, match="durable automation command"):
        if action == "create":
            await service.create_job(
                project_id="project-1",
                tenant_id="tenant-1",
                name="Nightly review",
                schedule=CronSchedule.every(interval_seconds=300),
                payload=CronPayload.agent_turn(message="Review changes"),
            )
        elif action == "update":
            await service.update_job("job-1", name="Updated")
        elif action == "delete":
            await service.delete_job("job-1")
        else:
            await service.toggle_job("job-1", enabled=False)

    job_repo.save.assert_not_awaited()
    job_repo.delete.assert_not_awaited()
