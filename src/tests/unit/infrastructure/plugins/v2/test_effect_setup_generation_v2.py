"""Pending effect setup remains owned through real generation teardown."""

from __future__ import annotations

import asyncio

import pytest

from src.tests.unit.infrastructure.plugins.v2.test_publication_cancellation_v2 import _host
from src.tests.unit.infrastructure.plugins.v2.test_reconciler import _envelope, _snapshot


def _provider(disposed):
    def apply(context, _config):
        context.provide("service:clock", 7)
        return lambda: disposed.append("provider")

    return apply


@pytest.mark.unit
async def test_cancelled_stage_waits_late_setup_disposer_before_earlier_fiber_cleanup() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    disposed: list[str] = []

    async def consumer(context, _config):
        context.require("clock")

        async def setup():
            entered.set()
            await release.wait()
            return lambda: disposed.append("late-setup")

        await context.effect(setup, label="blocked-setup")

    host = _host(_provider(disposed), consumer)
    snapshot = _snapshot()
    staging = asyncio.create_task(host.apply(snapshot, _envelope(snapshot, 1)))
    await asyncio.wait_for(entered.wait(), timeout=2)
    staging.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    try:
        assert not staging.done()
        assert disposed == []
        assert host.manager.current is None
    finally:
        release.set()
        result = await asyncio.gather(staging, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert disposed == ["late-setup", "provider"]
    assert host.manager.current is None
    await host.close()


@pytest.mark.unit
async def test_active_generation_close_waits_pending_setup_and_its_late_disposer() -> None:
    contexts = []
    disposed: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    def consumer(context, _config):
        context.require("clock")
        contexts.append(context)

    host = _host(_provider(disposed), consumer)
    snapshot = _snapshot()
    await host.apply(snapshot, _envelope(snapshot, 1))
    generation = host.manager.current

    async def setup():
        entered.set()
        await release.wait()
        return lambda: disposed.append("late-setup")

    setting_up = asyncio.create_task(contexts[0].effect(setup, label="active-setup"))
    await asyncio.wait_for(entered.wait(), timeout=2)
    closing = asyncio.create_task(host.close())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    try:
        assert not closing.done()
        assert generation is not None and not generation._disposed
        assert disposed == []
    finally:
        release.set()
        outcomes = await asyncio.gather(setting_up, closing, return_exceptions=True)
    assert outcomes == [None, None]
    assert disposed == ["late-setup", "provider"]
    assert generation._disposed


@pytest.mark.unit
async def test_delivered_setup_error_stays_original_through_fiber_and_loader_cleanup() -> None:
    failure = ValueError("setup failed before returning a disposer")
    disposed: list[str] = []

    async def consumer(context, _config):
        context.require("clock")

        async def setup():
            raise failure

        await context.effect(setup, label="failed-setup")

    host = _host(_provider(disposed), consumer)
    with pytest.raises(ValueError) as error:
        await host.loader.stage(_snapshot())
    assert error.value is failure
    assert disposed == ["provider"]
    assert host.manager.current is None


@pytest.mark.unit
async def test_cancelled_setup_waiter_leaves_late_failure_owned_by_generation_disposal() -> None:
    contexts = []
    entered = asyncio.Event()
    release = asyncio.Event()
    failure = ValueError("unobserved late setup failure")
    disposed: list[str] = []

    def consumer(context, _config):
        context.require("clock")
        contexts.append(context)

    host = _host(_provider(disposed), consumer)
    snapshot = _snapshot()
    await host.apply(snapshot, _envelope(snapshot, 1))

    async def setup():
        entered.set()
        await release.wait()
        raise failure

    waiting = asyncio.create_task(contexts[0].effect(setup, label="late-failed-setup"))
    await asyncio.wait_for(entered.wait(), timeout=2)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    release.set()
    with pytest.raises(ValueError) as error:
        await host.close()
    assert error.value is failure
    assert disposed == ["provider"]


@pytest.mark.unit
async def test_async_iterable_partial_setup_failure_cleans_yielded_effect_and_preserves_error() -> (
    None
):
    failure = ValueError("async iterable failed after first effect")
    disposed: list[str] = []

    async def consumer(context, _config):
        context.require("clock")

        async def setup_results():
            yield lambda: disposed.append("yielded-effect")
            raise failure

        await context.effect(setup_results, label="partial-iterable")

    host = _host(_provider(disposed), consumer)
    with pytest.raises(ValueError) as error:
        await host.loader.stage(_snapshot())
    assert error.value is failure
    assert disposed == ["yielded-effect", "provider"]
    assert host.manager.current is None
