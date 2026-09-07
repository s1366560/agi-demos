"""Real Loader isolation and retirement checks for independent scope authorities."""

from __future__ import annotations

import asyncio

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RuntimeTestArtifactResolverV2,
)
from src.tests.unit.infrastructure.plugins.v2.test_runtime import (
    _catalog,
    _definition,
    _entry,
    _snapshot,
)

pytestmark = pytest.mark.unit
_MODULE = "test://scoped/value"
_SERVICE = "service:scoped.value"


def _scope(tenant="a", project="p", session="s"):
    return ScopeV2(
        kind=ScopeKindV2.SESSION, tenant_id=tenant, project_id=project, session_id=session
    )


def _profile(scope, generation=1, service=_SERVICE):
    return _snapshot(
        generation, (_entry("value", _MODULE, scope=scope),), provides={_MODULE: (service,)}
    )


def _registry(snapshot, apply):
    return ScopedRuntimeRegistryV2(
        (_definition(snapshot, _MODULE, apply),),
        target_catalog=_catalog(snapshot),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )


async def _publish(registry, scope, generation=1):
    snapshot = _profile(scope, generation)
    return await registry.publish(
        scope, snapshot, control_envelope_v2(snapshot, version=generation)
    )


async def test_complete_scope_identity_and_nack_are_independent():
    scopes = (_scope(), _scope("b"), _scope(project="q"), _scope(session="t"))

    seen = set()

    def apply(context, _config):
        if context.scope == scopes[0] and context.scope in seen:
            raise ValueError("candidate rejected")
        seen.add(context.scope)
        context.provide(_SERVICE, object())

    registry = _registry(_profile(scopes[0]), apply)
    try:
        for scope in scopes:
            assert (await _publish(registry, scope)).accepted
        leases = [await registry.acquire(scope) for scope in scopes]
        generations = [lease.generation for lease in leases]
        assert len({id(generation) for generation in generations}) == 4
        assert not (await _publish(registry, scopes[0], 2)).accepted
        for scope, generation in zip(scopes, generations, strict=True):
            async with await registry.acquire(scope) as current:
                assert current is generation
        for lease in leases:
            await lease.release()
        with pytest.raises(RuntimeV2Error, match="scope authority is unavailable"):
            await registry.acquire(_scope("missing"))
    finally:
        await registry.close()


@pytest.mark.parametrize("foreign", [_scope("b"), _scope(project="q"), _scope(session="t")])
async def test_foreign_scope_rejected_before_real_apply(foreign):
    calls = []
    snapshot = _profile(foreign)
    registry = _registry(snapshot, lambda *_args: calls.append(True))
    try:
        with pytest.raises(RuntimeV2Error, match="foreign scope"):
            await registry.publish(_scope(), snapshot, control_envelope_v2(snapshot, version=1))
        assert calls == []
    finally:
        await registry.close()


async def test_declared_global_route_service_is_rejected_before_apply():
    snapshot = _profile(_scope(), service=ROUTE_TABLE_BUILDER_SERVICE_V2)
    calls = []
    registry = _registry(snapshot, lambda *_args: calls.append(True))
    try:
        with pytest.raises(RuntimeV2Error, match="global HTTP routes"):
            await registry.publish(_scope(), snapshot, control_envelope_v2(snapshot, version=1))
        assert calls == []
    finally:
        await registry.close()


async def test_close_scope_retires_lease_and_explicit_publish_uses_fresh_slot():
    cleaned = []

    async def apply(context, _config):
        context.provide(_SERVICE, object())
        await context.effect(lambda: lambda: cleaned.append(True), label="cleanup")

    registry = _registry(_profile(_scope()), apply)
    assert (await _publish(registry, _scope())).accepted
    lease = await registry.acquire(_scope())
    await registry.close_scope(_scope())
    assert cleaned == []
    assert lease.generation.resolve(_SERVICE, _scope()) is not None
    assert (await _publish(registry, _scope())).accepted
    async with await registry.acquire(_scope()) as replacement:
        assert replacement is not lease.generation
    await lease.release()
    assert cleaned == [True]
    await registry.close()
    assert cleaned == [True, True]


