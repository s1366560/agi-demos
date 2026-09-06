"""Atomic desired-source fencing shares the receipt transaction's PostgreSQL scope lock."""

import asyncio
from contextlib import suppress
from dataclasses import replace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.marketplace_publication_receipt_v2 import (
    persist_marketplace_receipt_v2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_model_v2 import (
    PlatformPluginV2PublicationSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.integration import test_root_startup_postgres as root_support
from src.tests.unit.application.services.test_marketplace_live_requested_recovery_v2 import (
    _recovery,
)
from src.tests.unit.infrastructure.adapters.primary.web.startup.test_root_requested_restart_v2 import (
    _failed_marketplace_request,
    _state,
)

pytestmark = pytest.mark.integration
root_sessions = root_support.root_sessions
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


@pytest_asyncio.fixture(loop_scope="function")
async def pending_root(root_sessions, request):
    factory = root_sessions
    after_commit = getattr(request, "param", False)
    app = FastAPI()
    recovery = None

    class FaultSession(AsyncSession):
        async def commit(self):
            if after_commit:
                await super().commit()
            raise OSError("receipt commit response lost")

    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        await _failed_marketplace_request(factory, app, host, OSError("requested response lost"))
        recovery = _recovery(
            app,
            host,
            async_sessionmaker(factory.kw["bind"], class_=FaultSession, expire_on_commit=False),
        )
        with pytest.raises(OSError):
            await recovery.run_once()
        assert host.pending_receipt is not None and host.pending_receipt.accepted
        assert (await _state(factory))[2] == (2, 2 if after_commit else 1)
        yield app, host, factory
    finally:
        if recovery is not None:
            await recovery.stop()
        await shutdown_plugin_runtime_v2(app)


async def _advance_desired(session):
    repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
    current = (await repository.current_desired_set(ROOT)).desired_set
    desired = replace(current, revision=current.revision + 1)
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    await repository.record_desired_set(
        scope=ROOT,
        desired_set=desired,
        expected_revision=current.revision,
        actor_id="postgres-fence-writer",
    )
    await session.commit()


async def _persist(app, factory, publication):
    await persist_marketplace_receipt_v2(
        factory, publication, policy=app.state.platform_plugin_publication_policy_v2
    )


async def test_desired_commit_after_precheck_prevents_receipt_write(pending_root):
    app, host, factory = pending_root
    coordinator = app.state.platform_plugin_http_route_publication_v2
    pending = host.pending_receipt
    # The same real precheck formerly ran in its own transaction, leaving this exact gap.
    await coordinator._pending_receipt_check(pending)
    async with factory() as writer:
        await _advance_desired(writer)
    before = await _state(factory)
    with pytest.raises(RuntimeV2Error) as caught:
        await _persist(app, factory, pending)
    assert caught.value.code == "root_recovery_changed"
    assert await _state(factory) == before
    assert before[2] == (2, 1)
    assert host.pending_receipt is pending
    with pytest.raises(RuntimeV2Error) as blocked:
        await host.acquire()
    assert blocked.value.code == "publication_receipt_pending"


async def _unlocked_counts(factory):
    async with factory() as session:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (
                    PlatformPluginV2PublicationModel,
                    PlatformPluginV2ApplyStateEventModel,
                )
            ]
        )


async def _wait_for_blocker(factory, blocked_pid, blocking_pid):
    async with asyncio.timeout(10), factory() as observer:
        while True:
            blockers = await observer.scalar(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": blocked_pid}
            )
            if blocking_pid in blockers:
                return blockers
            # Each query yields to the database/event loop; no wall-time sleep proves ordering.


