#[allow(dead_code)]
#[path = "../src/local_plugin_installations_v2.rs"]
mod store;

use agistack_plugin_host::protocol_v2::{
    signed_archive::TrustedEd25519KeyV2, BundleReferenceV2, ScopeKindV2, ScopeV2,
};
use rusqlite::Connection;
use std::{
    collections::BTreeSet,
    io::{Cursor, Read},
};

const RAW: &[u8] = include_bytes!("../../../../../src/tests/unit/infrastructure/plugins/v2/fixtures/signed_wasm_marker/marker.mspkg");
const PEM: &str = include_str!("../../../../../src/tests/unit/infrastructure/plugins/v2/fixtures/signed_wasm_marker/signer-public.pem");
fn scope(project: &str) -> ScopeV2 {
    ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some("tenant-a".into()),
        project_id: Some(project.into()),
        session_id: None,
    }
}
fn reference() -> BundleReferenceV2 {
    let mut zip = zip::ZipArchive::new(Cursor::new(RAW)).unwrap();
    let mut raw = String::new();
    zip.by_name("bundle.json")
        .unwrap()
        .read_to_string(&mut raw)
        .unwrap();
    let value: serde_json::Value = serde_json::from_str(&raw).unwrap();
    BundleReferenceV2 {
        bundle_id: value["bundle_id"].as_str().unwrap().into(),
        version: value["version"].as_str().unwrap().into(),
        digest: value["digest"].as_str().unwrap().into(),
        source: "marketplace://qa-marketplace-marker-bundle/1.0.0".into(),
    }
}
fn keys() -> Vec<TrustedEd25519KeyV2> {
    vec![TrustedEd25519KeyV2::from_spki_pem(PEM).unwrap()]
}
fn grants() -> BTreeSet<String> {
    BTreeSet::from(["tools.execute".into()])
}

#[test]
fn installation_reopens_and_reverifies_without_serialized_proof() {
    let path = std::env::temp_dir().join(format!(
        "local-plugin-store-{}.sqlite",
        uuid::Uuid::new_v4()
    ));
    {
        let db = Connection::open(&path).unwrap();
        store::initialize(&db).unwrap();
        store::install(&db, &keys(), &scope("a"), &reference(), RAW, &grants()).unwrap();
        assert_eq!(store::load_enabled(&db, &keys()).unwrap().len(), 1);
    }
    let db = Connection::open(&path).unwrap();
    store::initialize(&db).unwrap();
    let items = store::load_enabled(&db, &keys()).unwrap();
    assert_eq!(items[0].scope, scope("a"));
    assert_eq!(items[0].archive.reference(), &reference());
    assert!(store::load_enabled(&db, &[]).is_err());
    db.execute(
        "UPDATE desktop_local_plugin_installations_v2 SET archive = x'00'",
        [],
    )
    .unwrap();
    assert!(store::load_enabled(&db, &keys()).is_err());
    drop(db);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn invalid_import_never_replaces_existing_installation() {
    let db = Connection::open_in_memory().unwrap();
    store::initialize(&db).unwrap();
    for (raw, trusted, approved) in [
        (RAW, vec![], grants()),
        (RAW, keys(), BTreeSet::new()),
        (&b"invalid"[..], keys(), grants()),
    ] {
        assert!(store::install(&db, &trusted, &scope("a"), &reference(), raw, &approved).is_err());
    }
    assert!(store::load_enabled(&db, &keys()).unwrap().is_empty());
    store::install(&db, &keys(), &scope("a"), &reference(), RAW, &grants()).unwrap();
    assert!(store::install(
        &db,
        &keys(),
        &scope("a"),
        &reference(),
        b"invalid",
        &grants()
    )
    .is_err());
    assert_eq!(store::load_enabled(&db, &keys()).unwrap().len(), 1);
}

#[test]
fn lifecycle_is_scoped_and_revocation_cannot_be_reenabled_without_approval() {
    let db = Connection::open_in_memory().unwrap();
    store::initialize(&db).unwrap();
    let reference = reference();
    store::install(&db, &keys(), &scope("a"), &reference, RAW, &grants()).unwrap();
    assert!(store::set_enabled(&db, &keys(), &scope("b"), &reference, false).is_err());
    store::set_enabled(&db, &keys(), &scope("a"), &reference, false).unwrap();
    assert!(store::load_enabled(&db, &keys()).unwrap().is_empty());
    store::set_enabled(&db, &keys(), &scope("a"), &reference, true).unwrap();
    store::revoke(&db, &scope("a"), &reference).unwrap();
    assert!(store::set_enabled(&db, &keys(), &scope("a"), &reference, true).is_err());
    assert!(store::load_enabled(&db, &keys()).unwrap().is_empty());
    store::uninstall(&db, &scope("a"), &reference).unwrap();
    assert!(store::uninstall(&db, &scope("a"), &reference).is_err());
}
