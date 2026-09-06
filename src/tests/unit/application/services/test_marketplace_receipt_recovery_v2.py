"""Supervised recovery persists real pending marketplace receipts without reapplying."""

import asyncio

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.marketplace_receipt_recovery_v2 import MarketplaceReceiptRecoveryV2
from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_outcome_supersession_model_v2 import (
    PlatformPluginV2OutcomeSupersessionModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.application.services.test_marketplace_verified_execution_v2 import (
    _NoExternalArtifactClient,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def pending_marketplace(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    completed = asyncio.Event()

    class FailedReceiptSession(AsyncSession):
        async def commit(self):
            raise OSError("receipt store temporarily unavailable")

    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        coordinator = app.state.platform_plugin_http_route_publication_v2
        policy = app.state.platform_plugin_publication_policy_v2
        async with factory() as mutation:
            service = PluginMarketplacePublicationServiceV2(
                mutation_session=mutation,
                receipt_session_factory=async_sessionmaker(
                    db_session.bind, class_=FailedReceiptSession, expire_on_commit=False
                ),
                desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(mutation),
                source_repository=PlatformPluginProfileSourceRepositoryV2(mutation),
                governance_repository=PlatformPluginGovernanceRepository(mutation),
                publication_repository=PlatformPluginRepositoryV2(mutation),
                artifact_client=_NoExternalArtifactClient(),
                production_sources=production_bundle_sources_v2(),
                trusted_public_keys=(),
                allowed_registries=frozenset(),
                host=host,
                route_coordinator=coordinator,
                publication_policy=policy,
                on_route_commit=lambda _graph: completed.set(),
            )
            with pytest.raises(OSError):
                await service.publish_current()
        assert host.pending_receipt is not None
        yield app, host, coordinator, factory, policy, completed
    finally:
        await shutdown_plugin_runtime_v2(app)


async def _receipt_count(factory):
    async with factory() as session:
        return await session.scalar(
            select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
        )


async def test_run_once_persists_actual_pending_then_reports_no_work(pending_marketplace):
    _app, host, coordinator, factory, policy, completed = pending_marketplace
    recovery = MarketplaceReceiptRecoveryV2(
        host=host, coordinator=coordinator, session_factory=factory, policy=policy
    )
    generation = host.manager.current
    assert await _receipt_count(factory) == 1
    assert await recovery.run_once() is True
    assert host.pending_receipt is None
    assert host.manager.current is generation
    assert completed.is_set()
    assert await _receipt_count(factory) == 2
    assert await recovery.run_once() is False
    assert await _receipt_count(factory) == 2
    await recovery.stop()


@pytest.mark.parametrize(
    "failure", [OSError("retry unavailable"), asyncio.CancelledError("retry cancelled")]
)
async def test_background_recovers_after_transient_error_and_stops_promptly(
    pending_marketplace, failure
):
    _app, host, coordinator, factory, policy, completed = pending_marketplace
    attempts = []

    class RecoverySession(AsyncSession):
        async def commit(self):
            attempts.append(self)
            if len(attempts) == 1:
                raise failure
            await super().commit()

    recovery = MarketplaceReceiptRecoveryV2(
        host=host,
        coordinator=coordinator,
        session_factory=async_sessionmaker(
            factory.kw["bind"], class_=RecoverySession, expire_on_commit=False
        ),
        policy=policy,
        poll_interval_seconds=0.01,
    )
    try:
        recovery.start()
        await asyncio.wait_for(completed.wait(), 30)
        assert recovery.is_running
        assert len(attempts) == 2 and attempts[0] is not attempts[1]
        assert host.pending_receipt is None
        assert await _receipt_count(factory) == 2
    finally:
        await asyncio.wait_for(recovery.stop(), 5)
    assert not recovery.is_running


async def test_stale_receipt_is_not_rewritten_or_admitted(pending_marketplace):
    _app, host, coordinator, factory, policy, completed = pending_marketplace
    pending = host.pending_receipt
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        version = await repository.allocate_publication_version()
        await repository.record_requested_distribution(
            pending.snapshot, control_envelope_v2(pending.snapshot, version=version)
        )
        await session.commit()
    recovery = MarketplaceReceiptRecoveryV2(
        host=host, coordinator=coordinator, session_factory=factory, policy=policy
    )
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await recovery.run_once()
        assert caught.value.code == "root_receipt_pending"
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(PlatformPluginV2OutcomeSupersessionModel)
                )
                == 0
            )
        assert host.pending_receipt is pending
        assert not completed.is_set()
        assert await _receipt_count(factory) == 1
        with pytest.raises(RuntimeV2Error) as blocked:
            await host.acquire()
        assert blocked.value.code == "publication_receipt_pending"
    finally:
        await recovery.stop()


@pytest.mark.parametrize("cancel_waiter", [False, True])
async def test_stop_drains_held_commit_even_when_waiter_is_cancelled(
    pending_marketplace, cancel_waiter
):
    app, host, coordinator, factory, policy, completed = pending_marketplace
    entered, release, stop_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class HeldReceiptSession(AsyncSession):
        async def commit(self):
            entered.set()
            await release.wait()
            await super().commit()

    recovery = MarketplaceReceiptRecoveryV2(
        host=host,
        coordinator=coordinator,
        session_factory=async_sessionmaker(
            factory.kw["bind"], class_=HeldReceiptSession, expire_on_commit=False
        ),
        policy=policy,
        poll_interval_seconds=0.01,
    )

    app.state.platform_plugin_receipt_recovery_v2 = recovery

    async def stop():
        stop_entered.set()
        if cancel_waiter:
            await recovery.stop()
        else:
            await shutdown_plugin_runtime_v2(app)

    recovery.start()
    waiter = None
    try:
        await asyncio.wait_for(entered.wait(), 30)
        waiter = asyncio.create_task(stop())
        await stop_entered.wait()
        assert not waiter.done()
        assert not completed.is_set()
        assert host.manager.current is not None
        if cancel_waiter:
            waiter.cancel()
        release.set()
        await asyncio.wait_for(asyncio.gather(waiter, return_exceptions=True), 5)
        await asyncio.wait_for(recovery.stop(), 5)
        assert completed.is_set()
        assert host.pending_receipt is None
        assert not recovery.is_running
        assert await _receipt_count(factory) == 2
        if not cancel_waiter:
            assert host.manager.current is None
    finally:
        release.set()
        if waiter is not None:
            await asyncio.gather(waiter, return_exceptions=True)
        await recovery.stop()
