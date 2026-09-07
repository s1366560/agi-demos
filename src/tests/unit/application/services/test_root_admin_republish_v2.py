"""Admin rollback restores bound ROOT configuration through real routes and restart."""

from dataclasses import replace
from types import MappingProxyType

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import (
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.tests.unit.application.services.test_marketplace_verified_execution_v2 import (
    _NoExternalArtifactClient,
)
from src.tests.unit.infrastructure.adapters.primary.web.startup.test_root_profile_startup_v2 import (
    exact_source,
)
from src.tests.unit.infrastructure.adapters.primary.web.startup.test_root_startup_restore_fence_v2 import (
    _evidence,
)

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)
ENDPOINT = "/api/v1/platform-plugins/v2/publications/republish-last-ready"


@pytest_asyncio.fixture(loop_scope="function")
async def rollback_sessions(db_session):
    return async_sessionmaker(db_session.bind, expire_on_commit=False)


async def _configure_b(factory, snapshot):
    record, original = await exact_source(factory)
    canvas = next(
        entry
        for entry in snapshot.entries
        if entry.module_ref == "builtin://memstack/agent/tool/canvas"
    )
    source = replace(
        original,
        revision=original.revision + 1,
        layers=(
            *original.layers,
            ProfileLayerV2(
                layer_id="rollback-test-disable-canvas",
                kind=ProfileLayerKindV2.PROFILE,
                scope=ROOT,
                entries=(),
                replacements=(),
                disabled_entry_ids=(canvas.entry_id,),
            ),
        ),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = replace(
        record.desired_set,
        revision=record.desired_set.revision + 1,
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id,
            revision=source.revision,
            digest=source.digest,
        ),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    async with factory() as session:
        await PlatformPluginProfileSourceRepositoryV2(session).record_source(
            scope=ROOT,
            source=source,
            expected_revision=original.revision,
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=ROOT,
            desired_set=desired,
            expected_revision=record.desired_set.revision,
            actor_id="rollback-admin",
        )
        await session.commit()
    return record.desired_set, desired, canvas.entry_id


def _publisher(app, host, session, factory):
    return PluginMarketplacePublicationServiceV2(
        mutation_session=session,
        receipt_session_factory=factory,
        desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(session),
        source_repository=PlatformPluginProfileSourceRepositoryV2(session),
        governance_repository=PlatformPluginGovernanceRepository(session),
        publication_repository=PlatformPluginRepositoryV2(session),
        artifact_client=_NoExternalArtifactClient(),
        production_sources=production_bundle_sources_v2(),
        trusted_public_keys=(),
        allowed_registries=frozenset(),
        host=host,
        route_coordinator=app.state.platform_plugin_http_route_publication_v2,
        publication_policy=app.state.platform_plugin_publication_policy_v2,
        on_route_commit=lambda graph: setattr(app.state, "platform_plugin_route_graph_v2", graph),
    )


def _install_http(app, factory):
    app.include_router(platform_plugins.router)

    async def database():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: User(
        id="rollback-admin",
        email="rollback@example.com",
        hashed_password="unused",
        full_name="Rollback Admin",
        is_active=True,
        is_superuser=True,
    )


async def test_bound_rollback_after_nack_restores_routes_and_survives_restart(
    rollback_sessions,
    monkeypatch,
):
    factory = rollback_sessions
    app = FastAPI()
    restarted = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        a = host.current_publication
        a_routes = app.state.platform_plugin_route_registry_v2.current
        desired_a, desired_b, canvas_id = await _configure_b(factory, a.snapshot)
        async with factory() as session:
            publisher = _publisher(app, host, session, factory)
            load = publisher._bundle_loader.load

            async def corrupt(reference):
                archive = await load(reference)
                return replace(
                    archive,
                    artifacts=MappingProxyType(
                        {
                            key: value + b"\nrollback-byte-fault"
                            for key, value in archive.artifacts.items()
                        }
                    ),
                )

            monkeypatch.setattr(publisher._bundle_loader, "load", corrupt)
            b = (await publisher.publish_current()).publication
        assert not b.accepted
        assert host.current_publication is a
        assert app.state.platform_plugin_route_registry_v2.current is a_routes
        assert (await exact_source(factory))[0].desired_set == desired_b
        _install_http(app, factory)
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post(ENDPOINT)
        assert response.status_code == 200, response.text
        payload = response.json()
        rollback = host.current_publication
        assert payload["republished_from_nonce"] == a.envelope.nonce
        assert payload["status"] == "ready"
        assert rollback.accepted
        assert rollback.snapshot.generation > b.snapshot.generation
        assert rollback.envelope.version > b.envelope.version
        assert next(
            entry for entry in rollback.snapshot.entries if entry.entry_id == canvas_id
        ).enabled
        record, source = await exact_source(factory)
        assert record.desired_set.revision == desired_b.revision + 1
        assert record.desired_set.profile_source == desired_a.profile_source
        assert source.digest == desired_a.profile_source.digest
        counts, state = await _evidence(factory)
        assert counts == (3, 3)
        assert state.source == record.desired_set
        assert (
            app.state.platform_plugin_route_registry_v2.current.descriptor
            == host.manager.current.descriptor
        )
        assert (
            app.state.platform_plugin_route_graph_v2.table
            is app.state.platform_plugin_route_registry_v2.current.table
        )
        await shutdown_plugin_runtime_v2(app)
        restored = await initialize_plugin_runtime_v2(restarted, session_factory=factory)
        assert restored.current_publication == rollback
        assert (await _evidence(factory))[0] == counts
        assert (
            restarted.state.platform_plugin_route_registry_v2.current.descriptor
            == restored.manager.current.descriptor
        )
    finally:
        await shutdown_plugin_runtime_v2(restarted)
        await shutdown_plugin_runtime_v2(app)


async def _record_other_receipt(factory, publication):
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        await repository.record_data_plane_receipt(
            data_plane_id="fixture-other-plane",
            nonce=publication.envelope.nonce,
            receipt=publication.receipt,
        )
        readiness = await repository.publication_readiness(publication.envelope.nonce)
        await session.commit()
        return readiness


async def _check_old_and_current_leases(host, old_generation):
    retained = await host.acquire_exact(old_generation, old_generation.descriptor)
    await retained.release()
    current = await host.acquire()
    assert current.generation is host.manager.current
    await current.release()


async def test_rollback_creates_new_generation_while_old_a_lease_remains(rollback_sessions):
    """The second required plane uses a real Python Host as a protocol fixture, not Rust QA."""
    factory = rollback_sessions
    app, other_plane = FastAPI(), FastAPI()
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("python-api-v2", "fixture-other-plane"),
    )
    old_lease = None
    try:
        host = await initialize_plugin_runtime_v2(
            app, session_factory=factory, publication_policy=policy
        )
        a = host.current_publication
        await _record_other_receipt(factory, a)
        remote = await initialize_plugin_runtime_v2(
            other_plane, session_factory=factory, publication_policy=policy
        )
        old_lease = await host.acquire()
        old_generation = old_lease.generation
        _desired_a, _desired_b, canvas_id = await _configure_b(factory, a.snapshot)
        async with factory() as session:
            b = (await _publisher(app, host, session, factory).publish_current()).publication
        assert b.accepted
        assert not next(
            entry for entry in b.snapshot.entries if entry.entry_id == canvas_id
        ).enabled
        assert host.manager.current is not old_generation
        remote_nack = await remote.apply(b.snapshot, b.envelope, verified_archives=())
        assert not remote_nack.accepted
        readiness = await _record_other_receipt(factory, remote_nack)
        assert readiness.ready_at is None
        _install_http(app, factory)
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post(ENDPOINT)
        assert response.status_code == 200, response.text
        assert response.json()["republished_from_nonce"] == a.envelope.nonce
        assert response.json()["status"] == "reconciling"
        rollback = host.current_publication
        assert rollback.accepted
        assert rollback.snapshot.generation > b.snapshot.generation
        assert host.manager.current is not old_generation
        assert next(
            entry for entry in rollback.snapshot.entries if entry.entry_id == canvas_id
        ).enabled
        assert old_lease.generation is old_generation
        await _check_old_and_current_leases(host, old_generation)
        assert (
            app.state.platform_plugin_route_registry_v2.current.descriptor
            == host.manager.current.descriptor
        )
        async with factory() as session:
            readiness = await PlatformPluginRepositoryV2(session).publication_readiness(
                rollback.envelope.nonce
            )
            await session.commit()
        assert (
            next(
                plane for plane in readiness.data_planes if plane.data_plane_id == "python-api-v2"
            ).status
            == "ack"
        )
        assert (await _evidence(factory))[0] == (3, 5)
    finally:
        if old_lease is not None:
            await old_lease.release()
        await shutdown_plugin_runtime_v2(other_plane)
        await shutdown_plugin_runtime_v2(app)
