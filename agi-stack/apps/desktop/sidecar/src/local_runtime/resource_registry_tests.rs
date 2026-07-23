use super::*;

#[test]
fn seeded_resources_are_scope_isolated_and_revision_guarded() {
    let store = DesktopSessionStore::in_memory().expect("store");
    let local_skills = store
        .list_managed_resources(ManagedResourceKind::Skill, "tenant", "local")
        .expect("local skills");
    let orbital_skills = store
        .list_managed_resources(ManagedResourceKind::Skill, "tenant", "orbital")
        .expect("orbital skills");
    assert_eq!(local_skills.len(), 3);
    assert_eq!(orbital_skills.len(), 3);

    let immutable = store.set_managed_resource_enabled(
        ManagedResourceKind::Skill,
        "tenant",
        "local",
        "implementation",
        false,
        1_752_384_000_000,
    );
    assert!(matches!(
        immutable,
        Err(ResourceRegistryError::Immutable {
            kind: ManagedResourceKind::Skill,
            ref id,
        }) if id == "implementation"
    ));
    let implementation = store
        .managed_resource(
            ManagedResourceKind::Skill,
            "tenant",
            "local",
            "implementation",
        )
        .expect("persisted skill")
        .expect("implementation skill");
    assert_eq!(implementation["revision"], 0);
    assert_eq!(implementation["status"], "active");

    let custom = store
        .put_managed_resource(
            ManagedResourceKind::Skill,
            "tenant",
            "local",
            "custom-skill",
            "active",
            None,
            json!({
                "name": "Custom skill",
                "scope": "tenant",
                "status": "active",
                "is_system_skill": false,
            }),
            1_752_384_000_000,
        )
        .expect("create mutable skill");
    assert_eq!(custom["revision"], 0);
    let disabled = store
        .set_managed_resource_enabled(
            ManagedResourceKind::Skill,
            "tenant",
            "local",
            "custom-skill",
            false,
            1_752_384_001_000,
        )
        .expect("disable mutable skill");
    assert_eq!(disabled["status"], "disabled");
    assert_eq!(disabled["revision"], 1);
    assert_eq!(orbital_skills[1]["status"], "active");
    assert!(store
        .managed_resource(
            ManagedResourceKind::Skill,
            "tenant",
            "orbital",
            "custom-skill",
        )
        .expect("orbital skill lookup")
        .is_none());

    let conflict = store.put_managed_resource(
        ManagedResourceKind::Skill,
        "tenant",
        "local",
        "custom-skill",
        "active",
        Some(0),
        disabled,
        1_752_384_002_000,
    );
    assert!(matches!(
        conflict,
        Err(ResourceRegistryError::RevisionConflict {
            expected: 0,
            actual: 1
        })
    ));

    store
        .put_managed_resource(
            ManagedResourceKind::Skill,
            "tenant",
            "local",
            "legacy-system-scope",
            "active",
            None,
            json!({
                "name": "Legacy system skill",
                "scope": "system",
                "status": "active",
                "is_system_skill": false,
            }),
            1_752_384_003_000,
        )
        .expect("create legacy system-scope skill");
    let immutable_scope = store.set_managed_resource_enabled(
        ManagedResourceKind::Skill,
        "tenant",
        "local",
        "legacy-system-scope",
        false,
        1_752_384_004_000,
    );
    assert!(matches!(
        immutable_scope,
        Err(ResourceRegistryError::Immutable {
            kind: ManagedResourceKind::Skill,
            ref id,
        }) if id == "legacy-system-scope"
    ));
}

#[test]
fn legacy_disabled_builtin_resources_are_reconciled_on_initialization() {
    let store = DesktopSessionStore::in_memory().expect("store");

    let mut skill = stored_resource(
        &store,
        ManagedResourceKind::Skill,
        "tenant",
        "local",
        "implementation",
    );
    skill["status"] = json!("disabled");
    write_legacy_resource(
        &store,
        ManagedResourceKind::Skill,
        "tenant",
        "local",
        "implementation",
        skill,
    );

    let mut plugin = stored_resource(
        &store,
        ManagedResourceKind::Plugin,
        "tenant",
        "local",
        "local-workspace",
    );
    plugin["enabled"] = json!(false);
    plugin["status"] = json!("disabled");
    write_legacy_resource(
        &store,
        ManagedResourceKind::Plugin,
        "tenant",
        "local",
        "local-workspace",
        plugin,
    );

    let mut agent = stored_resource(
        &store,
        ManagedResourceKind::Agent,
        "project",
        "local-project",
        "builtin:all-access",
    );
    agent["enabled"] = json!(false);
    agent["status"] = json!("disabled");
    agent
        .as_object_mut()
        .expect("agent object")
        .remove("source");
    write_legacy_resource(
        &store,
        ManagedResourceKind::Agent,
        "project",
        "local-project",
        "builtin:all-access",
        agent,
    );

    {
        let connection = store.connection().expect("resource registry connection");
        initialize_resource_registry(&connection).expect("reconcile resource registry");
    }

    let skill = stored_resource(
        &store,
        ManagedResourceKind::Skill,
        "tenant",
        "local",
        "implementation",
    );
    assert_eq!(skill["revision"], 5);
    assert_eq!(skill["status"], "active");
    assert_eq!(skill["is_system_skill"], true);

    let plugin = stored_resource(
        &store,
        ManagedResourceKind::Plugin,
        "tenant",
        "local",
        "local-workspace",
    );
    assert_eq!(plugin["revision"], 5);
    assert_eq!(plugin["status"], "active");
    assert_eq!(plugin["enabled"], true);
    assert_eq!(plugin["source"], "builtin");

    let agent = stored_resource(
        &store,
        ManagedResourceKind::Agent,
        "project",
        "local-project",
        "builtin:all-access",
    );
    assert_eq!(agent["revision"], 5);
    assert_eq!(agent["status"], "active");
    assert_eq!(agent["enabled"], true);
    assert_eq!(agent["source"], "builtin");
}

fn stored_resource(
    store: &DesktopSessionStore,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    id: &str,
) -> Value {
    store
        .managed_resource(kind, scope_kind, scope_id, id)
        .expect("stored resource lookup")
        .expect("stored resource")
}

fn write_legacy_resource(
    store: &DesktopSessionStore,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    id: &str,
    mut value: Value,
) {
    value["revision"] = json!(4);
    value["updated_at"] = json!("2025-07-20T00:00:00Z");
    let connection = store.connection().expect("resource registry connection");
    connection
        .execute(
            "UPDATE desktop_managed_resources
             SET status = 'disabled', revision = 4, updated_at_ms = 1752969600000,
                 value_json = ?1
             WHERE kind = ?2 AND scope_kind = ?3 AND scope_id = ?4 AND id = ?5",
            params![
                serde_json::to_string(&value).expect("legacy resource JSON"),
                kind.as_str(),
                scope_kind,
                scope_id,
                id,
            ],
        )
        .expect("write legacy resource");
}
