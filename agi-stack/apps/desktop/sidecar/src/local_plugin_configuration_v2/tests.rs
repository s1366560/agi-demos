use super::*;

const ENTRY_ID: &str = "builtin-desktop-settings-general";
const ALTERNATE_PLUGIN_ID: &str = "test-compatible-desktop-renderer";
const ALTERNATE_MODULE_REF: &str = "builtin://test/compatible-desktop-renderer";

fn fixture() -> (ProfileSnapshotV2, ScopeV2, LocalProfileConfigurationV2) {
    let mut snapshot = agistack_plugin_host::parse_profile_snapshot_v2(include_str!(
        "../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    let entry = snapshot
        .entries
        .iter()
        .find(|entry| entry.entry_id == ENTRY_ID)
        .unwrap();
    let mut manifest = snapshot
        .manifests
        .iter()
        .find(|manifest| manifest.plugin_id == entry.plugin_ref)
        .unwrap()
        .clone();
    let mut alternate = module(&snapshot, entry).unwrap().clone();
    alternate.module_ref = ALTERNATE_MODULE_REF.into();
    manifest.plugin_id = ALTERNATE_PLUGIN_ID.into();
    manifest.modules = vec![alternate];
    // The fixture models an already admitted compatible candidate. It does not
    // register an implementation or alter the production module trust catalog.
    snapshot.manifests.push(manifest);
    snapshot.digest = digest(&json!(snapshot), true)
        .unwrap()
        .trim_start_matches("sha256:")
        .into();
    let scope = ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some("test-tenant".into()),
        project_id: Some("test-project".into()),
        session_id: None,
    };
    let configuration = baseline(&snapshot, &scope).unwrap();
    (snapshot, scope, configuration)
}

fn replacement(plugin_id: &str, module_ref: &str) -> InstanceChangeV2 {
    InstanceChangeV2 {
        entry_id: ENTRY_ID.into(),
        enabled: None,
        config: None,
        replacement: Some(ReplacementV2 {
            plugin_id: plugin_id.into(),
            module_ref: module_ref.into(),
        }),
    }
}

#[test]
fn compatible_implementation_replacement_restores_without_changing_neighbors() {
    let (base, scope, current) = fixture();
    let original = base
        .entries
        .iter()
        .find(|entry| entry.entry_id == ENTRY_ID)
        .unwrap();
    let request = replacement(ALTERNATE_PLUGIN_ID, ALTERNATE_MODULE_REF);
    let listed = rows(&base, &scope, true).unwrap();
    let row = listed
        .iter()
        .find(|row| row["entry_id"] == ENTRY_ID)
        .unwrap();
    assert!(row["replacement_candidates"]
        .as_array()
        .unwrap()
        .contains(&json!(request.replacement)));

    let updated = revise(&base, &current, &scope, 1, &[request]).unwrap();
    let replaced = compose(&base, &updated, &scope).unwrap();
    let mut expected = original.clone();
    expected.plugin_ref = ALTERNATE_PLUGIN_ID.into();
    expected.module_ref = ALTERNATE_MODULE_REF.into();
    expected.scope = scope.clone();
    assert_eq!(updated.desired.revision, 2);
    assert_eq!(replaced.generation, base.generation + 1);
    assert_eq!(
        replaced
            .entries
            .iter()
            .find(|entry| entry.entry_id == ENTRY_ID),
        Some(&expected)
    );
    assert_eq!(
        replaced
            .entries
            .iter()
            .filter(|entry| entry.entry_id != ENTRY_ID)
            .collect::<Vec<_>>(),
        base.entries
            .iter()
            .filter(|entry| entry.entry_id != ENTRY_ID)
            .collect::<Vec<_>>()
    );

    let restored = revise(
        &base,
        &updated,
        &scope,
        2,
        &[replacement(&original.plugin_ref, &original.module_ref)],
    )
    .unwrap();
    let restored_snapshot = compose(&base, &restored, &scope).unwrap();
    expected.plugin_ref.clone_from(&original.plugin_ref);
    expected.module_ref.clone_from(&original.module_ref);
    assert_eq!(restored.desired.revision, 3);
    assert_eq!(restored.source.layers.len(), 2);
    assert_eq!(
        restored_snapshot
            .entries
            .iter()
            .find(|entry| entry.entry_id == ENTRY_ID),
        Some(&expected)
    );
    assert_ne!(replaced.digest, restored_snapshot.digest);
    assert_eq!(current.desired.revision, 1);
    assert!(current.source.layers.is_empty());
}

#[test]
fn rejected_replacement_batch_preserves_the_previous_configuration() {
    let (base, scope, baseline) = fixture();
    let current = revise(
        &base,
        &baseline,
        &scope,
        1,
        &[replacement(ALTERNATE_PLUGIN_ID, ALTERNATE_MODULE_REF)],
    )
    .unwrap();
    let retained = compose(&base, &current, &scope).unwrap();
    let before = json!(current);
    let original = base
        .entries
        .iter()
        .find(|entry| entry.entry_id == ENTRY_ID)
        .unwrap();
    let restore = replacement(&original.plugin_ref, &original.module_ref);
    let missing = InstanceChangeV2 {
        entry_id: "missing-entry".into(),
        enabled: Some(false),
        config: None,
        replacement: None,
    };
    for (revision, changes, expected) in [
        (1, vec![restore.clone()], "instance_revision_conflict"),
        (
            2,
            vec![replacement("unknown-plugin", "builtin://test/unknown")],
            "instance_replacement_incompatible",
        ),
        (2, vec![restore.clone(), missing], "instance_change_invalid"),
        (2, vec![restore.clone(), restore], "instance_change_invalid"),
    ] {
        assert_eq!(
            revise(&base, &current, &scope, revision, &changes).unwrap_err(),
            expected
        );
        assert_eq!(json!(current), before);
        assert_eq!(compose(&base, &current, &scope).unwrap(), retained);
    }
}

#[test]
fn replacement_cannot_carry_invalid_config_or_cross_project_scope() {
    let (base, scope, current) = fixture();
    let mut request = replacement(ALTERNATE_PLUGIN_ID, ALTERNATE_MODULE_REF);
    request.config = Some(BTreeMap::from([("unexpected".into(), json!(true))]));
    let before = json!(current);
    assert!(revise(&base, &current, &scope, 1, &[request]).is_err());
    assert_eq!(json!(current), before);

    let updated = revise(
        &base,
        &current,
        &scope,
        1,
        &[replacement(ALTERNATE_PLUGIN_ID, ALTERNATE_MODULE_REF)],
    )
    .unwrap();
    let foreign_scope = ScopeV2 {
        project_id: Some("other-project".into()),
        ..scope
    };
    assert_eq!(
        compose(&base, &updated, &foreign_scope).unwrap_err(),
        "instance_scope_mismatch"
    );
    assert_eq!(json!(current), before);
}
