#![cfg(not(target_arch = "wasm32"))]

use agistack_plugin_host::protocol_v2::signed_archive::{
    bundle_manifest_digest_v2, verify_signed_bundle_archive_v2, TrustedEd25519KeyV2,
};
use agistack_plugin_host::protocol_v2::{BundleReferenceV2, DataPlaneTargetV2};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use ring::{
    rand::SystemRandom,
    signature::{Ed25519KeyPair, KeyPair},
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    io::{Cursor, Read, Write},
};
use zip::{write::SimpleFileOptions, ZipArchive, ZipWriter};

const ARCHIVE: &[u8] = include_bytes!(
    "../../../../src/tests/unit/infrastructure/plugins/v2/fixtures/signed_wasm_marker/marker.mspkg"
);
const PUBLIC_KEY: &str = include_str!("../../../../src/tests/unit/infrastructure/plugins/v2/fixtures/signed_wasm_marker/signer-public.pem");

fn files() -> Vec<(String, Vec<u8>)> {
    let mut zip = ZipArchive::new(Cursor::new(ARCHIVE)).expect("real fixture ZIP");
    (0..zip.len())
        .map(|index| {
            let mut file = zip.by_index(index).expect("file");
            let name = file.name().to_owned();
            let mut bytes = vec![];
            file.read_to_end(&mut bytes).expect("bytes");
            (name, bytes)
        })
        .collect()
}

fn pack(files: &[(String, Vec<u8>)]) -> Vec<u8> {
    let mut zip = ZipWriter::new(Cursor::new(vec![]));
    for (name, bytes) in files {
        zip.start_file(name, SimpleFileOptions::default())
            .expect("ZIP entry");
        zip.write_all(bytes).expect("ZIP contents");
    }
    zip.finish().expect("ZIP finish").into_inner()
}

fn reference(value: &Value) -> BundleReferenceV2 {
    BundleReferenceV2 {
        bundle_id: value["bundle_id"].as_str().unwrap().into(),
        version: value["version"].as_str().unwrap().into(),
        digest: value["digest"].as_str().unwrap().into(),
        source: "marketplace://qa-marketplace-marker-bundle/1.0.0".into(),
    }
}

fn fixture_reference() -> BundleReferenceV2 {
    let all = files();
    let descriptor = &all
        .iter()
        .find(|(name, _)| name == "bundle.json")
        .unwrap()
        .1;
    reference(&serde_json::from_slice::<Value>(descriptor).unwrap())
}

fn approved() -> BTreeSet<String> {
    BTreeSet::from(["tools.execute".to_owned()])
}
fn key() -> TrustedEd25519KeyV2 {
    TrustedEd25519KeyV2::from_spki_pem(PUBLIC_KEY).unwrap()
}

fn rejection(
    raw: &[u8],
    expected: &BundleReferenceV2,
    keys: &[TrustedEd25519KeyV2],
    permissions: &BTreeSet<String>,
) -> &'static str {
    match verify_signed_bundle_archive_v2(raw, expected, keys, permissions) {
        Ok(_) => panic!("archive should be rejected"),
        Err(error) => error.code,
    }
}

/// Changes are signed with an ephemeral real Ed25519 key to exercise post-signature policy.
fn signed_change(
    change: impl FnOnce(&mut Value),
) -> (Vec<u8>, BundleReferenceV2, TrustedEd25519KeyV2) {
    let mut all = files();
    let descriptor = &mut all
        .iter_mut()
        .find(|(name, _)| name == "bundle.json")
        .unwrap()
        .1;
    let mut value: Value = serde_json::from_slice(descriptor).unwrap();
    change(&mut value);
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
    let expected = reference(&value);
    *descriptor = serde_json::to_vec(&value).unwrap();
    (pack(&all), expected, key)
}

#[test]
fn python_signed_archive_verifies_and_preserves_package_module_attribution() {
    let reference = fixture_reference();
    let verified =
        verify_signed_bundle_archive_v2(ARCHIVE, &reference, &[key()], &approved()).unwrap();
    let artifact = verified
        .wasm_artifact(
            "qa-marketplace-marker",
            "wasm://qa-marketplace-marker/score-v1",
            DataPlaneTargetV2::Python,
        )
        .unwrap();
    assert_eq!(artifact.reference(), &reference);
    assert_ne!(
        artifact.reference().bundle_id,
        artifact.manifest().plugin_id
    );
    assert_eq!(
        format!("sha256:{:x}", Sha256::digest(artifact.bytes())),
        artifact.module().artifact.digest
    );
    assert!(artifact.bytes().starts_with(b"\0asm"));
    assert_eq!(verified.approved_permissions(), &approved());
    assert!(verified
        .wasm_artifact(
            "qa-marketplace-marker",
            "wasm://qa-marketplace-marker/score-v1",
            DataPlaneTargetV2::DesktopSidecar
        )
        .is_err());
}

#[test]
fn untrusted_signature_and_missing_permissions_fail_closed() {
    assert_eq!(
        rejection(ARCHIVE, &fixture_reference(), &[], &approved()),
        "bundle_signature_untrusted"
    );
    let (_, _, other_key) = signed_change(|_| {});
    assert_eq!(
        rejection(ARCHIVE, &fixture_reference(), &[other_key], &approved()),
        "bundle_signature_invalid"
    );
    assert_eq!(
        rejection(ARCHIVE, &fixture_reference(), &[key()], &BTreeSet::new()),
        "bundle_permission_not_approved"
    );
}

