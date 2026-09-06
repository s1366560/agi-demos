"""Pending effect acquisition stays owned until its resource has drained."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.tests.unit.infrastructure.plugins.v2.test_reconciler import _loader, _snapshot

pytestmark = pytest.mark.unit


@pytest.fixture
async def operation() -> AsyncIterator[OperationContextV2]:
    generation = await _loader().stage(_snapshot())
    context = OperationContextV2(
        generation=generation,
        operation_id="pending-setup-test",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    await context.__aenter__()
    try:
        yield context
    finally:
        # Error tests observe the cached disposal result explicitly in their body.
        await asyncio.gather(context.dispose(), generation.dispose(), return_exceptions=True)


async def test_dispose_waits_for_blocked_setup_and_reclaims_returned_disposer_once(
    operation,
) -> None:
    started, resume = asyncio.Event(), asyncio.Event()
    disposed: list[str] = []

    async def setup():
        started.set()
        await resume.wait()
        return lambda: disposed.append("resource")

    acquiring = asyncio.create_task(operation.effect(setup, label="blocked"))
    await asyncio.wait_for(started.wait(), 1)
    closing = asyncio.create_task(operation.dispose())
    try:
        await asyncio.sleep(0)
        assert not closing.done()
        assert disposed == []
    finally:
        resume.set()
        results = await asyncio.wait_for(
            asyncio.gather(acquiring, closing, return_exceptions=True), 1
        )
    assert not isinstance(results[1], BaseException)
    assert disposed == ["resource"]
    await operation.dispose()
    assert disposed == ["resource"]


async def test_interleaved_setups_dispose_in_actual_registration_lifo(operation) -> None:
    first_started, second_started = asyncio.Event(), asyncio.Event()
    first_resume, second_resume = asyncio.Event(), asyncio.Event()
    disposed: list[str] = []

    async def first_setup():
        first_started.set()
        await first_resume.wait()
        return lambda: disposed.append("first")

    async def second_setup():
        second_started.set()
        await second_resume.wait()
        return lambda: disposed.append("second")

    first = asyncio.create_task(operation.effect(first_setup, label="first"))
    second = asyncio.create_task(operation.effect(second_setup, label="second"))
    try:
        await asyncio.wait_for(asyncio.gather(first_started.wait(), second_started.wait()), 1)
        second_resume.set()
        await asyncio.wait_for(second, 1)
        first_resume.set()
        await asyncio.wait_for(first, 1)
        await operation.dispose()
        assert disposed == ["first", "second"]
    finally:
        first_resume.set()
        second_resume.set()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_cancelled_effect_waiter_does_not_cancel_setup_or_leak_its_resource(
    operation,
) -> None:
    started, resume, reclaimed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    setup_cancelled: list[bool] = []

    async def setup():
        started.set()
        try:
            await resume.wait()
        except asyncio.CancelledError:
            setup_cancelled.append(True)
            raise
        return reclaimed.set

    acquiring = asyncio.create_task(operation.effect(setup, label="cancelled-waiter"))
    closing = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        acquiring.cancel()
        await asyncio.sleep(0)
        assert setup_cancelled == []
        closing = asyncio.create_task(operation.dispose())
        await asyncio.sleep(0)
        assert not closing.done()
        assert not reclaimed.is_set()
    finally:
        resume.set()
        await asyncio.wait_for(asyncio.gather(acquiring, return_exceptions=True), 1)
        if closing is not None:
            await asyncio.wait_for(closing, 1)
    assert reclaimed.is_set()
    assert setup_cancelled == []
    await operation.dispose()


async def test_dispose_drains_async_iterable_late_yields(operation) -> None:
    waiting, resume = asyncio.Event(), asyncio.Event()
    disposed: list[str] = []

    async def resources():
        yield lambda: disposed.append("first")
        waiting.set()
        await resume.wait()
        yield lambda: disposed.append("late")

    acquiring = asyncio.create_task(operation.effect(resources, label="iterable"))
    await asyncio.wait_for(waiting.wait(), 1)
    closing = asyncio.create_task(operation.dispose())
    try:
        await asyncio.sleep(0)
        assert not closing.done()
    finally:
        resume.set()
        results = await asyncio.wait_for(
            asyncio.gather(acquiring, closing, return_exceptions=True), 1
        )
    assert not isinstance(results[1], BaseException)
    assert disposed == ["late", "first"]
    await operation.dispose()
    assert disposed == ["late", "first"]


async def test_inactive_context_rejects_setup_without_executing_it(operation) -> None:
    await operation.dispose()
    calls: list[str] = []

    def setup():
        calls.append("started")
        return None

    with pytest.raises(RuntimeV2Error) as error:
        await operation.effect(setup, label="late-setup")
    assert error.value.code == "inactive_effect"
    assert calls == []


async def test_delivered_setup_error_is_not_rethrown_by_dispose(operation) -> None:
    failure = ValueError("setup rejected")

    async def setup():
        raise failure

    with pytest.raises(ValueError) as error:
        await operation.effect(setup, label="delivered-error")
    assert error.value is failure
    await operation.dispose()


async def test_unobserved_setup_error_survives_cancelled_waiter_and_is_reported_on_dispose(
    operation,
) -> None:
    started, resume = asyncio.Event(), asyncio.Event()
    failure = ValueError("unobserved setup rejected")

    async def setup():
        started.set()
        await resume.wait()
        raise failure

    acquiring = asyncio.create_task(operation.effect(setup, label="unobserved-error"))
    try:
        await asyncio.wait_for(started.wait(), 1)
        acquiring.cancel()
        await asyncio.sleep(0)
    finally:
        resume.set()
        await asyncio.gather(acquiring, return_exceptions=True)
    with pytest.raises((ValueError, ExceptionGroup)) as error:
        await operation.dispose()
    errors = (
        error.value.exceptions if isinstance(error.value, BaseExceptionGroup) else (error.value,)
    )
    assert any(item is failure for item in errors)
