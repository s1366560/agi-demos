"""Actual Loader publications retain admission ownership until their receipt is durable."""

import asyncio
from contextlib import suppress

import pytest

from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    control_envelope_v2_to_payload,
    profile_snapshot_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.infrastructure.plugins.v2 import test_root_verified_artifacts_v2 as support

pytestmark = pytest.mark.unit
candidate = support.candidate


@pytest.mark.parametrize("accepted", [True, False])
async def test_failed_receipt_blocks_new_work_but_retains_old_lease(candidate, accepted):
    host, snapshot, archive, events, _fault = candidate
    first = await host.apply(snapshot, control_envelope_v2(snapshot, version=1))
    old_lease = await host.acquire()
    old = host.manager.current
    old_distribution = host.distribution_for_generation(old)
    newer = support._next(snapshot, 2)
    failure = OSError("receipt transaction unavailable")
    receipts = []

    async def fail(publication):
        receipts.append(publication)
        raise failure

    try:
        with pytest.raises(OSError) as caught:
            await host.apply(
                newer,
                control_envelope_v2(newer, version=2),
                verified_archives=(archive,) if accepted else (),
                receipt_persister=fail,
            )
        assert caught.value is failure
        pending = host.pending_receipt
        assert pending is receipts[0]
        assert pending.accepted is accepted
        assert pending.envelope.version == 2
        assert host.current_publication is first
        assert host.distribution_for_generation(old) is old_distribution
        if accepted:
            pending_generation = host.manager.current
            with pytest.raises(RuntimeV2Error) as pending_exact:
                await host.acquire_exact(pending_generation, pending_generation.descriptor)
            assert pending_exact.value.code == "generation_distribution_unavailable"
        with pytest.raises(RuntimeV2Error) as blocked:
            await host.acquire()
        assert blocked.value.code == "publication_receipt_pending"
        with pytest.raises(RuntimeV2Error) as blocked_apply:
            await host.apply(newer, control_envelope_v2(newer, version=3))
        assert blocked_apply.value.code == "publication_receipt_pending"
        retained = await host.acquire_exact(old, old.descriptor)
        await retained.release()
        before = tuple(events)

        async def persist(publication):
            assert publication is pending
            receipts.append(publication)

        retried = await host.retry_pending_receipt(persist)
        assert retried is pending
        assert host.pending_receipt is None
        assert tuple(events) == before
        assert receipts == [pending, pending]
        lease = await host.acquire()
        await lease.release()
    finally:
        await old_lease.release()


async def test_same_digest_ack_still_persists_without_reapplying(candidate):
    host, snapshot, _archive, events, _fault = candidate
    first = await host.apply(snapshot, control_envelope_v2(snapshot, version=1))
    generation = host.manager.current
    before = tuple(events)
    receipts = []

    async def persist(publication):
        receipts.append(publication)

    second = await host.apply(
        snapshot,
        control_envelope_v2(snapshot, version=2),
        receipt_persister=persist,
    )
    assert second.accepted and second.envelope.nonce != first.envelope.nonce
    assert receipts == [second]
    assert host.manager.current is generation
    assert tuple(events) == before
    assert host.pending_receipt is None


@pytest.mark.parametrize("retry", [False, True])
async def test_caller_cancellation_does_not_abandon_receipt_persistence(candidate, retry):
    host, snapshot, _archive, events, _fault = candidate
    entered, finish, persisted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    receipts = []

    async def persist(publication):
        receipts.append(publication)
        entered.set()
        await finish.wait()
        persisted.set()

    if retry:

        async def fail(_publication):
            raise OSError("first commit failed")

        with pytest.raises(OSError):
            await host.apply(
                snapshot, control_envelope_v2(snapshot, version=1), receipt_persister=fail
            )
        task = asyncio.create_task(host.retry_pending_receipt(persist))
    else:
        task = asyncio.create_task(
            host.apply(
                snapshot, control_envelope_v2(snapshot, version=1), receipt_persister=persist
            )
        )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        before = tuple(events)
        task.cancel()
        finish.set()
        with suppress(asyncio.CancelledError):
            await task
        # Admission waits for the same owned publication task, not a second apply.
        lease = await asyncio.wait_for(host.acquire(), 5)
        await lease.release()
        assert persisted.is_set()
        assert len(receipts) == 1 and receipts[0].accepted
        assert host.pending_receipt is None
        assert tuple(events) == before
    finally:
        finish.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_close_clears_pending_and_retry_without_receipt_rejects(candidate):
    host, snapshot, _archive, _events, _fault = candidate
    calls = []

    async def persist(publication):
        calls.append(publication)

    with pytest.raises(RuntimeV2Error) as missing:
        await host.retry_pending_receipt(persist)
    assert missing.value.code == "publication_receipt_unavailable"
    assert calls == []

    async def fail(_publication):
        raise OSError("commit failed")

    with pytest.raises(OSError):
        await host.apply(snapshot, control_envelope_v2(snapshot, version=1), receipt_persister=fail)
    assert host.pending_receipt is not None
    await host.close()
    assert host.pending_receipt is None
    assert host.current_publication is None
    assert host.manager.current is None
    with pytest.raises(RuntimeV2Error) as closed:
        await host.retry_pending_receipt(persist)
    assert closed.value.code == "publication_receipt_unavailable"
    assert calls == []


async def test_distribution_forwards_receipt_persister(candidate):
    host, snapshot, archive, _events, _fault = candidate
    envelope = control_envelope_v2(snapshot, version=1)
    receipts = []

    async def persist(publication):
        receipts.append(publication)

    publication = await host.apply_distribution(
        {
            "descriptor": {
                "profile_id": snapshot.profile_id,
                "generation": snapshot.generation,
                "digest": snapshot.digest,
            },
            "snapshot": profile_snapshot_v2_to_payload(snapshot),
            "envelope": control_envelope_v2_to_payload(envelope),
        },
        verified_archives=(archive,),
        receipt_persister=persist,
    )
    assert publication.accepted
    assert receipts == [publication]
    assert host.pending_receipt is None


async def test_same_digest_pending_preserves_durable_distribution_until_retry(candidate):
    host, snapshot, _archive, events, _fault = candidate
    first = await host.apply(snapshot, control_envelope_v2(snapshot, version=1))
    old = host.manager.current
    lease = await host.acquire()
    distribution = host.distribution_for_generation(old)
    before = tuple(events)

    async def fail(_publication):
        raise OSError("same digest receipt commit failed")

    try:
        with pytest.raises(OSError):
            await host.apply(
                snapshot, control_envelope_v2(snapshot, version=2), receipt_persister=fail
            )
        pending = host.pending_receipt
        assert pending.accepted
        assert host.manager.current is old
        assert host.current_publication is first
        assert host.distribution_for_generation(old) is distribution
        assert distribution.envelope.nonce == first.envelope.nonce
        retained = await host.acquire_exact(old, old.descriptor)
        await retained.release()

        async def persist(publication):
            assert publication is pending
            assert host.distribution_for_generation(old) is distribution

        assert await host.retry_pending_receipt(persist) is pending
        assert host.distribution_for_generation(old).envelope == pending.envelope
        assert pending.envelope.nonce != first.envelope.nonce
        assert tuple(events) == before
    finally:
        await lease.release()
