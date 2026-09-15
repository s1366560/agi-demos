"""Build a real signed ABI fixture. Does not install, publish, or change runtime catalogs."""

import asyncio
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import wasmtime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.infrastructure.plugins.v2.protocol import (
    canonical_json_v2,
    parse_bundle_manifest_v2,
    parse_plugin_manifest_v2,
    _profile_layer_from_payload,
    bundle_manifest_v2_to_payload,
)
from src.domain.model.plugins.generated_v2 import (
    BundleManifestV2,
    BundleArtifactV2,
    DataPlaneTargetV2,
)
from src.infrastructure.plugins.v2.layer_composer import bundle_manifest_digest_v2
from dataclasses import replace
from src.infrastructure.plugins.v2.bundle_archive import (
    parse_bundle_archive_v2,
    BundleArchiveV2Error,
)
from src.infrastructure.plugins.wasm_host import WasmToolHost, WasmHostError
from src.infrastructure.plugins.v2.runtime import LoaderV2
from src.infrastructure.plugins.v2.protocol import build_profile_snapshot_v2

ROOT = Path(__file__).resolve().parent
WAT = '(module (func (export "score") (param i32) (result i32) i32.const 20260914))'


def digest(value):
    return "sha256:" + hashlib.sha256(canonical_json_v2(value)).hexdigest()


def archive(descriptor, wasm):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("bundle.json", canonical_json_v2(descriptor))
        z.writestr("artifacts/marker.wasm", wasm)
    return out.getvalue()


async def main():
    wasm = bytes(wasmtime.wat2wasm(WAT))
    artifact_digest = "sha256:" + hashlib.sha256(wasm).hexdigest()
    contract = {
        "services": {
            "provides": [],
            "requires": [
                {
                    "alias": "catalog",
                    "service": "service:tool-set-catalog",
                    "version": "1.0.0",
                    "contributes": True,
                }
            ],
        },
        "events": {"emits": [], "handles": []},
        "config_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "properties": {"tool_name": {"const": "qa_marketplace_marker"}},
            "required": ["tool_name"],
        },
    }
    module = {
        "module_ref": "wasm://qa-marketplace-marker/score-v1",
        "entrypoint": "score",
        "artifact": {
            "digest": artifact_digest,
            "source": "bundle://qa-marketplace-marker/artifacts/marker.wasm",
        },
        "targets": ["python"],
        "contract": contract,
        "contract_digest": digest(contract),
    }
    manifest = {
        "schema_version": 2,
        "plugin_id": "qa-marketplace-marker",
        "version": "1.0.0",
        "runtime": "wasm",
        "trust": "signed",
        "modules": [module],
        "permissions": ["tools.execute"],
        "quotas": {"max_wasm_fuel": 10000, "max_wasm_memory_bytes": 65536},
    }
    entry = {
        "entry_id": "qa-marketplace-marker",
        "parent_entry_id": None,
        "plugin_ref": manifest["plugin_id"],
        "module_ref": module["module_ref"],
        "enabled": True,
        "config": {"tool_name": "qa_marketplace_marker"},
        "inject": {"catalog": "service:tool-set-catalog"},
        "isolate": {},
        "scope": {"kind": "root"},
        "permissions": ["tools.execute"],
        "quotas": manifest["quotas"],
        "restart_policy": "hot-generation",
    }
    bundle = {
        "schema_version": 2,
        "bundle_id": "qa-marketplace-marker-bundle",
        "version": "1.0.0",
        "manifests": [manifest],
        "layers": [
            {
                "layer_id": "qa-marketplace-marker",
                "kind": "bundle",
                "scope": {"kind": "root"},
                "entries": [entry],
                "replacements": [],
                "disabled_entry_ids": [],
            }
        ],
        "artifacts": [
            {
                "artifact_id": "marker-wasm",
                "target": "python",
                "path": "artifacts/marker.wasm",
                "digest": artifact_digest,
                "size_bytes": len(wasm),
                "media_type": "application/wasm",
            }
        ],
        "provenance": "repo://qa/marketplace-wasm-fixture",
    }
    model = BundleManifestV2(
        schema_version=2,
        bundle_id=bundle["bundle_id"],
        version="1.0.0",
        manifests=(parse_plugin_manifest_v2(manifest),),
        layers=tuple(_profile_layer_from_payload(x) for x in bundle["layers"]),
        artifacts=tuple(
            BundleArtifactV2(**(x | {"target": DataPlaneTargetV2(x["target"])}))
            for x in bundle["artifacts"]
        ),
        digest="sha256:" + "0" * 64,
        signature=None,
        provenance=bundle["provenance"],
    )
    model = replace(model, digest=bundle_manifest_digest_v2(model))
    bundle = bundle_manifest_v2_to_payload(model)
    private = Ed25519PrivateKey.generate()
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    bundle["signature"] = base64.b64encode(private.sign(bundle["digest"].encode("ascii"))).decode()
    parsed = parse_bundle_manifest_v2(bundle)
    raw = archive(bundle, wasm)
    verify = dict(
        source="fixture://qa-marketplace-marker",
        trusted_public_keys=(public,),
        approved_permissions=frozenset({"tools.execute"}),
        require_signature=True,
        require_provenance=True,
    )
    parse_bundle_archive_v2(raw, **verify)
    outcome = WasmToolHost(
        "qa-marketplace-marker", wasm, fuel_budget=10000, audit=lambda _: None
    ).call("qa_marketplace_marker", "{}")
    assert outcome.score == 20260914
    errors = {}
    for name, content, kwargs in [
        ("tampered_artifact", archive(bundle, wasm + b"X"), verify),
        ("untrusted_signer", raw, verify | {"trusted_public_keys": ()}),
        ("permission_missing", raw, verify | {"approved_permissions": frozenset()}),
    ]:
        try:
            parse_bundle_archive_v2(content, **kwargs)
        except BundleArchiveV2Error as exc:
            errors[name] = exc.code
        else:
            raise AssertionError(name)
    try:
        WasmToolHost(
            "qa-infinite",
            bytes(
                wasmtime.wat2wasm(
                    '(module (func (export "score") (param i32) (result i32) (loop br 0) i32.const 0))'
                )
            ),
            fuel_budget=100,
            audit=lambda _: None,
        ).call("loop", "{}")
    except WasmHostError:
        errors["fuel_exhaustion"] = "trapped"
    else:
        raise AssertionError("infinite guest escaped budget")
    snapshot = build_profile_snapshot_v2(
        profile_id="qa-marketplace-fixture",
        generation=1,
        manifests=parsed.manifests,
        entries=parsed.layers[0].entries,
    )
    try:
        await LoaderV2().stage(snapshot)
    except Exception as exc:
        errors["current_production_loader"] = getattr(exc, "code", type(exc).__name__)
    else:
        raise AssertionError("unsupported marketplace WASM unexpectedly activated")
    (ROOT / "marker.wat").write_text(WAT + "\n")
    (ROOT / "marker.wasm").write_bytes(wasm)
    (ROOT / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n")
    (ROOT / "signer-public.pem").write_text(public)
    (ROOT / "marker.mspkg").write_bytes(raw)
    result = {
        "actual_wasm_score": outcome.score,
        "signed_archive_verified": True,
        "wasm_sha256": hashlib.sha256(wasm).hexdigest(),
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "negative_checks": errors,
        "installed": False,
        "native_acceptance": False,
        "signing_private_key_persisted": False,
    }
    (ROOT / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


asyncio.run(main())
