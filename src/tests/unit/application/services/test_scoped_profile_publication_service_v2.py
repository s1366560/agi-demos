"""Stored configuration to verified archive to actual Loader and durable admission."""

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.scoped_profile_publication_service_v2 import (
    ScopedProfilePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ServiceRequiredV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
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

pytestmark = pytest.mark.unit


@pytest.fixture
async def setup_service(db_session):
    signer = Ed25519PrivateKey.generate()
    bundle, raw, source, desired = _candidate_inputs(signer)
    scope = source.layers[0].scope
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        await PlatformPluginProfileSourceRepositoryV2(session).record_source(
            scope=scope, source=source, expected_revision=None
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=scope, desired_set=desired, expected_revision=None, actor_id="fixture"
        )
        await session.commit()
    events = []
    # The catalog carries the exact artifact digest from this verified test bundle.
    snapshot = replace(_fixture_snapshot(), manifests=bundle.manifests)
    registry = ScopedRuntimeRegistryV2(
        _definitions(bundle, events),
        target_catalog=target_catalog_from_snapshot_v2(snapshot),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )
    coordinator = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry)

    async def load(_reference):
        return parse_bundle_archive_v2(
            raw,
            source="test-verified",
            trusted_public_keys=(_public_key_pem(signer),),
            require_signature=True,
            approved_permissions=frozenset({"service.clock.read"}),
        )

    service = ScopedProfilePublicationServiceV2(
        session_factory=factory,
        coordinator=coordinator,
        load_verified_bundle=load,
        required_services=(
            ServiceRequiredV2(service="service:clock", version="1.0.0", alias="clock"),
        ),
    )
    try:
        yield service, coordinator, scope, desired, factory, events, load
    finally:
        await coordinator.close()


async def test_exact_configuration_reaches_real_loader_and_receipt(setup_service):
    service, coordinator, scope, desired, _factory, events, _load = setup_service
    result = await service.publish_current(scope)
    assert result.desired_revision == desired.revision
    assert result.publication.accepted
    assert result.publication.snapshot.generation == desired.revision
    lease = await coordinator.acquire(scope)
    assert events == ["apply:provider:根"]
    await lease.release()


async def test_desired_change_while_loading_is_fenced_before_requested_commit(setup_service):
    _service, coordinator, scope, desired, factory, events, load = setup_service
    newer = replace(desired, revision=2)
    newer = replace(newer, digest=desired_bundle_set_digest_v2(newer))

    async def changed(reference):
        async with factory() as session:
            await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
                scope=scope, desired_set=newer, expected_revision=1, actor_id="concurrent"
            )
            await session.commit()
        return await load(reference)

    service = ScopedProfilePublicationServiceV2(
        session_factory=factory,
        coordinator=coordinator,
        load_verified_bundle=changed,
        required_services=(
            ServiceRequiredV2(service="service:clock", version="1.0.0", alias="clock"),
        ),
    )
    with pytest.raises(RuntimeV2Error, match="desired source changed"):
        await service.publish_current(scope)
    assert events == []
    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(PlatformPluginV2PublicationModel))
            == 0
        )


async def test_wrong_verified_bundle_reference_never_applies(setup_service):
    _service, coordinator, scope, _desired, factory, events, load = setup_service

    async def wrong(reference):
        archive = await load(reference)
        from src.infrastructure.plugins.v2.layer_composer import bundle_manifest_digest_v2

        manifest = replace(archive.manifest, bundle_id="other-bundle")
        manifest = replace(manifest, digest=bundle_manifest_digest_v2(manifest))
        return replace(archive, manifest=manifest)

    service = ScopedProfilePublicationServiceV2(
        session_factory=factory,
        coordinator=coordinator,
        load_verified_bundle=wrong,
        required_services=(),
    )
    with pytest.raises(RuntimeV2Error, match="exact reference"):
        await service.publish_current(scope)
    assert events == []
