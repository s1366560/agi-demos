"""A second runtime reconstructs durable scoped ACKs without manufacturing new history."""

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from sqlalchemy import func, select

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
from src.tests.unit.application.services import (
    test_scoped_profile_publication_service_v2 as service_support,
)
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RuntimeTestArtifactResolverV2,
    target_catalog_from_snapshot_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_profile_watcher_v2 import _definitions

setup_service = service_support.setup_service
pytestmark = pytest.mark.unit


async def _read(factory, scope):
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
        PlatformPluginRecoveryRepositoryV2,
    )

    async with factory() as session:
        return await PlatformPluginRecoveryRepositoryV2(session).read(scope, "python-api-v2")


async def _counts(factory):
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


@asynccontextmanager
async def _restart(setup, snapshot):
    _service, _first, _scope, desired, factory, _events, load = setup
    archive = await load(desired.bundles[0])
    events = []
    registry = ScopedRuntimeRegistryV2(
        _definitions(archive.manifest, events),
        target_catalog=target_catalog_from_snapshot_v2(snapshot),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )
    restarted = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry)
    try:
        yield restarted, (archive,), events
    finally:
        await restarted.close()


def _next_snapshot(snapshot):
    return compose_profile_v2(
        ProfileDocumentV2(profile_id=snapshot.profile_id, entries=snapshot.entries),
        {manifest.plugin_id: manifest for manifest in snapshot.manifests},
        generation=snapshot.generation + 1,
    )


async def test_second_instance_restores_exact_ack_without_appending_history(setup_service):
    service, first, scope, _desired, factory, _events, _load = setup_service
    saved = (await service.publish_current(scope)).publication
    assert saved.accepted
    before = await _counts(factory)
    await first.close()
    state = await _read(factory, scope)
    async with _restart(setup_service, saved.snapshot) as (second, archives, events):
        restored = await second.restore_last_good(
            scope, expected_state=state, verified_archives=archives
        )
        assert restored.accepted
        assert restored.snapshot == saved.snapshot
        assert restored.envelope == saved.envelope
        lease = await second.acquire(scope)
        assert lease.generation.descriptor.generation == saved.snapshot.generation
        await lease.release()
        assert events == ["apply:provider:根"]
        assert await _counts(factory) == before


async def test_latest_nack_restores_prior_ack_and_retains_observed_nack(setup_service):
    service, first, scope, _desired, factory, _events, _load = setup_service
    saved = (await service.publish_current(scope)).publication
    rejected = await first.publish(scope, _next_snapshot(saved.snapshot), verified_archives=())
    assert not rejected.accepted
    before = await _counts(factory)
    await first.close()
    state = await _read(factory, scope)
    async with _restart(setup_service, saved.snapshot) as (second, archives, events):
        restored = await second.restore_last_good(
            scope, expected_state=state, verified_archives=archives
        )
        assert restored.accepted
        assert restored.envelope == saved.envelope
        lease = await second.acquire(scope)
        await lease.release()
        assert events == ["apply:provider:根"]
        assert await _read(factory, scope) == state
        assert await _counts(factory) == before


async def test_unreceipted_latest_request_cannot_admit_recovered_ack(setup_service):
    service, first, scope, _desired, factory, _events, _load = setup_service
    saved = (await service.publish_current(scope)).publication
    next_snapshot = _next_snapshot(saved.snapshot)
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session, scope=scope)
        version = await repository.allocate_publication_version()
        await repository.record_requested_distribution(
            next_snapshot, control_envelope_v2(next_snapshot, version=version)
        )
        await session.commit()
    before = await _counts(factory)
    await first.close()
    state = await _read(factory, scope)
    async with _restart(setup_service, saved.snapshot) as (second, archives, events):
        with pytest.raises(RuntimeV2Error):
            await second.restore_last_good(scope, expected_state=state, verified_archives=archives)
        with pytest.raises(RuntimeV2Error):
            await second.acquire(scope)
        assert events == []
        assert await _counts(factory) == before


async def test_changed_desired_does_not_turn_recovery_into_new_publication(setup_service):
    service, first, scope, desired, factory, _events, _load = setup_service
    saved = (await service.publish_current(scope)).publication
    newer = replace(desired, revision=desired.revision + 1)
    newer = replace(newer, digest=desired_bundle_set_digest_v2(newer))
    async with factory() as session:
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=scope,
            desired_set=newer,
            expected_revision=desired.revision,
            actor_id="new-config",
        )
        await session.commit()
    before = await _counts(factory)
    await first.close()
    state = await _read(factory, scope)
    async with _restart(setup_service, saved.snapshot) as (second, archives, _events):
        restored = await second.restore_last_good(
            scope, expected_state=state, verified_archives=archives
        )
        assert restored.snapshot == saved.snapshot
        assert restored.snapshot.generation != newer.revision
        lease = await second.acquire(scope)
        await lease.release()
        assert await _counts(factory) == before


