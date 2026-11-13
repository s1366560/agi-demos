"""Cron add/list uses the durable command service and does not start a run."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from src.domain.model.cron.value_objects import CronPayload, CronSchedule
from src.infrastructure.adapters.secondary.persistence.models import CronJobRunModel
from src.infrastructure.agent.tools.cron_tool import _build_service

pytestmark = pytest.mark.unit


async def test_create_is_idempotent_and_does_not_queue_execution(
    db_session,
    test_project_db,
    test_user,
) -> None:
    service = _build_service(db_session)
    key = f"round2-{uuid.uuid4()}"
    schedule = CronSchedule.every(interval_seconds=3600)
    payload = CronPayload.agent_turn(message="temporary round2 probe")
    created = await service.create_job(
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        name="round2-temporary",
        schedule=schedule,
        payload=payload,
        created_by=test_user.id,
        idempotency_key=key,
    )
    again = await service.create_job(
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        name="round2-temporary",
        schedule=schedule,
        payload=payload,
        created_by=test_user.id,
        idempotency_key=key,
    )
    listed = await service.list_jobs(test_project_db.id, include_disabled=True)
    visible = [job for job in listed if job.id == created.id]
    runs = await db_session.scalar(
        select(func.count())
        .select_from(CronJobRunModel)
        .where(CronJobRunModel.job_id == created.id)
    )
    await service.delete_job(
        created.id,
        project_id=test_project_db.id,
        actor_user_id=test_user.id,
        expected_revision=created.revision,
        idempotency_key=f"{key}-delete",
    )

    assert again.id == created.id
    assert len(visible) == 1
    assert runs == 0
    assert await service.get_job(created.id) is None
