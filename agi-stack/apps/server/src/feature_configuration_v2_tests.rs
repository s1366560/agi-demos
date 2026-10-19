use serde_json::json;

use super::*;

fn source() -> Value {
    // Produced by Python profile_source_digest_v2 from the generated dataclasses.
    serde_json::from_str(r#"{"schema_version":2,"source_id":"test-source","profile_id":"test-profile","revision":1,"digest":"sha256:37ba4a6f3bdf2b195db274e4425d6ea59f9821e73d37e072ae3e0901590d35f4","provenance":null,"layers":[{"layer_id":"base","kind":"profile","scope":{"kind":"root"},"entries":[{"entry_id":"builtin-web-feature-tenant-skills","parent_entry_id":null,"plugin_ref":"test","module_ref":"builtin://test/feature","enabled":true,"config":{},"inject":{},"isolate":{},"scope":{"kind":"root"},"permissions":[],"quotas":{},"restart_policy":"hot-generation"}],"replacements":[],"disabled_entry_ids":[]}]}"#).unwrap()
}

fn project() -> ScopeV2 {
    ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some("tenant".into()),
        project_id: Some("project".into()),
        session_id: None,
    }
}

fn applied(source: Value) -> AppliedSourceRow {
    AppliedSourceRow {
        applied_publication_id: Some("accepted".into()),
        applied_version: Some(4),
        applied_digest: Some("accepted-digest".into()),
        requested_version: Some(4),
        snapshot_digest: Some("accepted-digest".into()),
        distribution: None,
        desired: Some(
            json!({"profile_source":{"source_id":source["source_id"],"revision":source["revision"],"digest":source["digest"]}}),
        ),
        source: Some(source),
    }
}

#[test]
fn python_source_digest_normalizes_omitted_nullable_fields_and_rejects_changes() {
    verify_source_digest(&source()).unwrap();
    let mut tampered = source();
    tampered["layers"][0]["entries"][0]["enabled"] = json!(false);
    assert_eq!(
        verify_source_digest(&tampered).unwrap_err().code,
        "feature_configuration_unavailable"
    );
}

#[test]
fn partial_ledger_schema_never_falls_back_to_defaults() {
    assert!(!has_shared_ledger(0).unwrap());
    assert!(has_shared_ledger(5).unwrap());
    for count in 1..5 {
        assert!(has_shared_ledger(count).is_err());
    }
}

#[test]
fn accepted_binding_uses_its_exact_source_and_rejects_incomplete_or_wrong_identity() {
    let decoded = decode_accepted_configuration(&project(), applied(source())).unwrap();
    require_enabled(
        &feature_entries(decoded, &project()).unwrap(),
        &["tenant-skills"],
    )
    .unwrap();
    let mut row = applied(source());
    row.requested_version = Some(5);
    assert!(decode_accepted_configuration(&project(), row).is_err());
    let mut row = applied(source());
    row.snapshot_digest = Some("different".into());
    assert!(decode_accepted_configuration(&project(), row).is_err());
    let mut row = applied(source());
    row.applied_publication_id = None;
    assert!(decode_accepted_configuration(&project(), row).is_err());
    let mut row = applied(source());
    row.desired.as_mut().unwrap()["profile_source"]["revision"] = json!(2);
    assert!(decode_accepted_configuration(&project(), row).is_err());
}

#[test]
fn project_replacement_can_enable_its_copied_feature_and_other_scopes_do_not_apply() {
    let mut payload = source();
    let replacement = payload["layers"][0]["entries"][0].clone();
    payload["layers"][0]["disabled_entry_ids"] = json!(["builtin-web-feature-tenant-skills"]);
    payload["layers"].as_array_mut().unwrap().push(json!({"layer_id":"project","kind":"project","scope":{"kind":"project","tenant_id":"tenant","project_id":"project"},"entries":[],"replacements":[replacement],"disabled_entry_ids":[]}));
    let entries = feature_entries(
        AcceptedFeatureConfigurationV2::Source(payload.clone()),
        &project(),
    )
    .unwrap();
    require_enabled(&entries, &["tenant-skills"]).unwrap();
    let mut other = project();
    other.project_id = Some("other".into());
    let entries = feature_entries(AcceptedFeatureConfigurationV2::Source(payload), &other).unwrap();
    assert_eq!(
        require_enabled(&entries, &["tenant-skills"])
            .unwrap_err()
            .code,
        "feature_disabled"
    );
}

#[test]
fn disabled_parent_blocks_feature_and_legacy_snapshot_is_root_only() {
    let mut entries =
        feature_entries(AcceptedFeatureConfigurationV2::Source(source()), &project()).unwrap();
    let mut parent = entries["builtin-web-feature-tenant-skills"].clone();
    parent.entry_id = "parent".into();
    parent.enabled = false;
    entries
        .get_mut("builtin-web-feature-tenant-skills")
        .unwrap()
        .parent_entry_id = Some(parent.entry_id.clone());
    entries.insert(parent.entry_id.clone(), parent);
    assert_eq!(
        require_enabled(&entries, &["tenant-skills"])
            .unwrap_err()
            .code,
        "feature_disabled"
    );
    let mut row = applied(source());
    row.source = None;
    row.desired = None;
    row.distribution = Some(json!({"snapshot":{"digest":"accepted-digest","entries":[]}}));
    assert!(decode_accepted_configuration(&project(), row).is_err());
    let mut row = applied(source());
    row.source = None;
    row.desired = None;
    row.distribution = Some(json!({"snapshot":{"digest":"accepted-digest","entries":[]}}));
    let root = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    assert!(matches!(
        decode_accepted_configuration(&root, row).unwrap(),
        AcceptedFeatureConfigurationV2::Snapshot(_)
    ));
}
