"""Real asyncio cancellation with exact persisted identity matching."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from src.application.services.agent.run_cancellation_signal import (
    RunCancellationIdentity,
    cancellation_requested,
    watch_run_cancellation,
)


@pytest.mark.unit
@pytest.mark.parametrize("field", ["tenant_id", "project_id", "conversation_id", "run_id"])
async def test_signal_rejects_any_different_authority(field: str) -> None:
    identity = RunCancellationIdentity(
        tenant_id="t", project_id="p", conversation_id="c", run_id="r"
    )
    store = AsyncMock()
    store.get.return_value = replace(identity, **{field: "other"}).payload().encode()
    assert not await cancellation_requested(store, identity)
    store.get.return_value = identity.payload().encode()
    assert await cancellation_requested(store, identity)


@pytest.mark.unit
async def test_cancellation_interrupts_blocked_execution_without_cancelling_sibling() -> None:
    identity = RunCancellationIdentity(
        tenant_id="t", project_id="p", conversation_id="c", run_id="r"
    )
    store = AsyncMock()
    store.get.return_value = None
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def execute() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    execution = asyncio.create_task(execute())
    sibling = asyncio.create_task(asyncio.Event().wait())
    watcher = asyncio.create_task(watch_run_cancellation(store, identity, execution))
    try:
        await started.wait()
        store.get.return_value = identity.payload()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(execution, timeout=1)
        await watcher
        assert stopped.is_set()
        assert not sibling.done()
    finally:
        watcher.cancel()
        sibling.cancel()
        await asyncio.gather(watcher, sibling, return_exceptions=True)


@pytest.mark.unit
async def test_monitor_recovers_after_signal_store_interruption() -> None:
    identity = RunCancellationIdentity(
        tenant_id="t", project_id="p", conversation_id="c", run_id="r"
    )
    store = AsyncMock()
    store.get.side_effect = [ConnectionError("offline"), identity.payload()]
    execution = asyncio.create_task(asyncio.Event().wait())
    watcher = asyncio.create_task(watch_run_cancellation(store, identity, execution))
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution, timeout=1)
    await watcher
    assert store.get.await_count == 2
