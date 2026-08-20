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


@pytest.mark.unit
def test_quota_enforcer_covers_runtime_resource_dimensions() -> None:
    enforcer = ResourceQuotaEnforcer(
        {
            "plugin": ResourceQuota(
                max_wasm_fuel=1_000,
                max_wasm_memory_bytes=64 * 1024,
                max_wall_time_ms=100,
                max_output_bytes=128,
                max_network_requests_per_minute=2,
                max_storage_bytes=256,
                max_monthly_usd=0.01,
            )
        }
    )

    enforcer.acquire(
        "plugin",
        wasm_fuel=100,
        wasm_memory_bytes=64 * 1024,
        wall_time_ms=50,
        output_bytes=64,
        network_requests=1,
        storage_bytes=128,
        usd_micros=5_000,
    )
    enforcer.release("plugin", wall_time_ms=50)
    enforcer.acquire("plugin", network_requests=1, storage_bytes=128, usd_micros=5_000)
    enforcer.release("plugin", wall_time_ms=100)

    limits = {
        "max_output_bytes": lambda: enforcer.acquire("plugin", output_bytes=65, network_requests=0),
        "max_network_requests_per_minute": lambda: enforcer.acquire("plugin"),
        "max_storage_bytes": lambda: enforcer.acquire(
            "plugin", storage_bytes=1, network_requests=0
        ),
        "max_monthly_usd": lambda: enforcer.acquire("plugin", usd_micros=1, network_requests=0),
    }
    for limit, acquire in limits.items():
        with pytest.raises(PluginQuotaExceededError) as exc_info:
            acquire()
        assert exc_info.value.limit == limit

    with pytest.raises(PluginQuotaExceededError) as fuel:
        enforcer.acquire("plugin", wasm_fuel=1_001, network_requests=0)
    assert fuel.value.limit == "max_wasm_fuel"
    with pytest.raises(PluginQuotaExceededError) as memory:
        enforcer.acquire("plugin", wasm_memory_bytes=65 * 1024, network_requests=0)
    assert memory.value.limit == "max_wasm_memory_bytes"
    with pytest.raises(ValueError, match="cannot be negative"):
        enforcer.acquire("plugin", wall_time_ms=-1, network_requests=0)


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


@pytest.mark.unit
def test_trust_gate_allows_untrusted_wasm_tool_only_manifest() -> None:
    """I5: untrusted + wasm + tool-only passes the shape gate."""
    manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "untrusted-tool",
            "version": "1.0.0",
            "runtime": "wasm",
            "trust": "untrusted",
            "provides": [{"kind": "tool", "id": "demo", "permissions": ["tools.execute"]}],
        }
    )
    decision = PluginTrustGate().decide(manifest, frozenset({PluginPermission.TOOLS_EXECUTE}))
    assert decision.allowed is True


@pytest.mark.unit
def test_trust_gate_rejects_untrusted_non_tool_capabilities() -> None:
    """I5: untrusted manifests may only provide PlainCapability(Tool) rows."""
    manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "untrusted-hook",
            "version": "1.0.0",
            "runtime": "wasm",
            "trust": "untrusted",
            "provides": [
                {"kind": "tool", "id": "demo", "permissions": ["tools.execute"]},
                {"kind": "hook", "id": "on_session_start"},
            ],
        }
    )
    decision = PluginTrustGate().decide(manifest, frozenset({PluginPermission.TOOLS_EXECUTE}))
    assert decision.allowed is False
    assert "only provide tool capabilities" in decision.reason


@pytest.mark.unit
def test_manifest_rejects_untrusted_python_trusted_runtime() -> None:
    """I5: the python-trusted boundary is closed at manifest parse time."""
    from src.domain.model.plugins import PluginManifestError

    with pytest.raises(PluginManifestError, match="python-trusted"):
        parse_plugin_manifest(
            {
                "schemaVersion": 1,
                "id": "untrusted-python",
                "version": "1.0.0",
                "runtime": "python-trusted",
                "trust": "untrusted",
                "provides": [{"kind": "tool", "id": "demo", "permissions": ["tools.execute"]}],
            }
        )
