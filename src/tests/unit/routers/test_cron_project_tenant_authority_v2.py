"""Cron project lookup coverage for the first project/tenant V2 authority cutover."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.application.schemas.cron import CronJobCreate, PayloadConfig, ScheduleConfig
from src.domain.model.cron.value_objects import PayloadType, ScheduleType
from src.domain.model.project.project import Project
from src.infrastructure.adapters.primary.web.routers import cron as cron_router

pytestmark = pytest.mark.unit


def _body() -> CronJobCreate:
    return CronJobCreate(
        name="V2 authority lookup",
        schedule=ScheduleConfig(
            kind=ScheduleType.EVERY,
            config={"interval_seconds": 60},
        ),
        payload=PayloadConfig(
            kind=PayloadType.SYSTEM_EVENT,
            config={"content": "run"},
        ),
    )


async def test_create_cron_job_resolves_project_only_through_v2_authority() -> None:
    db = AsyncMock()
    cron_service = SimpleNamespace(
        create_job=AsyncMock(
            side_effect=cron_router.CronMutationUnavailableError("durable path unavailable")
        )
    )
    project_service = SimpleNamespace(
        get_project=AsyncMock(
            return_value=Project(
                id="project-1",
                tenant_id="tenant-1",
                name="Project",
                owner_id="user-1",
            )
        )
    )
    services = SimpleNamespace(
        require_project_access=AsyncMock(),
        cron_jobs=cron_service,
        projects=SimpleNamespace(project_service=project_service),
    )
    authority = SimpleNamespace(db=db, user_id="user-1", services=services)

    with pytest.raises(HTTPException) as error:
        await cron_router.create_cron_job(
            project_id="project-1",
            body=_body(),
            cron_application=authority,
        )

    assert error.value.status_code == 503
    project_service.get_project.assert_awaited_once_with("project-1")
    assert cron_service.create_job.await_args.kwargs["tenant_id"] == "tenant-1"