#[test]
fn signed_sidecar_artifact_requires_both_declared_target_and_matching_inventory() {
    let (raw, reference, key) = signed_change(|value| {
        value["manifests"][0]["modules"][0]["targets"] = serde_json::json!(["desktop-sidecar"]);
        value["artifacts"][0]["target"] = "desktop-sidecar".into();
    });
    let verified = verify_signed_bundle_archive_v2(&raw, &reference, &[key], &approved()).unwrap();
    let artifact = verified
        .wasm_artifact(
            "qa-marketplace-marker",
            "wasm://qa-marketplace-marker/score-v1",
            DataPlaneTargetV2::DesktopSidecar,
        )
        .unwrap();
    assert!(artifact.bytes().starts_with(b"\0asm"));
    assert!(verified
        .wasm_artifact(
            "qa-marketplace-marker",
            "wasm://qa-marketplace-marker/score-v1",
            DataPlaneTargetV2::Python
        )
        .is_err());
}

#[test]
fn missing_or_malformed_signature_cannot_construct_a_verified_value() {
    for (signature, expected) in [
        (Value::Null, "bundle_signature_required"),
        ("not base64".into(), "bundle_signature_invalid"),
    ] {
        let mut all = files();
        let descriptor = &mut all
            .iter_mut()
            .find(|(name, _)| name == "bundle.json")
            .unwrap()
            .1;
        let mut value: Value = serde_json::from_slice(descriptor).unwrap();
        value["signature"] = signature;
        *descriptor = serde_json::to_vec(&value).unwrap();
        assert_eq!(
            rejection(&pack(&all), &fixture_reference(), &[key()], &approved()),
            expected
        );
    }
}

#[test]
fn altered_bytes_missing_artifacts_and_extra_files_are_rejected() {
    let mut changed = files();
    let index = changed
        .iter()
        .position(|(name, _)| name != "bundle.json")
        .unwrap();
    changed[index].1[0] ^= 1;
    assert_eq!(
        rejection(&pack(&changed), &fixture_reference(), &[key()], &approved()),
        "bundle_artifact_digest_mismatch"
    );
    changed.remove(index);
    assert_eq!(
        rejection(&pack(&changed), &fixture_reference(), &[key()], &approved()),
        "bundle_artifact_missing"
    );
    let mut extra = files();
    extra.push(("extra.txt".into(), b"extra".to_vec()));
    assert_eq!(
        rejection(&pack(&extra), &fixture_reference(), &[key()], &approved()),
        "undeclared_archive_entry"
    );
}

#[test]
fn valid_signature_cannot_override_target_or_permission_ownership() {
    let (raw, reference, key) = signed_change(|value| {
        value["manifests"][0]["modules"][0]["targets"] = serde_json::json!(["desktop-sidecar"])
    });
    assert_eq!(
        rejection(&raw, &reference, &[key], &approved()),
        "bundle_artifact_coverage_missing"
    );
    let (raw, reference, key) = signed_change(|value| {
        value["layers"][0]["entries"][0]["permissions"] = serde_json::json!(["extra.permission"])
    });
    assert_eq!(
        rejection(&raw, &reference, &[key], &approved()),
        "bundle_permission_not_approved"
    );
}

#[test]
fn valid_signature_cannot_claim_builtin_namespace() {
    for plugin in ["memstack-runtime-kernel", "memstack-native-target-hosts"] {
        let (raw, reference, key) =
            signed_change(|value| value["manifests"][0]["plugin_id"] = plugin.into());
        assert_eq!(
            rejection(&raw, &reference, &[key], &approved()),
            "bundle_builtin_namespace_forbidden"
        );
    }
    let (raw, reference, key) = signed_change(|value| {
        value["manifests"][0]["modules"][0]["module_ref"] = "builtin://invented".into()
    });
    assert_eq!(
        rejection(&raw, &reference, &[key], &approved()),
        "bundle_builtin_namespace_forbidden"
    );
}

#[test]
fn provenance_and_exact_expected_reference_are_required() {
    let (raw, reference, key) = signed_change(|value| value["provenance"] = Value::Null);
    assert_eq!(
        rejection(&raw, &reference, &[key], &approved()),
        "bundle_provenance_required"
    );
    let mut reference = fixture_reference();
    reference.version = "9.0.0".into();
    assert_eq!(
        rejection(ARCHIVE, &reference, &[self::key()], &approved()),
        "bundle_reference_mismatch"
    );
}

#[test]
fn malformed_descriptor_and_zip_traversal_are_rejected() {
    let mut all = files();
    all.push(("../escape".into(), vec![]));
    assert_eq!(
        rejection(&pack(&all), &fixture_reference(), &[key()], &approved()),
        "unsafe_archive_path"
    );
    let mut all = files();
    let descriptor = &mut all
        .iter_mut()
        .find(|(name, _)| name == "bundle.json")
        .unwrap()
        .1;
    let mut value: Value = serde_json::from_slice(descriptor).unwrap();
    value["manifests"][0]["unexpected"] = true.into();
    *descriptor = serde_json::to_vec(&value).unwrap();
    assert_eq!(
        rejection(&pack(&all), &fixture_reference(), &[key()], &approved()),
        "bundle_descriptor_invalid"
    );
}
