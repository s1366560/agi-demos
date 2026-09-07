"""Disabled execution capabilities must also prevent durable command admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from src.application.schemas.cron import AutomationRunCommandV2, ManualRunRequest
from src.domain.model.cron.cron_job import CronJob
from src.infrastructure.adapters.primary.web.routers import cron
from src.infrastructure.plugins.v2.cron_services import CronProjectAccessDeniedV2

pytestmark = pytest.mark.unit


def _authority(*, job: CronJob | None, access_error: Exception | None = None):
    return SimpleNamespace(
        db=AsyncMock(),
        user_id="user-1",
        services=SimpleNamespace(
            require_project_access=AsyncMock(side_effect=access_error),
            cron_jobs=SimpleNamespace(
                get_job=AsyncMock(return_value=job),
                trigger_manual_run=AsyncMock(),
            ),
            commands=SimpleNamespace(queue_manual_run=AsyncMock()),
        ),
    )


@pytest.mark.parametrize(
    "body",
    [
        None,
        ManualRunRequest(conversation_id="conversation-1"),
        AutomationRunCommandV2(
            contract_version=2, expected_revision=1, idempotency_key="admission-1"
        ),
    ],
)
async def test_disabled_capability_rejects_every_command_without_persistence(body) -> None:
    job = CronJob(project_id="project-1", tenant_id="tenant-1", name="Disabled runtime")
    authority = _authority(job=job)
    capabilities = await cron.get_cron_job_capabilities("project-1", authority)
    assert capabilities.run_now.allowed is False

    with pytest.raises(HTTPException) as error:
        await cron.trigger_manual_run("project-1", job.id, body, authority)

    assert error.value.status_code == 503
    assert error.value.detail["reason_code"] == capabilities.run_now.reason_code
    authority.services.commands.queue_manual_run.assert_not_awaited()
    authority.services.cron_jobs.trigger_manual_run.assert_not_awaited()
    authority.db.commit.assert_not_awaited()


@pytest.mark.parametrize("missing", [True, False])
async def test_unavailable_execution_preserves_target_scope_check(missing: bool) -> None:
    job = (
        None
        if missing
        else CronJob(project_id="other-project", tenant_id="other-tenant", name="Private job")
    )
    authority = _authority(job=job)
    with pytest.raises(HTTPException) as error:
        await cron.trigger_manual_run("project-1", "job-1", None, authority)
    assert error.value.status_code == 404
    authority.services.commands.queue_manual_run.assert_not_awaited()
    authority.db.commit.assert_not_awaited()


async def test_unavailable_execution_preserves_membership_check() -> None:
    authority = _authority(job=None, access_error=CronProjectAccessDeniedV2())
    with pytest.raises(HTTPException) as error:
        await cron.trigger_manual_run("project-1", "job-1", None, authority)
    assert error.value.status_code == 403
    authority.services.cron_jobs.get_job.assert_not_awaited()
    authority.services.commands.queue_manual_run.assert_not_awaited()
    authority.db.commit.assert_not_awaited()


async def test_http_v2_command_matches_disabled_capability_reason() -> None:
    job = CronJob(project_id="project-1", tenant_id="tenant-1", name="HTTP admission")
    authority = _authority(job=job)
    app = FastAPI()
    app.include_router(cron.router)
    app.dependency_overrides[cron.cron_application_authority_dependency_v2] = lambda: authority
    base = "/api/v1/projects/project-1/cron-jobs"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        capabilities = await client.get(f"{base}/capabilities")
        response = await client.post(
            f"{base}/{job.id}/run",
            json={"contract_version": 2, "expected_revision": 1, "idempotency_key": "http-1"},
        )
    assert capabilities.status_code == 200
    assert response.status_code == 503
    assert (
        response.json()["detail"]["reason_code"] == (capabilities.json()["run_now"]["reason_code"])
    )
    authority.services.commands.queue_manual_run.assert_not_awaited()
    authority.db.commit.assert_not_awaited()