@pytest.mark.parametrize("close_all", [False, True])
async def test_close_fences_blocked_candidate_even_if_close_waiter_cancelled(close_all):
    entered = asyncio.Event()
    finish = asyncio.Event()
    cleaned = asyncio.Event()

    async def apply(context, _config):
        async def setup():
            entered.set()
            await finish.wait()
            return cleaned.set

        await context.effect(setup, label="blocked")
        context.provide(_SERVICE, object())

    registry = _registry(_profile(_scope()), apply)
    publication = asyncio.create_task(_publish(registry, _scope()))
    await asyncio.wait_for(entered.wait(), 2)
    closing = asyncio.create_task(registry.close() if close_all else registry.close_scope(_scope()))
    await asyncio.sleep(0)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    finish.set()
    result = await asyncio.wait_for(publication, 2)
    assert not result.accepted
    await asyncio.wait_for(cleaned.wait(), 2)
    with pytest.raises(RuntimeV2Error):
        await registry.acquire(_scope())
    await asyncio.wait_for(registry.close(), 2)
    with pytest.raises(RuntimeV2Error, match="registry is closed"):
        await _publish(registry, _scope())


@pytest.mark.parametrize(
    "ancestor",
    [
        ScopeV2(kind=ScopeKindV2.ROOT),
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="a"),
        ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="a", project_id="p"),
    ],
)
async def test_ancestor_entries_are_accepted_without_ancestor_host_fallback(ancestor):
    snapshot = _profile(ancestor)

    def apply(context, _config):
        context.provide(_SERVICE, object())

    registry = _registry(snapshot, apply)
    try:
        result = await registry.publish(
            _scope(), snapshot, control_envelope_v2(snapshot, version=1)
        )
        assert result.accepted
        async with await registry.acquire(_scope()) as generation:
            assert generation.resolve(_SERVICE, _scope()) is not None
        with pytest.raises(RuntimeV2Error, match="unavailable"):
            await registry.acquire(ancestor)
    finally:
        await registry.close()


async def test_completed_scope_churn_releases_hosts_and_slots():
    import gc
    import weakref

    def apply(context, _config):
        context.provide(_SERVICE, object())

    registry = _registry(_profile(_scope()), apply)
    references = []
    for _ in range(12):
        assert (await _publish(registry, _scope())).accepted
        slot = next(iter(registry._slots.values()))
        references.extend((weakref.ref(slot), weakref.ref(slot.host)))
        del slot
        await registry.close_scope(_scope())
    await asyncio.sleep(0)
    gc.collect()
    assert all(reference() is None for reference in references)
    await registry.close()


async def test_repeated_scope_close_and_global_close_wait_for_same_pending_cleanup():
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = []

    async def apply(context, _config):
        async def cleanup():
            calls.append(True)
            started.set()
            await finish.wait()

        await context.effect(lambda: cleanup, label="blocking-close")
        context.provide(_SERVICE, object())

    registry = _registry(_profile(_scope()), apply)
    assert (await _publish(registry, _scope())).accepted
    first = asyncio.create_task(registry.close_scope(_scope()))
    await asyncio.wait_for(started.wait(), 2)
    second = asyncio.create_task(registry.close_scope(_scope()))
    all_scopes = asyncio.create_task(registry.close())
    await asyncio.sleep(0)
    assert not first.done()
    assert not second.done()
    assert not all_scopes.done()
    finish.set()
    await asyncio.wait_for(asyncio.gather(first, second, all_scopes), 2)
    assert calls == [True]


async def test_completed_retirement_failure_remains_observable_on_repeated_close():
    failure = asyncio.CancelledError("physical disposer cancellation")

    async def apply(context, _config):
        def cleanup():
            raise failure

        await context.effect(lambda: cleanup, label="failing-close")
        context.provide(_SERVICE, object())

    def contains(error):
        return error is failure or (
            isinstance(error, BaseExceptionGroup)
            and any(contains(item) for item in error.exceptions)
        )

    registry = _registry(_profile(_scope()), apply)
    assert (await _publish(registry, _scope())).accepted
    with pytest.raises(BaseException) as scope_error:
        await registry.close_scope(_scope())
    assert contains(scope_error.value)
    with pytest.raises(BaseExceptionGroup) as first:
        await registry.close()
    with pytest.raises(BaseExceptionGroup) as second:
        await registry.close()
    assert first.value is second.value
    assert contains(first.value)


