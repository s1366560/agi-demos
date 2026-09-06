"""Real Loader and SQL tests for request/apply/receipt admission ordering."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
from src.tests.unit.infrastructure.plugins.v2.test_scoped_runtime_registry import (
    _SERVICE,
    _profile,
    _registry,
    _scope,
)

pytestmark = pytest.mark.unit


async def test_cancelled_publish_waiter_keeps_apply_and_close_owned(db_session):
    entered, release = asyncio.Event(), asyncio.Event()
    scope = _scope()

    async def apply(context, _config):
        entered.set()
        await release.wait()
        context.provide(_SERVICE, object())

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=factory, registry=_registry(_profile(scope), apply)
    )
    publishing = asyncio.create_task(coordinator.publish(scope, _profile(scope)))
    await asyncio.wait_for(entered.wait(), 2)
    publishing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await publishing
    closing = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0)
    assert not closing.done()
    with pytest.raises(RuntimeV2Error, match="coordinator is closed"):
        await coordinator.acquire(scope)
    release.set()
    await asyncio.wait_for(closing, 2)
    async with factory() as session:
        assert (
            await PlatformPluginRepositoryV2(session, scope=scope).last_good_distribution(
                "python-api-v2"
            )
            is not None
        )


async def test_nack_retains_locally_admitted_generation_and_scope_isolation(db_session):
    scope = _scope()
    calls = []

    def apply(context, _config):
        calls.append(context.scope)
        if len(calls) > 1:
            raise ValueError("candidate failure")
        context.provide(_SERVICE, object())

    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=async_sessionmaker(db_session.bind, expire_on_commit=False),
        registry=_registry(_profile(scope), apply),
    )
    try:
        assert (await coordinator.publish(scope, _profile(scope))).accepted
        old = await coordinator.acquire(scope)
        assert not (await coordinator.publish(scope, _profile(scope, 2))).accepted
        current = await coordinator.acquire(scope)
        assert current.generation is old.generation
        await current.release()
        await old.release()
        with pytest.raises(RuntimeV2Error, match="durable local admission"):
            await coordinator.acquire(_scope(tenant="other"))
    finally:
        await coordinator.close()


async def test_receipt_commit_failure_retry_does_not_reapply(db_session):
    scope = _scope()
    calls = []

    class FaultSession(AsyncSession):
        commits = 0

        async def commit(self):
            type(self).commits += 1
            if type(self).commits == 2:
                raise RuntimeError("receipt commit failed")
            await super().commit()

    def apply(context, _config):
        calls.append(context.scope)
        context.provide(_SERVICE, object())

    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=async_sessionmaker(
            db_session.bind, class_=FaultSession, expire_on_commit=False
        ),
        registry=_registry(_profile(scope), apply),
    )
    try:
        with pytest.raises(RuntimeError, match="receipt commit failed"):
            await coordinator.publish(scope, _profile(scope))
        with pytest.raises(RuntimeV2Error, match="durable local admission"):
            await coordinator.acquire(scope)
        assert (await coordinator.retry_receipt(scope)).accepted
        assert len(calls) == 1
        await (await coordinator.acquire(scope)).release()
    finally:
        await coordinator.close()


async def test_remote_new_request_blocks_local_acquisition(db_session):
    scope = _scope()

    def apply(context, _config):
        context.provide(_SERVICE, object())

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=factory, registry=_registry(_profile(scope), apply)
    )
    try:
        await coordinator.publish(scope, _profile(scope))
        from src.infrastructure.plugins.v2.protocol import control_envelope_v2

        async with factory() as session:
            repo = PlatformPluginRepositoryV2(session, scope=scope)
            version = await repo.allocate_publication_version()
            snapshot = _profile(scope, 2)
            await repo.record_requested_distribution(
                snapshot, control_envelope_v2(snapshot, version=version)
            )
            await session.commit()
        with pytest.raises(RuntimeV2Error, match="durable scope identity changed"):
            await coordinator.acquire(scope)
    finally:
        await coordinator.close()
