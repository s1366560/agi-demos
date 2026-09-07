"""Real PostgreSQL fences, identity checks, and rollback safety in private schemas."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from src.infrastructure.adapters.secondary.persistence.legacy_cron_admission_model import (
    LegacyCronAdmissionModel,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobRunModel,
    CronSchedulerOwnerModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
    SqlLegacyCronAdmissionRepository,
)
from src.infrastructure.agent.actor import legacy_cron_admission as terminal_bridge

pytestmark = pytest.mark.integration
migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("b36acb66634d").module


async def admit(session, suffix="one"):
    session.add(
        CronJobRunModel(
            id=f"run-{suffix}",
            job_id="job",
            project_id="project",
            status="queued",
            conversation_id="conversation",
        )
    )
    await session.flush()
    return await SqlLegacyCronAdmissionRepository(session).admit(
        tenant_id="tenant",
        project_id="project",
        job_id="job",
        run_id=f"run-{suffix}",
        message_id=f"message-{suffix}",
        conversation_id="conversation",
    )


async def test_missing_owner_initializes_python_and_concurrent_admissions_serialize(database):
    _, sessions = database

    async def attempt(suffix):
        async with sessions() as session:
            value = await admit(session, suffix)
            await session.commit()
            return value

    first, second = await asyncio.gather(attempt("one"), attempt("two"))
    assert first and second and first.admission_id != second.admission_id
    async with sessions() as session:
        assert (await session.get(CronSchedulerOwnerModel, "global")).owner_kind == "python"
        rows = list(await session.scalars(select(LegacyCronAdmissionModel)))
        assert len(rows) == 2
        assert all(row.status == "active" for row in rows)
        assert first.token not in [row.token_hash for row in rows]


@pytest.mark.parametrize("kind", ["off", "rust", "draining", "unknown"])
async def test_explicit_non_python_owner_denies_admission(database, kind):
    _, sessions = database
    async with sessions() as session:
        session.add(CronSchedulerOwnerModel(scope_id="global", owner_kind=kind))
        await session.commit()
        assert await admit(session) is None
        await session.commit()
        assert not list(await session.scalars(select(LegacyCronAdmissionModel)))


async def test_owner_row_lock_serializes_cutover_against_inflight_admission(database):
    _, sessions = database
    async with sessions() as first:
        first.add(CronSchedulerOwnerModel(scope_id="global", owner_kind="python"))
        await first.commit()
        value = await admit(first)
        assert value is not None
        attempted = asyncio.Event()

        async def cutover_observation():
            async with sessions() as second:
                attempted.set()
                owner = await second.scalar(select(CronSchedulerOwnerModel).with_for_update())
                active = list(await second.scalars(select(LegacyCronAdmissionModel)))
                return owner.owner_kind, len(active)

        observation = asyncio.create_task(cutover_observation())
        await attempted.wait()
        await asyncio.sleep(0.05)
        assert not observation.done()
        await first.commit()
        assert await observation == ("python", 1)


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "project_id",
        "job_id",
        "run_id",
        "message_id",
        "conversation_id",
        "token",
        "admission_id",
        "owner_epoch",
    ],
)
async def test_mismatched_terminal_identity_cannot_release(database, field):
    _, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        await session.commit()
        bad = replace(identity, **{field: 99 if field == "owner_epoch" else "other"})
        repository = SqlLegacyCronAdmissionRepository(session)
        assert not await repository.matches_active(bad)
        ticket = await repository.claim_execution(identity)
        assert ticket is not None
        assert not await repository.complete(replace(ticket, admission=bad), "success")
        await session.commit()
        assert await repository.matches_active(identity)


async def test_only_real_terminal_releases_and_old_replays_cannot_change_outcome(
    database, monkeypatch
):
    _, sessions = database
    monkeypatch.setattr(terminal_bridge, "async_session_factory", sessions)
    async with sessions() as session:
        identity = await admit(session)
        ticket = await SqlLegacyCronAdmissionRepository(session).claim_execution(identity)
        await session.commit()
    for outcome in ["dispatch_failed", "timeout", "cancelled", "unknown", "waiting_human"]:
        await terminal_bridge.complete_legacy_cron_admission(ticket, outcome)
        async with sessions() as session:
            assert await SqlLegacyCronAdmissionRepository(session).matches_active(identity)
    await terminal_bridge.complete_legacy_cron_admission(ticket, "success")
    await terminal_bridge.complete_legacy_cron_admission(ticket, "success")
    await terminal_bridge.complete_legacy_cron_admission(ticket, "failed")
    async with sessions() as session:
        row = await session.get(LegacyCronAdmissionModel, identity.admission_id)
        assert row.status == "success" and row.terminal_at is not None


async def test_migration_refuses_to_drop_active_admissions_and_preserves_owner(database):
    engine, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        await session.commit()

    def downgrade(sync):
        with Operations.context(MigrationContext.configure(sync)):
            migration.downgrade()

    with pytest.raises(DBAPIError, match="Cannot remove unresolved"):
        async with engine.begin() as connection:
            await connection.run_sync(downgrade)
    async with sessions() as session:
        assert await SqlLegacyCronAdmissionRepository(session).matches_active(identity)
        repository = SqlLegacyCronAdmissionRepository(session)
        ticket = await repository.claim_execution(identity)
        assert ticket is not None
        assert await repository.complete(ticket, "success")
        await session.commit()
    async with engine.begin() as connection:
        await connection.run_sync(downgrade)
        assert (
            await connection.scalar(text("SELECT owner_kind FROM agistack_cron_scheduler_owners"))
            == "python"
        )
        assert (
            await connection.scalar(text("SELECT to_regclass('agistack_legacy_cron_admissions')"))
            is None
        )


async def test_duplicate_actor_delivery_cannot_share_one_active_admission(database, monkeypatch):
    _, sessions = database
    monkeypatch.setattr(terminal_bridge, "async_session_factory", sessions)
    async with sessions() as session:
        identity = await admit(session)
        await session.commit()

    async def enter():
        return await terminal_bridge.validate_legacy_cron_admission(
            identity.to_wire(),
            tenant_id="tenant",
            project_id="project",
            conversation_id="conversation",
            message_id=identity.message_id,
        )

    results = await asyncio.gather(enter(), enter(), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1


async def test_only_one_resume_claim_and_stale_phase_cannot_release(database):
    _, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        repository = SqlLegacyCronAdmissionRepository(session)
        first = await repository.claim_execution(identity)
        await session.commit()
        assert await repository.claim_execution(identity) is None
        assert await repository.claim_execution(identity, resume=True) is None
        assert await repository.park_for_hitl(first)
        await session.commit()

    async def resume():
        async with sessions() as session:
            ticket = await SqlLegacyCronAdmissionRepository(session).claim_execution(
                identity, resume=True
            )
            await session.commit()
            return ticket

    candidates = await asyncio.gather(resume(), resume())
    tickets = [ticket for ticket in candidates if ticket is not None]
    assert len(tickets) == 1
    current = tickets[0]
    assert current.nonce != first.nonce
    async with sessions() as session:
        repository = SqlLegacyCronAdmissionRepository(session)
        assert not await repository.complete(first, "success")
        assert not await repository.park_for_hitl(first)
        assert await repository.matches_active(identity)
        assert await repository.complete(current, "success")
        await session.commit()


@pytest.mark.parametrize("failure", ["snapshot", "park"])
async def test_failed_hitl_parking_keeps_execution_running(database, monkeypatch, failure):
    from unittest.mock import AsyncMock

    from src.domain.model.agent.hitl.hitl_types import HITLPendingException, HITLType

    _, sessions = database
    monkeypatch.setattr(terminal_bridge, "async_session_factory", sessions)
    async with sessions() as session:
        identity = await admit(session)
        ticket = await SqlLegacyCronAdmissionRepository(session).claim_execution(identity)
        await session.commit()
    persist = AsyncMock(return_value=object())
    if failure == "snapshot":
        persist.side_effect = RuntimeError("snapshot unavailable")
    else:
        monkeypatch.setattr(
            SqlLegacyCronAdmissionRepository, "park_for_hitl", AsyncMock(return_value=False)
        )
    error = HITLPendingException(
        request_id="request",
        hitl_type=HITLType.CLARIFICATION,
        request_data={},
        conversation_id="conversation",
    )
    with pytest.raises((RuntimeError, ValueError)):
        await terminal_bridge.maybe_park_legacy_hitl(ticket, error, persist)
    async with sessions() as session:
        row = await session.get(LegacyCronAdmissionModel, identity.admission_id)
        assert row.status == "active" and row.execution_phase == "running"
        assert row.execution_nonce == ticket.nonce
