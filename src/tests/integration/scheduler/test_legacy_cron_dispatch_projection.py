"""Scheduler delivery cannot overwrite execution-owned runtime state."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence import database as database_module
from src.infrastructure.adapters.secondary.persistence.models import CronJobModel, CronJobRunModel
from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
    SqlLegacyCronAdmissionRepository,
)
from src.infrastructure.scheduler import job_executor

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("outcome", ["success", "failed"])
@pytest.mark.parametrize("delivery_error", [False, True])
async def test_late_dispatch_return_never_overwrites_terminal(
    database, monkeypatch, outcome, delivery_error
):
    _, sessions = database
    monkeypatch.setattr(database_module, "async_session_factory", sessions)
    monkeypatch.setattr(
        job_executor, "_resolve_conversation", AsyncMock(return_value="conversation")
    )
    observed = []

    async def dispatch(job, conversation_id, session, identity):
        async with sessions() as actor_session:
            repository = SqlLegacyCronAdmissionRepository(actor_session)
            ticket = await repository.claim_execution(identity)
            assert ticket is not None
            assert await repository.complete(ticket, outcome)
            await actor_session.commit()
            run = await actor_session.get(CronJobRunModel, identity.run_id)
            current_job = await actor_session.get(CronJobModel, job.id)
            observed.append((identity, run.finished_at, dict(current_job.state)))
        if delivery_error:
            raise RuntimeError("dispatch response lost after execution finished")

    monkeypatch.setattr(job_executor, "_execute_payload", dispatch)
    await job_executor.execute_cron_job("job")
    assert len(observed) == 1
    identity, finished_at, state = observed[0]
    async with sessions() as session:
        run = await session.get(CronJobRunModel, identity.run_id)
        job = await session.get(CronJobModel, "job")
        assert run.status == outcome and run.finished_at == finished_at
        assert job.state == state and job.conversation_id == "conversation"


@pytest.mark.parametrize("error", [TimeoutError, asyncio.CancelledError, RuntimeError])
async def test_uncertain_dispatch_keeps_nonterminal_run_and_statistics(
    database, monkeypatch, error
):
    _, sessions = database
    monkeypatch.setattr(database_module, "async_session_factory", sessions)
    monkeypatch.setattr(
        job_executor, "_resolve_conversation", AsyncMock(return_value="conversation")
    )
    identities = []

    async def dispatch(job, conversation_id, session, identity):
        identities.append(identity)
        raise error()

    monkeypatch.setattr(job_executor, "_execute_payload", dispatch)
    if error is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await job_executor.execute_cron_job("job")
    else:
        await job_executor.execute_cron_job("job")
    async with sessions() as session:
        identity = identities[0]
        run = await session.get(CronJobRunModel, identity.run_id)
        job = await session.get(CronJobModel, "job")
        assert run.status == "queued" and run.finished_at is None
        assert job.state == {"next_run": "preserved"}
        assert await SqlLegacyCronAdmissionRepository(session).matches_active(identity)


async def test_preparation_failure_records_safe_error_with_current_policy(database, monkeypatch):
    _, sessions = database
    monkeypatch.setattr(database_module, "async_session_factory", sessions)

    async def fail_preparation(job, session):
        async with sessions() as editor:
            current = await editor.get(CronJobModel, job.id)
            current.name = "edited configuration"
            current.max_retries = 1
            await editor.commit()
        raise RuntimeError("secret must not be stored")

    monkeypatch.setattr(job_executor, "_resolve_conversation", fail_preparation)
    await job_executor.execute_cron_job("job")
    async with sessions() as session:
        run = (await session.scalars(select(CronJobRunModel))).one()
        job = await session.get(CronJobModel, "job")
        assert run.status == "failed" and run.error_message == "legacy_preparation_failed"
        assert job.name == "edited configuration" and not job.enabled
        assert job.state["consecutive_errors"] == 1
        assert job.state["next_run"] == "preserved"
