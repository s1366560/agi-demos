"""Exact installed references reuse real archive signature and permission validation."""

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.application.services.installed_verified_bundle_loader_v2 import (
    InstalledVerifiedBundleLoaderV2,
    MarketplacePublicationV2Error,
)
from src.infrastructure.plugins.package_registry import RegistryPluginArtifact
from src.infrastructure.plugins.v2.production_bundle import (
    PRODUCTION_BASE_BUNDLE_SOURCE_V2,
    ProductionBundleSourcesV2,
)
from src.infrastructure.plugins.v2.protocol import bundle_manifest_v2_to_payload
from src.tests.unit.infrastructure.plugins.v2.test_profile_watcher_v2 import (
    _archive,
    _candidate_inputs,
    _public_key_pem,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def inputs():
    signer = Ed25519PrivateKey.generate()
    bundle, raw, source, desired = _candidate_inputs(signer)
    reference = replace(
        desired.bundles[0], source=f"marketplace://{bundle.bundle_id}/{bundle.version}"
    )
    package = SimpleNamespace(
        install_status="installed",
        revoked=False,
        artifact_registry="https://registry.example",
        artifact_repository="plugins/clock",
        oci_manifest_digest="a" * 64,
        artifact_digest=hashlib.sha256(raw).hexdigest(),
        manifest=bundle_manifest_v2_to_payload(bundle),
    )
    governance = SimpleNamespace(
        get_package_version=AsyncMock(return_value=package),
        list_permissions=AsyncMock(
            return_value=[SimpleNamespace(permission="service.clock.read")]
        ),
    )
    artifact = RegistryPluginArtifact(
        registry=package.artifact_registry,
        repository=package.artifact_repository,
        manifest_digest=package.oci_manifest_digest,
        layer_digest=package.artifact_digest,
        archive=raw,
    )
    client = SimpleNamespace(fetch=AsyncMock(return_value=artifact))
    options = {
        "governance_repository": governance,
        "artifact_client": client,
        "production_sources": ProductionBundleSourcesV2(
            bundle=bundle, bundle_archive=raw, profile_source=source, desired_set=desired
        ),
        "trusted_public_keys": (_public_key_pem(signer),),
        "allowed_registries": frozenset({package.artifact_registry}),
    }
    return reference, package, governance, client, options


async def test_signed_archive_returned_and_old_error_identity_preserved(inputs):
    from src.application.services.plugin_marketplace_publication_service_v2 import (
        MarketplacePublicationV2Error as OldError,
    )

    reference, _, governance, client, options = inputs
    verified = await InstalledVerifiedBundleLoaderV2(**options).load(reference)
    assert verified.manifest.digest == reference.digest
    assert OldError is MarketplacePublicationV2Error
    client.fetch.assert_awaited_once()
    governance.list_permissions.assert_awaited_once_with(
        reference.bundle_id, scope_type="root", scope_id="global"
    )


@pytest.mark.parametrize("field", ["bundle_id", "version", "digest"])
async def test_builtin_reference_requires_all_identity_fields(inputs, field):
    reference, _, _, client, options = inputs
    reference = replace(reference, source=PRODUCTION_BASE_BUNDLE_SOURCE_V2)
    reference = replace(reference, **{field: "wrong"})
    with pytest.raises(MarketplacePublicationV2Error, match="exact reference"):
        await InstalledVerifiedBundleLoaderV2(**options).load(reference)
    client.fetch.assert_not_awaited()


@pytest.mark.parametrize("failure", ["source", "revoked", "uninstalled", "registry"])
async def test_rejects_before_fetch(inputs, failure):
    reference, package, _, client, options = inputs
    if failure == "source":
        reference = replace(reference, source="https://untrusted.example/archive")
    elif failure == "revoked":
        package.revoked = True
    elif failure == "uninstalled":
        package.install_status = "pending"
    else:
        options["allowed_registries"] = frozenset()
    with pytest.raises(MarketplacePublicationV2Error):
        await InstalledVerifiedBundleLoaderV2(**options).load(reference)
    client.fetch.assert_not_awaited()


@pytest.mark.parametrize("failure", ["bytes", "manifest", "reference", "permissions", "key"])
async def test_real_archive_trust_chain_rejects_changes(inputs, failure):
    reference, package, governance, client, options = inputs
    if failure == "bytes":
        client.fetch.return_value = replace(client.fetch.return_value, archive=b"changed")
    elif failure == "manifest":
        package.manifest = {**package.manifest, "version": "99.0.0"}
    elif failure == "reference":
        reference = replace(reference, digest="sha256:" + "0" * 64)
    elif failure == "permissions":
        governance.list_permissions.return_value = []
    else:
        options["trusted_public_keys"] = (_public_key_pem(Ed25519PrivateKey.generate()),)
    with pytest.raises(ValueError):
        await InstalledVerifiedBundleLoaderV2(**options).load(reference)


async def test_builtin_and_legacy_none_allowlist_remain_supported(inputs):
    reference, _, _, client, options = inputs
    unsigned = replace(options["production_sources"].bundle, signature=None)
    options["production_sources"] = replace(
        options["production_sources"], bundle=unsigned, bundle_archive=_archive(unsigned)
    )
    builtin = await InstalledVerifiedBundleLoaderV2(**options).load(
        replace(reference, source=PRODUCTION_BASE_BUNDLE_SOURCE_V2)
    )
    assert builtin.manifest.digest == reference.digest
    client.fetch.assert_not_awaited()
    options["allowed_registries"] = None
    assert (
        await InstalledVerifiedBundleLoaderV2(**options).load(reference)
    ).manifest.digest == builtin.manifest.digest
