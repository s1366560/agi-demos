"""Host supersession journals real outcomes and requires an ACK before reopening admission."""

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.infrastructure.plugins.v2 import test_root_verified_artifacts_v2 as support

pytestmark = pytest.mark.unit
candidate = support.candidate


@pytest.fixture
async def pending(candidate, request):
    host, snapshot, archive, _events, _fault = candidate
    await host.apply(snapshot, control_envelope_v2(snapshot, version=1))
    lease = await host.acquire()
    old = host.manager.current
    second = support._next(snapshot, 2)

    async def fail(_publication):
        raise OSError("old receipt unavailable")

    try:
        with pytest.raises(OSError):
            await host.apply(
                second,
                control_envelope_v2(second, version=2),
                verified_archives=() if getattr(request, "param", "ACK") == "NACK" else (archive,),
                receipt_persister=fail,
            )
        yield host, second, archive, host.pending_receipt, lease, old
    finally:
        await lease.release()


async def _blocked(host):
    with pytest.raises(RuntimeV2Error) as caught:
        await host.acquire()
    assert caught.value.code == "publication_receipt_pending"


@pytest.mark.parametrize("pending", ["ACK", "NACK"], indirect=True)
async def test_superseding_real_pending_with_ack_preserves_old_exact_lease(pending):
    host, snapshot, archive, previous, _lease, old = pending
    next_snapshot = support._next(snapshot, 3)
    order = []

    async def audit(publication):
        assert publication is previous
        assert host.pending_receipt is previous
        order.append("audit")

    async def persist(publication):
        assert publication.accepted
        assert order == ["audit"]
        order.append("receipt")

    result = await host.supersede_pending(
        previous,
        next_snapshot,
        control_envelope_v2(next_snapshot, version=3),
        audit_persister=audit,
        receipt_persister=persist,
        verified_archives=(archive,),
    )
    assert result.accepted
    assert order == ["audit", "receipt"]
    assert host.pending_receipt is None and not host.pending_requires_ack
    assert host.current_publication is result
    retained = await host.acquire_exact(old, old.descriptor)
    await retained.release()
    current = await host.acquire()
    await current.release()


@pytest.mark.parametrize("after", [False, True])
async def test_audit_fault_retains_previous_outcome_and_never_applies(pending, monkeypatch, after):
    host, snapshot, archive, previous, _lease, _old = pending
    apply = AsyncMock(wraps=host.reconciler.apply)
    monkeypatch.setattr(host.reconciler, "apply", apply)
    audit_commits = []
    failure = OSError("audit acknowledgement lost")

    async def audit(publication):
        assert publication is previous
        if after:
            audit_commits.append(publication)
        raise failure

    persist = AsyncMock()
    newer = support._next(snapshot, 3)
    with pytest.raises(OSError) as caught:
        await host.supersede_pending(
            previous,
            newer,
            control_envelope_v2(newer, version=3),
            audit_persister=audit,
            receipt_persister=persist,
            verified_archives=(archive,),
        )
    assert caught.value is failure
    assert audit_commits == ([previous] if after else [])
    assert host.pending_receipt is previous
    apply.assert_not_awaited()
    persist.assert_not_awaited()
    await _blocked(host)


