"""Route supersession preserves actual pending results until an acknowledged replacement."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.infrastructure.adapters.primary.web.startup import (
    test_http_route_receipt_v2 as support,
)

pytestmark = pytest.mark.unit
routes = support.routes


@pytest.fixture
async def pending(routes):
    app, coordinator, host = routes
    snapshot, envelope = support._next(host)
    with pytest.raises(OSError):
        await coordinator.publish_snapshot(
            snapshot,
            envelope,
            receipt_persister=AsyncMock(side_effect=OSError("old receipt failed")),
        )
    yield app, coordinator, host, host.pending_receipt


def _successor(previous, offset=1):
    from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2

    snapshot = compose_profile_v2(
        ProfileDocumentV2(
            profile_id=previous.snapshot.profile_id, entries=previous.snapshot.entries
        ),
        {manifest.plugin_id: manifest for manifest in previous.snapshot.manifests},
        generation=previous.snapshot.generation + offset,
    )
    return snapshot, control_envelope_v2(snapshot, version=previous.envelope.version + offset)


async def test_ack_supersession_publishes_exact_routes_and_graph_callback(pending):
    app, coordinator, host, previous = pending
    snapshot, envelope = _successor(previous)
    old_routes = app.state.platform_plugin_route_registry_v2.current
    audits, callbacks = [], []

    async def audit(publication):
        assert publication is previous
        audits.append(publication)

    result = await coordinator.supersede_pending(
        previous,
        snapshot,
        envelope,
        audit_persister=audit,
        receipt_persister=AsyncMock(),
        on_commit=callbacks.append,
    )
    assert result.plugin_publication.accepted
    assert result.route_publication is app.state.platform_plugin_route_registry_v2.current
    assert result.route_publication is not old_routes
    assert result.graph.table is result.route_publication.table
    assert callbacks == [result.graph] and audits == [previous]
    assert host.current_publication is result.plugin_publication
    assert host.pending_receipt is None
    lease = await host.acquire()
    await lease.release()


async def test_nack_retains_pending_cache_without_callback_until_higher_ack(pending):
    app, coordinator, host, previous = pending
    snapshot, envelope = _successor(previous)
    routes_before = app.state.platform_plugin_route_registry_v2.current
    persisted, callbacks, audits = [], [], []

    async def persist(publication):
        persisted.append(publication)

    async def audit(publication):
        audits.append(publication)

    with pytest.raises(RuntimeV2Error) as caught:
        await coordinator.supersede_pending(
            previous,
            snapshot,
            envelope,
            verified_archives=(),
            audit_persister=audit,
            receipt_persister=persist,
            on_commit=callbacks.append,
        )
    assert caught.value.code == "publication_supersession_nack"
    nack = host.pending_receipt
    assert nack is persisted[0] and not nack.accepted
    assert coordinator._pending.plugin_publication is nack
    assert callbacks == []
    assert app.state.platform_plugin_route_registry_v2.current is routes_before
    forbidden = AsyncMock()
    with pytest.raises(RuntimeV2Error) as retry:
        await coordinator.retry_pending_receipt(forbidden)
    assert retry.value.code == "publication_supersession_nack"
    forbidden.assert_not_awaited()
    assert coordinator._pending.plugin_publication is nack
    snapshot, envelope = _successor(nack)
    result = await coordinator.supersede_pending(
        nack,
        snapshot,
        envelope,
        audit_persister=audit,
        receipt_persister=persist,
        on_commit=callbacks.append,
    )
    assert result.plugin_publication.accepted
    assert audits == [previous, nack]
    assert callbacks == [result.graph]
    assert host.pending_receipt is None and not host.pending_requires_ack


async def test_audit_failure_preserves_original_route_cache(pending, monkeypatch):
    app, coordinator, host, previous = pending
    cached = coordinator._pending
    route = app.state.platform_plugin_route_registry_v2.current
    apply = AsyncMock(wraps=host.reconciler.apply)
    monkeypatch.setattr(host.reconciler, "apply", apply)
    snapshot, envelope = _successor(previous)
    failure = OSError("audit unavailable")
    with pytest.raises(OSError) as caught:
        await coordinator.supersede_pending(
            previous,
            snapshot,
            envelope,
            audit_persister=AsyncMock(side_effect=failure),
            receipt_persister=AsyncMock(),
        )
    assert caught.value is failure
    assert coordinator._pending is cached
    assert host.pending_receipt is previous
    assert app.state.platform_plugin_route_registry_v2.current is route
    apply.assert_not_awaited()


async def test_ack_receipt_retry_keeps_same_graph_without_restaging(pending, monkeypatch):
    app, coordinator, host, previous = pending
    apply = AsyncMock(wraps=host.reconciler.apply)
    monkeypatch.setattr(host.reconciler, "apply", apply)
    snapshot, envelope = _successor(previous)
    callbacks = []
    with pytest.raises(OSError):
        await coordinator.supersede_pending(
            previous,
            snapshot,
            envelope,
            audit_persister=AsyncMock(),
            receipt_persister=AsyncMock(side_effect=OSError("new ACK receipt unavailable")),
            on_commit=callbacks.append,
        )
    pending_result = coordinator._pending
    route = app.state.platform_plugin_route_registry_v2.current
    assert pending_result.plugin_publication is host.pending_receipt
    assert callbacks == []
    result = await coordinator.retry_pending_receipt(AsyncMock())
    assert result is pending_result
    assert result.route_publication is route
    assert result.graph.table is route.table
    assert callbacks == [result.graph]
    assert apply.await_count == 1


async def test_pre_apply_check_holds_coordinator_lock_and_failure_never_applies(
    pending, monkeypatch
):
    _app, coordinator, host, previous = pending
    snapshot, envelope = _successor(previous)
    apply = AsyncMock(wraps=host.reconciler.apply)
    monkeypatch.setattr(host.reconciler, "apply", apply)
    checked = []
    audit = AsyncMock()

    async def check():
        assert coordinator._lock.locked()
        checked.append(True)
        raise RuntimeV2Error("root_recovery_changed", "request superseded")

    with pytest.raises(RuntimeV2Error) as caught:
        await coordinator.supersede_pending(
            previous,
            snapshot,
            envelope,
            audit_persister=audit,
            receipt_persister=AsyncMock(),
            pre_apply_check=check,
        )
    assert caught.value.code == "root_recovery_changed"
    assert checked == [True]
    audit.assert_not_awaited()
    apply.assert_not_awaited()
    assert host.pending_receipt is previous


async def test_foreground_winner_prevents_old_pending_from_applying_again(pending, monkeypatch):
    _app, coordinator, host, previous = pending
    snapshot, envelope = _successor(previous)
    winner = await coordinator.supersede_pending(
        previous,
        snapshot,
        envelope,
        audit_persister=AsyncMock(),
        receipt_persister=AsyncMock(),
    )
    apply = AsyncMock(wraps=host.reconciler.apply)
    monkeypatch.setattr(host.reconciler, "apply", apply)
    with pytest.raises(RuntimeV2Error) as caught:
        await coordinator.supersede_pending(
            previous,
            snapshot,
            envelope,
            audit_persister=AsyncMock(),
            receipt_persister=AsyncMock(),
        )
    assert caught.value.code == "route_receipt_mismatch"
    apply.assert_not_awaited()
    assert host.current_publication is winner.plugin_publication
    assert host.pending_receipt is None
