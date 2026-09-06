"""Real PostgreSQL scoped restart fences on an explicitly migrated, isolated database.

Every case appends only UUID-scoped rows; it never deletes pre-existing history.
The shared sessions fixture requires PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.scoped_profile_publication_service_v2 import (
    ScopedProfilePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2, ServiceRequiredV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scope import scope_key_v2
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
from src.tests.integration import test_platform_plugin_scoped_ledger_postgres as ledger_support
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RuntimeTestArtifactResolverV2,
    target_catalog_from_snapshot_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_profile_watcher_v2 import (
    _candidate_inputs,
    _definitions,
    _fixture_snapshot,
    _public_key_pem,
)

sessions = ledger_support.sessions
pytestmark = pytest.mark.integration


async def _read(factory, scope):
    async with factory() as session:
        return await PlatformPluginRecoveryRepositoryV2(session).read(scope, "python-api-v2")


async def _counts(factory, scope):
    async with factory() as session:
        return tuple(
            [
                await session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.scope_key == scope_key_v2(scope))
                )
                for model in (
                    PlatformPluginV2PublicationModel,
                    PlatformPluginV2ApplyStateEventModel,
                )
            ]
        )


def _next_snapshot(snapshot):
    return compose_profile_v2(
        ProfileDocumentV2(profile_id=snapshot.profile_id, entries=snapshot.entries),
        {manifest.plugin_id: manifest for manifest in snapshot.manifests},
        generation=snapshot.generation + 1,
    )


@asynccontextmanager
async def _configured(sessions):
    signer = Ed25519PrivateKey.generate()
    bundle, raw, source, desired = _candidate_inputs(signer)
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=uuid4().hex,
        project_id=uuid4().hex,
        session_id=uuid4().hex,
    )
    # Only structured scope fields change; artifact bytes and their signature remain exact.
    source = replace(
        source,
        layers=tuple(
            replace(
                layer,
                scope=scope,
                entries=tuple(replace(entry, scope=scope) for entry in layer.entries),
            )
            for layer in source.layers
        ),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = replace(desired, profile_source=replace(desired.profile_source, digest=source.digest))
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    commit_pids = []

    class PidSession(AsyncSession):
        async def commit(self):
            commit_pids.append(await self.scalar(text("SELECT pg_backend_pid()")))
            await super().commit()

    factory = async_sessionmaker(sessions.kw["bind"], class_=PidSession, expire_on_commit=False)
    async with factory() as session:
        await PlatformPluginProfileSourceRepositoryV2(session).record_source(
            scope=scope,
            source=source,
            expected_revision=None,
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=scope,
            desired_set=desired,
            expected_revision=None,
            actor_id="postgres-test",
        )
        await session.commit()
    archive = parse_bundle_archive_v2(
        raw,
        source="test-verified",
        trusted_public_keys=(_public_key_pem(signer),),
        require_signature=True,
        approved_permissions=frozenset({"service.clock.read"}),
    )
    catalog = target_catalog_from_snapshot_v2(
        replace(_fixture_snapshot(), manifests=bundle.manifests)
    )
    events = []

    def registry(apply=None):
        definitions = _definitions(bundle, events)
        if apply is not None:
            definitions = (replace(definitions[0], apply=apply), *definitions[1:])
        return ScopedRuntimeRegistryV2(
            definitions, target_catalog=catalog, artifact_resolver=RuntimeTestArtifactResolverV2()
        )

    first = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry())

    async def load(reference):
        assert reference == desired.bundles[0]
        return archive

    service = ScopedProfilePublicationServiceV2(
        session_factory=factory,
        coordinator=first,
        load_verified_bundle=load,
        required_services=(
            ServiceRequiredV2(service="service:clock", version="1.0.0", alias="clock"),
        ),
    )
    try:
        saved = (await service.publish_current(scope)).publication
        assert saved.accepted
        yield factory, scope, first, saved, archive, registry, events, commit_pids
    finally:
        await first.close()


async def test_restart_restores_exact_ack_without_new_postgres_history(sessions):
    async with _configured(sessions) as (
        factory,
        scope,
        first,
        saved,
        archive,
        registry,
        _events,
        _pids,
    ):
        await first.close()
        state = await _read(factory, scope)
        assert state.source is not None
        before = await _counts(factory, scope)
        async with factory() as one, factory() as two:
            assert await one.scalar(text("SELECT pg_backend_pid()")) != await two.scalar(
                text("SELECT pg_backend_pid()")
            )
        second = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry())
        try:
            restored = await second.restore_last_good(
                scope, expected_state=state, verified_archives=(archive,)
            )
            assert restored.envelope == saved.envelope
            assert restored.snapshot == saved.snapshot
            lease = await second.acquire(scope)
            await lease.release()
            assert await _counts(factory, scope) == before
        finally:
            await second.close()


async def test_other_connection_publication_during_staging_rejects_final_fence(sessions):
    async with _configured(sessions) as (
        factory,
        scope,
        first,
        saved,
        archive,
        registry,
        events,
        pids,
    ):
        state = await _read(factory, scope)
        before = await _counts(factory, scope)
        entered = asyncio.Event()
        resume = asyncio.Event()
        staging_pids = []

        async def apply(context, _config):
            async with factory() as held:
                staging_pids.append(await held.scalar(text("SELECT pg_backend_pid()")))
                context.provide("service:clock", 7)
                entered.set()
                await resume.wait()
            return lambda: events.append("dispose:restored")

        second = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry(apply))
        task = asyncio.create_task(
            second.restore_last_good(scope, expected_state=state, verified_archives=(archive,))
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            offset = len(pids)
            newer = await asyncio.wait_for(
                first.publish(scope, _next_snapshot(saved.snapshot), verified_archives=(archive,)),
                timeout=10,
            )
            assert newer.accepted
            assert (
                len(pids[offset:]) == 2
            )  # Real requested and receipt commits on another connection.
            assert all(pid != staging_pids[0] for pid in pids[offset:])
            resume.set()
            with pytest.raises(RuntimeV2Error) as caught:
                await asyncio.wait_for(task, timeout=10)
            assert caught.value.code == "scope_recovery_changed"
            with pytest.raises(RuntimeV2Error):
                await second.acquire(scope)
            assert await _counts(factory, scope) == (before[0] + 1, before[1] + 1)
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)
            await second.close()
        assert events.count("dispose:restored") == 1


async def test_unreceipted_latest_postgres_request_cannot_restore_old_ack(sessions):
    async with _configured(sessions) as (
        factory,
        scope,
        first,
        saved,
        archive,
        registry,
        events,
        _pids,
    ):
        await first.close()
        snapshot = _next_snapshot(saved.snapshot)
        async with factory() as session:
            repository = PlatformPluginRepositoryV2(session, scope=scope)
            version = await repository.allocate_publication_version()
            await repository.record_requested_distribution(
                snapshot, control_envelope_v2(snapshot, version=version)
            )
            await session.commit()
        state = await _read(factory, scope)
        assert state.last_good is not None and state.latest_receipt is None
        before = await _counts(factory, scope)
        previous_events = list(events)
        second = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry())
        try:
            with pytest.raises(RuntimeV2Error) as caught:
                await second.restore_last_good(
                    scope, expected_state=state, verified_archives=(archive,)
                )
            assert caught.value.code == "scope_recovery_unavailable"
            with pytest.raises(RuntimeV2Error):
                await second.acquire(scope)
            assert events == previous_events
            assert await _counts(factory, scope) == before
        finally:
            await second.close()
