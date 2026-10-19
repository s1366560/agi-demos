"""Signed test-only implementations exercise instance persistence and publication.

The alternative manifest is a configuration-service fixture, not an implementation
registered in the production renderer catalog. Publication receipts below model
data-plane acceptance; these tests do not claim browser execution of the fixture.
"""

import base64
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.installed_verified_bundle_loader_v2 import (
    InstalledVerifiedBundleLoaderV2,
)
from src.application.services.plugin_instance_service_v2 import PluginInstanceServiceV2
from src.application.services.plugin_marketplace_desired_bundle_service_v2 import (
    PluginMarketplaceDesiredBundleServiceV2,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.application.services.scoped_profile_initialization_service_v2 import (
    ScopedProfileInitializationServiceV2,
)
from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    BundleManifestV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ScopeKindV2,
    ScopeV2,
    SnapshotApplyReceiptV2,
    TrustKindV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import (
    parse_bundle_archive_v2,
    require_signed_archive_verification_v2,
)
from src.infrastructure.plugins.v2.layer_composer import bundle_manifest_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.tests.unit.application.services.test_plugin_marketplace_install_service import (
    FakeArtifactClient,
    _request,
)
from src.tests.unit.infrastructure.plugins.v2.test_bundle_archive_v2 import (
    _archive,
    _public_key_pem,
)
from src.tests.unit.infrastructure.plugins.v2.test_instance_configuration import SCOPE

pytestmark = pytest.mark.unit
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)
_ORIGINAL = {
    "plugin_id": "memstack-renderer-contributions",
    "module_ref": "builtin://memstack/web/renderer-feature",
}
_ALTERNATIVE = {
    "plugin_id": "test-renderer-alternative",
    "module_ref": "marketplace://test-renderer-alternative/feature",
}


def signed_alternative(sources, signer):
    manifest = next(
        row for row in sources.bundle.manifests if row.plugin_id == _ORIGINAL["plugin_id"]
    )
    module = next(row for row in manifest.modules if row.module_ref == _ORIGINAL["module_ref"])
    artifact = next(
        row
        for row in sources.bundle.artifacts
        if row.target in module.targets and row.digest == module.artifact.digest
    )
    baseline = parse_bundle_archive_v2(
        sources.bundle_archive,
        source=sources.desired_set.bundles[0].source,
        approved_permissions=frozenset(
            permission for row in sources.bundle.manifests for permission in row.permissions
        ),
        require_provenance=True,
    )
    alternative = replace(
        module,
        module_ref=_ALTERNATIVE["module_ref"],
        artifact=replace(module.artifact, source="marketplace://test-renderer-alternative/runtime"),
    )
    default_entry = next(
        entry
        for layer in sources.profile_source.layers
        for entry in layer.entries
        if entry.module_ref == _ORIGINAL["module_ref"]
    )
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id=_ALTERNATIVE["plugin_id"],
        version="1.0.0",
        manifests=(
            replace(
                manifest,
                plugin_id=_ALTERNATIVE["plugin_id"],
                version="1.0.0",
                trust=TrustKindV2.SIGNED,
                modules=(alternative,),
                permissions=(),
            ),
        ),
        layers=(
            ProfileLayerV2(
                layer_id="test-alternative",
                kind=ProfileLayerKindV2.BUNDLE,
                scope=_ROOT_SCOPE,
                entries=(
                    replace(
                        default_entry,
                        entry_id="test-alternative-disabled-default",
                        plugin_ref=_ALTERNATIVE["plugin_id"],
                        module_ref=_ALTERNATIVE["module_ref"],
                        enabled=False,
                    ),
                ),
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
        artifacts=(artifact,),
        digest="sha256:" + "0" * 64,
        signature=None,
        provenance="test://instance-replacement",
    )
    bundle = replace(bundle, digest=bundle_manifest_digest_v2(bundle))
    bundle = replace(
        bundle, signature=base64.b64encode(signer.sign(bundle.digest.encode())).decode()
    )
    return bundle, _archive(bundle, artifact_bytes=baseline.artifacts[artifact.artifact_id])


@pytest.fixture
async def replacement_manager(db_session):
    sources = production_bundle_sources_v2()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await PlatformPluginDesiredBundleSetRepositoryV2(db_session).record_desired_set(
        scope=_ROOT_SCOPE, desired_set=sources.desired_set, expected_revision=None, actor_id="setup"
    )
    await db_session.commit()
    initializer = ScopedProfileInitializationServiceV2(
        session_factory=factory, production_sources=sources
    )
    await initializer.ensure_initialized(
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=SCOPE.tenant_id), actor_id="setup"
    )
    signer = Ed25519PrivateKey.generate()
    key = _public_key_pem(signer)
    bundle, archive = signed_alternative(sources, signer)
    artifact_client = FakeArtifactClient(archive)
    installer = PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db_session),
        PluginMarketplaceDesiredBundleServiceV2(
            PlatformPluginDesiredBundleSetRepositoryV2(db_session), baseline=sources.desired_set
        ),
        artifact_client,
        trusted_public_keys=(key,),
    )
    request = _request(bundle, archive, key).model_copy(
        update={"tenant_id": SCOPE.tenant_id, "approved_permissions": frozenset()}
    )
    decision = await installer.request_install(request=request, actor_id="installer")
    assert decision.status == "approved", decision.reason
    await db_session.commit()
    await initializer.ensure_initialized(SCOPE, actor_id="setup")

    async def load_bundle(reference):
        async with factory() as session:
            verified = await InstalledVerifiedBundleLoaderV2(
                governance_repository=PlatformPluginGovernanceRepository(session),
                artifact_client=artifact_client,
                production_sources=sources,
                trusted_public_keys=(key,),
                scope=SCOPE,
            ).load(reference)
        if reference.bundle_id == bundle.bundle_id:
            assert require_signed_archive_verification_v2(verified) == frozenset()
        return verified

    result = {"accept": True, "applied": None}

    async def publish():
        current = await service.configuration()
        async with factory() as session:
            repository = PlatformPluginRepositoryV2(session, scope=SCOPE)
            version = await repository.allocate_publication_version()
            envelope = control_envelope_v2(current.snapshot, version=version)
            publication = await repository.record_requested_distribution(
                current.snapshot,
                envelope,
                policy=PlatformPluginPublicationPolicyV2(
                    required_data_plane_ids=(PYTHON_API_DATA_PLANE_ID_V2,)
                ),
            )
            await PlatformPluginPublicationSourceRepositoryV2(session).record(
                scope=SCOPE, publication_id=publication.id, desired_set=current.desired
            )
            if result["accept"]:
                result["applied"] = (version, current.snapshot.digest)
            applied = result["applied"]
            await repository.record_data_plane_receipt(
                data_plane_id=PYTHON_API_DATA_PLANE_ID_V2,
                nonce=envelope.nonce,
                receipt=SnapshotApplyReceiptV2(
                    status=ApplyStatusV2.ACK if result["accept"] else ApplyStatusV2.NACK,
                    requested_version=version,
                    requested_digest=current.snapshot.digest,
                    applied_version=None if applied is None else applied[0],
                    applied_digest=None if applied is None else applied[1],
                    error_code=None if result["accept"] else "candidate_failed",
                    error_message=None
                    if result["accept"]
                    else "test data plane rejected candidate",
                ),
            )
            await session.commit()

    service = PluginInstanceServiceV2(
        session_factory=factory,
        initializer=initializer,
        load_bundle=load_bundle,
        publish=publish,
        scope=SCOPE,
    )
    await publish()
    snapshot = (await service.configuration()).snapshot
    entry = next(row for row in snapshot.entries if row.module_ref == _ORIGINAL["module_ref"])
    return service, entry, result


