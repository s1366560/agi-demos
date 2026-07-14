from __future__ import annotations

import pytest

from src.application.schemas.cron import cron_job_run_to_response, cron_job_to_response
from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.cron_job_run import CronJobRun
from src.domain.model.cron.value_objects import (
    CronDelivery,
    CronPayload,
    CronRunStatus,
    CronSchedule,
)

pytestmark = pytest.mark.unit


def test_cron_job_response_includes_revision_fences() -> None:
    job = CronJob(
        project_id="project-1",
        tenant_id="tenant-1",
        name="Revisioned job",
        revision=7,
        schedule_revision=3,
        schedule=CronSchedule.every(interval_seconds=300),
        payload=CronPayload.agent_turn(message="Summarize status"),
    )

    response = cron_job_to_response(job)

    assert response.revision == 7
    assert response.schedule_revision == 3


def test_cron_read_responses_redact_credentials_and_delivery_locations() -> None:
    job = CronJob(
        project_id="project-1",
        tenant_id="tenant-1",
        name="Credential-safe job",
        schedule=CronSchedule.every(interval_seconds=300),
        payload=CronPayload.agent_turn(message="Summarize status"),
        delivery=CronDelivery.webhook(
            url="https://example.invalid/hook?token=should-not-leak",
            headers={"Authorization": "Bearer should-not-leak"},
        ),
        state={
            "credential_ref": "vault://delivery/42",
            "diagnostics": {"access_token": "should-not-leak"},
        },
    )
    run = CronJobRun(
        job_id=job.id,
        project_id=job.project_id,
        status=CronRunStatus.SUCCESS,
        result_summary={"nested": {"api-key": "should-not-leak"}, "tokens_used": 42},
    )

    job_response = cron_job_to_response(job)
    run_response = cron_job_run_to_response(run)

    assert job_response.delivery.config["url"] == "[REDACTED]"
    assert job_response.delivery.config["headers"] == "[REDACTED]"
    assert job_response.state["credential_ref"] == "vault://delivery/42"
    assert job_response.state["diagnostics"]["access_token"] == "[REDACTED]"
    assert run_response.result_summary["nested"]["api-key"] == "[REDACTED]"
    assert run_response.result_summary["tokens_used"] == 42
    assert "should-not-leak" not in job_response.model_dump_json()
    assert "should-not-leak" not in run_response.model_dump_json()
