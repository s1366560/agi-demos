"""Strict protocol-v2 bundle archive and desired-source parsing tests."""

from __future__ import annotations

import base64
import json
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    BundleArtifactV2,
    BundleManifestV2,
    BundleReferenceV2,
    DesiredBundleSetV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.plugins.v2.bundle_archive import (
    BundleArchiveV2Error,
    parse_bundle_archive_v2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    bundle_manifest_digest_v2,
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.protocol import (
    PluginProtocolV2Error,
    bundle_manifest_v2_to_payload,
    desired_bundle_set_v2_to_payload,
    parse_bundle_manifest_v2,
    parse_desired_bundle_set_v2,
    parse_profile_snapshot_v2,
    parse_profile_source_v2,
    profile_source_v2_to_payload,
)

_ROOT = Path(__file__).resolve().parents[6]
_ARTIFACT_BYTES = b"memstack-plugin-runtime-v2-test-artifact\n"
_ZERO_DIGEST = f"sha256:{'0' * 64}"


def _snapshot():
    payload = json.loads(
        (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
    )
    return parse_profile_snapshot_v2(payload)


def _bundle(
    *,
    signer: Ed25519PrivateKey | None = None,
    permissions: tuple[str, ...] = (),
    provenance: str | None = "tests",
) -> BundleManifestV2:
    snapshot = _snapshot()
    digest = artifact_digest_v2(_ARTIFACT_BYTES)
    manifest = snapshot.manifests[0]
    modules = tuple(
        replace(module, artifact=replace(module.artifact, digest=digest))
        for module in manifest.modules
    )
    manifest = replace(manifest, modules=modules, permissions=permissions)
    entry = replace(
        snapshot.entries[0],
        plugin_ref=manifest.plugin_id,
        module_ref=modules[0].module_ref,
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    targets = tuple(dict.fromkeys(target for module in modules for target in module.targets))
    artifacts = tuple(
        BundleArtifactV2(
            artifact_id=f"conformance-{target.value}",
            target=target,
            path=f"artifacts/{target.value}/conformance.bin",
            digest=digest,
            size_bytes=len(_ARTIFACT_BYTES),
            media_type="application/octet-stream",
        )
        for target in targets
    )
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id="conformance-v2",
        version="1.0.0",
        manifests=(manifest,),
        layers=(
            ProfileLayerV2(
                layer_id="conformance-base",
                kind=ProfileLayerKindV2.BUNDLE,
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
                entries=(entry,),
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
        artifacts=artifacts,
        digest=_ZERO_DIGEST,
        signature=None,
        provenance=provenance,
    )
    bundle = replace(bundle, digest=bundle_manifest_digest_v2(bundle))
    if signer is not None:
        signature = base64.b64encode(signer.sign(bundle.digest.encode("ascii"))).decode()
        bundle = replace(bundle, signature=signature)
    return bundle


def _payload(value: object) -> dict[str, object]:
    if isinstance(value, BundleManifestV2):
        return bundle_manifest_v2_to_payload(value)
    if isinstance(value, ProfileSourceV2):
        return profile_source_v2_to_payload(value)
    if isinstance(value, DesiredBundleSetV2):
        return desired_bundle_set_v2_to_payload(value)
    raise TypeError(f"unsupported payload type: {type(value).__name__}")


def _archive(
    bundle: BundleManifestV2,
    *,
    artifact_bytes: bytes = _ARTIFACT_BYTES,
    omit_path: str | None = None,
    extras: tuple[tuple[str, bytes], ...] = (),
) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle.json", json.dumps(_payload(bundle)))
        for artifact in bundle.artifacts:
            if artifact.path != omit_path:
                archive.writestr(artifact.path, artifact_bytes)
        for name, content in extras:
            archive.writestr(name, content)
    return output.getvalue()


def _public_key_pem(signer: Ed25519PrivateKey) -> str:
    return (
        signer.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


@pytest.mark.unit
def test_signed_archive_closes_every_target_artifact_and_permission() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle = _bundle(signer=signer, permissions=("sandbox.execute",))

    verified = parse_bundle_archive_v2(
        _archive(bundle),
        source="memory://conformance-v2.mspkg",
        trusted_public_keys=(_public_key_pem(signer),),
        approved_permissions=frozenset({"sandbox.execute"}),
        require_signature=True,
        require_provenance=True,
    )

    assert verified.manifest == bundle
    assert tuple(verified.artifacts) == tuple(artifact.artifact_id for artifact in bundle.artifacts)
    assert all(content == _ARTIFACT_BYTES for content in verified.artifacts.values())


@pytest.mark.unit
def test_v1_bundle_descriptor_is_explicitly_incompatible() -> None:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("bundle.json", json.dumps({"schemaVersion": 1, "id": "legacy"}))

    with pytest.raises(BundleArchiveV2Error) as error:
        parse_bundle_archive_v2(output.getvalue(), source="memory://legacy.mspkg")

    assert error.value.code == "incompatible_schema_version"


@pytest.mark.unit
@pytest.mark.parametrize("unsafe_name", ("../escape", "/absolute", "artifacts\\escape"))
def test_archive_rejects_zip_slip_and_non_posix_entries(unsafe_name: str) -> None:
    with pytest.raises(BundleArchiveV2Error) as error:
        parse_bundle_archive_v2(
            _archive(_bundle(), extras=((unsafe_name, b"escape"),)),
            source="memory://unsafe.mspkg",
        )

    assert error.value.code == "unsafe_archive_path"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case", "code"),
    (
        ("missing", "bundle_artifact_missing"),
        ("digest", "bundle_artifact_digest_mismatch"),
        ("size", "bundle_artifact_size_mismatch"),
        ("extra", "undeclared_archive_entry"),
    ),
)
def test_archive_artifact_inventory_is_exact(case: str, code: str) -> None:
    bundle = _bundle()
    omit_path = None
    artifact_bytes = _ARTIFACT_BYTES
    extras: tuple[tuple[str, bytes], ...] = ()
    if case == "missing":
        omit_path = bundle.artifacts[0].path
    elif case == "digest":
        artifact_bytes = b"x" * len(_ARTIFACT_BYTES)
    elif case == "size":
        changed = replace(bundle.artifacts[0], size_bytes=len(_ARTIFACT_BYTES) + 1)
        bundle = replace(bundle, artifacts=(changed, *bundle.artifacts[1:]), digest=_ZERO_DIGEST)
        bundle = replace(bundle, digest=bundle_manifest_digest_v2(bundle))
    else:
        extras = (("undeclared.bin", b"extra"),)

    with pytest.raises(BundleArchiveV2Error) as error:
        parse_bundle_archive_v2(
            _archive(
                bundle,
                artifact_bytes=artifact_bytes,
                omit_path=omit_path,
                extras=extras,
            ),
            source=f"memory://{case}.mspkg",
        )

    assert error.value.code == code


@pytest.mark.unit
def test_archive_requires_trusted_signature_provenance_and_permissions() -> None:
    signer = Ed25519PrivateKey.generate()
    signed = _bundle(signer=signer, permissions=("sandbox.execute",))

    with pytest.raises(BundleArchiveV2Error) as signature_error:
        parse_bundle_archive_v2(
            _archive(signed),
            source="memory://untrusted.mspkg",
            require_signature=True,
        )
    assert signature_error.value.code == "bundle_signature_untrusted"

    with pytest.raises(BundleArchiveV2Error) as permission_error:
        parse_bundle_archive_v2(
            _archive(signed),
            source="memory://permission.mspkg",
            trusted_public_keys=(_public_key_pem(signer),),
            require_signature=True,
        )
    assert permission_error.value.code == "bundle_permission_not_approved"

    unsigned_without_provenance = _bundle(provenance=None)
    with pytest.raises(BundleArchiveV2Error) as provenance_error:
        parse_bundle_archive_v2(
            _archive(unsigned_without_provenance),
            source="memory://provenance.mspkg",
            require_provenance=True,
        )
    assert provenance_error.value.code == "bundle_provenance_required"


@pytest.mark.unit
def test_bundle_profile_source_and_desired_set_parsers_verify_content_digests() -> None:
    bundle = _bundle()
    profile_layer = replace(
        bundle.layers[0],
        layer_id="profile-base",
        kind=ProfileLayerKindV2.PROFILE,
    )
    source = ProfileSourceV2(
        schema_version=2,
        source_id="default-source",
        profile_id="memstack-default-v2",
        revision=1,
        digest=_ZERO_DIGEST,
        provenance="tests",
        layers=(profile_layer,),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = DesiredBundleSetV2(
        schema_version=2,
        desired_set_id="default-desired",
        revision=1,
        bundles=(
            BundleReferenceV2(
                bundle_id=bundle.bundle_id,
                version=bundle.version,
                digest=bundle.digest,
                source="memory://conformance-v2.mspkg",
            ),
        ),
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id,
            revision=source.revision,
            digest=source.digest,
        ),
        digest=_ZERO_DIGEST,
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))

    assert parse_bundle_manifest_v2(_payload(bundle)) == bundle
    assert parse_profile_source_v2(_payload(source)) == source
    assert parse_desired_bundle_set_v2(_payload(desired)) == desired

    with pytest.raises(PluginProtocolV2Error) as error:
        parse_desired_bundle_set_v2({**_payload(desired), "digest": _ZERO_DIGEST})

    assert error.value.code == "desired_bundle_set_digest_mismatch"
