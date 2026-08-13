use super::*;
use rusqlite::Connection;

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
    agent["allowed_tools"] = json!(["terminal"]);
    agent["allowed_skills"] = json!(["code-exploration"]);
    agent["allowed_mcp_servers"] = json!(["local-runtime"]);
    agent
        .as_object_mut()
        .expect("agent object")
        .remove("can_spawn");
    agent
        .as_object_mut()
        .expect("agent object")
        .remove("spawn_policy");
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
    assert_eq!(agent["allowed_tools"], json!(["*"]));
    assert_eq!(agent["allowed_skills"], json!(["*"]));
    assert_eq!(agent["allowed_mcp_servers"], json!(["*"]));
    assert_eq!(agent["can_spawn"], true);
    assert_eq!(agent["spawn_policy"]["allowed_subagents"], json!(["*"]));
}

#[test]
fn managed_resource_v2_records_versions_receipts_rollbacks_and_tombstones() {
    let store = DesktopSessionStore::in_memory().expect("store");
    let create = ManagedResourceMutationCommand {
        actor_id: "user-local".to_string(),
        kind: ManagedResourceKind::SubAgent,
        scope_kind: "tenant".to_string(),
        scope_id: "local".to_string(),
        resource_id: "reviewer".to_string(),
        operation: ManagedResourceMutationOperation::Create,
        expected_revision: 0,
        idempotency_key: "subagent-create-1".to_string(),
        payload_hash: "sha256:create-reviewer".to_string(),
        status: "active".to_string(),
        value: Some(json!({
            "name": "reviewer",
            "display_name": "Reviewer",
            "system_prompt": "Review the supplied change.",
            "enabled": true,
            "source": "database",
        })),
        target_revision: None,
        vault_refs: vec!["vault://subagent/reviewer/provider".to_string()],
        now_ms: 1_752_384_000_000,
    };

    let created = store
        .mutate_managed_resource(create.clone())
        .expect("create subagent");
    assert!(!created.duplicate);
    assert_eq!(
        created.resource.as_ref().expect("created resource")["revision"],
        0
    );

    let replayed = store
        .mutate_managed_resource(create.clone())
        .expect("replay create");
    assert!(replayed.duplicate);
    assert_eq!(replayed.receipt_id, created.receipt_id);

    let conflicting_replay = store.mutate_managed_resource(ManagedResourceMutationCommand {
        payload_hash: "sha256:different-create".to_string(),
        ..create.clone()
    });
    assert!(matches!(
        conflicting_replay,
        Err(ResourceRegistryError::IdempotencyConflict)
    ));

    let updated = store
        .mutate_managed_resource(ManagedResourceMutationCommand {
            actor_id: "user-local".to_string(),
            kind: ManagedResourceKind::SubAgent,
            scope_kind: "tenant".to_string(),
            scope_id: "local".to_string(),
            resource_id: "reviewer".to_string(),
            operation: ManagedResourceMutationOperation::Update,
            expected_revision: 0,
            idempotency_key: "subagent-update-1".to_string(),
            payload_hash: "sha256:update-reviewer".to_string(),
            status: "active".to_string(),
            value: Some(json!({
                "name": "reviewer",
                "display_name": "Senior reviewer",
                "system_prompt": "Review the supplied change.",
                "enabled": true,
                "source": "database",
            })),
            target_revision: None,
            vault_refs: vec![],
            now_ms: 1_752_384_001_000,
        })
        .expect("update subagent");
    assert_eq!(
        updated.resource.as_ref().expect("updated resource")["revision"],
        1
    );

    let rolled_back = store
        .mutate_managed_resource(ManagedResourceMutationCommand {
            actor_id: "user-local".to_string(),
            kind: ManagedResourceKind::SubAgent,
            scope_kind: "tenant".to_string(),
            scope_id: "local".to_string(),
            resource_id: "reviewer".to_string(),
            operation: ManagedResourceMutationOperation::Rollback,
            expected_revision: 1,
            idempotency_key: "subagent-rollback-1".to_string(),
            payload_hash: "sha256:rollback-reviewer-0".to_string(),
            status: "active".to_string(),
            value: None,
            target_revision: Some(0),
            vault_refs: vec![],
            now_ms: 1_752_384_002_000,
        })
        .expect("rollback subagent");
    assert_eq!(
        rolled_back.resource.as_ref().expect("rolled back resource")["revision"],
        2
    );
    assert_eq!(
        rolled_back.resource.as_ref().expect("rolled back resource")["display_name"],
        "Reviewer"
    );

    let deleted = store
        .mutate_managed_resource(ManagedResourceMutationCommand {
            actor_id: "user-local".to_string(),
            kind: ManagedResourceKind::SubAgent,
            scope_kind: "tenant".to_string(),
            scope_id: "local".to_string(),
            resource_id: "reviewer".to_string(),
            operation: ManagedResourceMutationOperation::Delete,
            expected_revision: 2,
            idempotency_key: "subagent-delete-1".to_string(),
            payload_hash: "sha256:delete-reviewer".to_string(),
            status: "deleted".to_string(),
            value: None,
            target_revision: None,
            vault_refs: vec![],
            now_ms: 1_752_384_003_000,
        })
        .expect("delete subagent");
    assert!(deleted.resource.is_none());
    assert!(store
        .managed_resource(ManagedResourceKind::SubAgent, "tenant", "local", "reviewer",)
        .expect("deleted lookup")
        .is_none());

    let versions = store
        .list_managed_resource_versions(
            ManagedResourceKind::SubAgent,
            "tenant",
            "local",
            "reviewer",
        )
        .expect("subagent versions");
    assert_eq!(
        versions
            .iter()
            .map(|version| version.revision)
            .collect::<Vec<_>>(),
        vec![3, 2, 1, 0]
    );
    assert!(versions[0].tombstone);
    assert_eq!(versions[1].value["display_name"], "Reviewer");
}

