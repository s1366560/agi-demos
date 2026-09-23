"""Protocol-v2 marketplace install, approval, revocation, and uninstall tests."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.schemas.plugin_marketplace import (
    MarketplaceArtifactSource,
    MarketplacePackageProvenance,
    MarketplacePackageRequest,
    MarketplacePackageSignature,
)
from src.application.services.plugin_marketplace_catalog_service import (
    PluginMarketplaceCatalogService,
)
from src.application.services.plugin_marketplace_desired_bundle_service_v2 import (
    PluginMarketplaceDesiredBundleServiceV2,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    BundleArtifactV2,
    BundleManifestV2,
    DataPlaneTargetV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    RuntimeKindV2,
    ScopeKindV2,
    ScopeV2,
    TrustKindV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginCatalogModel,
    PlatformPluginDesiredStateModel,
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
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.package_registry import RegistryPluginArtifact
from src.infrastructure.plugins.v2.layer_composer import bundle_manifest_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import (
    bundle_manifest_v2_to_payload,
    canonical_json_v2,
    parse_profile_snapshot_v2,
)
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RUNTIME_TEST_ARTIFACT_BYTES_V2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[5]
_ZERO_DIGEST_V2 = f"sha256:{'0' * 64}"


class FakeArtifactClient:
    def __init__(self, archive: bytes, *, layer_digest: str | None = None) -> None:
        self.archive = archive
        self.layer_digest = layer_digest or hashlib.sha256(archive).hexdigest()

    async def fetch(
        self,
        *,
        registry: str,
        repository: str,
        manifest_digest: str,
    ) -> RegistryPluginArtifact:
        return RegistryPluginArtifact(
            registry=registry,
            repository=repository,
            manifest_digest=manifest_digest,
            layer_digest=self.layer_digest,
            archive=self.archive,
        )


def _signed_bundle(
    signer: Ed25519PrivateKey,
    *,
    trust: TrustKindV2 = TrustKindV2.SIGNED,
    version: str = "1.0.0",
    module_ref: str | None = None,
    target: DataPlaneTargetV2 = DataPlaneTargetV2.WEB,
) -> tuple[BundleManifestV2, bytes]:
    snapshot = parse_profile_snapshot_v2(
        json.loads(
            (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
        )
    )
    artifact_digest = artifact_digest_v2(RUNTIME_TEST_ARTIFACT_BYTES_V2)
    source_manifest = snapshot.manifests[0]
    modules = tuple(
        replace(
            module,
            module_ref=(f"{module_ref}/{index}" if module_ref is not None else module.module_ref),
            artifact=replace(
                module.artifact,
                source="marketplace://third-party-tools/runtime",
                digest=artifact_digest,
            ),
            targets=(target,),
        )
        for index, module in enumerate(source_manifest.modules)
    )
    manifest = replace(
        source_manifest,
        plugin_id="third-party-tool",
        version=version,
        runtime=RuntimeKindV2.PYTHON_TRUSTED,
        trust=trust,
        modules=modules,
        permissions=("tools.execute",),
    )
    entry = replace(
        snapshot.entries[0],
        entry_id="third-party-tool-root",
        plugin_ref=manifest.plugin_id,
        module_ref=modules[0].module_ref,
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        permissions=("tools.execute",),
    )
    targets = tuple(dict.fromkeys(target for module in modules for target in module.targets))
    artifacts = tuple(
        BundleArtifactV2(
            artifact_id=f"third-party-{target.value}",
            target=target,
            path=f"artifacts/{target.value}/runtime.bin",
            digest=artifact_digest,
            size_bytes=len(RUNTIME_TEST_ARTIFACT_BYTES_V2),
            media_type="application/octet-stream",
        )
        for target in targets
    )
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id="third-party-tools",
        version=version,
        manifests=(manifest,),
        layers=(
            ProfileLayerV2(
                layer_id="third-party-tools",
                kind=ProfileLayerKindV2.BUNDLE,
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
                entries=(entry,),
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
        artifacts=artifacts,
        digest=_ZERO_DIGEST_V2,
        signature=None,
        provenance="https://slsa.dev/provenance/v1#third-party-tools",
    )
    bundle = replace(bundle, digest=bundle_manifest_digest_v2(bundle))
    bundle = replace(
        bundle,
        signature=base64.b64encode(signer.sign(bundle.digest.encode("ascii"))).decode("ascii"),
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("bundle.json", canonical_json_v2(bundle_manifest_v2_to_payload(bundle)))
        for artifact in bundle.artifacts:
            archive.writestr(artifact.path, RUNTIME_TEST_ARTIFACT_BYTES_V2)
    return bundle, output.getvalue()


def _public_key_pem(signer: Ed25519PrivateKey) -> str:
    return (
        signer.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def _request(
    bundle: BundleManifestV2,
    archive: bytes,
    public_key_pem: str,
) -> MarketplacePackageRequest:
    return MarketplacePackageRequest(
        plugin_id=bundle.bundle_id,
        version=bundle.version,
        publisher="memstack",
        tenant_id="tenant-1",
        artifact=MarketplaceArtifactSource(
            registry="https://registry.memstack.test",
            repository="memstack/plugins/third-party-tools",
            manifest_sha256="1" * 64,
        ),
        artifact_sha256=hashlib.sha256(archive).hexdigest(),
        manifest=bundle_manifest_v2_to_payload(bundle),
        signature=MarketplacePackageSignature(
            public_key_pem=public_key_pem,
            signature_base64=bundle.signature or "",
        ),
        provenance=MarketplacePackageProvenance(
            predicate_type="https://slsa.dev/provenance/v1",
            builder_id="https://builder.memstack.test",
            subject_name=bundle.bundle_id,
        ),
        approved_permissions=frozenset({"tools.execute"}),
        tenant_admin_approved=True,
        security_scan_passed=True,
    )


def _desired_service(db: AsyncSession) -> PluginMarketplaceDesiredBundleServiceV2:
    return PluginMarketplaceDesiredBundleServiceV2(
        PlatformPluginDesiredBundleSetRepositoryV2(db),
        baseline=production_bundle_sources_v2().desired_set,
    )


@pytest.fixture(autouse=True)
async def initialized_marketplace_scope(db_session):
    from src.application.services.scoped_profile_initialization_service_v2 import (
        ScopedProfileInitializationServiceV2,
    )
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    await PlatformPluginDesiredBundleSetRepositoryV2(db_session).record_desired_set(
        scope=root, desired_set=production_bundle_sources_v2().desired_set,
        expected_revision=None, actor_id="setup",
    )
    await db_session.commit()
    await ScopedProfileInitializationServiceV2(
        session_factory=async_sessionmaker(db_session.bind, expire_on_commit=False),
        production_sources=production_bundle_sources_v2(),
    ).ensure_initialized(ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-1"), "setup")


async def _install(db: AsyncSession):
    signer = Ed25519PrivateKey.generate()
    public_key_pem = _public_key_pem(signer)
    bundle, archive = _signed_bundle(signer)
    service = PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db),
        _desired_service(db),
        FakeArtifactClient(archive),
        trusted_public_keys=(public_key_pem,),
    )
    decision = await service.request_install(
        request=_request(bundle, archive, public_key_pem),
        actor_id="admin-1",
    )
    return decision, bundle, archive, public_key_pem


async def test_marketplace_install_persists_only_v2_desired_state(
    db_session: AsyncSession,
) -> None:
    decision, bundle, _archive, _public_key = await _install(db_session)

    desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-1")
    )
    packages = await PlatformPluginGovernanceRepository(db_session).list_packages()
    legacy_catalog_count = await db_session.scalar(
        select(func.count()).select_from(PlatformPluginCatalogModel)
    )
    legacy_desired_count = await db_session.scalar(
        select(func.count()).select_from(PlatformPluginDesiredStateModel)
    )

    assert decision.status == "approved"
    assert decision.desired_revision == 2
    assert decision.desired_changed is True
    assert desired is not None
    assert desired.desired_set.bundles[-1].bundle_id == bundle.bundle_id
    assert packages[0].manifest == bundle_manifest_v2_to_payload(bundle)
    assert legacy_catalog_count == 0
    assert legacy_desired_count == 0


async def test_marketplace_reinstall_is_idempotent(db_session: AsyncSession) -> None:
    first, bundle, archive, public_key = await _install(db_session)
    service = PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db_session),
        _desired_service(db_session),
        FakeArtifactClient(archive),
        trusted_public_keys=(public_key,),
    )

    repeated = await service.request_install(
        request=_request(bundle, archive, public_key),
        actor_id="admin-2",
    )

    assert first.desired_revision == 2
    assert repeated.status == "approved"
    assert repeated.desired_revision == 2
    assert repeated.desired_changed is False


async def test_marketplace_same_version_cannot_replace_immutable_bundle(
    db_session: AsyncSession,
) -> None:
    first, original, _archive, _public_key = await _install(db_session)
    signer = Ed25519PrivateKey.generate()
    public_key = _public_key_pem(signer)
    replacement, replacement_archive = _signed_bundle(
        signer,
        module_ref="marketplace://replacement/runtime",
    )
    service = PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db_session),
        _desired_service(db_session),
        FakeArtifactClient(replacement_archive),
        trusted_public_keys=(public_key,),
    )

    decision = await service.request_install(
        request=_request(replacement, replacement_archive, public_key),
        actor_id="admin-2",
    )
    desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-1")
    )

    assert first.status == "approved"
    assert decision.status == "quarantined"
    assert "version is immutable" in decision.reason
    assert desired is not None
    assert desired.desired_set.revision == 2
    assert desired.desired_set.bundles[-1].digest == original.digest


async def test_marketplace_install_without_signature_material_resolves_from_catalog(
    db_session: AsyncSession,
) -> None:
    """Catalog-driven reinstall omits PEM secrets the catalog redacts anyway."""
    decision, bundle, archive, public_key = await _install(db_session)
    repository = PlatformPluginGovernanceRepository(db_session)
    _ = await repository.uninstall_package(bundle.bundle_id, bundle.version)
    stored = await repository.get_package_version(bundle.bundle_id, bundle.version)
    assert stored is not None
    stored_signature = dict(stored.signature)
    stored_provenance = dict(stored.provenance)
    service = PluginMarketplaceInstallService(
        repository,
        _desired_service(db_session),
        FakeArtifactClient(archive),
        trusted_public_keys=(public_key,),
    )

    resolved = await service.request_install(
        request=_request(bundle, archive, public_key).model_copy(
            update={"signature": None, "provenance": None}
        ),
        actor_id="admin-3",
    )

    assert decision.status == "approved"
    assert resolved.status == "approved"
    # The desired set never dropped the bundle (raw row uninstall), so the
    # reinstall is a no-op at the desired-state layer.
    assert resolved.desired_changed is False
    assert resolved.desired_revision == decision.desired_revision
    reinstalled = await repository.get_package_version(bundle.bundle_id, bundle.version)
    assert reinstalled is not None
    assert reinstalled.install_status == "installed"
    assert reinstalled.signature == stored_signature
    assert reinstalled.provenance == stored_provenance


async def test_marketplace_install_without_material_requires_catalog_entry(
    db_session: AsyncSession,
) -> None:
    signer = Ed25519PrivateKey.generate()
    public_key = _public_key_pem(signer)
    bundle, archive = _signed_bundle(signer)
    service = PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db_session),
        _desired_service(db_session),
        FakeArtifactClient(archive),
        trusted_public_keys=(public_key,),
    )

    decision = await service.request_install(
        request=_request(bundle, archive, public_key).model_copy(
            update={"signature": None, "provenance": None}
        ),
        actor_id="admin-1",
    )

    assert decision.status == "quarantined"
    assert "catalog entry is required" in decision.reason


async def test_marketplace_install_rejects_signature_digest_drift_from_catalog(
    db_session: AsyncSession,
) -> None:
    decision, bundle, archive, public_key = await _install(db_session)
    repository = PlatformPluginGovernanceRepository(db_session)
    _ = await repository.uninstall_package(bundle.bundle_id, bundle.version)
    stored = await repository.get_package_version(bundle.bundle_id, bundle.version)
    assert stored is not None
    stored.signature = {**stored.signature, "signature_sha256": "a" * 64}
    await db_session.flush()
    service = PluginMarketplaceInstallService(
        repository,
        _desired_service(db_session),
        FakeArtifactClient(archive),
        trusted_public_keys=(public_key,),
    )

    resolved = await service.request_install(
        request=_request(bundle, archive, public_key).model_copy(
            update={"signature": None, "provenance": None}
        ),
        actor_id="admin-3",
    )

    assert decision.status == "approved"
    assert resolved.status == "quarantined"
    assert "Bundle signature differs from its catalog declaration" in resolved.reason


@pytest.mark.parametrize(
    ("case", "reason"),
    (
        ("empty-trust", "trust store is empty"),
        ("untrusted-claim", "signing key is not trusted"),
        ("wrong-layer", "requested artifact digest does not match"),
        ("builtin", "cannot claim builtin trust"),
    ),
)
async def test_marketplace_install_quarantines_untrusted_v2_bundle(
    db_session: AsyncSession,
    case: str,
    reason: str,
) -> None:
    signer = Ed25519PrivateKey.generate()
    public_key = _public_key_pem(signer)
    bundle, archive = _signed_bundle(
        signer,
        trust=TrustKindV2.BUILTIN if case == "builtin" else TrustKindV2.SIGNED,
    )
    trusted_keys = () if case == "empty-trust" else (public_key,)
    request_public_key = (
        _public_key_pem(Ed25519PrivateKey.generate()) if case == "untrusted-claim" else public_key
    )
    layer_digest = "f" * 64 if case == "wrong-layer" else None
    service = PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db_session),
        _desired_service(db_session),
        FakeArtifactClient(archive, layer_digest=layer_digest),
        trusted_public_keys=trusted_keys,
    )

    decision = await service.request_install(
        request=_request(bundle, archive, request_public_key),
        actor_id="admin-1",
    )

    assert decision.status == "quarantined"
    assert decision.desired_changed is False
    assert reason in decision.reason


async def test_marketplace_catalog_approval_revocation_and_uninstall_use_v2_desired(
    db_session: AsyncSession,
) -> None:
    decision, bundle, _archive, _public_key = await _install(db_session)
    assert decision.status == "approved"
    governance = PlatformPluginGovernanceRepository(db_session)
    service = PluginMarketplaceCatalogService(governance, _desired_service(db_session))

    approval = await service.approve(
        plugin_id=bundle.bundle_id,
        version=bundle.version,
        tenant_id="tenant-2",
        approved_permissions=frozenset({"tools.execute"}),
        actor_id="admin-2",
    )
    with pytest.raises(PermissionError, match="not declared"):
        await service.approve(
            plugin_id=bundle.bundle_id,
            version=bundle.version,
            tenant_id="tenant-2",
            approved_permissions=frozenset({"ui.render"}),
            actor_id="admin-2",
        )
    revoked = await service.revoke(
        plugin_id=bundle.bundle_id,
        reason="publisher compromised",
        actor_id="platform-admin",
    )
    uninstall = await service.uninstall(
        tenant_id="tenant-1",
        plugin_id=bundle.bundle_id,
        version=bundle.version,
        actor_id="platform-admin",
    )

    assert approval.granted_permissions == ("tools.execute",)
    assert revoked.revoked_versions == (bundle.version,)
    assert revoked.revoked_permissions == 2
    assert revoked.desired_removed is False
    assert uninstall.desired_removed is True
    assert (
        await governance.list_permissions(
            bundle.bundle_id,
            scope_id="tenant-1",
        )
        == []
    )


@pytest.mark.parametrize("stored_source", [False, True])
async def test_marketplace_desired_revision_publishes_a_real_v2_generation(
    db_session: AsyncSession,
    stored_source: bool,
) -> None:
    decision, _bundle, archive, public_key = await _install(db_session)
    assert decision.status == "approved"
    # Explicit ROOT publication coverage is separate from tenant marketplace installation.
    from src.domain.model.plugins.generated_v2 import BundleReferenceV2
    await _desired_service(db_session).install(scope=ScopeV2(kind=ScopeKindV2.ROOT),
        bundle=BundleReferenceV2(bundle_id=_bundle.bundle_id, version=_bundle.version,
            digest=_bundle.digest, source=f"marketplace://{_bundle.bundle_id}/{_bundle.version}"),
        actor_id="platform-test")
    await PlatformPluginGovernanceRepository(db_session).grant_permission(
        plugin_id=_bundle.bundle_id, permission="tools.execute", scope_type="root",
        scope_id="global", granted_by="platform-test")
    if stored_source:
        from src.infrastructure.plugins.v2.layer_composer import (
            desired_bundle_set_digest_v2,
            profile_source_digest_v2,
        )

        scope = ScopeV2(kind=ScopeKindV2.ROOT)
        source = production_bundle_sources_v2().profile_source
        source = replace(
            source,
            source_id="explicit-root",
            layers=(
                *source.layers[:-1],
                replace(
                    source.layers[-1],
                    disabled_entry_ids=(
                        *source.layers[-1].disabled_entry_ids,
                        "builtin-agent-canvas-tools",
                    ),
                ),
            ),
        )
        source = replace(source, digest=profile_source_digest_v2(source))
        await PlatformPluginProfileSourceRepositoryV2(db_session).record_source(
            scope=scope, source=source, expected_revision=None
        )
        repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
        previous = await repository.current_desired_set(scope)
        assert previous is not None
        desired = replace(
            previous.desired_set,
            revision=3,
            profile_source=replace(
                previous.desired_set.profile_source,
                source_id=source.source_id,
                revision=source.revision,
                digest=source.digest,
            ),
        )
        desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
        await repository.record_desired_set(
            scope=scope, desired_set=desired, expected_revision=2, actor_id="admin"
        )
    from fastapi import FastAPI

    app = FastAPI()
    host = await initialize_plugin_runtime_v2(app)
    try:
        publisher = PluginMarketplacePublicationServiceV2(
            mutation_session=db_session,
            receipt_session_factory=async_sessionmaker(db_session.bind, expire_on_commit=False),
            desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(db_session),
            source_repository=PlatformPluginProfileSourceRepositoryV2(db_session),
            governance_repository=PlatformPluginGovernanceRepository(db_session),
            publication_repository=PlatformPluginRepositoryV2(db_session),
            artifact_client=FakeArtifactClient(archive),
            production_sources=production_bundle_sources_v2(),
            trusted_public_keys=(public_key,),
            host=host,
            route_coordinator=app.state.platform_plugin_http_route_publication_v2,
            publication_policy=PlatformPluginPublicationPolicyV2.local_default(),
            on_route_commit=lambda graph: setattr(
                app.state,
                "platform_plugin_route_graph_v2",
                graph,
            ),
        )

        result = await publisher.publish_current()
        readiness = await PlatformPluginRepositoryV2(db_session).latest_publication_readiness()

        assert result.desired_revision == (3 if stored_source else 2)
        canvas = next(
            entry
            for entry in result.publication.snapshot.entries
            if entry.entry_id == "builtin-agent-canvas-tools"
        )
        assert canvas.enabled is not stored_source
        assert result.publication.accepted is True
        assert result.publication.snapshot.generation == 2
        assert any(
            manifest.plugin_id == "third-party-tool"
            for manifest in result.publication.snapshot.manifests
        )
        assert host.current_publication == result.publication
        assert readiness is not None
        assert readiness.status.value == "ready"
    finally:
        await shutdown_plugin_runtime_v2(app)
