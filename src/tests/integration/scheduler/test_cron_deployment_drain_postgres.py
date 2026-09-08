"""Real PostgreSQL admission transactions serialize with deployment preparation."""

import asyncio
from types import SimpleNamespace

import pytest

from src.domain.model.cron.cutover import CronDeploymentManifest
from src.infrastructure.adapters.secondary.persistence.models import CronSchedulerOwnerModel
from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
    SqlCronCutoverRepository,
)
from src.infrastructure.scheduler import scheduler_service
from src.tests.unit.domain.model.cron.test_cutover import manifest_wire

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("existing_owner", [False, True])
async def test_prepare_waits_for_inflight_schedule_registration(
    database, monkeypatch, existing_owner
):
    from src.infrastructure.adapters.secondary.persistence import database as database_module

    _, sessions = database
    if existing_owner:
        async with sessions() as session:
            session.add(CronSchedulerOwnerModel(scope_id="global", owner_kind="python"))
            await session.commit()
    started = asyncio.Event()
    release = asyncio.Event()
    committed = asyncio.Event()

    async def add_schedule(*_args, **_kwargs):
        started.set()
        await release.wait()

    monkeypatch.setattr(database_module, "async_session_factory", sessions)
    monkeypatch.setattr(scheduler_service, "_scheduler_lock", asyncio.Lock())
    monkeypatch.setattr(scheduler_service, "_cron_registration_seal", None)
    monkeypatch.setattr(scheduler_service, "_scheduler", SimpleNamespace(add_schedule=add_schedule))

    async def prepare():
        async with sessions() as session:
            await SqlCronCutoverRepository(session).prepare(
                CronDeploymentManifest.from_wire(manifest_wire()), 0
            )
            await session.commit()
            committed.set()

    registration = asyncio.create_task(
        scheduler_service.register_job(
            job_id="job", schedule_type="every", schedule_config={"interval_seconds": 60}
        )
    )
    preparation = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        preparation = asyncio.create_task(prepare())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(committed.wait(), 0.2)
    finally:
        release.set()
        await asyncio.wait_for(registration, 3)
        if preparation:
            await asyncio.wait_for(preparation, 3)
    assert committed.is_set()
    with pytest.raises(scheduler_service.CronProducerRegistrationClosed):
        await scheduler_service.register_job(
            job_id="job", schedule_type="every", schedule_config={"interval_seconds": 60}
        )


