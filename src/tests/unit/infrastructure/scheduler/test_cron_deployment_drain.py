"""Local schedule closure never attests queues, executions or deployment readiness."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.model.cron.cutover import CronCutoverPhase, CronCutoverSnapshot
from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
    CronCutoverConflictError,
    SqlCronCutoverRepository,
)
from src.infrastructure.scheduler import scheduler_service

pytestmark = pytest.mark.unit
_REAL_SYNC = scheduler_service.sync_all_jobs
CRON_TASK = "src.infrastructure.scheduler.job_executor:execute_cron_job"


def snapshot(*, phase="prepared", revision=1, owner="draining"):
    return CronCutoverSnapshot(
        phase=CronCutoverPhase(phase),
        revision=revision,
        owner_kind=owner,
        deployment_id="deployment-1" if phase != "unverified" else None,
        blockers=(),
    )


def schedule(identity, *, task_id=CRON_TASK, job_id=None):
    return SimpleNamespace(
        id=identity,
        task_id=task_id,
        args=(),
        kwargs={"job_id": identity if job_id is None else job_id},
    )


class FakeScheduler:
    identity = "python-api-1"

    def __init__(self):
        self.schedules = {"job": schedule("job"), "other": schedule("other", task_id="other-task")}
        self.tasks = [
            SimpleNamespace(id=CRON_TASK, func=CRON_TASK),
            SimpleNamespace(id="other-task", func="other.module:run"),
        ]
        self.removed = []
        self.added = []
        self.remove_started = asyncio.Event()
        self.finish_remove = None
        self.add_started = asyncio.Event()
        self.finish_add = None
        self.remove_error = None

    async def get_tasks(self):
        return self.tasks

    async def get_schedules(self):
        return list(self.schedules.values())

    async def get_schedule(self, identity):
        from apscheduler import ScheduleLookupError

        if identity not in self.schedules:
            raise ScheduleLookupError(identity)
        return self.schedules[identity]

    async def remove_schedule(self, identity):
        self.remove_started.set()
        if self.finish_remove:
            await self.finish_remove.wait()
        if self.remove_error:
            raise self.remove_error
        self.removed.append(identity)
        self.schedules.pop(identity, None)

    async def add_schedule(self, _task, _trigger, *, id, kwargs, **_options):
        self.add_started.set()
        if self.finish_add:
            await self.finish_add.wait()
        self.added.append(id)
        self.schedules[id] = schedule(id, job_id=kwargs["job_id"])
        return id


@pytest.fixture
def fixture(monkeypatch):
    from src.infrastructure.adapters.secondary.persistence import database

    monkeypatch.setattr(scheduler_service, "sync_all_jobs", _REAL_SYNC)
    state = SimpleNamespace(snapshot=snapshot(), checks=0)
    scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_service, "_scheduler", scheduler)
    monkeypatch.setattr(scheduler_service, "_scheduler_lock", asyncio.Lock())
    monkeypatch.setattr(scheduler_service, "_cron_registration_seal", None, raising=False)

    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def sessions():
        yield SimpleNamespace(begin=transaction)

    async def read(_self):
        return state.snapshot

    async def require(_self, *, deployment_id, source_generation, expected_revision, producer_id):
        state.checks += 1
        if (
            deployment_id != "deployment-1"
            or source_generation != "python-old"
            or producer_id != "python-api-1"
            or expected_revision != state.snapshot.revision
            or state.snapshot.owner_kind != "draining"
            or state.snapshot.phase not in {CronCutoverPhase.PREPARED, CronCutoverPhase.BLOCKED}
        ):
            raise CronCutoverConflictError("prepared deployment changed")

    monkeypatch.setattr(database, "async_session_factory", sessions)
    monkeypatch.setattr(SqlCronCutoverRepository, "read", read)
    monkeypatch.setattr(SqlCronCutoverRepository, "lock_registration_boundary", read)
    monkeypatch.setattr(
        SqlCronCutoverRepository, "require_prepared_deployment", require, raising=False
    )
    return scheduler, state


def request(**patch):
    from src.infrastructure.scheduler.cron_deployment_drain import CronProducerCloseRequest

    return CronProducerCloseRequest(
        **{
            "deployment_id": "deployment-1",
            "source_generation": "python-old",
            "producer_id": "python-api-1",
            "expected_revision": 1,
            "schedule_ids": ("job",),
        }
        | patch
    )


async def close(**patch):
    from src.infrastructure.scheduler.cron_deployment_drain import close_local_cron_producer

    return await close_local_cron_producer(request(**patch))


async def register():
    await scheduler_service.register_job(
        job_id="job", schedule_type="every", schedule_config={"interval_seconds": 60}
    )


async def test_persisted_prepare_blocks_registration_even_without_local_seal(fixture):
    scheduler, _ = fixture
    with pytest.raises(RuntimeError):
        await register()
    assert scheduler.added == []


async def test_close_preserves_other_schedules_and_reports_only_unverified_local_boundary(fixture):
    scheduler, state = fixture
    result = await close()
    assert result.observation == "closed"
    assert result.removed_schedule_ids == ("job",)
    assert set(scheduler.schedules) == {"other"}
    assert scheduler_service._scheduler is scheduler
    assert state.checks >= 2
    assert result.to_wire()["verified"] is False
    assert result.to_wire()["boundary"] == "local_cron_schedule_production"
    assert scheduler_service._cron_registration_seal is not None


@pytest.mark.parametrize(
    "patch",
    [
        {"deployment_id": "wrong"},
        {"source_generation": "wrong"},
        {"expected_revision": 2},
        {"producer_id": "wrong"},
    ],
)
async def test_wrong_deployment_generation_revision_or_local_producer_cannot_remove(fixture, patch):
    scheduler, _ = fixture
    result = await close(**patch)
    assert result.observation == "unresolved"
    assert scheduler.removed == []


async def test_close_before_prepare_does_not_remove(fixture):
    scheduler, state = fixture
    state.snapshot = snapshot(phase="unverified", revision=0, owner="python")
    assert (await close()).observation == "unresolved"
    assert scheduler.removed == []


@pytest.mark.parametrize("mutation", ["other-task", "wrong-job-id", "rebound-task"])
async def test_only_exact_cron_callable_and_structured_job_identity_can_be_removed(
    fixture, mutation
):
    scheduler, _ = fixture
    if mutation == "other-task":
        scheduler.schedules["job"].task_id = "other-task"
    elif mutation == "wrong-job-id":
        scheduler.schedules["job"].kwargs = {"job_id": "another-job"}
    else:
        scheduler.tasks[0].func = "other.module:run"
    result = await close()
    assert result.observation == "unresolved"
    assert scheduler.removed == []


async def test_unlisted_cron_schedule_is_preserved_and_blocks_closed_observation(fixture):
    scheduler, _ = fixture
    scheduler.schedules["unlisted"] = schedule("unlisted")
    result = await close()
    assert result.observation == "unresolved"
    assert "unlisted" in scheduler.schedules
    assert "unlisted" not in scheduler.removed


async def test_registration_in_flight_settles_before_close_can_observe_or_remove(fixture):
    scheduler, state = fixture
    state.snapshot = snapshot(phase="unverified", revision=0, owner="python")
    scheduler.finish_add = asyncio.Event()
    registering = asyncio.create_task(register())
    await asyncio.wait_for(scheduler.add_started.wait(), 2)
    state.snapshot = snapshot()
    closing = asyncio.create_task(close())
    await asyncio.sleep(0)
    assert not closing.done() and scheduler.removed == []
    scheduler.finish_add.set()
    await registering
    assert (await closing).observation == "closed"
    assert "job" not in scheduler.schedules


async def test_waiting_registration_cannot_recreate_after_close(fixture):
    scheduler, _ = fixture
    scheduler.finish_remove = asyncio.Event()
    closing = asyncio.create_task(close())
    await asyncio.wait_for(scheduler.remove_started.wait(), 2)
    registering = asyncio.create_task(register())
    await asyncio.sleep(0)
    assert not registering.done()
    scheduler.finish_remove.set()
    assert (await closing).observation == "closed"
    with pytest.raises(RuntimeError):
        await registering
    assert scheduler.added == []


async def test_changed_persisted_revision_after_removal_remains_unresolved(fixture):
    scheduler, state = fixture
    scheduler.finish_remove = asyncio.Event()
    closing = asyncio.create_task(close())
    await asyncio.wait_for(scheduler.remove_started.wait(), 2)
    state.snapshot = snapshot(revision=2)
    scheduler.finish_remove.set()
    assert (await closing).observation == "unresolved"
    with pytest.raises(RuntimeError):
        await register()


async def test_remove_failure_and_cancel_leave_registration_sealed(fixture):
    scheduler, _ = fixture
    scheduler.remove_error = OSError("private storage failure")
    failed = await close()
    assert failed.observation == "unresolved"
    assert "private" not in str(failed.to_wire())
    scheduler.remove_error = None
    scheduler.remove_started.clear()
    scheduler.finish_remove = asyncio.Event()
    closing = asyncio.create_task(close())
    await asyncio.wait_for(scheduler.remove_started.wait(), 2)
    closing.cancel()
    cancelled = await closing
    assert cancelled.observation == "unresolved"
    assert scheduler_service._cron_registration_seal is not None
    with pytest.raises(RuntimeError):
        await register()


async def test_sync_after_restart_never_loads_or_re_registers_jobs_behind_prepare(
    fixture, monkeypatch
):
    from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
        SqlCronJobRepository,
    )

    scheduler, _ = fixture
    monkeypatch.setattr(scheduler_service, "_cron_registration_seal", None)
    find = AsyncMock(return_value=[])
    monkeypatch.setattr(SqlCronJobRepository, "find_due_jobs", find)
    await scheduler_service.sync_all_jobs()
    find.assert_not_awaited()
    assert scheduler.added == []


async def test_schedule_reappearance_cannot_report_closed(fixture, monkeypatch):
    scheduler, _ = fixture
    original = scheduler.remove_schedule

    async def recreate(identity):
        await original(identity)
        scheduler.schedules[identity] = schedule(identity)

    monkeypatch.setattr(scheduler, "remove_schedule", recreate)
    assert (await close()).observation == "unresolved"


async def test_revision_change_during_final_schedule_read_cannot_report_closed(
    fixture, monkeypatch
):
    scheduler, state = fixture
    original = scheduler.get_schedules

    async def changed():
        if scheduler.removed:
            state.snapshot = snapshot(revision=2)
        return await original()

    monkeypatch.setattr(scheduler, "get_schedules", changed)
    assert (await close()).observation == "unresolved"


async def test_sync_inflight_settles_before_close_and_does_not_recreate(fixture, monkeypatch):
    from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
        SqlCronJobRepository,
    )

    scheduler, state = fixture
    state.snapshot = snapshot(phase="unverified", revision=0, owner="python")
    job = SimpleNamespace(
        id="job",
        timezone="UTC",
        schedule=SimpleNamespace(
            kind=SimpleNamespace(value="every"), config={"interval_seconds": 60}
        ),
    )
    monkeypatch.setattr(SqlCronJobRepository, "find_due_jobs", AsyncMock(return_value=[job]))
    scheduler.finish_add = asyncio.Event()
    syncing = asyncio.create_task(scheduler_service.sync_all_jobs())
    await asyncio.wait_for(scheduler.add_started.wait(), 2)
    state.snapshot = snapshot()
    closing = asyncio.create_task(close())
    await asyncio.sleep(0)
    assert not closing.done()
    scheduler.finish_add.set()
    await syncing
    assert (await closing).observation == "closed"
    assert "job" not in scheduler.schedules


@pytest.mark.parametrize(
    "patch",
    [
        {"expected_revision": True},
        {"expected_revision": 0},
        {"schedule_ids": ["job"]},
        {"schedule_ids": ([],)},
        {"schedule_ids": ("job", "job")},
        {"producer_id": " "},
    ],
)
def test_request_rejects_invalid_structural_identity(patch):
    with pytest.raises(ValueError):
        request(**patch)