def restarted(service):
    return PluginInstanceServiceV2(
        session_factory=service._sessions,
        initializer=service._initializer,
        load_bundle=service._load_bundle,
        publish=AsyncMock(side_effect=AssertionError("accepted source must survive restart")),
        scope=SCOPE,
    )


async def test_verified_installed_implementation_replaces_and_restores(replacement_manager):
    service, entry, _ = replacement_manager
    initial = await service.view()
    row = next(row for row in initial["instances"] if row["entry_id"] == entry.entry_id)
    assert row["replacement_candidates"] == [_ALTERNATIVE]
    changed = await service.apply(
        actor_id="owner",
        expected_revision=1,
        changes=[{"entry_id": entry.entry_id, "replacement": _ALTERNATIVE}],
    )
    assert changed["revision"] == 2 and changed["publication"]["status"] == "ready"
    row = next(row for row in changed["instances"] if row["entry_id"] == entry.entry_id)
    assert row["module_ref"] == _ALTERNATIVE["module_ref"]
    assert row["state"]["status"] == "active" and row["replacement_candidates"] == [_ORIGINAL]
    accepted = await restarted(service).effective_snapshot()
    assert next(row for row in accepted.entries if row.entry_id == entry.entry_id) == replace(
        entry,
        scope=SCOPE,
        plugin_ref=_ALTERNATIVE["plugin_id"],
        module_ref=_ALTERNATIVE["module_ref"],
    )
    restored = await service.apply(
        actor_id="owner",
        expected_revision=2,
        changes=[{"entry_id": entry.entry_id, "replacement": _ORIGINAL}],
    )
    assert restored["revision"] == 3 and restored["publication"]["status"] == "ready"
    accepted = await restarted(service).effective_snapshot()
    assert next(row for row in accepted.entries if row.entry_id == entry.entry_id) == replace(
        entry, scope=SCOPE
    )
    configuration = await service.configuration()
    assert [layer.replacements[0].module_ref for layer in configuration.source.layers[-2:]] == [
        _ALTERNATIVE["module_ref"],
        _ORIGINAL["module_ref"],
    ]
    assert configuration.desired.profile_source.digest == configuration.source.digest


async def test_rejected_replacement_keeps_durable_original_implementation(replacement_manager):
    service, entry, result = replacement_manager
    result["accept"] = False
    rejected = await service.apply(
        actor_id="owner",
        expected_revision=1,
        changes=[{"entry_id": entry.entry_id, "replacement": _ALTERNATIVE}],
    )
    assert rejected["revision"] == 2 and rejected["publication"]["status"] == "degraded"
    row = next(row for row in rejected["instances"] if row["entry_id"] == entry.entry_id)
    assert row["module_ref"] == _ALTERNATIVE["module_ref"] and row["state"]["status"] == "failed"
    accepted = await restarted(service).effective_snapshot()
    assert next(row for row in accepted.entries if row.entry_id == entry.entry_id) == entry
