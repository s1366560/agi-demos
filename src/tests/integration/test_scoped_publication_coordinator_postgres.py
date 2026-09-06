"""Real PostgreSQL transaction failures around real scoped Loader activation."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
from src.tests.integration.test_platform_plugin_scoped_ledger_postgres import sessions  # noqa: F401
from src.tests.unit.infrastructure.plugins.v2.test_scoped_runtime_registry import (
    _SERVICE,
    _profile,
    _registry,
    _scope,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("after_commit", [False, True])
async def test_receipt_commit_failure_blocks_admission_and_retry_does_not_apply(
    sessions,  # noqa: F811
    after_commit,
):
    calls = []
    scope = _scope(tenant=uuid4().hex)
    snapshot = _profile(scope)

    def apply(context, _config):
        calls.append(context.scope)
        context.provide(_SERVICE, object())

    class FaultSession(AsyncSession):
        commits = 0

        async def commit(self):
            type(self).commits += 1
            if type(self).commits == 2:
                if after_commit:
                    await super().commit()
                raise OSError("injected receipt commit failure")
            await super().commit()

    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=async_sessionmaker(
            sessions.kw["bind"], class_=FaultSession, expire_on_commit=False
        ),
        registry=_registry(snapshot, apply),
    )
    try:
        with pytest.raises(OSError, match="injected receipt"):
            await coordinator.publish(scope, snapshot)
        assert len(calls) == 1
        with pytest.raises(RuntimeV2Error):
            await coordinator.acquire(scope)
        publication = await coordinator.retry_receipt(scope)
        assert publication.accepted
        assert len(calls) == 1
        async with await coordinator.acquire(scope) as generation:
            assert generation.descriptor.digest == snapshot.digest
        async with sessions() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(PlatformPluginV2ApplyStateEventModel)
                .where(PlatformPluginV2ApplyStateEventModel.requested_digest == snapshot.digest)
            )
            assert count == 1
    finally:
        await coordinator.close()


async def test_requested_commit_failure_never_applies_candidate(sessions):  # noqa: F811
    calls = []
    scope = _scope(tenant=uuid4().hex)
    snapshot = _profile(scope)

    class FaultSession(AsyncSession):
        async def commit(self):
            raise OSError("injected requested commit failure")

    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=async_sessionmaker(
            sessions.kw["bind"], class_=FaultSession, expire_on_commit=False
        ),
        registry=_registry(snapshot, lambda *_: calls.append(True)),
    )
    try:
        with pytest.raises(OSError, match="injected requested"):
            await coordinator.publish(scope, snapshot)
        assert calls == []
        with pytest.raises(RuntimeV2Error):
            await coordinator.acquire(scope)
    finally:
        await coordinator.close()


async def test_requested_commit_failure_preserves_previous_admitted_generation(sessions):  # noqa: F811
    calls = []
    scope = _scope(tenant=uuid4().hex)
    snapshot = _profile(scope)

    def apply(context, _config):
        calls.append(True)
        context.provide(_SERVICE, object())

    class FaultSession(AsyncSession):
        fail = False

        async def commit(self):
            if type(self).fail:
                type(self).fail = False
                raise OSError("injected requested replacement failure")
            await super().commit()

    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=async_sessionmaker(
            sessions.kw["bind"], class_=FaultSession, expire_on_commit=False
        ),
        registry=_registry(snapshot, apply),
    )
    try:
        await coordinator.publish(scope, snapshot)
        old = await coordinator.acquire(scope)
        try:
            FaultSession.fail = True
            with pytest.raises(OSError, match="injected requested replacement"):
                await coordinator.publish(scope, _profile(scope, generation=2))
            assert len(calls) == 1
            async with await coordinator.acquire(scope) as current:
                assert current is old.generation
        finally:
            await old.release()
    finally:
        await coordinator.close()


async def test_other_process_supersedes_receipt_and_explicit_publish_recovers(sessions):  # noqa: F811
    scope = _scope(tenant=uuid4().hex)
    snapshot = _profile(scope)
    entered, resume = asyncio.Event(), asyncio.Event()

    async def slow_apply(context, _config):
        entered.set()
        await resume.wait()
        context.provide(_SERVICE, object())

    def apply(context, _config):
        context.provide(_SERVICE, object())

    first = ScopedPublicationCoordinatorV2(
        session_factory=sessions, registry=_registry(snapshot, slow_apply)
    )
    second = ScopedPublicationCoordinatorV2(
        session_factory=sessions, registry=_registry(snapshot, apply)
    )
    pending = asyncio.create_task(first.publish(scope, snapshot))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        newer = await second.publish(scope, snapshot)
        assert newer.accepted
        resume.set()
        with pytest.raises(PlatformPluginLedgerV2Error) as caught:
            await asyncio.wait_for(pending, 5)
        assert caught.value.code == "stale_receipt"
        with pytest.raises(RuntimeV2Error):
            await first.acquire(scope)
        restored = await first.publish(scope, _profile(scope, generation=2))
        assert restored.accepted
        assert restored.envelope.version > newer.envelope.version
        async with await first.acquire(scope):
            pass
        with pytest.raises(RuntimeV2Error, match="durable scope identity changed"):
            await second.acquire(scope)
    finally:
        resume.set()
        await asyncio.gather(pending, return_exceptions=True)
        await first.close()
        await second.close()


async def test_same_digest_fast_ack_still_requires_its_new_durable_receipt(sessions):  # noqa: F811
    calls = []
    scope = _scope(tenant=uuid4().hex)
    snapshot = _profile(scope)

    def apply(context, _config):
        calls.append(True)
        context.provide(_SERVICE, object())

    class FaultSession(AsyncSession):
        commits = 0

        async def commit(self):
            type(self).commits += 1
            if type(self).commits == 4:
                raise OSError("same digest receipt failure")
            await super().commit()

    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=async_sessionmaker(
            sessions.kw["bind"], class_=FaultSession, expire_on_commit=False
        ),
        registry=_registry(snapshot, apply),
    )
    try:
        first = await coordinator.publish(scope, snapshot)
        with pytest.raises(OSError, match="same digest receipt"):
            await coordinator.publish(scope, snapshot)
        assert len(calls) == 1
        with pytest.raises(RuntimeV2Error):
            await coordinator.acquire(scope)
        second = await coordinator.retry_receipt(scope)
        assert second.envelope.version > first.envelope.version
        assert second.envelope.nonce != first.envelope.nonce
        assert second.snapshot.digest == first.snapshot.digest
        async with await coordinator.acquire(scope):
            pass
        assert len(calls) == 1
    finally:
        await coordinator.close()