async def test_scope_close_drains_other_retirements_before_reporting_first_failure():
    starts = [asyncio.Event(), asyncio.Event()]
    releases = [asyncio.Event(), asyncio.Event()]
    failure = asyncio.CancelledError("first physical retirement failed")
    applied = 0

    async def apply(context, _config):
        nonlocal applied
        index = applied
        applied += 1

        async def cleanup():
            starts[index].set()
            await releases[index].wait()
            if index == 0:
                raise failure

        await context.effect(lambda: cleanup, label="retirement")
        context.provide(_SERVICE, object())

    registry = _registry(_profile(_scope()), apply)
    assert (await _publish(registry, _scope())).accepted
    first_close = asyncio.create_task(registry.close_scope(_scope()))
    await asyncio.wait_for(starts[0].wait(), 2)
    assert (await _publish(registry, _scope())).accepted
    second_close = asyncio.create_task(registry.close_scope(_scope()))
    await asyncio.wait_for(starts[1].wait(), 2)
    releases[0].set()
    with pytest.raises(BaseExceptionGroup):
        await asyncio.wait_for(first_close, 2)
    assert not second_close.done()
    releases[1].set()
    with pytest.raises(BaseExceptionGroup):
        await asyncio.wait_for(second_close, 2)
    # Empty scope close has no pending operation; global close retains the failure.
    await registry.close_scope(_scope())
    with pytest.raises(BaseExceptionGroup) as error:
        await registry.close()

    def contains(value):
        return value is failure or (
            isinstance(value, BaseExceptionGroup)
            and any(contains(item) for item in value.exceptions)
        )

    assert contains(error.value)


async def test_bound_reservation_keeps_exact_host_after_scope_recreation():
    scope = _scope()
    registry = _registry(
        _profile(scope), lambda context, _config: context.provide(_SERVICE, object())
    )
    await _publish(registry, scope)
    original = await registry.acquire_bound(scope)
    old = original.lease.generation
    await registry.close_scope(scope)
    await _publish(registry, scope)
    replacement = await registry.acquire_bound(scope)
    assert replacement.lease.generation is not old
    assert replacement.lease.generation.descriptor == old.descriptor
    with pytest.raises(RuntimeV2Error, match="retired"):
        await original.host.acquire()
    exact = await original.host.acquire_exact(old, old.descriptor)
    assert exact.generation is old
    assert original.host.distribution_for_generation(old).descriptor == old.descriptor
    with pytest.raises(RuntimeV2Error):
        await replacement.host.acquire_exact(old, old.descriptor)
    await exact.release()
    await original.lease.release()
    with pytest.raises(RuntimeV2Error):
        await original.host.acquire_exact(old, old.descriptor)
    await replacement.lease.release()
    await registry.close()


async def test_reservation_claim_rejects_reuse_and_released_lease():
    scope = _scope()
    registry = _registry(
        _profile(scope), lambda context, _config: context.provide(_SERVICE, object())
    )
    await _publish(registry, scope)
    reservation = await registry.acquire_bound(scope)
    reservation.claim()
    with pytest.raises(RuntimeV2Error) as error:
        reservation.claim()
    assert error.value.code == "scope_reservation_consumed"
    assert not reservation.lease._released
    await reservation.lease.release()
    released = await registry.acquire_bound(scope)
    await released.lease.release()
    with pytest.raises(RuntimeV2Error) as error:
        released.claim()
    assert error.value.code == "scope_reservation_consumed"
    await registry.close()


async def test_bound_current_acquire_rechecks_retirement_after_host_lock_wait():
    scope = _scope()
    registry = _registry(
        _profile(scope), lambda context, _config: context.provide(_SERVICE, object())
    )
    await _publish(registry, scope)
    reservation = await registry.acquire_bound(scope)
    lock = reservation.host._slot.host._apply_lock
    await lock.acquire()
    acquiring = asyncio.create_task(reservation.host.acquire())
    await asyncio.sleep(0)
    closing = asyncio.create_task(registry.close_scope(scope))
    await asyncio.sleep(0)
    lock.release()
    with pytest.raises(RuntimeV2Error, match="retired"):
        await asyncio.wait_for(acquiring, 2)
    await asyncio.wait_for(closing, 2)
    assert reservation.lease.generation._lease_count == 1
    await reservation.lease.release()
    await registry.close()
