use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicAddWorkspaceMemberInput, PublicDeleteWorkspaceInput,
    PublicRemoveWorkspaceMemberInput, PublicUpdateWorkspaceInput, PublicUpdateWorkspaceMemberInput,
    PublicWorkspaceMemberMutationService, PublicWorkspaceMutationContext,
    PublicWorkspaceMutationErrorKind, PublicWorkspaceMutationService, WorkspaceCreationService,
    WorkspaceMemberRole,
};
use serde_json::json;

#[tokio::test]
async fn update_workspace_commits_revision_outbox_and_idempotent_response()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let service = PublicWorkspaceMutationService::new(&db, DbSqlFlavor::Sqlite);
    let input = update_input("update-intent", Some(1), "Renamed Space");

    let updated = service.update(&input).await?;
    let replayed = service.update(&input).await?;

    assert_eq!(updated.committed_revision, 2);
    assert!(!updated.replayed);
    assert_eq!(updated.response["name"], "Renamed Space");
    assert!(replayed.replayed);
    assert_eq!(replayed.receipt_id, updated.receipt_id);
    assert_eq!(replayed.response, updated.response);
    assert_eq!(
        scalar_string(&db, "SELECT name AS value FROM workspace_profiles").await?,
        "Renamed Space"
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        2
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        2
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT event_type AS value FROM workspace_outbox ORDER BY event_sequence DESC LIMIT 1",
        )
        .await?,
        "workspace_updated"
    );
    Ok(())
}

#[tokio::test]
async fn autonomous_update_ensures_one_bootstrap_and_skips_an_existing_goal_root()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    for ddl in [
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, \
         project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, metadata_json TEXT NOT NULL)",
        "CREATE TABLE workspace_autonomy_bootstrap_outbox (bootstrap_id TEXT PRIMARY KEY, \
         tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL UNIQUE, \
         actor_id TEXT NOT NULL, objective_title TEXT NOT NULL, objective_description TEXT, \
         status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, \
         max_attempts INTEGER NOT NULL DEFAULT 8, next_attempt_at_ms INTEGER NOT NULL DEFAULT 0, \
         lease_generation INTEGER NOT NULL DEFAULT 0, created_at_ms INTEGER NOT NULL)",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    let service = PublicWorkspaceMutationService::new(&db, DbSqlFlavor::Sqlite);
    let transition = PublicUpdateWorkspaceInput {
        context: mutation_context("autonomous-transition", Some(1), "owner-1"),
        name: Some("Autonomous Space".to_string()),
        description: Some("Advance the root objective".to_string()),
        is_archived: None,
        metadata: Some(json!({
            "workspace_type": "general",
            "collaboration_mode": "autonomous"
        })),
    };

    service.update(&transition).await?;
    service.update(&transition).await?;
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT actor_id AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        "owner-1"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT objective_title AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        "Autonomous Space"
    );

    db.execute(DbStatement::new(
        "DELETE FROM workspace_autonomy_bootstrap_outbox",
    ))
    .await?;
    service
        .update(&PublicUpdateWorkspaceInput {
            context: mutation_context("autonomous-repair", Some(2), "owner-1"),
            name: Some("Autonomous Space Repaired".to_string()),
            description: None,
            is_archived: None,
            metadata: None,
        })
        .await?;
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        1
    );

    db.execute(DbStatement::new(
        "DELETE FROM workspace_autonomy_bootstrap_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, metadata_json) \
         VALUES ('root-1', 'tenant-1', 'project-1', 'workspace-1', \
         '{\"task_role\":\"goal_root\",\"objective_id\":\"objective-1\"}')",
    ))
    .await?;
    service
        .update(&PublicUpdateWorkspaceInput {
            context: mutation_context("autonomous-existing-root", Some(3), "owner-1"),
            name: Some("Autonomous Space With Root".to_string()),
            description: None,
            is_archived: None,
            metadata: None,
        })
        .await?;
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        0
    );
    Ok(())
}

