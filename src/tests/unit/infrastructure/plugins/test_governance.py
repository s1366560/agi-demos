import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.application.services.plugin_marketplace_service import PluginMarketplaceService
from src.domain.model.plugins import (
    parse_plugin_manifest,
)
from src.domain.ports.plugins import PluginPermission, ResourceQuota
from src.infrastructure.plugins.governance import (
    MarketplaceCatalogEntry,
    PluginPackageBundle,
    PluginPackageVerifier,
    PluginQuotaExceededError,
    PluginTrustGate,
    PluginTrustGateError,
    ResourceQuotaEnforcer,
    canonical_plugin_json,
    sha256_hex,
)


def _manifest() -> object:
    return parse_plugin_manifest(
        {
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
    )


@pytest.mark.unit
def test_trust_gate_restricts_runtime_permissions() -> None:
    decision = PluginTrustGate().decide(
        _manifest(),
        frozenset({PluginPermission.TOOLS_EXECUTE}),
    )
    assert decision.allowed

    storage_manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "storage-wasm",
            "version": "1.0.0",
            "runtime": "wasm",
            "trust": "signed",
            "provides": [
                {"kind": "tool", "id": "write", "permissions": ["storage.write"]},
            ],
        }
    )
    denied = PluginTrustGate().decide(storage_manifest, frozenset())
    assert not denied.allowed
    assert denied.reason.startswith("runtime wasm cannot request")


@pytest.mark.unit
def test_quota_enforcer_returns_structured_errors() -> None:
    enforcer = ResourceQuotaEnforcer({"plugin": ResourceQuota(max_concurrent_calls=1)})
    enforcer.acquire("plugin")

    with pytest.raises(PluginQuotaExceededError) as exc_info:
        enforcer.acquire("plugin")
    assert exc_info.value.limit == "max_concurrent_calls"

    enforcer.release("plugin")
    enforcer.acquire("plugin")


def _bundle(manifest, private_key, public_pem, artifact):
    canonical = manifest.to_json()
    payload = canonical_plugin_json(
        {
            "manifest_digest": sha256_hex(canonical.encode()),
            "artifact_digest": artifact,
        }
    )
    signature = base64.b64encode(private_key.sign(payload)).decode()
    return PluginPackageBundle(
        manifest=manifest,
        canonical_manifest=canonical,
        artifact_digest=artifact,
        signature_base64=signature,
        public_key_pem=public_pem,
        provenance={
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"name": manifest.id, "digest": {"sha256": artifact}}],
            "builder": {"id": "https://builder.memstack.test"},
        },
        checksum={"sha256": artifact},
    )


@pytest.mark.unit
def test_marketplace_approves_valid_signed_package() -> None:
    manifest = _manifest()
    private_key = Ed25519PrivateKey.generate()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    artifact = sha256_hex(b"artifact")
    entry = MarketplaceCatalogEntry(
        plugin_id=manifest.id,
        version=manifest.version,
        publisher="memstack",
        bundle=_bundle(manifest, private_key, public_pem, artifact),
    )
    verifier = PluginPackageVerifier((public_pem,))
    service = PluginMarketplaceService(verifier)

    decision = service.decide(
        entry,
        artifact_sha256=artifact,
        approved_permissions=frozenset({PluginPermission.TOOLS_EXECUTE}),
        tenant_admin_approved=True,
        security_scan_passed=True,
    )
    assert decision.status == "approved"


@pytest.mark.unit
def test_marketplace_quarantines_tampered_artifact() -> None:
    manifest = _manifest()
    private_key = Ed25519PrivateKey.generate()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    artifact = sha256_hex(b"artifact")
    entry = MarketplaceCatalogEntry(
        plugin_id=manifest.id,
        version=manifest.version,
        publisher="memstack",
        bundle=_bundle(manifest, private_key, public_pem, artifact),
    )
    service = PluginMarketplaceService(PluginPackageVerifier((public_pem,)))

    decision = service.decide(
        entry,
        artifact_sha256=sha256_hex(b"tampered"),
        approved_permissions=frozenset({PluginPermission.TOOLS_EXECUTE}),
        tenant_admin_approved=True,
        security_scan_passed=True,
    )
    assert decision.status == "quarantined"
    assert decision.reason == "artifact digest mismatch"


@pytest.mark.unit
def test_revoked_publisher_key_never_installs() -> None:
    manifest = _manifest()
    private_key = Ed25519PrivateKey.generate()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    artifact = sha256_hex(b"artifact")
    entry = MarketplaceCatalogEntry(
        plugin_id=manifest.id,
        version=manifest.version,
        publisher="memstack",
        bundle=_bundle(manifest, private_key, public_pem, artifact),
        revoked=True,
        revocation_reason="publisher compromised",
    )
    verifier = PluginPackageVerifier((public_pem,))

    with pytest.raises(PluginTrustGateError, match="package revoked"):
        verifier.verify(entry, artifact_sha256=artifact)
