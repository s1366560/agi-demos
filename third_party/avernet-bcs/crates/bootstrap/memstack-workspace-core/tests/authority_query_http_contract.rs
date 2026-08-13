use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{
    WorkspaceCoreState, desktop_schema::run_desktop_workspace_schema_migrations, workspace_router,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "authority-query-contract-token";

#[tokio::test]
async fn authority_query_batches_profiles_roles_archive_and_task_links()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(LocalSqliteDbPlugin::new()?);
    bcs::migrations::run_sqlite_migrations(db.as_ref()).await?;
    run_desktop_workspace_schema_migrations(db.as_ref()).await?;
    seed_authority(db.as_ref()).await?;
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db,
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    let response = workspace_router(state)
        .oneshot(authority_request(false, "member-1")?)
        .await?;
    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
    assert_eq!(body["profiles"].as_array().map(Vec::len), Some(2));
    assert_eq!(body["profiles"][0]["workspace_id"], "workspace-archived");
    assert_eq!(body["profiles"][0]["is_archived"], true);
    assert_eq!(body["profiles"][0]["member_role"], "viewer");
    assert_eq!(body["profiles"][1]["workspace_id"], "workspace-live");
    assert_eq!(body["profiles"][1]["name"], "Live Workspace");
    assert_eq!(body["profiles"][1]["member_role"], "editor");
    assert_eq!(body["task_links"][0]["linked"], true);
    assert_eq!(body["task_links"][1]["linked"], false);
    Ok(())
}

#[tokio::test]
async fn authority_query_hides_non_member_profiles_and_superuser_reads_without_role()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(LocalSqliteDbPlugin::new()?);
    bcs::migrations::run_sqlite_migrations(db.as_ref()).await?;
    run_desktop_workspace_schema_migrations(db.as_ref()).await?;
    seed_authority(db.as_ref()).await?;
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db,
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    let denied = workspace_router(Arc::clone(&state))
        .oneshot(authority_request(false, "outsider")?)
        .await?;
    assert_eq!(denied.status(), StatusCode::OK);
    let denied: Value = serde_json::from_slice(&to_bytes(denied.into_body(), usize::MAX).await?)?;
    assert_eq!(denied["profiles"], json!([]));
    assert_eq!(denied["task_links"][0]["linked"], false);

    let superuser = workspace_router(state)
        .oneshot(authority_request(true, "admin")?)
        .await?;
    let superuser: Value =
        serde_json::from_slice(&to_bytes(superuser.into_body(), usize::MAX).await?)?;
    assert_eq!(superuser["profiles"].as_array().map(Vec::len), Some(2));
    assert!(superuser["profiles"][0]["member_role"].is_null());
    assert_eq!(superuser["task_links"][0]["linked"], true);
    Ok(())
}

fn authority_request(is_superuser: bool, user_id: &str) -> Result<Request<Body>, Box<dyn Error>> {
    Ok(Request::builder()
        .method("POST")
        .uri("/internal/v1/workspace-authority/query")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "actor": {"user_id": user_id, "is_superuser": is_superuser},
                "workspace_ids": ["workspace-live", "workspace-archived", "workspace-missing"],
                "task_refs": [
                    {"workspace_id": "workspace-live", "task_id": "task-live"},
                    {"workspace_id": "workspace-live", "task_id": "task-missing"}
                ]
            })
            .to_string(),
        ))?)
}

async fn seed_authority(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for statement in [
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by, is_archived, metadata_json) VALUES ('workspace-live', 'tenant-1', 'project-1', 'group-live', 'Live Workspace', 'owner-1', 0, '{\"kind\":\"live\"}')",
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by, is_archived, metadata_json) VALUES ('workspace-archived', 'tenant-1', 'project-1', 'group-archived', 'Archived Workspace', 'owner-1', 1, '{}')",
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-live', 'tenant-1', 'project-1', 'workspace-live', 'member-1', 'human:member-1', 'editor')",
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-archived', 'tenant-1', 'project-1', 'workspace-archived', 'member-1', 'human:member-1', 'viewer')",
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, created_by) VALUES ('task-live', 'tenant-1', 'project-1', 'workspace-live', 'Live task', 'owner-1')",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(())
}
