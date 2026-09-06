"""Real APScheduler/AnyIO task ownership, with memory storage and a local broker."""

import asyncio

import pytest
from apscheduler import AsyncScheduler
from apscheduler.datastores.memory import MemoryDataStore
from apscheduler.eventbrokers.local import LocalEventBroker

from src.infrastructure.plugins.v2.lifecycle_tasks import OwnedLifecycleTaskV2
from src.infrastructure.scheduler import scheduler_service

_REAL_START = scheduler_service.start_scheduler
_REAL_STOP = scheduler_service.stop_scheduler


@pytest.fixture
def isolated_scheduler(monkeypatch):
    import apscheduler.datastores.sqlalchemy as data_stores
    import apscheduler.eventbrokers.redis as brokers

    monkeypatch.setattr(scheduler_service, "start_scheduler", _REAL_START)
    monkeypatch.setattr(scheduler_service, "stop_scheduler", _REAL_STOP)
    monkeypatch.setattr(scheduler_service, "_scheduler", None)
    monkeypatch.setattr(scheduler_service, "_scheduler_owner", None, raising=False)
    monkeypatch.setattr(scheduler_service, "_scheduler_lock", asyncio.Lock(), raising=False)
    monkeypatch.setattr(data_stores, "SQLAlchemyDataStore", lambda _engine: MemoryDataStore())
    monkeypatch.setattr(brokers, "RedisEventBroker", lambda _url: LocalEventBroker())
    return monkeypatch


async def test_real_scheduler_can_stop_from_owned_effect_task(isolated_scheduler):
    async def lifecycle():
        try:
            scheduler = await scheduler_service.start_scheduler()
            assert isinstance(scheduler, AsyncScheduler)
            await OwnedLifecycleTaskV2(
                scheduler_service.stop_scheduler, name="effect-dispose"
            ).wait()
            await asyncio.sleep(0)
            assert asyncio.current_task().cancelling() == 0
            return None
        except BaseException as error:
            return error

    # Keep the pytest task outside the scheduler's AnyIO cancel scope even on RED.
    task = asyncio.create_task(lifecycle())
    result = await asyncio.wait_for(asyncio.shield(task), timeout=5)
    assert result is None
    assert scheduler_service._scheduler is None


async def test_startup_failure_exits_real_scheduler_in_its_owner_task(isolated_scheduler):
    import apscheduler

    failure = ValueError("startup failed")
    entered = []
    exited = []

    class FailingScheduler(AsyncScheduler):
        async def __aenter__(self):
            entered.append(asyncio.current_task())
            return await super().__aenter__()

        async def start_in_background(self):
            await super().start_in_background()
            raise failure

        async def __aexit__(self, *args):
            try:
                return await super().__aexit__(*args)
            finally:
                exited.append(asyncio.current_task())

    isolated_scheduler.setattr(apscheduler, "AsyncScheduler", FailingScheduler)
    with pytest.raises(BaseExceptionGroup) as caught:
        await scheduler_service.start_scheduler()
    assert caught.value.subgroup(lambda error: error is failure) is not None
    assert entered == exited
    assert len(exited) == 1
    assert scheduler_service._scheduler is None
    assert asyncio.current_task().cancelling() == 0
    assert scheduler_service._scheduler_owner is None
    isolated_scheduler.setattr(apscheduler, "AsyncScheduler", AsyncScheduler)
    await scheduler_service.start_scheduler()
    await scheduler_service.stop_scheduler()


async def test_cancelled_start_waiter_waits_for_real_context_cleanup(isolated_scheduler):
    import apscheduler

    starting = asyncio.Event()
    finish_start = asyncio.Event()
    closed = asyncio.Event()

    class SlowScheduler(AsyncScheduler):
        async def start_in_background(self):
            await super().start_in_background()
            starting.set()
            await finish_start.wait()

        async def __aexit__(self, *args):
            try:
                return await super().__aexit__(*args)
            finally:
                closed.set()

    isolated_scheduler.setattr(apscheduler, "AsyncScheduler", SlowScheduler)
    task = asyncio.create_task(scheduler_service.start_scheduler())
    await asyncio.wait_for(starting.wait(), 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert not closed.is_set()
    finish_start.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert closed.is_set()
    assert scheduler_service._scheduler is None
    assert scheduler_service._scheduler_owner is None


async def test_cancelled_stop_waiter_does_not_cancel_owner_cleanup(isolated_scheduler):
    import apscheduler

    exiting = asyncio.Event()
    finish_exit = asyncio.Event()
    closed = asyncio.Event()
    tasks = []

    class SlowExitScheduler(AsyncScheduler):
        async def __aenter__(self):
            tasks.append(asyncio.current_task())
            return await super().__aenter__()

        async def __aexit__(self, *args):
            tasks.append(asyncio.current_task())
            exiting.set()
            await finish_exit.wait()
            try:
                return await super().__aexit__(*args)
            finally:
                closed.set()

    isolated_scheduler.setattr(apscheduler, "AsyncScheduler", SlowExitScheduler)
    await scheduler_service.start_scheduler()
    stop = asyncio.create_task(scheduler_service.stop_scheduler())
    await asyncio.wait_for(exiting.wait(), 5)
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop
    assert not closed.is_set()
    assert scheduler_service._scheduler is None
    finish_exit.set()
    await asyncio.wait_for(scheduler_service.stop_scheduler(), 5)
    assert closed.is_set()
    assert tasks[0] is tasks[1]
    assert scheduler_service._scheduler_owner is None


async def test_finished_failed_stop_is_reported_without_poisoning_restart(isolated_scheduler):
    import apscheduler

    failure = ValueError("cleanup failed")

    class FailedExitScheduler(AsyncScheduler):
        async def __aexit__(self, *args):
            await super().__aexit__(*args)
            raise failure

    isolated_scheduler.setattr(apscheduler, "AsyncScheduler", FailedExitScheduler)
    await scheduler_service.start_scheduler()
    with pytest.raises(ValueError) as caught:
        await scheduler_service.stop_scheduler()
    assert caught.value is failure
    assert scheduler_service._scheduler_owner is None
    isolated_scheduler.setattr(apscheduler, "AsyncScheduler", AsyncScheduler)
    await scheduler_service.start_scheduler()
    await scheduler_service.stop_scheduler()
