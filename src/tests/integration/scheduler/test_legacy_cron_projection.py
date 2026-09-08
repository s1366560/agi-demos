"""Legacy run projection follows real execution under the admission transaction."""

from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.infrastructure.adapters.secondary.persistence.legacy_cron_admission_model import (
    LegacyCronAdmissionModel,
)
from src.infrastructure.adapters.secondary.persistence.models import CronJobModel, CronJobRunModel
from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
    SqlLegacyCronAdmissionRepository,
)
from src.tests.integration.scheduler.test_legacy_cron_admission import admit

pytestmark = pytest.mark.integration


async def test_claim_park_resume_and_terminal_project_with_same_admission(database):
    _, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        repository = SqlLegacyCronAdmissionRepository(session)
        ticket = await repository.claim_execution(identity)
        await session.commit()
        run = await session.get(CronJobRunModel, identity.run_id)
        assert run.status == "running" and run.finished_at is None
        started_at = run.started_at
        assert await repository.park_for_hitl(ticket)
        await session.commit()
        assert run.status == "waiting_human"
        resumed = await repository.claim_execution(identity, resume=True)
        await session.commit()
        assert run.status == "running" and run.started_at == started_at
        assert await repository.complete(resumed, "success")
        await session.commit()
        job = await session.get(CronJobModel, "job")
        assert run.status == "success" and run.finished_at is not None
        assert run.duration_ms >= 0
        assert job.state["last_run_at"] == run.finished_at.isoformat()
        assert job.state["next_run"] == "preserved"


async def test_duplicate_terminal_counts_failure_once_and_retains_current_configuration(database):
    _, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        repository = SqlLegacyCronAdmissionRepository(session)
        ticket = await repository.claim_execution(identity)
        await session.commit()
        job = await session.get(CronJobModel, "job")
        job.name = "edited while running"
        job.max_retries = 1
        await session.commit()
        assert await repository.complete(ticket, "failed")
        await session.commit()
        first_state = dict(job.state)
        assert await repository.complete(ticket, "failed")
        assert not await repository.complete(ticket, "success")
        await session.commit()
        assert job.state == first_state
        assert job.state["consecutive_errors"] == 1
        assert job.name == "edited while running" and not job.enabled


@pytest.mark.parametrize("schedule,delete_after", [("at", False), ("every", True)])
async def test_one_shot_success_retires_without_deleting_history(database, schedule, delete_after):
    _, sessions = database
    async with sessions() as session:
        job = await session.get(CronJobModel, "job")
        job.schedule_type = schedule
        job.delete_after_run = delete_after
        identity = await admit(session)
        repository = SqlLegacyCronAdmissionRepository(session)
        ticket = await repository.claim_execution(identity)
        assert await repository.complete(ticket, "success")
        await session.commit()
        assert not job.enabled and job.state["retired_at"]
        assert await session.get(CronJobRunModel, identity.run_id) is not None


async def test_projection_failure_rolls_back_terminal_admission(database):
    _, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        repository = SqlLegacyCronAdmissionRepository(session)
        ticket = await repository.claim_execution(identity)
        await session.commit()
        await session.execute(
            text(
                "ALTER TABLE cron_job_runs ADD CONSTRAINT qa_no_success CHECK (status <> 'success')"
            )
        )
        await session.commit()
        with pytest.raises(DBAPIError):
            await repository.complete(ticket, "success")
            await session.commit()
        await session.rollback()
        admission = await session.get(LegacyCronAdmissionModel, identity.admission_id)
        run = await session.get(CronJobRunModel, identity.run_id)
        assert admission.status == "active" and admission.execution_nonce == ticket.nonce
        assert run.status == "running" and run.finished_at is None


async def test_future_hitl_progress_requires_current_ticket_and_matching_request(database):
    _, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        repository = SqlLegacyCronAdmissionRepository(session)
        ticket = await repository.claim_execution(identity)
        other = await admit(session, "two")
        other_ticket = await repository.claim_execution(other)
        assert not await repository.project_hitl(
            replace(ticket, nonce=other_ticket.nonce), "request", waiting=True
        )
        assert await repository.project_hitl(ticket, "request", waiting=True)
        await session.commit()
        run = await session.get(CronJobRunModel, identity.run_id)
        assert run.status == "waiting_human"
        assert not await repository.project_hitl(ticket, "other-request", waiting=False)
        assert await repository.project_hitl(ticket, "request", waiting=False)
        await session.commit()
        admission = await session.get(LegacyCronAdmissionModel, identity.admission_id)
        assert run.status == "running" and admission.execution_phase == "running"
        assert admission.execution_nonce == ticket.nonce


async def test_active_admission_repairs_old_dispatch_success_but_never_rust_run(database):
    _, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        run = await session.get(CronJobRunModel, identity.run_id)
        run.status = "success"
        repository = SqlLegacyCronAdmissionRepository(session)
        ticket = await repository.claim_execution(identity)
        await session.commit()
        assert run.status == "running"
        run.runtime_execution_id = "rust-run"
        await session.commit()
        assert not await repository.complete(ticket, "failed")
        await session.commit()
        assert run.status == "running"
        assert await repository.matches_active(identity)


async def test_terminal_last_run_timestamp_does_not_move_apscheduler_next_fire(
    database, monkeypatch
):
    from apscheduler import AsyncScheduler

    from src.infrastructure.adapters.secondary.persistence import database as database_module
    from src.infrastructure.scheduler import scheduler_service

    _, sessions = database
    monkeypatch.setattr(database_module, "async_session_factory", sessions)
    monkeypatch.setattr(scheduler_service, "_cron_registration_seal", None)
    async with AsyncScheduler() as scheduler:
        monkeypatch.setattr(scheduler_service, "_scheduler", scheduler)
        await scheduler_service.register_job(
            job_id="job", schedule_type="every", schedule_config={"interval_seconds": 60}
        )
        before = (await scheduler.get_schedule("job")).next_fire_time
        async with sessions() as session:
            identity = await admit(session)
            repository = SqlLegacyCronAdmissionRepository(session)
            ticket = await repository.claim_execution(identity)
            assert await repository.complete(ticket, "success")
            await session.commit()
            job = await session.get(CronJobModel, "job")
            assert job.state["last_run_at"]
        schedule = await scheduler.get_schedule("job")
        assert schedule.next_fire_time == before
        assert (schedule.trigger.next() - before).total_seconds() == 60