#[tokio::test]
async fn update_workspace_rejects_stale_revision_without_partial_writes()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let service = PublicWorkspaceMutationService::new(&db, DbSqlFlavor::Sqlite);

    let error = match service
        .update(&update_input("stale-intent", Some(0), "Must Not Commit"))
        .await
    {
        Ok(_) => return Err("stale revision must fail".into()),
        Err(error) => error,
    };

    assert_eq!(error.kind(), PublicWorkspaceMutationErrorKind::Conflict);
    assert_eq!(
        scalar_string(&db, "SELECT name AS value FROM workspace_profiles").await?,
        "Team Space"
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn delete_workspace_tombstones_group_and_preserves_replay_history()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let service = PublicWorkspaceMutationService::new(&db, DbSqlFlavor::Sqlite);
    let input = PublicDeleteWorkspaceInput {
        context: mutation_context("delete-intent", Some(1), "owner-1"),
    };

    let deleted = service.delete(&input).await?;
    let replayed = service.delete(&input).await?;

    assert_eq!(deleted.committed_revision, 2);
    assert!(!deleted.replayed);
    assert!(replayed.replayed);
    assert_eq!(replayed.receipt_id, deleted.receipt_id);
    assert_eq!(
        scalar_string(&db, "SELECT deleted_by AS value FROM workspace_profiles").await?,
        "owner-1"
    );
    assert_eq!(
        scalar_string(&db, "SELECT lifecycle_status AS value FROM bcs_groups").await?,
        "deleted"
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        )
        .await?,
        2
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        2
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT event_type AS value FROM workspace_outbox ORDER BY event_sequence DESC LIMIT 1",
        )
        .await?,
        "workspace_deleted"
    );
    Ok(())
}

#[tokio::test]
async fn update_and_delete_preserve_legacy_role_permissions() -> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('viewer-member', 'tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer-1', 'viewer')",
    ))
    .await?;
    let service = PublicWorkspaceMutationService::new(&db, DbSqlFlavor::Sqlite);

    let update_error = match service
        .update(&PublicUpdateWorkspaceInput {
            context: mutation_context("viewer-update", Some(1), "viewer-1"),
            name: Some("Forbidden".to_string()),
            description: None,
            is_archived: None,
            metadata: None,
        })
        .await
    {
        Ok(_) => return Err("viewer update must fail".into()),
        Err(error) => error,
    };
    let delete_error = match service
        .delete(&PublicDeleteWorkspaceInput {
            context: mutation_context("viewer-delete", Some(1), "viewer-1"),
        })
        .await
    {
        Ok(_) => return Err("viewer delete must fail".into()),
        Err(error) => error,
    };

    assert_eq!(
        update_error.kind(),
        PublicWorkspaceMutationErrorKind::Forbidden
    );
    assert_eq!(
        delete_error.kind(),
        PublicWorkspaceMutationErrorKind::Forbidden
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn member_mutations_commit_acl_bcs_roster_revision_and_outbox() -> Result<(), Box<dyn Error>>
{
    let db = seeded_db().await?;
    seed_project_member(&db, "member-user").await?;
    let service = PublicWorkspaceMemberMutationService::new(&db, DbSqlFlavor::Sqlite);
    let add_input = PublicAddWorkspaceMemberInput {
        context: mutation_context("member-add", Some(1), "owner-1"),
        user_id: "member-user".to_string(),
        role: WorkspaceMemberRole::Viewer,
    };

    let added = service.add(&add_input).await?;
    let replayed_add = service.add(&add_input).await?;
    let updated = service
        .update(&PublicUpdateWorkspaceMemberInput {
            context: mutation_context("member-update", Some(2), "owner-1"),
            user_id: "member-user".to_string(),
            role: WorkspaceMemberRole::Editor,
        })
        .await?;
    let remove_input = PublicRemoveWorkspaceMemberInput {
        context: mutation_context("member-remove", Some(3), "owner-1"),
        user_id: "member-user".to_string(),
    };
    let removed = service.remove(&remove_input).await?;
    let replayed_remove = service.remove(&remove_input).await?;

    assert_eq!(added.committed_revision, 2);
    assert_eq!(added.response["role"], "viewer");
    assert!(replayed_add.replayed);
    assert_eq!(updated.committed_revision, 3);
    assert_eq!(updated.response["role"], "editor");
    assert_eq!(removed.committed_revision, 4);
    assert!(replayed_remove.replayed);
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        4
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_members").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM bcs_group_participants").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        4
    );
    Ok(())
}

