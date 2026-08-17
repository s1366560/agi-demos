import base64
import hashlib
import io
import json
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.application.schemas.plugin_marketplace import (
    MarketplaceArtifactSource,
    MarketplacePackageProvenance,
    MarketplacePackageRequest,
    MarketplacePackageSignature,
)
from src.application.services.platform_plugin_profile_service import (
    PlatformPluginProfileService,
)
from src.application.services.plugin_marketplace_catalog_service import (
    PluginMarketplaceCatalogService,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.domain.model.plugins import parse_plugin_manifest
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins.governance import canonical_plugin_json, sha256_hex
from src.infrastructure.plugins.package_registry import RegistryPluginArtifact


def base_manifest() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "id": "third-party-tool",
        "version": "1.0.0",
        "runtime": "wasm",
        "trust": "signed",
        "provides": [
            {
                "kind": "tool",
                "id": "demo",
                "permissions": ["tools.execute"],
            }
        ],
    }


def package_archive(manifest: dict[str, object]) -> bytes:
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
    runtime = b"wasm-runtime"
    checksums = {
        "plugin.manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
        "runtime/plugin.wasm": hashlib.sha256(runtime).hexdigest(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("plugin.manifest.json", manifest_bytes)
        bundle.writestr("runtime/plugin.wasm", runtime)
        bundle.writestr("checksums.json", json.dumps(checksums, separators=(",", ":")))
    return output.getvalue()


class FakeArtifactClient:
    def __init__(self, archive: bytes, layer_digest: str | None = None) -> None:
        self.archive = archive
        self.layer_digest = layer_digest or hashlib.sha256(archive).hexdigest()

    async def fetch(
        self, *, registry: str, repository: str, manifest_digest: str
    ) -> RegistryPluginArtifact:
        return RegistryPluginArtifact(
            registry=registry,
            repository=repository,
            manifest_digest=manifest_digest,
            layer_digest=self.layer_digest,
            archive=self.archive,
        )


def _request(
    private_key: Ed25519PrivateKey,
    public_pem: str,
    *,
    artifact: str | None = None,
    signed_artifact: str | None = None,
) -> MarketplacePackageRequest:
    manifest = base_manifest()
    artifact = artifact or hashlib.sha256(package_archive(manifest)).hexdigest()
    canonical = parse_plugin_manifest(manifest).to_json()
    payload = canonical_plugin_json(
        {
            "manifest_digest": sha256_hex(canonical.encode()),
            "artifact_digest": signed_artifact or artifact,
        }
    )
    signature = base64.b64encode(private_key.sign(payload)).decode()
    return MarketplacePackageRequest(
        plugin_id="third-party-tool",
        version="1.0.0",
        publisher="memstack",
        tenant_id="tenant-1",
        artifact=MarketplaceArtifactSource(
            registry="https://registry.memstack.test",
            repository="memstack/plugins/third-party-tool",
            manifest_sha256="1" * 64,
        ),
        artifact_sha256=artifact,
        manifest=manifest,
        signature=MarketplacePackageSignature(
            public_key_pem=public_pem,
            signature_base64=signature,
        ),
        provenance=MarketplacePackageProvenance(
            predicate_type="https://slsa.dev/provenance/v1",
            builder_id="https://builder.memstack.test",
            subject_name="third-party-tool",
        ),
        approved_permissions=frozenset({"tools.execute"}),
        tenant_admin_approved=True,
        security_scan_passed=True,
    )


@pytest.mark.unit
async def test_marketplace_install_validates_and_persists(db_session):
    private_key = Ed25519PrivateKey.generate()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    service = PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db_session),
        PlatformPluginRepository(db_session),
        FakeArtifactClient(package_archive(base_manifest())),
        trusted_public_keys=(public_pem,),
    )

    decision = await service.request_install(request=_request(private_key, public_pem))

    assert decision.status == "approved"
    assert await PlatformPluginGovernanceRepository(db_session).list_packages()
    catalog = await PlatformPluginRepository(db_session).list_catalog()
    assert [(row.plugin_id, row.version) for row in catalog] == [("third-party-tool", "1.0.0")]
    desired = await PlatformPluginRepository(db_session).get_desired_state("third-party-tool")
    assert desired is not None
    assert desired.enabled is True
    assert desired.revision == 1

    publication = await PlatformPluginProfileService(PlatformPluginRepository(db_session)).publish(
        version=6, nonce="nonce-6"
    )
    installed = next(
        row for row in publication.snapshot.rows if row.manifest.id == "third-party-tool"
    )
    layer_digest = hashlib.sha256(package_archive(base_manifest())).hexdigest()
    assert installed.manifest.runtime.value == "wasm"
    assert installed.config["artifact"] == {
        "registry": "https://registry.memstack.test",
        "repository": "memstack/plugins/third-party-tool",
        "manifest_sha256": "1" * 64,
        "layer_sha256": layer_digest,
    }
    uninstall = await PluginMarketplaceCatalogService(
        PlatformPluginGovernanceRepository(db_session),
        PlatformPluginRepository(db_session),
    ).uninstall(plugin_id="third-party-tool", version="1.0.0")
    uninstalled_publication = await PlatformPluginProfileService(
        PlatformPluginRepository(db_session)
    ).publish(version=7, nonce="nonce-7")

    assert uninstall.desired_removed is True
    assert all(
        row.manifest.id != "third-party-tool" for row in uninstalled_publication.snapshot.rows
    )


