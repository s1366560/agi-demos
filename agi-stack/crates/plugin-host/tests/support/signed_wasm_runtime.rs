use agistack_plugin_host::protocol_v2::{
    signed_archive::{
        bundle_manifest_digest_v2, verify_signed_bundle_archive_v2, TrustedEd25519KeyV2,
        VerifiedBundleArchiveV2,
    },
    BundleManifestV2, BundleReferenceV2, ProfileSnapshotV2,
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use ring::{
    rand::SystemRandom,
    signature::{Ed25519KeyPair, KeyPair},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    io::{Cursor, Read, Write},
};
use zip::{write::SimpleFileOptions, ZipArchive, ZipWriter};

pub fn signed_fixture(
    wat_source: &str,
    mutate: impl FnOnce(&mut Value),
) -> (VerifiedBundleArchiveV2, ProfileSnapshotV2) {
    let (archive, snapshot, _, _, _) = signed_fixture_with_bytes(wat_source, mutate);
    (archive, snapshot)
}

pub fn signed_fixture_with_bytes(
    wat_source: &str,
    mutate: impl FnOnce(&mut Value),
) -> (
    VerifiedBundleArchiveV2,
    ProfileSnapshotV2,
    Vec<u8>,
    TrustedEd25519KeyV2,
    String,
) {
    let raw = include_bytes!("../../../../../src/tests/unit/infrastructure/plugins/v2/fixtures/signed_wasm_marker/marker.mspkg");
    let mut zip = ZipArchive::new(Cursor::new(raw)).unwrap();
    let mut descriptor = String::new();
    zip.by_name("bundle.json")
        .unwrap()
        .read_to_string(&mut descriptor)
        .unwrap();
    let mut value: Value = serde_json::from_str(&descriptor).unwrap();
    let bytes = wat::parse_str(wat_source).unwrap();
    let artifact_digest = format!("sha256:{:x}", Sha256::digest(&bytes));
    value["artifacts"][0]["digest"] = artifact_digest.clone().into();
    value["artifacts"][0]["size_bytes"] = bytes.len().into();
    value["artifacts"][0]["target"] = "desktop-sidecar".into();
    let module = &mut value["manifests"][0]["modules"][0];
    module["artifact"]["digest"] = artifact_digest.into();
    module["targets"] = json!(["desktop-sidecar"]);
    module["contract"]["services"] =
        json!({"provides":[{"service":"service:wasm-tool-set","version":"1.0.0"}],"requires":[]});
    module["contract_digest"] = format!(
        "sha256:{:x}",
        Sha256::digest(serde_jcs::to_vec(&module["contract"]).unwrap())
    )
    .into();
    value["layers"][0]["entries"][0]["inject"] = json!({});
    mutate(&mut value);
    let digest =
        bundle_manifest_digest_v2(&serde_json::from_value(value.clone()).unwrap()).unwrap();
    value["digest"] = digest.clone().into();
    let pkcs8 = Ed25519KeyPair::generate_pkcs8(&SystemRandom::new()).unwrap();
    let signer = Ed25519KeyPair::from_pkcs8(pkcs8.as_ref()).unwrap();
    value["signature"] = STANDARD
        .encode(signer.sign(digest.as_bytes()).as_ref())
        .into();
    let mut spki = vec![
        0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00,
    ];
    spki.extend(signer.public_key().as_ref());
    let pem = format!(
        "-----BEGIN PUBLIC KEY-----\n{}\n-----END PUBLIC KEY-----",
        STANDARD.encode(spki)
    );
    let key = TrustedEd25519KeyV2::from_spki_pem(&pem).unwrap();
    let manifest: BundleManifestV2 = serde_json::from_value(value.clone()).unwrap();
    let mut zip = ZipWriter::new(Cursor::new(vec![]));
    zip.start_file("bundle.json", SimpleFileOptions::default())
        .unwrap();
    zip.write_all(&serde_json::to_vec(&value).unwrap()).unwrap();
    zip.start_file("artifacts/marker.wasm", SimpleFileOptions::default())
        .unwrap();
    zip.write_all(&bytes).unwrap();
    let raw = zip.finish().unwrap().into_inner();
    let reference = BundleReferenceV2 {
        bundle_id: manifest.bundle_id.clone(),
        version: manifest.version.clone(),
        digest,
        source: "marketplace://qa-marketplace-marker-bundle/1.0.0".into(),
    };
    let archive = verify_signed_bundle_archive_v2(
        &raw,
        &reference,
        std::slice::from_ref(&key),
        &BTreeSet::from(["tools.execute".into()]),
    )
    .unwrap();
    let mut snapshot = json!({"schema_version":2,"profile_id":"signed-local-wasm", "generation":1,
        "manifests":manifest.manifests,"entries":manifest.layers[0].entries});
    snapshot["digest"] = format!(
        "{:x}",
        Sha256::digest(serde_jcs::to_vec(&snapshot).unwrap())
    )
    .into();
    let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&snapshot.to_string()).unwrap();
    (archive, snapshot, raw, key, pem)
}
