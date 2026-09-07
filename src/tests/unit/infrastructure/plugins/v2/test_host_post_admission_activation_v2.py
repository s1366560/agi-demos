"""Real Loader coverage for explicit, durable ROOT background activation."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.unit.infrastructure.plugins.v2.test_reconciler import (
    _envelope as fixture_envelope,
    _loader,
    _snapshot,
)

pytestmark = pytest.mark.unit


def snapshot(number):
    return replace(_snapshot(), generation=number + 1, digest=f"{number:064x}")


def _envelope(value, version):
    return fixture_envelope(value, version + 1)


async def enable_after_initial_publication(host, callback):
    """Establish initial authority, then observe only subsequent HMR callbacks.

    The initial callback runs for real and is recorded separately; the dedicated
    initial-enable test asserts its publication/admission behavior directly.
    """
    initial = snapshot(0)
    assert (await host.apply(initial, fixture_envelope(initial, 1))).accepted
    initial_generation = host.manager.current
    initial_activations = []

    async def dispatch(generation):
        if generation is initial_generation:
            initial_activations.append(generation)
        else:
            await callback(generation)

    await host.enable_post_admission_activation(dispatch)
    assert initial_activations == [initial_generation]


async def test_unconfigured_host_only_stages_and_publishes_until_explicit_enable():
    applied = []
    host = PlatformPluginRuntimeHostV2(loader=_loader(activations=applied))
    seen = []

    async def activate(generation):
        seen.append(generation)
        assert host.current_publication.accepted
        assert not host._receipt_blocked

    try:
        value = snapshot(1)
        assert (await host.apply(value, _envelope(value, 1))).accepted
        assert applied == ["provider", "consumer"]
        assert seen == []
        await host.enable_post_admission_activation(activate)
        assert seen == [host.manager.current]
        assert not seen[0]._disposed
    finally:
        await host.close()


async def test_hmr_persists_before_activation_and_same_generation_is_not_reactivated():
    host = PlatformPluginRuntimeHostV2(loader=_loader())
    events = []

    async def activate(generation):
        assert not host._receipt_blocked
        events.append(("activate", generation.snapshot.generation))

    async def persist(publication):
        assert host._receipt_blocked
        events.append(("persist", publication.snapshot.generation))

    try:
        await enable_after_initial_publication(host, activate)
        for number in (1, 2, 2):
            value = snapshot(number)
            assert (
                await host.apply(value, _envelope(value, number), receipt_persister=persist)
            ).accepted
        assert events == [
            ("persist", 2),
            ("activate", 2),
            ("persist", 3),
            ("activate", 3),
            ("persist", 3),
        ]
    finally:
        await host.close()


async def test_real_candidate_stage_failure_never_activates():
    disposed = []
    host = PlatformPluginRuntimeHostV2(loader=_loader(fail=True, disposals=disposed))
    seen = []

    async def activate(generation):
        seen.append(generation)

    try:
        value = snapshot(1)
        result = await host.apply(value, _envelope(value, 1))
        assert not result.accepted
        with pytest.raises(RuntimeV2Error, match="requires an accepted publication"):
            await host.enable_post_admission_activation(activate)
        assert host.manager.current is None
        assert seen == []
        assert disposed == ["provider"]
    finally:
        await host.close()


async def test_nack_retains_old_current_without_reactivating_it():
    host = PlatformPluginRuntimeHostV2(loader=_loader())
    seen = []

    async def activate(generation):
        seen.append(generation)

    try:
        await enable_after_initial_publication(host, activate)
        value = snapshot(1)
        await host.apply(value, _envelope(value, 2))
        previous = host.manager.current
        rejected = snapshot(2)
        result = await host.apply(rejected, _envelope(rejected, 1))
        assert not result.accepted
        assert host.manager.current is previous
        assert seen == [previous]
    finally:
        await host.close()


async def test_failed_receipt_stays_inactive_until_successful_retry():
    host = PlatformPluginRuntimeHostV2(loader=_loader())
    seen = []
    failure = RuntimeError("receipt transaction failed")

    async def activate(generation):
        assert not host._receipt_blocked
        seen.append(generation)

    async def fail(_publication):
        raise failure

    async def persist(publication):
        assert publication is host.pending_receipt
        assert seen == []

    try:
        await enable_after_initial_publication(host, activate)
        value = snapshot(1)
        with pytest.raises(RuntimeError) as caught:
            await host.apply(value, _envelope(value, 1), receipt_persister=fail)
        assert caught.value is failure
        assert seen == []
        assert host._receipt_blocked
        result = await host.retry_pending_receipt(persist)
        assert result.accepted
        assert seen == [host.manager.current]
        await host.apply(value, _envelope(value, 1))
        assert seen == [host.manager.current]
    finally:
        await host.close()


async def test_supersession_activates_only_after_new_receipt_commits():
    host = PlatformPluginRuntimeHostV2(loader=_loader())
    events = []

    async def activate(generation):
        events.append(("activate", generation.snapshot.generation))

    async def fail(_publication):
        raise RuntimeError("receipt transaction failed")

    async def audit(publication):
        events.append(("audit", publication.snapshot.generation))

    async def persist(publication):
        events.append(("persist", publication.snapshot.generation))

    try:
        await enable_after_initial_publication(host, activate)
        first, second = snapshot(1), snapshot(2)
        with pytest.raises(RuntimeError, match="receipt transaction failed"):
            await host.apply(first, _envelope(first, 1), receipt_persister=fail)
        pending = host.pending_receipt
        result = await host.supersede_pending(
            pending, second, _envelope(second, 2), audit_persister=audit, receipt_persister=persist
        )
        assert result.accepted
        assert events == [("audit", 2), ("persist", 3), ("activate", 3)]
    finally:
        await host.close()


async def test_cancelled_publisher_does_not_cancel_owned_activation():
    host = PlatformPluginRuntimeHostV2(loader=_loader())
    entered, resume, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen = []

    async def activate(generation):
        seen.append(generation)
        entered.set()
        await resume.wait()
        assert not generation._disposed
        completed.set()

    async def persist(_publication):
        return None

    task = None
    try:
        await enable_after_initial_publication(host, activate)
        value = snapshot(1)
        task = asyncio.create_task(
            host.apply(value, _envelope(value, 1), receipt_persister=persist)
        )
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not completed.is_set()
        assert not seen[0]._disposed
        resume.set()
        await asyncio.wait_for(completed.wait(), 2)
        async with await host.acquire() as generation:
            assert generation is seen[0]
    finally:
        resume.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await host.close()


async def test_activation_failure_fences_admission_and_retry_reuses_actual_generation():
    host = PlatformPluginRuntimeHostV2(loader=_loader())
    failure = RuntimeError("background activation failed")
    attempts = []
    persisted = []

    async def activate(generation):
        attempts.append(generation)
        if len(attempts) == 1:
            raise failure

    async def persist(publication):
        persisted.append(publication)

    try:
        await enable_after_initial_publication(host, activate)
        value = snapshot(1)
        with pytest.raises(RuntimeError) as caught:
            await host.apply(value, _envelope(value, 1), receipt_persister=persist)
        assert caught.value is failure
        generation = host.manager.current
        pending = host.pending_receipt
        assert pending.accepted
        assert generation is attempts[0]
        assert not generation._disposed
        with pytest.raises(RuntimeV2Error, match="receipt must be persisted"):
            await host.acquire()
        retried = await host.retry_pending_receipt(persist)
        assert retried is pending
        assert attempts == [generation, generation]
        assert persisted == [pending, pending]
        async with await host.acquire() as admitted:
            assert admitted is generation
        await host.apply(value, _envelope(value, 1))
        assert attempts == [generation, generation]
    finally:
        await host.close()