#[tokio::test]
async fn add_member_requires_project_membership_without_partial_roster_writes()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let service = PublicWorkspaceMemberMutationService::new(&db, DbSqlFlavor::Sqlite);

    let error = match service
        .add(&PublicAddWorkspaceMemberInput {
            context: mutation_context("missing-project-member", Some(1), "owner-1"),
            user_id: "outside-user".to_string(),
            role: WorkspaceMemberRole::Viewer,
        })
        .await
    {
        Ok(_) => return Err("outside Project principal must be rejected".into()),
        Err(error) => error,
    };

    assert_eq!(error.kind(), PublicWorkspaceMutationErrorKind::Forbidden);
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_members").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM bcs_group_participants").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn member_owner_guards_match_legacy_self_demotion_and_removal_rules()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    seed_project_member(&db, "owner-2").await?;
    let service = PublicWorkspaceMemberMutationService::new(&db, DbSqlFlavor::Sqlite);
    service
        .add(&PublicAddWorkspaceMemberInput {
            context: mutation_context("add-second-owner", Some(1), "owner-1"),
            user_id: "owner-2".to_string(),
            role: WorkspaceMemberRole::Owner,
        })
        .await?;

    let demote_self = match service
        .update(&PublicUpdateWorkspaceMemberInput {
            context: mutation_context("demote-self", Some(2), "owner-1"),
            user_id: "owner-1".to_string(),
            role: WorkspaceMemberRole::Editor,
        })
        .await
    {
        Ok(_) => return Err("owner cannot demote itself".into()),
        Err(error) => error,
    };
    let remove_other_owner = match service
        .remove(&PublicRemoveWorkspaceMemberInput {
            context: mutation_context("remove-other-owner", Some(2), "owner-1"),
            user_id: "owner-2".to_string(),
        })
        .await
    {
        Ok(_) => return Err("owner cannot remove another owner".into()),
        Err(error) => error,
    };
    let remove_self = service
        .remove(&PublicRemoveWorkspaceMemberInput {
            context: mutation_context("remove-self-owner", Some(2), "owner-1"),
            user_id: "owner-1".to_string(),
        })
        .await?;

    assert_eq!(
        demote_self.kind(),
        PublicWorkspaceMutationErrorKind::Validation
    );
    assert_eq!(
        remove_other_owner.kind(),
        PublicWorkspaceMutationErrorKind::Validation
    );
    assert_eq!(remove_self.committed_revision, 3);
    assert_eq!(
        scalar_string(
            &db,
            "SELECT user_id AS value FROM workspace_members WHERE role = 'owner'",
        )
        .await?,
        "owner-2"
    );
    Ok(())
}

fn update_input(
    idempotency_key: &str,
    expected_revision: Option<u64>,
    name: &str,
) -> PublicUpdateWorkspaceInput {
    PublicUpdateWorkspaceInput {
        context: mutation_context(idempotency_key, expected_revision, "owner-1"),
        name: Some(name.to_string()),
        description: Some("Updated description".to_string()),
        is_archived: Some(true),
        metadata: Some(json!({"workspace_type": "general", "updated": true})),
    }
}

fn mutation_context(
    idempotency_key: &str,
    expected_revision: Option<u64>,
    user_id: &str,
) -> PublicWorkspaceMutationContext {
    PublicWorkspaceMutationContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        user_id: user_id.to_string(),
        expected_revision,
        idempotency_key: Some(idempotency_key.to_string()),
    }
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = empty_db().await?;
    WorkspaceCreationService::new(&db, DbSqlFlavor::Sqlite)
        .create(&CreateWorkspaceInput {
            scope: CreateWorkspaceScopeInput {
                tenant_id: "tenant-1".to_string(),
                project_id: "project-1".to_string(),
                workspace_id: "workspace-1".to_string(),
                group_id: "group-workspace-1".to_string(),
            },
            owner: CreateWorkspaceOwnerInput {
                member_id: "member-1".to_string(),
                user_id: "owner-1".to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "Team Space".to_string(),
                description: Some("Shared workspace".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "create-intent".to_string(),
        })
        .await?;
    Ok(db)
}

async fn empty_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE bcs_groups (group_id TEXT NOT NULL, label TEXT, status TEXT NOT NULL, driver_bot TEXT NOT NULL, originator TEXT, env TEXT NOT NULL, routing_policy_json TEXT, context TEXT, group_kind TEXT NOT NULL DEFAULT 'normal', version INTEGER NOT NULL DEFAULT 1, record_status TEXT NOT NULL DEFAULT 'active', lifecycle_status TEXT NOT NULL DEFAULT 'active', group_strategy TEXT NOT NULL DEFAULT 'chat', created_by TEXT, visibility TEXT NOT NULL DEFAULT 'private', gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(group_id, env))",
        "CREATE TABLE bcs_group_participants (group_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, role TEXT NOT NULL, env TEXT NOT NULL, actor_kind TEXT NOT NULL DEFAULT 'bot', mode TEXT NOT NULL DEFAULT 'auto', gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(env, group_id, bot_uuid))",
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, is_archived INTEGER NOT NULL DEFAULT 0, office_status TEXT NOT NULL DEFAULT 'inactive', hex_layout_config_json TEXT NOT NULL DEFAULT '{}', default_blocking_categories_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT, deleted_by TEXT, UNIQUE(tenant_id, project_id, workspace_id), UNIQUE(tenant_id, project_id, name))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, invited_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(workspace_id, user_id), UNIQUE(workspace_id, participant_actor_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, is_active) VALUES ('tenant-1', 'project-1', 'owner-1', 'owner-1', 1)",
    ))
    .await?;
    Ok(db)
}

async fn seed_project_member(db: &dyn DbPlugin, user_id: &str) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::with_params(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, is_active) VALUES ('tenant-1', 'project-1', ?, ?, 1)",
        vec![user_id.into(), user_id.into()],
    ))
    .await?;
    Ok(())
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}
