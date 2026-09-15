"""The cross-language projection must preserve the actual verified package manifest."""

import json
from pathlib import Path

from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.protocol import (
    bundle_manifest_v2_to_payload,
    parse_profile_snapshot_v2,
)


def test_cross_plane_fixture_is_exactly_the_real_signed_archive_manifest_and_entries():
    root = Path(__file__).resolve().parents[6]
    fixture = Path(__file__).parent / "fixtures" / "signed_wasm_marker"
    archive = parse_bundle_archive_v2(
        (fixture / "marker.mspkg").read_bytes(),
        source="fixture://signed-marker",
        trusted_public_keys=((fixture / "signer-public.pem").read_text(),),
        approved_permissions=frozenset({"tools.execute"}),
        require_signature=True,
        require_provenance=True,
    )
    payload = json.loads(
        (root / "shared/fixtures/marketplace-python-wasm-distribution.v2.json").read_text()
    )
    snapshot = parse_profile_snapshot_v2(payload["snapshot"])
    verified = bundle_manifest_v2_to_payload(archive.manifest)
    assert payload["snapshot"]["manifests"] == verified["manifests"]
    assert payload["snapshot"]["entries"] == [
        entry for layer in verified["layers"] for entry in layer["entries"]
    ]
    assert payload["descriptor"]["digest"] == snapshot.digest
    assert payload["envelope"]["snapshot_digest"] == snapshot.digest
