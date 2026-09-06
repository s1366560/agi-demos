"""ROOT restart admission is fenced by retained lineage and durable publication state."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
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
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


@pytest.fixture
async def saved_root(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        saved = host.current_publication
    finally:
        await shutdown_plugin_runtime_v2(app)
    yield factory, saved


async def _evidence(factory):
    async with factory() as session:
        counts = tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (
                    PlatformPluginV2PublicationModel,
                    PlatformPluginV2ApplyStateEventModel,
                )
            ]
        )
        state = await PlatformPluginRecoveryRepositoryV2(session).read(ROOT, "python-api-v2")
        return counts, state


async def _new_request(factory, snapshot):
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        version = await repository.allocate_publication_version()
        await repository.record_requested_distribution(
            snapshot, control_envelope_v2(snapshot, version=version)
        )
        await session.commit()


async def _change_desired(factory):
    async with factory() as session:
        repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
        current = (await repository.current_desired_set(ROOT)).desired_set
        newer = replace(current, revision=current.revision + 1)
        newer = replace(newer, digest=desired_bundle_set_digest_v2(newer))
        await repository.record_desired_set(
            scope=ROOT, desired_set=newer, expected_revision=current.revision, actor_id="concurrent"
        )
        await session.commit()
        return newer


@pytest.mark.parametrize("failure", ["unreceipted", "missing-binding"])
async def test_incomplete_root_history_prevents_restore_before_apply(
    saved_root, monkeypatch, failure
):
    factory, saved = saved_root
    if failure == "unreceipted":
        await _new_request(factory, saved.snapshot)
    else:
        async with factory() as session:
            publication_id = (
                await session.scalars(
                    select(PlatformPluginV2PublicationModel.id).where(
                        PlatformPluginV2PublicationModel.nonce == saved.envelope.nonce
                    )
                )
            ).one()
            # Isolated fixture fault: simulate a legacy publication with no lineage.
            await session.execute(
                delete(PlatformPluginV2PublicationSourceModel).where(
                    PlatformPluginV2PublicationSourceModel.publication_id == publication_id
                )
            )
            await session.commit()
    before = await _evidence(factory)
    calls = []
    original = PlatformPluginRuntimeHostV2.apply

    async def apply(host, *args, **kwargs):
        calls.append(host)
        return await original(host, *args, **kwargs)

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    app = FastAPI()
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await initialize_plugin_runtime_v2(app, session_factory=factory)
        assert caught.value.code == (
            "root_profile_migration_required"
            if failure == "missing-binding"
            else "root_receipt_pending"
        )
        assert calls == []
        assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
        assert await _evidence(factory) == before
    finally:
        await shutdown_plugin_runtime_v2(app)


@pytest.mark.parametrize("change", ["requested", "desired"])
async def test_root_restore_final_fence_closes_candidate_after_staging_change(
    saved_root, monkeypatch, change
):
    factory, saved = saved_root
    original = PlatformPluginRuntimeHostV2.apply
    hosts = []
    after_change = []

    async def apply(host, snapshot, envelope, **kwargs):
        hosts.append(host)
        stage = kwargs["publication_stager"]

        async def changed(generation):
            if change == "requested":
                await _new_request(factory, saved.snapshot)
            else:
                await _change_desired(factory)
            after_change.append(await _evidence(factory))
            return await stage(generation)

        return await original(host, snapshot, envelope, **{**kwargs, "publication_stager": changed})

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    app = FastAPI()
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await initialize_plugin_runtime_v2(app, session_factory=factory)
        assert caught.value.code == "root_recovery_changed"
        assert len(hosts) == 1 and hosts[0].manager.current is None
        assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
        assert await _evidence(factory) == after_change[0]
    finally:
        await shutdown_plugin_runtime_v2(app)


async def test_local_restore_nack_never_rewrites_publication_or_receipt(saved_root, monkeypatch):
    factory, _saved = saved_root
    before = await _evidence(factory)
    original = ScopedInstalledBundleLoaderV2.__call__

    async def corrupted(loader, reference):
        archive = await original(loader, reference)
        return replace(
            archive, artifacts={key: value + b"corrupt" for key, value in archive.artifacts.items()}
        )

    monkeypatch.setattr(ScopedInstalledBundleLoaderV2, "__call__", corrupted)
    app = FastAPI()
    try:
        with pytest.raises(RuntimeV2Error):
            await initialize_plugin_runtime_v2(app, session_factory=factory)
        assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
        assert await _evidence(factory) == before
    finally:
        await shutdown_plugin_runtime_v2(app)


async def test_identical_runtime_but_new_desired_revision_gets_new_publication_binding(saved_root):
    factory, saved = saved_root
    desired = await _change_desired(factory)
    before, _state = await _evidence(factory)
    app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        current = host.current_publication
        assert current.accepted
        assert current.snapshot.entries == saved.snapshot.entries
        assert current.envelope.nonce != saved.envelope.nonce
        assert current.snapshot.generation > saved.snapshot.generation
        async with factory() as session:
            publication_id = (
                await session.scalars(
                    select(PlatformPluginV2PublicationModel.id).where(
                        PlatformPluginV2PublicationModel.nonce == current.envelope.nonce
                    )
                )
            ).one()
            bound = await PlatformPluginPublicationSourceRepositoryV2(session).read(
                scope=ROOT, publication_id=publication_id
            )
            assert bound == desired
        counts, _state = await _evidence(factory)
        assert counts == (before[0] + 1, before[1] + 1)
    finally:
        await shutdown_plugin_runtime_v2(app)


async def test_latest_real_nack_restores_old_ack_without_rewriting_receipt(db_session):
    from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    first_app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(first_app, session_factory=factory)
        saved = host.current_publication
        snapshot = compose_profile_v2(
            ProfileDocumentV2(profile_id=saved.snapshot.profile_id, entries=saved.snapshot.entries),
            {manifest.plugin_id: manifest for manifest in saved.snapshot.manifests},
            generation=saved.snapshot.generation + 1,
        )
        rejected = await host.apply(
            snapshot,
            control_envelope_v2(snapshot, version=saved.envelope.version + 1),
            verified_archives=(),
        )
        assert not rejected.accepted
        assert rejected.receipt.error_code == "staging_failed"
        assert host.current_publication == saved
        async with factory() as session:
            await PlatformPluginRepositoryV2(session).record_publication_and_receipt(
                rejected,
                data_plane_id="python-api-v2",
            )
            await session.commit()
    finally:
        await shutdown_plugin_runtime_v2(first_app)
    before = await _evidence(factory)
    assert before[1].latest_receipt == rejected.receipt
    app = FastAPI()
    try:
        restored = await initialize_plugin_runtime_v2(app, session_factory=factory)
        assert restored.current_publication.accepted
        assert restored.current_publication.snapshot == saved.snapshot
        assert restored.current_publication.envelope == saved.envelope
        assert await _evidence(factory) == before
    finally:
        await shutdown_plugin_runtime_v2(app)
