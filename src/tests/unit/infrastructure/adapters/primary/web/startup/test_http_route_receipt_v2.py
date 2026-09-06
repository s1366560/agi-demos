"""Real route coordination with injectable durable receipt transaction outcomes."""

import asyncio
from contextlib import suppress
from dataclasses import replace

import pytest

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.infrastructure.adapters.primary.web.startup.test_http_route_publication_v2 import (
    _coordinator,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def routes():
    app, coordinator = await _coordinator()
    try:
        yield app, coordinator, app.state.platform_plugin_runtime_v2
    finally:
        await shutdown_plugin_runtime_v2(app)


def _next(host, *, nack=False):
    current = host.current_distribution
    entries = tuple(
        replace(entry, enabled=False)
        if nack and entry.entry_id == "builtin-billing-http-routes"
        else entry
        for entry in current.snapshot.entries
    )
    snapshot = compose_profile_v2(
        ProfileDocumentV2(profile_id=current.snapshot.profile_id, entries=entries),
        {manifest.plugin_id: manifest for manifest in current.snapshot.manifests},
        generation=current.snapshot.generation + 1,
    )
    return snapshot, control_envelope_v2(snapshot, version=current.envelope.version + 1)


async def test_same_digest_reuses_exact_startup_graph(routes):
    app, coordinator, host = routes
    current = host.current_distribution
    graph = app.state.platform_plugin_route_graph_v2
    registry = app.state.platform_plugin_route_registry_v2
    route = registry.current
    receipts = []

    async def persist(publication):
        receipts.append(publication)

    result = await coordinator.publish_snapshot(
        current.snapshot,
        control_envelope_v2(current.snapshot, version=current.envelope.version + 1),
        receipt_persister=persist,
    )
    assert result.plugin_publication.accepted
    assert result.graph is graph
    assert result.route_publication is route is registry.current
    assert receipts == [result.plugin_publication]


@pytest.mark.parametrize("nack", [False, True])
async def test_receipt_failure_retry_preserves_routes_and_defers_callback(routes, nack):
    app, coordinator, host = routes
    registry = app.state.platform_plugin_route_registry_v2
    old_routes = registry.current
    old_lease = await host.acquire()
    snapshot, envelope = _next(host, nack=nack)
    callbacks, receipts = [], []
    failure = OSError("receipt persistence failed")

    async def fail(publication):
        receipts.append(publication)
        raise failure

    try:
        with pytest.raises(OSError) as caught:
            await coordinator.publish_snapshot(
                snapshot, envelope, receipt_persister=fail, on_commit=callbacks.append
            )
        assert caught.value is failure
        pending = host.pending_receipt
        assert pending is receipts[0]
        assert pending.accepted is not nack
        assert callbacks == []
        committed_routes = registry.current
        if nack:
            assert committed_routes is old_routes
        else:
            assert committed_routes is not old_routes
        with pytest.raises(RuntimeV2Error) as blocked:
            await host.acquire()
        assert blocked.value.code == "publication_receipt_pending"

        async def persist(publication):
            assert publication is pending
            assert callbacks == []
            receipts.append(publication)

        result = await coordinator.retry_pending_receipt(persist)
        assert result.plugin_publication is pending
        assert registry.current is committed_routes
        assert receipts == [pending, pending]
        assert host.pending_receipt is None
        if nack:
            assert result.graph is None and result.route_publication is None
            assert callbacks == []
        else:
            assert result.route_publication is committed_routes
            assert result.graph.table is committed_routes.table
            assert callbacks == [result.graph]
    finally:
        await old_lease.release()


async def test_cancelled_caller_retains_owned_persistence_and_commit(routes):
    _app, coordinator, host = routes
    entered, finish = asyncio.Event(), asyncio.Event()
    order = []
    snapshot, envelope = _next(host)

    async def persist(_publication):
        entered.set()
        await finish.wait()
        order.append("persisted")

    task = asyncio.create_task(
        coordinator.publish_snapshot(
            snapshot,
            envelope,
            receipt_persister=persist,
            on_commit=lambda _graph: order.append("committed"),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 30)
        task.cancel()
        finish.set()
        with suppress(asyncio.CancelledError):
            await task
        lease = await asyncio.wait_for(host.acquire(), 5)
        await lease.release()
        assert order == ["persisted", "committed"]
        assert host.pending_receipt is None
    finally:
        finish.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_retryable_commit_callback_failure_preserves_pending_result(routes):
    app, coordinator, host = routes
    snapshot, envelope = _next(host)
    persisted, callbacks = [], []
    failure = RuntimeError("application graph synchronization failed")

    async def persist(publication):
        persisted.append(publication)

    def commit(graph):
        # This explicit callback is retryable; the first attempt changes no application state.
        callbacks.append(graph)
        if len(callbacks) == 1:
            raise failure

    with pytest.raises(RuntimeError) as caught:
        await coordinator.publish_snapshot(
            snapshot, envelope, receipt_persister=persist, on_commit=commit
        )
    assert caught.value is failure
    pending = host.pending_receipt
    assert pending is persisted[0] and pending.accepted
    route = app.state.platform_plugin_route_registry_v2.current
    result = await coordinator.retry_pending_receipt(persist)
    assert result.plugin_publication is pending
    assert result.route_publication is route
    assert callbacks == [result.graph, result.graph]
    assert host.pending_receipt is None


async def test_same_digest_mismatched_graph_table_fails_closed(routes):
    app, coordinator, host = routes
    current = host.current_distribution
    graph = app.state.platform_plugin_route_graph_v2
    coordinator._graph = replace(graph, table=object())
    receipts = []

    async def persist(publication):
        receipts.append(publication)

    with pytest.raises(RuntimeV2Error) as caught:
        await coordinator.publish_snapshot(
            current.snapshot,
            control_envelope_v2(current.snapshot, version=current.envelope.version + 1),
            receipt_persister=persist,
        )
    assert caught.value.code == "route_publication_unavailable"
    assert receipts == []
    assert host.pending_receipt is not None
    with pytest.raises(RuntimeV2Error) as blocked:
        await host.acquire()
    assert blocked.value.code == "publication_receipt_pending"


async def test_persister_self_cancellation_preserves_actual_pending_for_retry(routes):
    _app, coordinator, host = routes
    snapshot, envelope = _next(host)
    callbacks = []

    async def cancel(_publication):
        raise asyncio.CancelledError("database transaction cancelled")

    with pytest.raises(asyncio.CancelledError):
        await coordinator.publish_snapshot(
            snapshot, envelope, receipt_persister=cancel, on_commit=callbacks.append
        )
    pending = host.pending_receipt
    assert pending is not None and pending.accepted
    assert callbacks == []

    async def persist(publication):
        assert publication is pending

    result = await coordinator.retry_pending_receipt(persist)
    assert result.plugin_publication is pending
    assert callbacks == [result.graph]
    assert host.pending_receipt is None