@pytest.mark.parametrize("denied", [False, True])
async def test_application_acquire_restores_without_initializing_or_publishing(
    setup_service, monkeypatch, denied
):
    from unittest.mock import AsyncMock, MagicMock

    from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
        ScopedProfileRuntimeV2,
    )

    service, first, scope, desired, factory, _events, load = setup_service
    saved = (await service.publish_current(scope)).publication
    await first.close()
    before = await _counts(factory)
    async with _restart(setup_service, saved.snapshot) as (second, _archives, events):
        initializer = MagicMock()
        initializer.ensure_initialized = AsyncMock(
            side_effect=AssertionError("Recovery cannot initialize")
        )
        error = RuntimeError("installed artifact revoked")
        loader = AsyncMock(side_effect=error if denied else load)
        restore = AsyncMock(wraps=second.restore_last_good)
        monkeypatch.setattr(second, "restore_last_good", restore)
        monkeypatch.setattr(
            second, "publish", AsyncMock(side_effect=AssertionError("Recovery cannot publish"))
        )
        runtime = ScopedProfileRuntimeV2(
            session_factory=factory,
            coordinator=second,
            bundle_loader=loader,
            initializer=initializer,
        )
        if denied:
            with pytest.raises(RuntimeError) as caught:
                await runtime.acquire(scope)
            assert caught.value is error
            restore.assert_not_awaited()
            assert events == []
            with pytest.raises(RuntimeV2Error):
                await second.acquire(scope)
        else:
            reservation = await runtime.acquire(scope)
            assert reservation.scope == scope
            await reservation.lease.release()
            restore.assert_awaited_once()
            assert events == ["apply:provider:根"]
        loader.assert_awaited_once_with(desired.bundles[0])
        initializer.ensure_initialized.assert_not_awaited()
        second.publish.assert_not_awaited()
        assert await _counts(factory) == before


@pytest.mark.parametrize("case", ["missing-source", "wrong-archives", "stale-state"])
async def test_incomplete_or_stale_recovery_evidence_never_admits(setup_service, case):
    service, first, scope, _desired, factory, _events, _load = setup_service
    saved = (await service.publish_current(scope)).publication
    await first.close()
    state = await _read(factory, scope)
    if case == "missing-source":
        state = replace(state, source=None)
    elif case == "stale-state":
        async with factory() as session:
            repository = PlatformPluginRepositoryV2(session, scope=scope)
            snapshot = _next_snapshot(saved.snapshot)
            version = await repository.allocate_publication_version()
            await repository.record_requested_distribution(
                snapshot, control_envelope_v2(snapshot, version=version)
            )
            await session.commit()
    before = await _counts(factory)
    async with _restart(setup_service, saved.snapshot) as (second, archives, events):
        with pytest.raises(RuntimeV2Error) as caught:
            await second.restore_last_good(
                scope,
                expected_state=state,
                verified_archives=() if case == "wrong-archives" else archives,
            )
        assert (
            caught.value.code
            == {
                "missing-source": "scope_recovery_unavailable",
                "wrong-archives": "scope_bundle_reference_mismatch",
                "stale-state": "scope_recovery_changed",
            }[case]
        )
        with pytest.raises(RuntimeV2Error):
            await second.acquire(scope)
        assert events == []
        assert await _counts(factory) == before


@pytest.mark.parametrize("cancel", [False, True])
async def test_restore_local_apply_failure_or_cancelled_waiter_preserves_owned_cleanup(
    setup_service, cancel
):
    import asyncio

    service, first, scope, desired, factory, _events, load = setup_service
    saved = (await service.publish_current(scope)).publication
    await first.close()
    state = await _read(factory, scope)
    before = await _counts(factory)
    archive = await load(desired.bundles[0])
    events = []
    definitions = _definitions(archive.manifest, events)
    provider = definitions[0]
    entered = asyncio.Event()
    resume = asyncio.Event()

    async def apply(context, config):
        if not cancel:
            raise RuntimeError("local provider unavailable")
        disposer = provider.apply(context, config)
        entered.set()
        await resume.wait()
        return disposer

    registry = ScopedRuntimeRegistryV2(
        (replace(provider, apply=apply), *definitions[1:]),
        target_catalog=target_catalog_from_snapshot_v2(saved.snapshot),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )
    second = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry)
    task = None
    try:
        if not cancel:
            with pytest.raises(RuntimeV2Error) as caught:
                await second.restore_last_good(
                    scope, expected_state=state, verified_archives=(archive,)
                )
            assert caught.value.code == "scope_recovery_rejected"
            with pytest.raises(RuntimeV2Error):
                await second.acquire(scope)
            assert events == []
        else:
            task = asyncio.create_task(
                second.restore_last_good(scope, expected_state=state, verified_archives=(archive,))
            )
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            # Caller cancellation cannot drop the still-owned candidate's disposer.
            assert events == ["apply:provider:根"]
            resume.set()
            await asyncio.wait_for(second.close(), timeout=5)
            assert events == ["apply:provider:根", "dispose:provider:根"]
        assert await _counts(factory) == before
    finally:
        resume.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await second.close()


async def test_durable_request_changed_during_real_staging_fails_final_fence(setup_service):
    service, first, scope, desired, factory, _events, load = setup_service
    saved = (await service.publish_current(scope)).publication
    await first.close()
    state = await _read(factory, scope)
    before = await _counts(factory)
    archive = await load(desired.bundles[0])
    events = []
    definitions = _definitions(archive.manifest, events)
    provider = definitions[0]

    async def apply(context, config):
        # A separate publisher commits after the recovery read and before its final fence.
        async with factory() as session:
            repository = PlatformPluginRepositoryV2(session, scope=scope)
            snapshot = _next_snapshot(saved.snapshot)
            version = await repository.allocate_publication_version()
            await repository.record_requested_distribution(
                snapshot, control_envelope_v2(snapshot, version=version)
            )
            await session.commit()
        return provider.apply(context, config)

    registry = ScopedRuntimeRegistryV2(
        (replace(provider, apply=apply), *definitions[1:]),
        target_catalog=target_catalog_from_snapshot_v2(saved.snapshot),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )
    second = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry)
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await second.restore_last_good(
                scope, expected_state=state, verified_archives=(archive,)
            )
        assert caught.value.code == "scope_recovery_changed"
        assert events == ["apply:provider:根"]
        with pytest.raises(RuntimeV2Error):
            await second.acquire(scope)
        assert await _counts(factory) == (before[0] + 1, before[1])
    finally:
        await second.close()
    assert events == ["apply:provider:根", "dispose:provider:根"]