@pytest.mark.unit
async def test_marketplace_install_quarantines_tampered_artifact(db_session):
    private_key = Ed25519PrivateKey.generate()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    request = _request(
        private_key,
        public_pem,
        artifact=sha256_hex(b"tampered"),
        signed_artifact=sha256_hex(b"artifact"),
    )
    service = PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db_session),
        PlatformPluginRepository(db_session),
        FakeArtifactClient(
            package_archive(base_manifest()),
            layer_digest=sha256_hex(b"tampered"),
        ),
        trusted_public_keys=(public_pem,),
    )

    decision = await service.request_install(request=request)

    assert decision.status == "quarantined"
    assert decision.reason == "package signature verification failed"


@pytest.mark.unit
async def test_marketplace_catalog_approval_and_revocation_fail_closed(db_session):
    repository = PlatformPluginGovernanceRepository(db_session)
    manifest = {
        "schemaVersion": 1,
        "id": "third-party-tool",
        "version": "1.0.0",
        "runtime": "wasm",
        "trust": "signed",
        "provides": [
            {"kind": "tool", "id": "demo", "permissions": ["tools.execute"]},
        ],
    }
    await repository.upsert_package(
        plugin_id="third-party-tool",
        version="1.0.0",
        publisher="memstack",
        artifact_digest="a" * 64,
        manifest=manifest,
        signature={"algorithm": "Ed25519"},
        provenance={"predicateType": "https://slsa.dev/provenance/v1"},
        security_scan_status="passed",
    )
    service = PluginMarketplaceCatalogService(
        repository,
        PlatformPluginRepository(db_session),
    )

    approval = await service.approve(
        plugin_id="third-party-tool",
        version="1.0.0",
        tenant_id="tenant-1",
        approved_permissions=frozenset({"tools.execute"}),
        actor_id="admin-1",
    )
    with pytest.raises(PermissionError):
        await service.approve(
            plugin_id="third-party-tool",
            version="1.0.0",
            tenant_id="tenant-1",
            approved_permissions=frozenset({"ui.render"}),
            actor_id="admin-1",
        )
    revocation = await service.revoke(
        plugin_id="third-party-tool",
        reason="publisher compromised",
    )
    uninstall = await service.uninstall(
        plugin_id="third-party-tool",
        version="1.0.0",
    )

    assert approval.granted_permissions == ("tools.execute",)
    assert revocation.revoked_versions == ("1.0.0",)
    assert revocation.revoked_permissions == 1
    assert (
        await repository.list_permissions(
            "third-party-tool",
            scope_id="tenant-1",
        )
        == []
    )
    assert uninstall.desired_removed is False
