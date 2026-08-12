use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceErrorKind, CreateWorkspaceInput,
    CreateWorkspaceOwnerInput, CreateWorkspaceScopeInput, WorkspaceCreationService,
};
use serde_json::json;

#[tokio::test]
async fn create_workspace_commits_and_replays_the_application_command() -> Result<(), Box<dyn Error>>
{
    let db = test_db(true).await?;
    let service = WorkspaceCreationService::new(&db, DbSqlFlavor::Sqlite);
    let input = create_input("Team Space");

    let created = service.create(&input).await?;
    let replayed = service.create(&input).await?;

    assert_eq!(created.committed_revision, 1);
    assert!(!created.replayed);
    assert_eq!(created.response["id"], "workspace-1");
    assert!(replayed.replayed);
    assert_eq!(replayed.receipt_id, created.receipt_id);
    assert_eq!(replayed.response, created.response);
    assert_eq!(table_count(&db, "workspace_profiles").await?, 1);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 1);
    Ok(())
}

#[tokio::test]
async fn create_workspace_rejects_changed_payload_for_the_same_intent() -> Result<(), Box<dyn Error>>
{
    let db = test_db(true).await?;
    let service = WorkspaceCreationService::new(&db, DbSqlFlavor::Sqlite);
    service.create(&create_input("Team Space")).await?;

    let error = match service.create(&create_input("Changed Space")).await {
        Ok(_) => return Err("changed idempotent payload must fail".into()),
        Err(error) => error,
    };

    assert_eq!(error.kind(), CreateWorkspaceErrorKind::Conflict);
    assert_eq!(table_count(&db, "workspace_profiles").await?, 1);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 1);
    Ok(())
}

#[tokio::test]
async fn create_workspace_denies_an_owner_without_project_membership() -> Result<(), Box<dyn Error>>
{
    let db = test_db(false).await?;
    let service = WorkspaceCreationService::new(&db, DbSqlFlavor::Sqlite);

    let error = match service.create(&create_input("Team Space")).await {
        Ok(_) => return Err("missing membership must fail".into()),
        Err(error) => error,
    };

    assert_eq!(error.kind(), CreateWorkspaceErrorKind::Forbidden);
    assert_eq!(table_count(&db, "workspace_profiles").await?, 0);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 0);
    Ok(())
}

fn create_input(name: &str) -> CreateWorkspaceInput {
    CreateWorkspaceInput {
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
            name: name.to_string(),
            description: Some("Shared workspace".to_string()),
            metadata: json!({"workspace_type": "general"}),
        },
        idempotency_key: "create-intent-1".to_string(),
    }
}

async fn test_db(project_member: bool) -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE bcs_groups (group_id TEXT NOT NULL, label TEXT, status TEXT NOT NULL, driver_bot TEXT NOT NULL, originator TEXT, env TEXT NOT NULL, routing_policy_json TEXT, context TEXT, group_kind TEXT NOT NULL DEFAULT 'normal', version INTEGER NOT NULL DEFAULT 1, record_status TEXT NOT NULL DEFAULT 'active', lifecycle_status TEXT NOT NULL DEFAULT 'active', group_strategy TEXT NOT NULL DEFAULT 'chat', created_by TEXT, visibility TEXT NOT NULL DEFAULT 'private', UNIQUE(group_id, env))",
        "CREATE TABLE bcs_group_participants (group_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, role TEXT NOT NULL, env TEXT NOT NULL, actor_kind TEXT NOT NULL DEFAULT 'bot', mode TEXT NOT NULL DEFAULT 'auto', UNIQUE(env, group_id, bot_uuid))",
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, is_archived INTEGER NOT NULL DEFAULT 0, office_status TEXT NOT NULL DEFAULT 'inactive', hex_layout_config_json TEXT NOT NULL DEFAULT '{}', default_blocking_categories_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT, deleted_by TEXT, UNIQUE(tenant_id, project_id, workspace_id), UNIQUE(tenant_id, project_id, name))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, invited_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(workspace_id, user_id), UNIQUE(workspace_id, participant_actor_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    if project_member {
        db.execute(DbStatement::new(
            "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, is_active) VALUES ('tenant-1', 'project-1', 'owner-1', 'owner-1', 1)",
        ))
        .await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_profiles" => "SELECT COUNT(*) AS value FROM workspace_profiles",
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows.first().ok_or("missing count row")?;
    Ok(row.get_i64("value")?.ok_or("missing count")?)
}