@pytest.mark.parametrize("receipt_fails", [False, True])
async def test_supersession_nack_stays_blocked_until_a_higher_ack(pending, receipt_fails):
    host, snapshot, archive, previous, _lease, _old = pending
    third = support._next(snapshot, 3)
    failure = OSError("new NACK receipt unavailable")
    audits, receipts = [], []

    async def audit(publication):
        audits.append(publication)

    async def persist(publication):
        receipts.append(publication)
        if receipt_fails:
            raise failure

    with pytest.raises((OSError, RuntimeV2Error)) as caught:
        await host.supersede_pending(
            previous,
            third,
            control_envelope_v2(third, version=3),
            audit_persister=audit,
            receipt_persister=persist,
            verified_archives=(),
        )
    if receipt_fails:
        assert caught.value is failure
    else:
        assert caught.value.code == "publication_supersession_nack"
    nack = host.pending_receipt
    assert nack is receipts[0] and not nack.accepted
    assert host.pending_requires_ack
    await _blocked(host)
    forbidden = AsyncMock()
    with pytest.raises(RuntimeV2Error) as retry:
        await host.retry_pending_receipt(forbidden)
    assert retry.value.code == "publication_supersession_nack"
    forbidden.assert_not_awaited()
    fourth = support._next(snapshot, 4)
    result = await host.supersede_pending(
        nack,
        fourth,
        control_envelope_v2(fourth, version=4),
        audit_persister=audit,
        receipt_persister=AsyncMock(),
        verified_archives=(archive,),
    )
    assert result.accepted
    assert audits == [previous, nack]
    assert host.pending_receipt is None and not host.pending_requires_ack
    lease = await host.acquire()
    await lease.release()


async def test_ack_receipt_failure_retries_without_reapplying(pending, monkeypatch):
    host, snapshot, archive, previous, _lease, _old = pending
    apply = AsyncMock(wraps=host.reconciler.apply)
    monkeypatch.setattr(host.reconciler, "apply", apply)
    third = support._next(snapshot, 3)
    with pytest.raises(OSError):
        await host.supersede_pending(
            previous,
            third,
            control_envelope_v2(third, version=3),
            audit_persister=AsyncMock(),
            receipt_persister=AsyncMock(side_effect=OSError("ACK receipt fault")),
            verified_archives=(archive,),
        )
    ack = host.pending_receipt
    assert ack.accepted
    await _blocked(host)
    assert await host.retry_pending_receipt(AsyncMock()) is ack
    assert apply.await_count == 1
    assert host.current_publication is ack and host.pending_receipt is None


@pytest.mark.parametrize("cancel_waiter", [False, True])
async def test_supersession_and_close_drain_persistence_through_caller_cancellation(
    pending, cancel_waiter
):
    host, snapshot, archive, previous, old_lease, _old = pending
    await old_lease.release()
    entered, finish, close_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    persisted = []

    async def persist(publication):
        entered.set()
        await finish.wait()
        persisted.append(publication)

    async def close():
        close_entered.set()
        await host.close()

    newer = support._next(snapshot, 3)
    task = asyncio.create_task(
        host.supersede_pending(
            previous,
            newer,
            control_envelope_v2(newer, version=3),
            audit_persister=AsyncMock(),
            receipt_persister=persist,
            verified_archives=(archive,),
        )
    )
    closer = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if cancel_waiter:
            task.cancel()
        closer = asyncio.create_task(close())
        await close_entered.wait()
        assert not closer.done() and persisted == []
        finish.set()
        with suppress(asyncio.CancelledError):
            await task
        await asyncio.wait_for(closer, 5)
        assert len(persisted) == 1 and persisted[0].accepted
        assert host.manager.current is None
    finally:
        finish.set()
        await asyncio.gather(
            *[item for item in (task, closer) if item is not None], return_exceptions=True
        )


@pytest.mark.parametrize("fault", ["identity", "version"])
async def test_supersession_rejects_wrong_pending_or_nonincreasing_version(pending, fault):
    host, snapshot, _archive, previous, _lease, _old = pending
    from dataclasses import replace

    expected = replace(previous) if fault == "identity" else previous
    audit, persist = AsyncMock(), AsyncMock()
    with pytest.raises(RuntimeV2Error) as caught:
        await host.supersede_pending(
            expected,
            snapshot,
            control_envelope_v2(snapshot, version=3 if fault == "identity" else 2),
            audit_persister=audit,
            receipt_persister=persist,
        )
    assert caught.value.code == (
        "publication_receipt_mismatch"
        if fault == "identity"
        else "publication_supersession_not_newer"
    )
    audit.assert_not_awaited()
    persist.assert_not_awaited()
    assert host.pending_receipt is previous
    await _blocked(host)
