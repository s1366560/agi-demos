"""Recover durable ROOT requests using their exact saved configuration and identity."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup import root_profile_startup_v2
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
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.unit.application.services.test_marketplace_verified_execution_v2 import (
    _NoExternalArtifactClient,
)

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


async def _state(factory):
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        return (
            await repository.latest_requested_distribution(),
            await repository.last_good_distribution("python-api-v2"),
            tuple(
                [
                    await session.scalar(select(func.count()).select_from(model))
                    for model in (
                        PlatformPluginV2PublicationModel,
                        PlatformPluginV2ApplyStateEventModel,
                    )
                ]
            ),
        )


async def _leave_requested(factory, monkeypatch, *, marketplace=False):
    app = FastAPI()
    failure = OSError("requested committed before caller lost response")
    original_apply = PlatformPluginRuntimeHostV2.apply
    calls = []

    async def apply(host, *args, **kwargs):
        calls.append(host)
        return await original_apply(host, *args, **kwargs)

    try:
        if marketplace:
            host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        with monkeypatch.context() as patch:
            patch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
            if marketplace:
                await _failed_marketplace_request(factory, app, host, failure)
            else:
                original = root_profile_startup_v2.prepare_root_startup_request_v2

                async def prepare(**kwargs):
                    await original(**kwargs)
                    raise failure

                patch.setattr(root_profile_startup_v2, "prepare_root_startup_request_v2", prepare)
                with pytest.raises(OSError) as caught:
                    await initialize_plugin_runtime_v2(app, session_factory=factory)
                assert caught.value is failure
            assert calls == []
    finally:
        await shutdown_plugin_runtime_v2(app)
    return await _state(factory)


async def _failed_marketplace_request(factory, app, host, failure):
    class MutationSession(AsyncSession):
        async def commit(self):
            await super().commit()
            raise failure

    mutation_factory = async_sessionmaker(
        factory.kw["bind"], class_=MutationSession, expire_on_commit=False
    )
    async with mutation_factory() as mutation:
        service = PluginMarketplacePublicationServiceV2(
            mutation_session=mutation,
            receipt_session_factory=factory,
            desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(mutation),
            source_repository=PlatformPluginProfileSourceRepositoryV2(mutation),
            governance_repository=PlatformPluginGovernanceRepository(mutation),
            publication_repository=PlatformPluginRepositoryV2(mutation),
            artifact_client=_NoExternalArtifactClient(),
            production_sources=production_bundle_sources_v2(),
            trusted_public_keys=(),
            allowed_registries=frozenset(),
            host=host,
            route_coordinator=app.state.platform_plugin_http_route_publication_v2,
            publication_policy=app.state.platform_plugin_publication_policy_v2,
        )
        with pytest.raises(OSError) as caught:
            await service.publish_current()
        assert caught.value is failure


@pytest.mark.parametrize("marketplace", [False, True])
async def test_restart_recovers_exact_committed_request_without_allocating(
    db_session, monkeypatch, marketplace
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    saved, _old, counts = await _leave_requested(factory, monkeypatch, marketplace=marketplace)
    assert counts == ((2, 1) if marketplace else (1, 0))
    app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        assert host.current_publication.accepted
        assert host.current_distribution.to_payload() == saved
        requested, good, restored_counts = await _state(factory)
        assert requested == good == saved
        assert restored_counts == (counts[0], counts[1] + 1)
        assert app.state.platform_plugin_runtime_v2 is host
    finally:
        await shutdown_plugin_runtime_v2(app)


async def test_new_requested_during_recovery_stage_prevents_install_and_receipt(
    db_session, monkeypatch
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    saved, _old, _counts = await _leave_requested(factory, monkeypatch)
    original = PlatformPluginRuntimeHostV2.apply
    hosts, changed = [], []

    async def apply(host, snapshot, envelope, **kwargs):
        hosts.append(host)
        stage = kwargs["publication_stager"]

        async def race(generation):
            async with factory() as session:
                repository = PlatformPluginRepositoryV2(session)
                version = await repository.allocate_publication_version()
                await repository.record_requested_distribution(
                    snapshot, control_envelope_v2(snapshot, version=version)
                )
                await session.commit()
            changed.append(await _state(factory))
            return await stage(generation)

        return await original(host, snapshot, envelope, **{**kwargs, "publication_stager": race})

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    app = FastAPI()
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await initialize_plugin_runtime_v2(app, session_factory=factory)
        assert caught.value.code == "root_recovery_changed"
        assert len(hosts) == 1 and hosts[0].manager.current is None
        assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
        assert await _state(factory) == changed[0]
        assert changed[0][2] == (2, 0)
        assert changed[0][0]["envelope"]["nonce"] != saved["envelope"]["nonce"]
    finally:
        await shutdown_plugin_runtime_v2(app)


async def test_bound_source_cannot_authorize_a_different_requested_snapshot(
    db_session, monkeypatch
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    saved, _old, _counts = await _leave_requested(factory, monkeypatch)
    original_snapshot = parse_profile_snapshot_v2(saved["snapshot"])
    snapshot = compose_profile_v2(
        ProfileDocumentV2(
            profile_id=original_snapshot.profile_id,
            entries=tuple(
                replace(entry, enabled=False)
                if entry.entry_id == "builtin-agent-canvas-tools"
                else entry
                for entry in original_snapshot.entries
            ),
        ),
        {manifest.plugin_id: manifest for manifest in original_snapshot.manifests},
        generation=original_snapshot.generation + 1,
    )
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        version = await repository.allocate_publication_version()
        row = await repository.record_requested_distribution(
            snapshot, control_envelope_v2(snapshot, version=version)
        )
        desired = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
            ROOT
        )
        await PlatformPluginPublicationSourceRepositoryV2(session).record(
            scope=ROOT, publication_id=row.id, desired_set=desired.desired_set
        )
        await session.commit()
    before = await _state(factory)
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
        assert caught.value.code == "root_recovery_snapshot_mismatch"
        assert calls == []
        assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
        assert await _state(factory) == before
    finally:
        await shutdown_plugin_runtime_v2(app)


async def test_changed_required_plane_policy_prevents_requested_recovery(db_session, monkeypatch):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await _leave_requested(factory, monkeypatch)
    policy = replace(
        PlatformPluginPublicationPolicyV2.local_default(),
        required_data_plane_ids=("python-api-v2", "rust-server-v2"),
    )
    before = await _state(factory)
    calls = []
    original = PlatformPluginRuntimeHostV2.apply

    async def apply(host, *args, **kwargs):
        calls.append(host)
        return await original(host, *args, **kwargs)

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    app = FastAPI()
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await initialize_plugin_runtime_v2(
                app, session_factory=factory, publication_policy=policy
            )
        assert caught.value.code == "root_recovery_policy_changed"
        assert calls == []
        assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
        assert await _state(factory) == before
    finally:
        await shutdown_plugin_runtime_v2(app)