async def test_real_scheduler_close_preserves_hitl_and_existing_execution(database, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from time import monotonic

    from apscheduler import AsyncScheduler
    from apscheduler.datastores.memory import MemoryDataStore
    from apscheduler.eventbrokers.local import LocalEventBroker
    from apscheduler.triggers.date import DateTrigger

    from src.infrastructure.adapters.secondary.persistence import database as database_module
    from src.infrastructure.adapters.secondary.persistence.models import (
        AgentSessionSnapshot,
        HITLRequest,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
        SqlLegacyCronAdmissionRepository,
    )
    from src.infrastructure.scheduler.cron_deployment_drain import (
        CronProducerCloseRequest,
        close_local_cron_producer,
    )
    from src.tests.integration.scheduler.test_legacy_cron_admission import admit

    _, sessions = database
    monkeypatch.setattr(database_module, "async_session_factory", sessions)
    monkeypatch.setattr(scheduler_service, "_scheduler_lock", asyncio.Lock())
    monkeypatch.setattr(scheduler_service, "_cron_registration_seal", None)
    async with AsyncScheduler(
        identity="python-api-1", data_store=MemoryDataStore(), event_broker=LocalEventBroker()
    ) as scheduler:
        monkeypatch.setattr(scheduler_service, "_scheduler", scheduler)
        await scheduler_service.register_job(
            job_id="job", schedule_type="every", schedule_config={"interval_seconds": 3600}
        )
        await scheduler.add_schedule(
            monotonic, DateTrigger(datetime.now(UTC) + timedelta(days=1)), id="unrelated"
        )
        async with sessions() as session:
            identity = await admit(session)
            admissions = SqlLegacyCronAdmissionRepository(session)
            ticket = await admissions.claim_execution(identity)
            assert await admissions.park_for_hitl(ticket)
            session.add(
                HITLRequest(
                    id="human-request",
                    request_type="decision",
                    conversation_id="conversation",
                    tenant_id="tenant",
                    project_id="project",
                    question="Continue?",
                    status="pending",
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            session.add(
                AgentSessionSnapshot(
                    id="hitl-snapshot",
                    tenant_id="tenant",
                    project_id="project",
                    agent_mode="default",
                    request_id="human-request",
                    snapshot_type="hitl",
                    snapshot_data={"preserve": True},
                )
            )
            await SqlCronCutoverRepository(session).prepare(
                CronDeploymentManifest.from_wire(manifest_wire()), 0
            )
            await session.commit()
            owner = await session.get(CronSchedulerOwnerModel, "global")
            before = (owner.owner_epoch, owner.cutover_revision, owner.cutover_evidence)
        result = await close_local_cron_producer(
            CronProducerCloseRequest(
                deployment_id="deployment-1",
                source_generation="python-old",
                producer_id="python-api-1",
                expected_revision=1,
                schedule_ids=("job",),
            )
        )
        assert result.observation == "closed" and result.to_wire()["verified"] is False
        assert {schedule.id for schedule in await scheduler.get_schedules()} == {"unrelated"}
        assert scheduler_service._scheduler is scheduler
        async with sessions() as session:
            owner = await session.get(CronSchedulerOwnerModel, "global")
            assert (owner.owner_epoch, owner.cutover_revision, owner.cutover_evidence) == before
            assert (await session.get(HITLRequest, "human-request")).status == "pending"
            assert (await session.get(AgentSessionSnapshot, "hitl-snapshot")).snapshot_data == {
                "preserve": True
            }
            admissions = SqlLegacyCronAdmissionRepository(session)
            resumed = await admissions.claim_execution(identity, resume=True)
            assert resumed is not None
            assert await admissions.complete(resumed, "success")
            await session.commit()
        # A restarted process has no local latch but still cannot register after prepare.
        monkeypatch.setattr(scheduler_service, "_cron_registration_seal", None)
        with pytest.raises(scheduler_service.CronProducerRegistrationClosed):
            await scheduler_service.register_job(
                job_id="job", schedule_type="every", schedule_config={"interval_seconds": 60}
            )


@pytest.mark.parametrize(
    "patch",
    [
        {"deployment_id": "other"},
        {"source_generation": "other"},
        {"producer_id": "other"},
        {"expected_revision": 2},
    ],
)
async def test_prepared_identity_read_rejects_mismatch_without_mutation(database, patch):
    from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
        CronCutoverConflictError,
    )

    _, sessions = database
    async with sessions() as session:
        repository = SqlCronCutoverRepository(session)
        await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        await session.commit()
        before = await repository.read()
        with pytest.raises(CronCutoverConflictError):
            await repository.require_prepared_deployment(
                **{
                    "deployment_id": "deployment-1",
                    "source_generation": "python-old",
                    "producer_id": "python-api-1",
                    "expected_revision": 1,
                }
                | patch
            )
        assert await repository.read() == before


async def test_receipt_revision_change_invalidates_prepared_identity_read(database):
    from src.domain.model.cron.cutover import CronDeploymentReceipt
    from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
        CronCutoverConflictError,
    )
    from src.tests.unit.domain.model.cron.test_cutover import receipt_wire

    _, sessions = database
    async with sessions() as session:
        repository = SqlCronCutoverRepository(session)
        fields = {
            "deployment_id": "deployment-1",
            "source_generation": "python-old",
            "producer_id": "python-api-1",
            "expected_revision": 1,
        }
        with pytest.raises(CronCutoverConflictError):
            await repository.require_prepared_deployment(**fields)
        await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        await session.commit()
        await repository.require_prepared_deployment(**fields)
        await repository.record_receipt(CronDeploymentReceipt.from_wire(receipt_wire()), 1)
        await session.commit()
        with pytest.raises(CronCutoverConflictError):
            await repository.require_prepared_deployment(**fields)
        assert (await repository.read()).revision == 2
