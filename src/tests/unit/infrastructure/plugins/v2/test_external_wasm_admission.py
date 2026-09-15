"""Real signed archive admission; no replacement loader or executable definitions."""

from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import DataPlaneTargetV2, RuntimeKindV2
from src.infrastructure.plugins.v2.bundle_archive import (
    BundleArchiveV2Error,
    VerifiedBundleArchiveV2,
    parse_bundle_archive_v2,
    require_signed_archive_verification_v2,
)
from src.infrastructure.plugins.v2.external_wasm_admission import admit_external_wasm_artifacts_v2
from src.infrastructure.plugins.v2.protocol import build_profile_snapshot_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_contracts import generated_target_catalog_v2

FIXTURE = Path(__file__).parent / "fixtures" / "signed_wasm_marker"


@pytest.fixture
def verified():
    return parse_bundle_archive_v2(
        (FIXTURE / "marker.mspkg").read_bytes(),
        source="fixture://signed-marker",
        trusted_public_keys=((FIXTURE / "signer-public.pem").read_text(),),
        approved_permissions=frozenset({"tools.execute"}),
        require_signature=True,
        require_provenance=True,
    )


def snapshot(archive):
    return build_profile_snapshot_v2(
        profile_id="qa-marker",
        generation=1,
        manifests=archive.manifest.manifests,
        entries=archive.manifest.layers[0].entries,
    )


def admit(archive, **overrides):
    args = {
        "manifests": archive.manifest.manifests,
        "entries": archive.manifest.layers[0].entries,
        "target": DataPlaneTargetV2.PYTHON,
        "target_catalog": generated_target_catalog_v2(DataPlaneTargetV2.PYTHON),
        "archives": [archive],
    }
    return admit_external_wasm_artifacts_v2(**(args | overrides))


def test_real_signed_archive_admits_exact_wasm_bytes_without_mutating_builtin_catalog(verified):
    original = generated_target_catalog_v2(DataPlaneTargetV2.PYTHON)
    catalog, resolved = admit(verified, target_catalog=original)
    module = verified.manifest.manifests[0].modules[0]
    assert module.module_ref not in original
    assert catalog[module.module_ref].artifact_digest == module.artifact.digest
    assert resolved[module.module_ref].canonical_bytes == verified.artifacts["marker-wasm"]
    assert resolved[module.module_ref].canonical_bytes.startswith(b"\x00asm")
    LoaderV2().verify_archives(snapshot(verified), [verified])


def test_external_module_without_verified_archive_is_not_admitted(verified):
    with pytest.raises(RuntimeV2Error, match="verified archives"):
        admit(verified, archives=None)


def test_handmade_or_replaced_archive_cannot_claim_parser_signature_verification(verified):
    for unverified in [
        VerifiedBundleArchiveV2(
            manifest=verified.manifest, artifacts=verified.artifacts, source=verified.source
        ),
        replace(verified),
    ]:
        with pytest.raises(BundleArchiveV2Error, match="verification"):
            admit(unverified)


def test_signed_manifest_deep_mutation_and_artifact_mutation_are_rejected(verified):
    manifest = verified.manifest.manifests[0]
    manifest.modules[0].contract.config_schema["title"] = "tampered"
    with pytest.raises(BundleArchiveV2Error, match="stale"):
        require_signed_archive_verification_v2(verified)


def test_payload_cannot_change_manifest_permissions_after_verification(verified):
    changed = replace(
        verified.manifest.manifests[0], permissions=("tools.execute", "filesystem.write")
    )
    with pytest.raises(RuntimeV2Error, match="differs"):
        admit(verified, manifests=[changed])


def test_snapshot_entry_cannot_request_unsigned_permissions(verified):
    changed = replace(verified.manifest.layers[0].entries[0], permissions=("filesystem.write",))
    with pytest.raises(RuntimeV2Error, match="undeclared"):
        admit(verified, entries=[changed])


def test_wrong_runtime_target_owner_and_builtin_identity_are_rejected(verified):
    manifest = verified.manifest.manifests[0]
    with pytest.raises(RuntimeV2Error, match="signed WASM"):
        admit(verified, manifests=[replace(manifest, runtime=RuntimeKindV2.PYTHON_TRUSTED)])
    with pytest.raises(RuntimeV2Error, match="one archive owner"):
        admit(verified, archives=[verified, verified])
    with pytest.raises(RuntimeV2Error, match="builtin identity"):
        admit(verified, manifests=[replace(manifest, plugin_id="memstack-runtime-kernel")])
    module = replace(manifest.modules[0], targets=(DataPlaneTargetV2.PYTHON, DataPlaneTargetV2.WEB))
    with pytest.raises(RuntimeV2Error, match="only Python"):
        admit(verified, manifests=[replace(manifest, modules=(module,))])


@pytest.mark.parametrize(
    "target",
    [
        DataPlaneTargetV2.WEB,
        DataPlaneTargetV2.DESKTOP_RENDERER,
        DataPlaneTargetV2.DESKTOP_SIDECAR,
        DataPlaneTargetV2.RUST_SERVER,
    ],
)
def test_other_planes_ignore_python_only_module_without_external_definition(verified, target):
    existing = generated_target_catalog_v2(target)
    catalog, resolved = admit(verified, target=target, target_catalog=existing)
    assert catalog == existing
    assert resolved == {}


def test_preloaded_definition_cannot_replace_verified_wasm_execution(verified):
    from src.infrastructure.plugins.v2.tool_set import builtin_tool_set_definition_v2

    module = verified.manifest.manifests[0].modules[0]
    substituted = replace(
        builtin_tool_set_definition_v2(),
        module_ref=module.module_ref,
        contract_digest=module.contract_digest,
    )
    with pytest.raises(RuntimeV2Error, match="verified artifact bytes"):
        LoaderV2([substituted]).verify_archives(snapshot(verified), [verified])


def test_signed_proof_rechecks_same_size_artifact_bytes(verified):
    from types import MappingProxyType

    content = verified.artifacts["marker-wasm"]
    # Even tampering beneath the frozen object cannot reuse its old verification proof.
    object.__setattr__(
        verified,
        "artifacts",
        MappingProxyType({"marker-wasm": content[:-1] + bytes([content[-1] ^ 1])}),
    )
    with pytest.raises(BundleArchiveV2Error, match="artifact changed"):
        admit(verified)
