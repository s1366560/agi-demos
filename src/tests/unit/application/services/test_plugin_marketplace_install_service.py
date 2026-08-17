import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.application.schemas.plugin_marketplace import (
    MarketplacePackageProvenance,
    MarketplacePackageRequest,
    MarketplacePackageSignature,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.domain.model.plugins import parse_plugin_manifest
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.governance import canonical_plugin_json, sha256_hex


def _request(
    private_key: Ed25519PrivateKey,
    public_pem: str,
    *,
    artifact: str | None = None,
    signed_artifact: str | None = None,
) -> MarketplacePackageRequest:
    manifest = {
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
    artifact = artifact or sha256_hex(b"artifact")
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
        trusted_public_keys=(public_pem,),
    )

    decision = await service.request_install(request=_request(private_key, public_pem))

    assert decision.status == "approved"


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
        trusted_public_keys=(public_pem,),
    )

    decision = await service.request_install(request=request)

    assert decision.status == "quarantined"
    assert decision.reason == "package signature verification failed"