#[test]
fn managed_resource_v2_migrates_the_legacy_kind_check_and_backfills_versions() {
    let connection = Connection::open_in_memory().expect("legacy connection");
    connection
        .execute_batch(
            "CREATE TABLE desktop_managed_resources (
               kind TEXT NOT NULL CHECK(kind IN ('provider', 'skill', 'plugin', 'agent')),
               scope_kind TEXT NOT NULL CHECK(scope_kind IN ('tenant', 'project')),
               scope_id TEXT NOT NULL,
               id TEXT NOT NULL,
               status TEXT NOT NULL,
               revision INTEGER NOT NULL CHECK(revision >= 0),
               created_at_ms INTEGER NOT NULL,
               updated_at_ms INTEGER NOT NULL,
               value_json TEXT NOT NULL,
               PRIMARY KEY(kind, scope_kind, scope_id, id)
             );
             INSERT INTO desktop_managed_resources(
               kind, scope_kind, scope_id, id, status, revision,
               created_at_ms, updated_at_ms, value_json
             ) VALUES (
               'skill', 'tenant', 'legacy', 'custom-skill', 'active', 4,
               1752384000000, 1752384000000,
               '{\"id\":\"custom-skill\",\"name\":\"Legacy\",\"revision\":4,\"status\":\"active\"}'
             );",
        )
        .expect("legacy resource schema");

    initialize_resource_registry(&connection).expect("migrate resource registry");

    let table_sql: String = connection
        .query_row(
            "SELECT sql FROM sqlite_master
             WHERE type = 'table' AND name = 'desktop_managed_resources'",
            [],
            |row| row.get(0),
        )
        .expect("resource table SQL");
    assert!(table_sql.contains("'subagent'"));
    assert!(table_sql.contains("'prompt_template'"));
    assert!(table_sql.contains("vault_refs_json"));

    let backfilled: i64 = connection
        .query_row(
            "SELECT COUNT(*) FROM desktop_managed_resource_versions
             WHERE kind = 'skill' AND scope_kind = 'tenant' AND scope_id = 'legacy'
               AND resource_id = 'custom-skill' AND revision = 4",
            [],
            |row| row.get(0),
        )
        .expect("backfilled version");
    assert_eq!(backfilled, 1);

    connection
        .execute(
            "INSERT INTO desktop_managed_resources(
               kind, scope_kind, scope_id, id, status, revision,
               created_at_ms, updated_at_ms, value_json, vault_refs_json
             ) VALUES (
               'prompt_template', 'tenant', 'legacy', 'template-1', 'active', 0,
               1752384000000, 1752384000000, '{}', '[]'
             )",
            [],
        )
        .expect("expanded kind check accepts prompt templates");
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
