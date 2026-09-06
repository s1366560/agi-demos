"""Live recovery consumes committed requests without allocating or replaying completed work."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services import marketplace_requested_recovery_v2 as requested_recovery
from src.application.services.marketplace_publication_receipt_v2 import (
    persist_marketplace_receipt_v2,
)
from src.application.services.marketplace_receipt_recovery_v2 import MarketplaceReceiptRecoveryV2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    parse_control_envelope_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.unit.infrastructure.adapters.primary.web.startup.test_root_requested_restart_v2 import (
    _failed_marketplace_request,
    _state,
)

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


@pytest.fixture
async def live_requested(db_session, monkeypatch):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        calls = []
        original = PlatformPluginRuntimeHostV2.apply

        async def apply(owner, *args, **kwargs):
            calls.append(owner)
            return await original(owner, *args, **kwargs)

        monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
        await _failed_marketplace_request(
            factory, app, host, OSError("requested commit response lost")
        )
        assert calls == []
        assert host.pending_receipt is None
        yield app, host, factory, calls
    finally:
        await shutdown_plugin_runtime_v2(app)


def _recovery(app, host, factory):
    return MarketplaceReceiptRecoveryV2(
        host=host,
        coordinator=app.state.platform_plugin_http_route_publication_v2,
        session_factory=factory,
        policy=app.state.platform_plugin_publication_policy_v2,
        trusted_public_keys=(),
        allowed_registries=frozenset(),
        on_route_commit=lambda graph: setattr(app.state, "platform_plugin_route_graph_v2", graph),
    )


async def test_live_recovery_applies_exact_unreceipted_request_on_same_host(live_requested):
    app, host, factory, calls = live_requested
    saved, _old, counts = await _state(factory)
    old_generation = host.manager.current
    recovery = _recovery(app, host, factory)
    try:
        assert counts == (2, 1)
        assert await recovery.run_once() is True
        assert calls == [host]
        assert host.manager.current is not old_generation
        assert host.current_distribution.to_payload() == saved
        latest, good, after = await _state(factory)
        assert latest == good == saved
        assert after == (2, 2)
        assert host.pending_receipt is None
        assert await recovery.run_once() is False
        assert calls == [host]
    finally:
        await recovery.stop()


async def test_foreground_completion_after_prepare_prevents_background_apply(
    live_requested, monkeypatch
):
    app, host, factory, calls = live_requested
    saved, _old, _counts = await _state(factory)
    coordinator = app.state.platform_plugin_http_route_publication_v2
    original = requested_recovery.load_requested_root_recovery_v2
    foreground = []

    async def load(*args, **kwargs):
        prepared = await original(*args, **kwargs)
        assert prepared is not None
        publication = await coordinator.publish_snapshot(
            parse_profile_snapshot_v2(saved["snapshot"]),
            parse_control_envelope_v2(saved["envelope"]),
            verified_archives=prepared.archives,
            receipt_persister=lambda result: persist_marketplace_receipt_v2(
                factory, result, policy=app.state.platform_plugin_publication_policy_v2
            ),
        )
        foreground.append(publication)
        return prepared

    monkeypatch.setattr(requested_recovery, "load_requested_root_recovery_v2", load)
    recovery = _recovery(app, host, factory)
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await recovery.run_once()
        assert caught.value.code == "root_recovery_changed"
        assert len(foreground) == 1
        assert calls == [host]  # Only the real foreground publication applied.
        assert host.pending_receipt is None
        assert host.current_publication is foreground[0].plugin_publication
        assert (await _state(factory))[2] == (2, 2)
        lease = await host.acquire()
        await lease.release()
    finally:
        await recovery.stop()


async def test_mismatched_source_keeps_old_live_host_and_never_applies(live_requested):
    app, host, factory, calls = live_requested
    saved, _old, _counts = await _state(factory)
    snapshot = parse_profile_snapshot_v2(saved["snapshot"])
    mismatched = compose_profile_v2(
        ProfileDocumentV2(
            profile_id=snapshot.profile_id,
            entries=tuple(
                replace(entry, enabled=False)
                if entry.entry_id == "builtin-agent-canvas-tools"
                else entry
                for entry in snapshot.entries
            ),
        ),
        {manifest.plugin_id: manifest for manifest in snapshot.manifests},
        generation=snapshot.generation + 1,
    )
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        version = await repository.allocate_publication_version()
        row = await repository.record_requested_distribution(
            mismatched, control_envelope_v2(mismatched, version=version)
        )
        desired = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
            ROOT
        )
        await PlatformPluginPublicationSourceRepositoryV2(session).record(
            scope=ROOT, publication_id=row.id, desired_set=desired.desired_set
        )
        await session.commit()
    before = await _state(factory)
    generation = host.manager.current
    publication = host.current_publication
    recovery = _recovery(app, host, factory)
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await recovery.run_once()
        assert caught.value.code == "root_recovery_snapshot_mismatch"
        assert calls == []
        assert host.pending_receipt is None
        assert host.manager.current is generation
        assert host.current_publication is publication
        assert await _state(factory) == before
        lease = await host.acquire()
        await lease.release()
    finally:
        await recovery.stop()


async def test_desired_change_during_stage_remains_rejected_on_receipt_retry(
    live_requested, monkeypatch
):
    app, host, factory, calls = live_requested
    original = PlatformPluginRuntimeHostV2.apply

    async def apply(owner, snapshot, envelope, **kwargs):
        stage = kwargs["publication_stager"]

        async def change_desired(generation):
            async with factory() as session:
                repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
                current = (await repository.current_desired_set(ROOT)).desired_set
                desired = replace(current, revision=current.revision + 1)
                desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
                await repository.record_desired_set(
                    scope=ROOT,
                    desired_set=desired,
                    expected_revision=current.revision,
                    actor_id="concurrent-desired-writer",
                )
                await session.commit()
            return await stage(generation)

        return await original(
            owner, snapshot, envelope, **{**kwargs, "publication_stager": change_desired}
        )

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    recovery = _recovery(app, host, factory)
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await recovery.run_once()
        assert caught.value.code == "root_recovery_changed"
        pending = host.pending_receipt
        assert pending is not None and pending.accepted
        before = await _state(factory)
        assert before[2] == (2, 1)
        with pytest.raises(RuntimeV2Error) as retry:
            await recovery.run_once()
        assert retry.value.code == "root_recovery_changed"
        assert host.pending_receipt is pending
        assert calls == [host]
        assert await _state(factory) == before
        with pytest.raises(RuntimeV2Error) as blocked:
            await host.acquire()
        assert blocked.value.code == "publication_receipt_pending"
    finally:
        await recovery.stop()


async def test_live_receipt_after_commit_failure_retries_same_outcome_without_reapply(
    live_requested,
):
    app, host, factory, calls = live_requested
    failure = OSError("receipt commit succeeded but response was lost")

    class AmbiguousReceiptSession(AsyncSession):
        async def commit(self):
            await super().commit()
            raise failure

    ambiguous_factory = async_sessionmaker(
        factory.kw["bind"], class_=AmbiguousReceiptSession, expire_on_commit=False
    )
    recovery = _recovery(app, host, ambiguous_factory)
    normal = _recovery(app, host, factory)
    try:
        with pytest.raises(OSError) as caught:
            await recovery.run_once()
        assert caught.value is failure
        pending = host.pending_receipt
        assert pending is not None and pending.accepted
        before = await _state(factory)
        assert before[2] == (2, 2)
        assert calls == [host]
        generation = host.manager.current
        assert await normal.run_once() is True
        assert host.pending_receipt is None
        assert host.manager.current is generation
        assert host.current_publication is pending
        assert calls == [host]
        assert await _state(factory) == before
        lease = await host.acquire()
        await lease.release()
    finally:
        await recovery.stop()
        await normal.stop()