async def test_receipt_scope_lock_blocks_desired_cas_until_actual_commit(pending_root, monkeypatch):
    app, host, factory = pending_root
    pending = host.pending_receipt
    entered, release, writer_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    receipt_pids, writer_pids = [], []
    original = PlatformPluginRepositoryV2.record_data_plane_receipt

    async def record(repository, **kwargs):
        if kwargs["nonce"] == pending.envelope.nonce:
            receipt_pids.append(await repository._session.scalar(text("SELECT pg_backend_pid()")))
            entered.set()
            await release.wait()
        return await original(repository, **kwargs)

    monkeypatch.setattr(PlatformPluginRepositoryV2, "record_data_plane_receipt", record)

    async def receipt():
        await _persist(app, factory, pending)

    async def desired():
        async with factory() as writer:
            writer_pids.append(await writer.scalar(text("SELECT pg_backend_pid()")))
            writer_entered.set()
            await _advance_desired(writer)

    receipt_task = asyncio.create_task(receipt())
    writer_task = None
    try:
        await asyncio.wait_for(entered.wait(), 10)
        writer_task = asyncio.create_task(desired())
        await asyncio.wait_for(writer_entered.wait(), 10)
        assert receipt_pids[0] != writer_pids[0]
        blockers = await _wait_for_blocker(factory, writer_pids[0], receipt_pids[0])
        assert receipt_pids[0] in blockers
        assert not writer_task.done()
        assert await _unlocked_counts(factory) == (2, 1)
        release.set()
        await asyncio.wait_for(asyncio.gather(receipt_task, writer_task), 10)
        assert (await _state(factory))[2] == (2, 2)
    finally:
        release.set()
        for task in (receipt_task, writer_task):
            if task is not None and not task.done():
                task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(
                *[task for task in (receipt_task, writer_task) if task is not None],
                return_exceptions=True,
            )


@pytest.mark.parametrize("pending_root", [True], indirect=True)
async def test_already_durable_ack_does_not_bypass_changed_desired_on_retry(pending_root):
    app, host, factory = pending_root
    pending = host.pending_receipt
    async with factory() as writer:
        await _advance_desired(writer)
    before = await _state(factory)
    assert before[2] == (2, 2)
    # Exercise the persistence helper directly so a retained outer callback cannot hide a bypass.
    with pytest.raises(RuntimeV2Error) as caught:
        await _persist(app, factory, pending)
    assert caught.value.code == "root_recovery_changed"
    with pytest.raises(RuntimeV2Error) as retry:
        await app.state.platform_plugin_http_route_publication_v2.retry_pending_receipt(
            lambda publication: _persist(app, factory, publication)
        )
    assert retry.value.code == "root_recovery_changed"
    assert host.pending_receipt is pending
    assert await _state(factory) == before
    with pytest.raises(RuntimeV2Error) as blocked:
        await host.acquire()
    assert blocked.value.code == "publication_receipt_pending"


@pytest.mark.parametrize("fault", ["missing-binding", "policy-changed"])
async def test_atomic_receipt_fence_rejects_missing_source_or_changed_policy(pending_root, fault):
    app, host, factory = pending_root
    pending = host.pending_receipt
    policy = app.state.platform_plugin_publication_policy_v2
    if fault == "missing-binding":
        async with factory() as session:
            publication_id = await session.scalar(
                select(PlatformPluginV2PublicationModel.id).where(
                    PlatformPluginV2PublicationModel.nonce == pending.envelope.nonce
                )
            )
            # Isolated legacy-lineage fault: do not synthesize or infer the absent source.
            await session.execute(
                delete(PlatformPluginV2PublicationSourceModel).where(
                    PlatformPluginV2PublicationSourceModel.publication_id == publication_id
                )
            )
            await session.commit()
    else:
        policy = replace(policy, required_data_plane_ids=("python-api-v2", "rust-server-v2"))
    before = await _state(factory)
    with pytest.raises(RuntimeV2Error) as caught:
        await persist_marketplace_receipt_v2(factory, pending, policy=policy)
    assert caught.value.code == (
        "root_publication_source_missing"
        if fault == "missing-binding"
        else "root_recovery_policy_changed"
    )
    assert host.pending_receipt is pending
    assert await _state(factory) == before
