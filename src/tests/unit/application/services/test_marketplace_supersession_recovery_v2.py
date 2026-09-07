"""Supersede actual pending outcomes with bound requests and durable audit records."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services import marketplace_requested_recovery_v2 as recovery_module
from src.application.services.marketplace_publication_receipt_v2 import (
    persist_marketplace_receipt_v2,
)
from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
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
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.application.services.test_marketplace_live_requested_recovery_v2 import (
    _recovery,
)
from src.tests.unit.application.services.test_marketplace_verified_execution_v2 import (
    _NoExternalArtifactClient,
)
from src.tests.unit.infrastructure.adapters.primary.web.startup.test_root_requested_restart_v2 import (
    _state,
)
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_outcome_supersession_v2 import (
    _next,
    _request,
)

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


@pytest_asyncio.fixture(loop_scope="function")
async def supersession_sessions(db_session):
    return async_sessionmaker(db_session.bind, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="function")
async def supersession_case(supersession_sessions, monkeypatch):
    factory = supersession_sessions
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
                    factory.kw["bind"], class_=FailedReceiptSession, expire_on_commit=False
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
        apply = AsyncMock(wraps=host.reconciler.apply)
        monkeypatch.setattr(host.reconciler, "apply", apply)
        yield app, host, coordinator, factory, policy, apply
    finally:
        await shutdown_plugin_runtime_v2(app)


async def _audit_count(factory):
    async with factory() as session:
        return await session.scalar(
            select(func.count()).select_from(PlatformPluginV2OutcomeSupersessionModel)
        )


async def _replacement(factory, pending, *, bound=True):
    async with factory() as session:
        desired = (
            await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(ROOT)
        ).desired_set
    return await _request(
        factory,
        ROOT,
        _next(pending.snapshot, pending.snapshot.generation + 1),
        desired if bound else None,
    )


async def _blocked(host):
    with pytest.raises(RuntimeV2Error) as error:
        await host.acquire()
    assert error.value.code == "publication_receipt_pending"


async def test_pending_ack_replaced_without_fabricating_its_receipt(supersession_case):
    app, host, _coordinator, factory, _policy, apply = supersession_case
    pending = host.pending_receipt
    replacement = await _replacement(factory, pending)
    assert await _recovery(app, host, factory).run_once() is True
    assert host.current_publication.envelope == replacement.envelope
    assert host.pending_receipt is None
    assert apply.await_count == 1
    assert await _audit_count(factory) == 1
    assert (await _state(factory))[2] == (3, 2)


@pytest.mark.parametrize("after_commit", [False, True])
async def test_audit_commit_failure_preserves_pending_and_retry_is_idempotent(
    supersession_case, after_commit
):
    app, host, _coordinator, factory, _policy, apply = supersession_case
    pending = host.pending_receipt
    await _replacement(factory, pending)
    failure = OSError("audit commit response unavailable")

    class AuditFaultSession(AsyncSession):
        async def commit(self):
            if after_commit:
                await super().commit()
            raise failure

    faulty = async_sessionmaker(
        factory.kw["bind"], class_=AuditFaultSession, expire_on_commit=False
    )
    with pytest.raises(OSError) as error:
        await _recovery(app, host, faulty).run_once()
    assert error.value is failure
    assert host.pending_receipt is pending
    await _blocked(host)
    assert apply.await_count == 0
    assert await _audit_count(factory) == int(after_commit)
    assert (await _state(factory))[2] == (3, 1)
    assert await _recovery(app, host, factory).run_once() is True
    assert apply.await_count == 1
    assert await _audit_count(factory) == 1
    assert (await _state(factory))[2] == (3, 2)


@pytest.mark.parametrize("old_ack_durable", [False, True])
async def test_replacement_nack_stays_blocked_until_a_higher_ack(
    supersession_case, monkeypatch, old_ack_durable
):
    app, host, coordinator, factory, policy, apply = supersession_case
    pending = host.pending_receipt
    if old_ack_durable:

        class LostResponseSession(AsyncSession):
            async def commit(self):
                await super().commit()
                raise OSError("ACK response lost")

        faulty = async_sessionmaker(
            factory.kw["bind"], class_=LostResponseSession, expire_on_commit=False
        )
        with pytest.raises(OSError):
            await coordinator.retry_pending_receipt(
                lambda publication: persist_marketplace_receipt_v2(
                    faulty, publication, policy=policy
                )
            )
        assert host.pending_receipt is pending
    await _replacement(factory, pending)
    load = recovery_module.load_requested_root_recovery_v2

    async def missing_archives(**kwargs):
        prepared = await load(**kwargs)
        return replace(prepared, archives=())

    monkeypatch.setattr(recovery_module, "load_requested_root_recovery_v2", missing_archives)
    with pytest.raises((RuntimeV2Error, PlatformPluginLedgerV2Error)) as error:
        await _recovery(app, host, factory).run_once()
    assert error.value.code == (
        "publication_supersession_nack" if old_ack_durable else "last_good_mismatch"
    )
    nack = host.pending_receipt
    assert nack is not pending and not nack.accepted
    assert host.pending_requires_ack
    await _blocked(host)
    counts = (await _state(factory))[2]
    assert counts == (3, 3 if old_ack_durable else 1)
    assert apply.await_count == 1
    assert await _audit_count(factory) == 1
    assert await _recovery(app, host, factory).run_once() is False
    assert host.pending_receipt is nack
    assert (await _state(factory))[2] == counts
    assert apply.await_count == 1
    monkeypatch.setattr(recovery_module, "load_requested_root_recovery_v2", load)
    replacement = await _replacement(factory, nack)
    assert await _recovery(app, host, factory).run_once() is True
    assert host.current_publication.envelope == replacement.envelope
    assert host.pending_receipt is None
    assert not host.pending_requires_ack
    assert apply.await_count == 2
    assert await _audit_count(factory) == 2
    assert (await _state(factory))[2] == (4, counts[1] + 1)


async def test_unbound_replacement_does_not_discard_actual_pending(supersession_case):
    app, host, _coordinator, factory, _policy, apply = supersession_case
    pending = host.pending_receipt
    await _replacement(factory, pending, bound=False)
    with pytest.raises(RuntimeV2Error) as error:
        await _recovery(app, host, factory).run_once()
    assert error.value.code == "root_receipt_pending"
    assert host.pending_receipt is pending
    await _blocked(host)
    assert apply.await_count == 0
    assert await _audit_count(factory) == 0
    assert (await _state(factory))[2] == (3, 1)


async def test_newer_bound_request_during_stage_preserves_both_actual_outcomes(supersession_case):
    app, host, _coordinator, factory, _policy, apply = supersession_case
    original_pending = host.pending_receipt
    candidate = await _replacement(factory, original_pending)
    later = []
    stages = []
    real_apply = type(host.reconciler).apply

    async def competing_apply(snapshot, envelope, **kwargs):
        original_stage = kwargs["publication_stager"]

        async def stage(staging):
            stages.append(envelope)
            if not later:
                later.append(await _replacement(factory, candidate))
            return await original_stage(staging)

        return await real_apply(
            host.reconciler, snapshot, envelope, **{**kwargs, "publication_stager": stage}
        )

    apply.side_effect = competing_apply
    with pytest.raises(RuntimeV2Error) as error:
        await _recovery(app, host, factory).run_once()
    assert error.value.code == "root_recovery_changed"
    actual_candidate = host.pending_receipt
    assert actual_candidate is not original_pending
    assert actual_candidate.accepted
    assert actual_candidate.envelope == candidate.envelope
    await _blocked(host)
    assert apply.await_count == 1
    assert stages == [candidate.envelope]
    assert await _audit_count(factory) == 1
    assert (await _state(factory))[2] == (4, 1)

    assert await _recovery(app, host, factory).run_once() is True
    assert host.current_publication.envelope == later[0].envelope
    assert host.pending_receipt is None
    assert apply.await_count == 2
    assert stages == [candidate.envelope, later[0].envelope]
    assert await _audit_count(factory) == 2
    assert (await _state(factory))[2] == (4, 2)
