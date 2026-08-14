use std::error::Error;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{
    DbError, DbExecuteResult, DbHealth, DbPlugin, DbResult, DbRow, DbSqlFlavor, DbStatement,
    DbTransactionStep, DbTransactionStepResult, DbValue,
};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{
    WorkspaceCoreAuthority, WorkspaceCoreState,
    autonomy_bootstrap_worker::{
        WorkspaceAutonomyBootstrapWorker, WorkspaceAutonomyBootstrapWorkerConfig,
    },
    desktop_schema::run_desktop_workspace_schema_migrations,
    workspace_router,
};
use memstack_workspace_service::{
    PublicCreateWorkspaceObjectiveInput, PublicWorkspaceAutonomyAttentionService,
    PublicWorkspaceAutonomyBootstrapService, PublicWorkspaceAutonomyContext,
    PublicWorkspaceObjectiveContext, PublicWorkspaceObjectiveService,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "creation-http-contract-token";

struct UnusedDb;

#[async_trait]
impl DbPlugin for UnusedDb {
    async fn query(&self, _statement: DbStatement) -> DbResult<Vec<DbRow>> {
        Err(DbError::Unsupported("query must not run".to_string()))
    }

    async fn execute(&self, _statement: DbStatement) -> DbResult<DbExecuteResult> {
        Err(DbError::Unsupported("execute must not run".to_string()))
    }

    async fn transaction(
        &self,
        _steps: Vec<DbTransactionStep>,
    ) -> DbResult<Vec<DbTransactionStepResult>> {
        Err(DbError::Unsupported("transaction must not run".to_string()))
    }

    async fn health_check(&self) -> DbResult<DbHealth> {
        Ok(DbHealth::healthy())
    }
}

#[tokio::test]
async fn internal_create_requires_an_explicit_idempotency_key() -> Result<(), Box<dyn Error>> {
    let state = Arc::new(WorkspaceCoreState::new(
        Arc::new(UnusedDb),
        SERVICE_TOKEN.to_string(),
    )?);
    let request = Request::builder()
        .method("POST")
        .uri("/internal/v1/tenants/tenant-1/projects/project-1/workspaces")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "workspace_id": "workspace-1",
                "group_id": "group-workspace-1",
                "owner_member_id": "member-1",
                "name": "Team Space",
                "description": "Shared workspace",
                "metadata": {"workspace_type": "general"}
            })
            .to_string(),
        ))?;

    let response = workspace_router(state).oneshot(request).await?;

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    let body = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&body)?;
    assert_eq!(
        payload,
        json!({"detail": "missing x-idempotency-key header"})
    );
    Ok(())
}

#[tokio::test]
async fn internal_create_commits_and_replays_through_the_http_adapter() -> Result<(), Box<dyn Error>>
{
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    let first = workspace_router(state.clone())
        .oneshot(create_request(true)?)
        .await?;
    let replay = workspace_router(state)
        .oneshot(create_request(true)?)
        .await?;

    assert_eq!(first.status(), StatusCode::CREATED);
    assert_eq!(replay.status(), StatusCode::CREATED);
    let first: Value = serde_json::from_slice(&to_bytes(first.into_body(), usize::MAX).await?)?;
    let replay: Value = serde_json::from_slice(&to_bytes(replay.into_body(), usize::MAX).await?)?;
    assert_eq!(first["replayed"], false);
    assert_eq!(replay["replayed"], true);
    assert_eq!(replay["receipt_id"], first["receipt_id"]);
    assert_eq!(replay["workspace"], first["workspace"]);
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);
    Ok(())
}

#[tokio::test]
async fn public_create_preserves_the_legacy_defaults_and_durable_owner_event()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    let response = workspace_router(state.clone())
        .oneshot(public_create_request(
            json!({
                "name": "Team Workspace",
                "description": "Workspace description"
            }),
            None,
        )?)
        .await?;

    assert_eq!(response.status(), StatusCode::CREATED);
    let payload: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
    let workspace_id = payload["id"].as_str().ok_or("missing workspace id")?;
    assert_eq!(workspace_id.len(), 36);
    assert_eq!(payload["tenant_id"], "tenant-1");
    assert_eq!(payload["project_id"], "project-1");
    assert_eq!(payload["name"], "Team Workspace");
    assert_eq!(payload["created_by"], "owner-1");
    assert_eq!(payload["description"], "Workspace description");
    assert_eq!(payload["is_archived"], false);
    assert_eq!(
        payload["metadata"],
        json!({
            "workspace_use_case": "general",
            "workspace_type": "general",
            "collaboration_mode": "single_agent",
            "agent_conversation_mode": "single_agent",
            "autonomy_profile": {"workspace_type": "general"}
        })
    );
    assert_eq!(payload["office_status"], "inactive");
    assert_eq!(payload["hex_layout_config"], json!({}));
    assert!(
        payload["created_at"]
            .as_str()
            .is_some_and(|value| value.ends_with('Z'))
    );
    assert!(
        payload["updated_at"]
            .as_str()
            .is_some_and(|value| value.ends_with('Z'))
    );

    let read_request = Request::builder()
        .uri(format!(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/{workspace_id}"
        ))
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .body(Body::empty())?;
    let read_response = workspace_router(state.clone())
        .oneshot(read_request)
        .await?;
    assert_eq!(read_response.status(), StatusCode::OK);
    let refreshed: Value =
        serde_json::from_slice(&to_bytes(read_response.into_body(), usize::MAX).await?)?;
    assert_eq!(refreshed["id"], payload["id"]);
    assert_eq!(refreshed["metadata"], payload["metadata"]);
    assert_eq!(refreshed["name"], payload["name"]);
    assert!(refreshed["created_at"].as_str().is_some());
    assert!(refreshed["updated_at"].as_str().is_some());

    let members_request = Request::builder()
        .uri(format!(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/{workspace_id}/members"
        ))
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .body(Body::empty())?;
    let members_response = workspace_router(state).oneshot(members_request).await?;
    assert_eq!(members_response.status(), StatusCode::OK);
    let members: Value =
        serde_json::from_slice(&to_bytes(members_response.into_body(), usize::MAX).await?)?;
    assert_eq!(members[0]["user_id"], "owner-1");
    assert_eq!(members[0]["user_email"], "owner-1@example.com");

    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_members").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_principal_identities").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);
    let event = outbox_event(db.as_ref()).await?;
    assert_eq!(event["event_type"], "workspace_member_joined");
    assert_eq!(event["payload"]["workspace_id"], workspace_id);
    assert_eq!(event["payload"]["user_id"], "owner-1");
    assert_eq!(event["payload"]["role"], "owner");
    assert_eq!(event["payload"]["member"]["workspace_id"], workspace_id);
    assert_eq!(event["payload"]["member"]["role"], "owner");
    assert!(
        event["payload"]["member"]["created_at"]
            .as_str()
            .is_some_and(|value| value.ends_with("+00:00"))
    );
    assert!(
        event["payload"]["member"]["updated_at"]
            .as_str()
            .is_some_and(|value| value.ends_with("+00:00"))
    );
    Ok(())
}

#[tokio::test]
async fn desktop_local_create_mirrors_the_authenticated_project_principal()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db_without_principal().await?);
    let state = Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );

    let response = workspace_router(state)
        .oneshot(public_local_create_request()?)
        .await?;

    assert_eq!(response.status(), StatusCode::CREATED);
    let rows = db
        .query(DbStatement::new(
            "SELECT tenant_id, project_id, user_id, participant_actor_id, \
             source_membership_id, role, permissions_json, is_active, identity_authority \
             FROM project_principal_memberships",
        ))
        .await?;
    let principal = rows.first().ok_or("missing Desktop principal mirror")?;
    assert_eq!(
        principal.get_string("tenant_id")?.as_deref(),
        Some("tenant-1")
    );
    assert_eq!(
        principal.get_string("project_id")?.as_deref(),
        Some("project-1")
    );
    assert_eq!(principal.get_string("user_id")?.as_deref(), Some("owner-1"));
    assert_eq!(
        principal.get_string("participant_actor_id")?.as_deref(),
        Some("owner-1")
    );
    assert!(
        principal
            .get_string("source_membership_id")?
            .is_some_and(|value| value.starts_with("desktop-sidecar:"))
    );
    assert_eq!(principal.get_string("role")?.as_deref(), Some("owner"));
    assert_eq!(
        principal.get_string("permissions_json")?.as_deref(),
        Some("{}")
    );
    assert_eq!(principal.get_i64("is_active")?, Some(1));
    assert_eq!(
        principal.get_string("identity_authority")?.as_deref(),
        Some("desktop-sidecar")
    );
    Ok(())
}

#[tokio::test]
async fn desktop_local_workspace_reads_survive_a_file_database_reopen() -> Result<(), Box<dyn Error>>
{
    let directory = tempfile::tempdir()?;
    let database_path = directory.path().join("avernet-workspace.db");
    let workspace_id = {
        let db = Arc::new(LocalSqliteDbPlugin::new_file(&database_path)?);
        bcs::migrations::run_sqlite_migrations(db.as_ref()).await?;
        run_desktop_workspace_schema_migrations(db.as_ref()).await?;
        let state = Arc::new(
            WorkspaceCoreState::new_with_sql_flavor(
                db,
                SERVICE_TOKEN.to_string(),
                DbSqlFlavor::Sqlite,
            )?
            .with_authority(WorkspaceCoreAuthority::Local),
        );
        let response = workspace_router(state)
            .oneshot(public_local_create_request()?)
            .await?;
        assert_eq!(response.status(), StatusCode::CREATED);
        let payload: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
        payload["id"]
            .as_str()
            .ok_or("missing Desktop workspace id")?
            .to_string()
    };

    let db = Arc::new(LocalSqliteDbPlugin::new_file(&database_path)?);
    bcs::migrations::run_sqlite_migrations(db.as_ref()).await?;
    run_desktop_workspace_schema_migrations(db.as_ref()).await?;
    let state = Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );

    for path in [
        "/api/v1/tenants/tenant-1/projects/project-1/workspaces?limit=500&offset=0".to_string(),
        format!("/api/v1/tenants/tenant-1/projects/project-1/workspaces/{workspace_id}"),
        format!("/api/v1/tenants/tenant-1/projects/project-1/workspaces/{workspace_id}/members"),
        format!(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/\
             {workspace_id}/collaboration/capabilities"
        ),
    ] {
        let request = Request::builder()
            .uri(path)
            .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
            .header("x-memstack-user-id", "owner-1")
            .header("x-memstack-user-is-superuser", "false")
            .body(Body::empty())?;
        let response = workspace_router(state.clone()).oneshot(request).await?;
        assert_eq!(response.status(), StatusCode::OK);
    }

    let revision_rows = db
        .query(DbStatement::with_params(
            "SELECT revision FROM workspace_authorities WHERE workspace_id = ?",
            vec![DbValue::from(workspace_id.as_str())],
        ))
        .await?;
    let revision = revision_rows
        .first()
        .ok_or("missing Desktop Workspace authority")?
        .get_i64("revision")?
        .ok_or("missing Desktop Workspace authority revision")?;
    let collaboration_path = format!(
        "/api/v1/tenants/tenant-1/projects/project-1/workspaces/{workspace_id}/collaboration/mutations"
    );
    let discussion_request = Request::builder()
        .method("POST")
        .uri(collaboration_path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .header("x-expected-revision", revision.to_string())
        .header("idempotency-key", "desktop-reopen-discussion")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "contract_version": "2.0.0",
                "surface": "discussion",
                "action": "create_post",
                "expected_revision": revision,
                "idempotency_key": "desktop-reopen-discussion",
                "payload": {
                    "title": "Desktop persistence",
                    "content": "Avernet collaboration mutation survived a file database reopen"
                }
            })
            .to_string(),
        ))?;
    let response = workspace_router(state.clone())
        .oneshot(discussion_request)
        .await?;
    assert_eq!(response.status(), StatusCode::OK);

    let messages_path =
        format!("/api/v1/tenants/tenant-1/projects/project-1/workspaces/{workspace_id}/messages");
    let list_request = Request::builder()
        .uri(messages_path.as_str())
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .header("x-memstack-user-email", "owner-1@example.com")
        .body(Body::empty())?;
    let response = workspace_router(state.clone())
        .oneshot(list_request)
        .await?;
    assert_eq!(response.status(), StatusCode::OK);
    let payload: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
    assert_eq!(payload["items"], json!([]));

    let create_request = Request::builder()
        .method("POST")
        .uri(messages_path.as_str())
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .header("x-memstack-user-email", "owner-1@example.com")
        .header("idempotency-key", "desktop-reopen-message")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({"content": "Persisted message"}).to_string(),
        ))?;
    let response = workspace_router(state).oneshot(create_request).await?;
    assert_eq!(response.status(), StatusCode::CREATED);

    let db = Arc::new(LocalSqliteDbPlugin::new_file(&database_path)?);
    bcs::migrations::run_sqlite_migrations(db.as_ref()).await?;
    run_desktop_workspace_schema_migrations(db.as_ref()).await?;
    let state = Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );
    let list_request = Request::builder()
        .uri(messages_path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .header("x-memstack-user-email", "owner-1@example.com")
        .body(Body::empty())?;
    let response = workspace_router(state).oneshot(list_request).await?;
    assert_eq!(response.status(), StatusCode::OK);
    let payload: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
    assert_eq!(payload["items"].as_array().map(Vec::len), Some(1));
    assert_eq!(payload["items"][0]["content"], "Persisted message");
    let posts = db
        .query(DbStatement::with_params(
            "SELECT title, content FROM workspace_blackboard_posts WHERE workspace_id = ?",
            vec![DbValue::from(workspace_id.as_str())],
        ))
        .await?;
    assert_eq!(posts.len(), 1);
    assert_eq!(
        posts[0].get_string("title")?.as_deref(),
        Some("Desktop persistence")
    );
    Ok(())
}

#[tokio::test]
async fn cloud_create_does_not_mirror_a_desktop_project_principal() -> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db_without_principal().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    let response = workspace_router(state)
        .oneshot(public_local_create_request()?)
        .await?;

    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        table_count(db.as_ref(), "project_principal_memberships").await?,
        0
    );
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 0);
    Ok(())
}

#[tokio::test]
async fn public_create_composes_programming_metadata_like_the_legacy_route()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db,
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    let response = workspace_router(state)
        .oneshot(public_create_request(
            json!({
                "name": "Delivery Room",
                "use_case": "programming",
                "collaboration_mode": "autonomous",
                "sandbox_code_root": "my-evo",
                "autonomy_profile": {
                    "completion_policy": {
                        "requires_external_artifact": true,
                        "minimum_verification_grade": "pass"
                    }
                },
                "source_control": {
                    "provider": "gitlab",
                    "repo": "platform/delivery-room"
                },
                "metadata": {
                    "source": "ui",
                    "delivery_cicd": {
                        "provider": "sandbox_native",
                        "install_command": "pnpm install"
                    }
                }
            }),
            None,
        )?)
        .await?;

    assert_eq!(response.status(), StatusCode::CREATED);
    let payload: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
    assert_eq!(payload["metadata"]["source"], "ui");
    assert_eq!(payload["metadata"]["workspace_use_case"], "programming");
    assert_eq!(
        payload["metadata"]["workspace_type"],
        "software_development"
    );
    assert_eq!(payload["metadata"]["collaboration_mode"], "autonomous");
    assert_eq!(payload["metadata"]["agent_conversation_mode"], "autonomous");
    assert_eq!(
        payload["metadata"]["autonomy_profile"],
        json!({
            "workspace_type": "software_development",
            "completion_policy": {
                "requires_external_artifact": true,
                "minimum_verification_grade": "pass"
            }
        })
    );
    assert_eq!(
        payload["metadata"]["sandbox_code_root"],
        "/workspace/my-evo"
    );
    assert_eq!(
        payload["metadata"]["code_context"]["sandbox_code_root"],
        "/workspace/my-evo"
    );
    assert_eq!(
        payload["metadata"]["delivery_cicd"]["provider"],
        "sandbox_native"
    );
    assert!(payload["metadata"].get("source_control").is_none());
    Ok(())
}

#[tokio::test]
async fn desktop_autonomous_create_bootstraps_one_root_objective_and_replays_idempotently()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(desktop_creation_db().await?);
    let state = Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );
    let payload = json!({
        "name": "Autonomous Delivery",
        "description": "Ship the desktop local-mode acceptance goals",
        "collaboration_mode": "autonomous"
    });

    let first = workspace_router(state.clone())
        .oneshot(public_local_create_request_with_payload(payload.clone())?)
        .await?;
    assert_eq!(first.status(), StatusCode::CREATED);
    let first: Value = serde_json::from_slice(&to_bytes(first.into_body(), usize::MAX).await?)?;
    let workspace_id = first["id"].as_str().ok_or("missing workspace id")?;

    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_bootstrap_outbox \
             WHERE status = 'pending'"
        )
        .await?,
        1,
        "the creation transaction must durably enqueue before the API returns"
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_objectives"
        )
        .await?,
        0,
        "bootstrap execution must not be required for a successful create response"
    );

    // Simulate the API process disappearing without a UI retry. A fresh
    // worker recovers solely from the durable database snapshot.
    drop(state);
    let worker_db: Arc<dyn DbPlugin> = db.clone();
    let worker = WorkspaceAutonomyBootstrapWorker::new(
        worker_db,
        DbSqlFlavor::Sqlite,
        WorkspaceAutonomyBootstrapWorkerConfig {
            worker_id: "creation-contract-restarted-bootstrap".to_string(),
            poll_interval: Duration::from_millis(10),
            ..WorkspaceAutonomyBootstrapWorkerConfig::default()
        },
    )?;
    let recovered = worker.advance_once().await?;
    let exactly_once = worker.advance_once().await?;
    assert_eq!(recovered.claimed, 1);
    assert_eq!(recovered.completed, 1);
    assert_eq!(exactly_once.claimed, 0);

    let replay_state = Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );
    let replay = workspace_router(replay_state)
        .oneshot(public_local_create_request_with_payload(payload)?)
        .await?;
    assert_eq!(replay.status(), StatusCode::CREATED);
    let replay: Value = serde_json::from_slice(&to_bytes(replay.into_body(), usize::MAX).await?)?;
    assert_eq!(replay, first);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        1
    );

    let objectives = db
        .query(DbStatement::with_params(
            "SELECT objective_id, title, description, objective_type, \
                    CAST(progress AS INTEGER) AS progress \
             FROM workspace_objectives WHERE workspace_id = ?",
            vec![DbValue::from(workspace_id)],
        ))
        .await?;
    assert_eq!(objectives.len(), 1);
    let objective = objectives.first().ok_or("missing root Objective")?;
    assert_eq!(
        objective.get_string("title")?.as_deref(),
        Some("Autonomous Delivery")
    );
    assert_eq!(
        objective.get_string("description")?.as_deref(),
        Some("Ship the desktop local-mode acceptance goals")
    );
    assert_eq!(
        objective.get_string("objective_type")?.as_deref(),
        Some("objective")
    );
    assert_eq!(objective.get_i64("progress")?, Some(0));

    let tasks = db
        .query(DbStatement::with_params(
            "SELECT task_id, title, description, metadata_json FROM workspace_tasks \
             WHERE workspace_id = ?",
            vec![DbValue::from(workspace_id)],
        ))
        .await?;
    assert_eq!(tasks.len(), 1);
    let task = tasks.first().ok_or("missing root Task")?;
    assert_eq!(
        task.get_string("title")?.as_deref(),
        Some("Autonomous Delivery")
    );
    assert_eq!(
        task.get_string("description")?.as_deref(),
        Some("Ship the desktop local-mode acceptance goals")
    );
    let task_metadata: Value = serde_json::from_str(
        task.get_string("metadata_json")?
            .as_deref()
            .ok_or("missing Task metadata")?,
    )?;
    assert_eq!(task_metadata["task_role"], "goal_root");
    assert_eq!(
        task_metadata["objective_id"],
        objective
            .get_string("objective_id")?
            .ok_or("missing Objective id")?
    );

    let projections = db
        .query(DbStatement::with_params(
            "SELECT objective_id, task_id FROM workspace_objective_task_projections \
             WHERE workspace_id = ?",
            vec![DbValue::from(workspace_id)],
        ))
        .await?;
    assert_eq!(projections.len(), 1);
    assert_eq!(
        projections[0].get_string("objective_id")?,
        objective.get_string("objective_id")?
    );
    assert_eq!(
        projections[0].get_string("task_id")?,
        task.get_string("task_id")?
    );
    Ok(())
}

#[tokio::test]
async fn autonomous_creation_rolls_back_when_the_bootstrap_outbox_write_fails()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(desktop_creation_db().await?);
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_autonomy_bootstrap BEFORE INSERT ON \
         workspace_autonomy_bootstrap_outbox BEGIN \
         SELECT RAISE(FAIL, 'injected bootstrap outbox failure'); END",
    ))
    .await?;
    let state = Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );

    let response = workspace_router(state)
        .oneshot(public_local_create_request_with_payload(json!({
            "name": "Atomic Autonomous Delivery",
            "collaboration_mode": "autonomous"
        }))?)
        .await?;

    assert_ne!(response.status(), StatusCode::CREATED);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_profiles"
        )
        .await?,
        0
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        0
    );
    Ok(())
}

#[tokio::test]
async fn expired_bootstrap_claim_recovers_after_objective_creation_and_revision_advance()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(desktop_creation_db().await?);
    let state = Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );
    let response = workspace_router(state)
        .oneshot(public_local_create_request_with_payload(json!({
            "name": "Revision Race Recovery",
            "description": "Recover after the Objective commits",
            "collaboration_mode": "autonomous"
        }))?)
        .await?;
    assert_eq!(response.status(), StatusCode::CREATED);
    let payload: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
    let workspace_id = payload["id"].as_str().ok_or("missing workspace id")?;

    let claim_now_ms = chrono::Utc::now().timestamp_millis();
    let bootstrap = PublicWorkspaceAutonomyBootstrapService::new(db.as_ref(), DbSqlFlavor::Sqlite);
    let claim = bootstrap
        .claim_bootstraps(
            "crashed-bootstrap-worker",
            claim_now_ms,
            claim_now_ms + 120_000,
            1,
        )
        .await?
        .pop()
        .ok_or("missing bootstrap claim")?;

    // The first worker committed the Objective and then disappeared before it
    // could project or ACK its fenced claim.
    let objective = PublicWorkspaceObjectiveService::new(db.as_ref(), DbSqlFlavor::Sqlite)
        .create(&PublicCreateWorkspaceObjectiveInput {
            context: PublicWorkspaceObjectiveContext {
                tenant_id: "tenant-1".to_string(),
                project_id: "project-1".to_string(),
                workspace_id: workspace_id.to_string(),
                user_id: "owner-1".to_string(),
                is_superuser: false,
                expected_revision: None,
                idempotency_key: Some(format!(
                    "workspace-autonomy-bootstrap-objective:{workspace_id}"
                )),
            },
            title: claim.objective_title.clone(),
            description: claim.objective_description.clone(),
            objective_type: "objective".to_string(),
            parent_objective_id: None,
            progress: 0.0,
        })
        .await?;
    assert!(!objective.replayed);

    // Model an unrelated authority commit plus lease expiry before restart.
    db.execute(DbStatement::with_params(
        "UPDATE workspace_authorities SET revision = revision + 1 WHERE workspace_id = ?",
        vec![DbValue::from(workspace_id)],
    ))
    .await?;
    db.execute(DbStatement::with_params(
        "UPDATE workspace_autonomy_bootstrap_outbox SET lease_expires_at_ms = 0 \
         WHERE bootstrap_id = ?",
        vec![DbValue::from(claim.bootstrap_id.as_str())],
    ))
    .await?;

    let worker_db: Arc<dyn DbPlugin> = db.clone();
    let restarted = WorkspaceAutonomyBootstrapWorker::new(
        worker_db,
        DbSqlFlavor::Sqlite,
        WorkspaceAutonomyBootstrapWorkerConfig {
            worker_id: "restarted-bootstrap-worker".to_string(),
            ..WorkspaceAutonomyBootstrapWorkerConfig::default()
        },
    )?;
    let outcome = restarted.advance_once().await?;

    assert_eq!(outcome.claimed, 1);
    assert_eq!(outcome.completed, 1);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_objectives"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_tasks WHERE \
             json_extract(metadata_json, '$.task_role') = 'goal_root'"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_bootstrap_outbox WHERE \
             status = 'completed' AND attempt_count = 2 AND objective_id IS NOT NULL \
             AND root_task_id IS NOT NULL"
        )
        .await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn bootstrap_dead_letter_creates_workspace_attention_and_editor_retry_recovers()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(desktop_creation_db().await?);
    let state = Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );
    let response = workspace_router(state)
        .oneshot(public_local_create_request_with_payload(json!({
            "name": "Recoverable Bootstrap",
            "collaboration_mode": "autonomous"
        }))?)
        .await?;
    assert_eq!(response.status(), StatusCode::CREATED);
    let payload: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
    let workspace_id = payload["id"].as_str().ok_or("missing workspace id")?;

    db.execute(DbStatement::new(
        "UPDATE workspace_autonomy_bootstrap_outbox SET max_attempts = 1",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_bootstrap_objective BEFORE INSERT ON workspace_objectives BEGIN \
         SELECT RAISE(FAIL, 'injected objective failure'); END",
    ))
    .await?;
    let worker_db: Arc<dyn DbPlugin> = db.clone();
    let worker = WorkspaceAutonomyBootstrapWorker::new(
        worker_db,
        DbSqlFlavor::Sqlite,
        WorkspaceAutonomyBootstrapWorkerConfig {
            worker_id: "bootstrap-dead-letter-worker".to_string(),
            retry_base: Duration::from_millis(1),
            retry_max: Duration::from_millis(1),
            ..WorkspaceAutonomyBootstrapWorkerConfig::default()
        },
    )?;

    let failed = worker.advance_once().await?;

    assert_eq!(failed.dead_lettered, 1);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_attentions WHERE \
             source_kind = 'bootstrap_dead_letter' AND root_task_id IS NULL AND status = 'open'"
        )
        .await?,
        1
    );
    let attention_id = scalar_string(
        db.as_ref(),
        "SELECT attention_id AS value FROM workspace_autonomy_attentions WHERE \
         source_kind = 'bootstrap_dead_letter'",
    )
    .await?;
    let attentions = PublicWorkspaceAutonomyAttentionService::new(db.as_ref(), DbSqlFlavor::Sqlite);
    let context = |user_id: &str| PublicWorkspaceAutonomyContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: workspace_id.to_string(),
        user_id: user_id.to_string(),
        is_superuser: false,
        expected_revision: None,
        idempotency_key: None,
    };

    let unauthorized = attentions
        .retry_bootstrap_dead_letter(&context("intruder"), attention_id.as_str(), 0)
        .await;
    assert!(unauthorized.is_err());

    db.execute(DbStatement::new("DROP TRIGGER reject_bootstrap_objective"))
        .await?;
    attentions
        .retry_bootstrap_dead_letter(&context("owner-1"), attention_id.as_str(), 0)
        .await?;
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_bootstrap_outbox WHERE \
             status = 'pending' AND attempt_count = 0"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_autonomy_attentions WHERE \
             source_kind = 'bootstrap_dead_letter' AND status = 'resolved' AND \
             resolved_by_actor_id = 'owner-1'"
        )
        .await?,
        1
    );

    let recovered = worker.advance_once().await?;
    assert_eq!(recovered.completed, 1);
    assert_eq!(
        scalar_i64(
            db.as_ref(),
            "SELECT COUNT(*) AS value FROM workspace_tasks WHERE \
             json_extract(metadata_json, '$.task_role') = 'goal_root'"
        )
        .await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn public_create_preserves_legacy_validation_and_permission_envelopes()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    let malformed = Request::builder()
        .method("POST")
        .uri("/api/v1/tenants/tenant-1/projects/project-1/workspaces")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-email", "owner-1@example.com")
        .header("x-memstack-user-is-superuser", "false")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from("{"))?;
    let malformed = workspace_router(state.clone()).oneshot(malformed).await?;
    assert_eq!(malformed.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let malformed: Value =
        serde_json::from_slice(&to_bytes(malformed.into_body(), usize::MAX).await?)?;
    assert_eq!(malformed["detail"][0]["type"], "json_invalid");
    assert_eq!(malformed["detail"][0]["loc"], json!(["body", 0]));

    let missing_email = workspace_router(state.clone())
        .oneshot(public_create_request_with_email(
            json!({"name": "Missing Identity"}),
            None,
            None,
        )?)
        .await?;
    assert_eq!(missing_email.status(), StatusCode::BAD_REQUEST);
    let missing_email: Value =
        serde_json::from_slice(&to_bytes(missing_email.into_body(), usize::MAX).await?)?;
    assert_eq!(
        missing_email,
        json!({"detail": "missing x-memstack-user-email header"})
    );

    let blank_email = workspace_router(state.clone())
        .oneshot(public_create_request_with_email(
            json!({"name": "Blank Identity"}),
            None,
            Some(" "),
        )?)
        .await?;
    assert_eq!(blank_email.status(), StatusCode::BAD_REQUEST);
    let blank_email: Value =
        serde_json::from_slice(&to_bytes(blank_email.into_body(), usize::MAX).await?)?;
    assert_eq!(
        blank_email,
        json!({"detail": "invalid x-memstack-user-email header"})
    );

    let invalid_name = workspace_router(state.clone())
        .oneshot(public_create_request(json!({"name": ""}), None)?)
        .await?;
    assert_eq!(invalid_name.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let invalid_name: Value =
        serde_json::from_slice(&to_bytes(invalid_name.into_body(), usize::MAX).await?)?;
    assert_eq!(invalid_name["detail"][0]["type"], "string_too_short");
    assert_eq!(invalid_name["detail"][0]["loc"], json!(["body", "name"]));

    let invalid_use_case = workspace_router(state.clone())
        .oneshot(public_create_request(
            json!({"name": "Invalid", "use_case": "coding"}),
            None,
        )?)
        .await?;
    assert_eq!(invalid_use_case.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let invalid_use_case: Value =
        serde_json::from_slice(&to_bytes(invalid_use_case.into_body(), usize::MAX).await?)?;
    assert_eq!(invalid_use_case["detail"][0]["type"], "literal_error");
    assert_eq!(
        invalid_use_case["detail"][0]["loc"],
        json!(["body", "use_case"])
    );

    let invalid_profile = workspace_router(state.clone())
        .oneshot(public_create_request(
            json!({
                "name": "Invalid Profile",
                "autonomy_profile": {"unknown_policy": true}
            }),
            None,
        )?)
        .await?;
    assert_eq!(invalid_profile.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let invalid_profile: Value =
        serde_json::from_slice(&to_bytes(invalid_profile.into_body(), usize::MAX).await?)?;
    assert_eq!(invalid_profile["detail"][0]["type"], "value_error");
    assert_eq!(
        invalid_profile["detail"][0]["loc"],
        json!(["body", "autonomy_profile"])
    );

    let unsafe_root = workspace_router(state.clone())
        .oneshot(public_create_request(
            json!({
                "name": "Unsafe Delivery Room",
                "use_case": "programming",
                "sandbox_code_root": "/workspace"
            }),
            None,
        )?)
        .await?;
    assert_eq!(unsafe_root.status(), StatusCode::BAD_REQUEST);
    let unsafe_root: Value =
        serde_json::from_slice(&to_bytes(unsafe_root.into_body(), usize::MAX).await?)?;
    assert_eq!(unsafe_root, json!({"detail": "Invalid workspace request"}));

    let first_duplicate = workspace_router(state.clone())
        .oneshot(public_create_request(
            json!({"name": "Duplicate Workspace"}),
            None,
        )?)
        .await?;
    assert_eq!(first_duplicate.status(), StatusCode::CREATED);
    let duplicate = workspace_router(state.clone())
        .oneshot(public_create_request(
            json!({"name": "Duplicate Workspace"}),
            None,
        )?)
        .await?;
    assert_eq!(duplicate.status(), StatusCode::CONFLICT);
    let duplicate: Value =
        serde_json::from_slice(&to_bytes(duplicate.into_body(), usize::MAX).await?)?;
    assert_eq!(duplicate, json!({"detail": "Workspace already exists"}));

    db.execute(DbStatement::new(
        "DELETE FROM project_principal_memberships WHERE tenant_id = 'tenant-1' AND project_id = 'project-1' AND user_id = 'owner-1'",
    ))
    .await?;
    let mut forbidden_request =
        public_create_request(json!({"name": "Unauthorized Workspace"}), None)?;
    forbidden_request
        .headers_mut()
        .insert("x-memstack-user-is-superuser", "true".parse()?);
    let forbidden = workspace_router(state).oneshot(forbidden_request).await?;
    assert_eq!(forbidden.status(), StatusCode::FORBIDDEN);
    let forbidden: Value =
        serde_json::from_slice(&to_bytes(forbidden.into_body(), usize::MAX).await?)?;
    assert_eq!(forbidden, json!({"detail": "Access denied"}));
    Ok(())
}

#[tokio::test]
async fn public_create_supports_optional_idempotency_without_requiring_old_clients_to_send_it()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let payload = json!({"name": "Idempotent Workspace", "metadata": {"source": "test"}});

    let first = workspace_router(state.clone())
        .oneshot(public_create_request(
            payload.clone(),
            Some("public-create-intent-1"),
        )?)
        .await?;
    let replay = workspace_router(state.clone())
        .oneshot(public_create_request(
            payload,
            Some("public-create-intent-1"),
        )?)
        .await?;

    assert_eq!(first.status(), StatusCode::CREATED);
    assert_eq!(replay.status(), StatusCode::CREATED);
    let first: Value = serde_json::from_slice(&to_bytes(first.into_body(), usize::MAX).await?)?;
    let replay: Value = serde_json::from_slice(&to_bytes(replay.into_body(), usize::MAX).await?)?;
    assert_eq!(replay, first);
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);

    let conflict = workspace_router(state)
        .oneshot(public_create_request(
            json!({"name": "Changed Workspace"}),
            Some("public-create-intent-1"),
        )?)
        .await?;
    assert_eq!(conflict.status(), StatusCode::CONFLICT);
    Ok(())
}

#[tokio::test]
async fn public_update_preserves_legacy_shape_and_explicit_cas_replay() -> Result<(), Box<dyn Error>>
{
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let created = workspace_router(state.clone())
        .oneshot(create_request(true)?)
        .await?;
    assert_eq!(created.status(), StatusCode::CREATED);

    let update = public_workspace_request(
        "PATCH",
        Some(json!({
            "name": "Renamed Space",
            "description": "Updated description",
            "is_archived": true,
            "metadata": {"workspace_type": "general", "updated": true}
        })),
        Some("public-update-intent"),
        Some("W/\"1\""),
    )?;
    let first = workspace_router(state.clone()).oneshot(update).await?;
    assert_eq!(first.status(), StatusCode::OK);
    let first_payload: Value =
        serde_json::from_slice(&to_bytes(first.into_body(), usize::MAX).await?)?;
    assert_eq!(first_payload["id"], "workspace-1");
    assert_eq!(first_payload["name"], "Renamed Space");
    assert_eq!(first_payload["description"], "Updated description");
    assert_eq!(first_payload["is_archived"], true);
    assert_eq!(first_payload["metadata"]["updated"], true);

    let replay = workspace_router(state.clone())
        .oneshot(public_workspace_request(
            "PATCH",
            Some(json!({
                "name": "Renamed Space",
                "description": "Updated description",
                "is_archived": true,
                "metadata": {"workspace_type": "general", "updated": true}
            })),
            Some("public-update-intent"),
            Some("1"),
        )?)
        .await?;
    assert_eq!(replay.status(), StatusCode::OK);
    let replay_payload: Value =
        serde_json::from_slice(&to_bytes(replay.into_body(), usize::MAX).await?)?;
    assert_eq!(replay_payload, first_payload);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 2);

    let stale = workspace_router(state)
        .oneshot(public_workspace_request(
            "PATCH",
            Some(json!({"name": "Must Not Commit"})),
            Some("stale-update-intent"),
            Some("1"),
        )?)
        .await?;
    assert_eq!(stale.status(), StatusCode::CONFLICT);
    Ok(())
}

#[tokio::test]
async fn public_update_keeps_old_clients_revision_header_optional_and_validates_body()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db,
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let created = workspace_router(state.clone())
        .oneshot(create_request(true)?)
        .await?;
    assert_eq!(created.status(), StatusCode::CREATED);

    let updated = workspace_router(state.clone())
        .oneshot(public_workspace_request(
            "PATCH",
            Some(json!({"name": "Legacy Update"})),
            None,
            None,
        )?)
        .await?;
    assert_eq!(updated.status(), StatusCode::OK);

    let invalid = workspace_router(state)
        .oneshot(public_workspace_request(
            "PATCH",
            Some(json!({"name": ""})),
            None,
            None,
        )?)
        .await?;
    assert_eq!(invalid.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let invalid_payload: Value =
        serde_json::from_slice(&to_bytes(invalid.into_body(), usize::MAX).await?)?;
    assert_eq!(invalid_payload["detail"][0]["loc"], json!(["body", "name"]));
    Ok(())
}

#[tokio::test]
async fn public_delete_tombstones_reads_and_replays_without_losing_outbox()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let created = workspace_router(state.clone())
        .oneshot(create_request(true)?)
        .await?;
    assert_eq!(created.status(), StatusCode::CREATED);

    let deleted = workspace_router(state.clone())
        .oneshot(public_workspace_request(
            "DELETE",
            None,
            Some("public-delete-intent"),
            Some("1"),
        )?)
        .await?;
    assert_eq!(deleted.status(), StatusCode::NO_CONTENT);
    assert!(to_bytes(deleted.into_body(), usize::MAX).await?.is_empty());

    let read = workspace_router(state.clone())
        .oneshot(public_workspace_request("GET", None, None, None)?)
        .await?;
    assert_eq!(read.status(), StatusCode::NOT_FOUND);

    let replay = workspace_router(state)
        .oneshot(public_workspace_request(
            "DELETE",
            None,
            Some("public-delete-intent"),
            Some("1"),
        )?)
        .await?;
    assert_eq!(replay.status(), StatusCode::NO_CONTENT);
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 2);
    Ok(())
}

#[tokio::test]
async fn public_member_mutations_preserve_legacy_status_shape_and_atomic_roster()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db().await?);
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships \
         (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, \
          permissions_json, is_active, identity_authority, source_created_at, source_updated_at) \
         VALUES ('tenant-1', 'project-1', 'member-user', 'member-user', \
                 'membership-member-user', 'member', '{}', 1, 'memstack', \
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    ))
    .await?;
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let created = workspace_router(state.clone())
        .oneshot(create_request(true)?)
        .await?;
    assert_eq!(created.status(), StatusCode::CREATED);

    let added = workspace_router(state.clone())
        .oneshot(public_member_request(
            "POST",
            None,
            Some(json!({"user_id": "member-user"})),
            Some("http-member-add"),
            Some("1"),
        )?)
        .await?;
    assert_eq!(added.status(), StatusCode::CREATED);
    let added_payload: Value =
        serde_json::from_slice(&to_bytes(added.into_body(), usize::MAX).await?)?;
    assert_eq!(added_payload["workspace_id"], "workspace-1");
    assert_eq!(added_payload["user_id"], "member-user");
    assert_eq!(added_payload["role"], "viewer");
    assert_eq!(added_payload["user_email"], Value::Null);

    let replayed_add = workspace_router(state.clone())
        .oneshot(public_member_request(
            "POST",
            None,
            Some(json!({"user_id": "member-user"})),
            Some("http-member-add"),
            Some("1"),
        )?)
        .await?;
    assert_eq!(replayed_add.status(), StatusCode::CREATED);
    let replayed_payload: Value =
        serde_json::from_slice(&to_bytes(replayed_add.into_body(), usize::MAX).await?)?;
    assert_eq!(replayed_payload, added_payload);

    let updated = workspace_router(state.clone())
        .oneshot(public_member_request(
            "PATCH",
            Some("member-user"),
            Some(json!({"role": "editor"})),
            Some("http-member-update"),
            Some("2"),
        )?)
        .await?;
    assert_eq!(updated.status(), StatusCode::OK);
    let updated_payload: Value =
        serde_json::from_slice(&to_bytes(updated.into_body(), usize::MAX).await?)?;
    assert_eq!(updated_payload["role"], "editor");

    let removed = workspace_router(state.clone())
        .oneshot(public_member_request(
            "DELETE",
            Some("member-user"),
            None,
            Some("http-member-remove"),
            Some("3"),
        )?)
        .await?;
    assert_eq!(removed.status(), StatusCode::NO_CONTENT);
    let replayed_remove = workspace_router(state)
        .oneshot(public_member_request(
            "DELETE",
            Some("member-user"),
            None,
            Some("http-member-remove"),
            Some("3"),
        )?)
        .await?;
    assert_eq!(replayed_remove.status(), StatusCode::NO_CONTENT);
    assert_eq!(table_count(db.as_ref(), "workspace_members").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 4);
    Ok(())
}

#[tokio::test]
async fn public_member_mutations_reject_invalid_roles_and_non_project_principals()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(creation_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db,
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let created = workspace_router(state.clone())
        .oneshot(create_request(true)?)
        .await?;
    assert_eq!(created.status(), StatusCode::CREATED);

    let invalid = workspace_router(state.clone())
        .oneshot(public_member_request(
            "POST",
            None,
            Some(json!({"user_id": "outside-user", "role": "admin"})),
            None,
            None,
        )?)
        .await?;
    assert_eq!(invalid.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let invalid_payload: Value =
        serde_json::from_slice(&to_bytes(invalid.into_body(), usize::MAX).await?)?;
    assert_eq!(invalid_payload["detail"][0]["loc"], json!(["body", "role"]));

    let forbidden = workspace_router(state)
        .oneshot(public_member_request(
            "POST",
            None,
            Some(json!({"user_id": "outside-user", "role": "viewer"})),
            Some("outside-project-member"),
            Some("1"),
        )?)
        .await?;
    assert_eq!(forbidden.status(), StatusCode::FORBIDDEN);
    Ok(())
}

fn create_request(with_idempotency_key: bool) -> Result<Request<Body>, Box<dyn Error>> {
    let mut builder = Request::builder()
        .method("POST")
        .uri("/internal/v1/tenants/tenant-1/projects/project-1/workspaces")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .header(header::CONTENT_TYPE, "application/json");
    if with_idempotency_key {
        builder = builder.header("x-idempotency-key", "create-intent-1");
    }
    Ok(builder.body(Body::from(
        json!({
            "workspace_id": "workspace-1",
            "group_id": "group-workspace-1",
            "owner_member_id": "member-1",
            "name": "Team Space",
            "description": "Shared workspace",
            "metadata": {"workspace_type": "general"}
        })
        .to_string(),
    ))?)
}

fn public_create_request(
    payload: Value,
    idempotency_key: Option<&str>,
) -> Result<Request<Body>, Box<dyn Error>> {
    public_create_request_with_email(payload, idempotency_key, Some("owner-1@example.com"))
}

fn public_create_request_with_email(
    payload: Value,
    idempotency_key: Option<&str>,
    owner_email: Option<&str>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut builder = Request::builder()
        .method("POST")
        .uri("/api/v1/tenants/tenant-1/projects/project-1/workspaces")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false")
        .header(header::CONTENT_TYPE, "application/json");
    if let Some(owner_email) = owner_email {
        builder = builder.header("x-memstack-user-email", owner_email);
    }
    if let Some(idempotency_key) = idempotency_key {
        builder = builder.header("idempotency-key", idempotency_key);
    }
    Ok(builder.body(Body::from(payload.to_string()))?)
}

fn public_local_create_request() -> Result<Request<Body>, Box<dyn Error>> {
    let mut request = public_create_request(
        json!({
            "name": "Desktop Local Workspace",
            "description": "Avernet Desktop authority contract"
        }),
        Some("desktop-local-create"),
    )?;
    request
        .headers_mut()
        .insert("x-memstack-project-membership-role", "owner".parse()?);
    Ok(request)
}

fn public_local_create_request_with_payload(
    payload: Value,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut request = public_create_request(payload, Some("desktop-local-autonomous-create"))?;
    request
        .headers_mut()
        .insert("x-memstack-project-membership-role", "owner".parse()?);
    Ok(request)
}

fn public_workspace_request(
    method: &str,
    payload: Option<Value>,
    idempotency_key: Option<&str>,
    if_match: Option<&str>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut builder = Request::builder()
        .method(method)
        .uri("/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false");
    if let Some(idempotency_key) = idempotency_key {
        builder = builder.header("idempotency-key", idempotency_key);
    }
    if let Some(if_match) = if_match {
        builder = builder.header("if-match", if_match);
    }
    let body = if let Some(payload) = payload {
        builder = builder.header(header::CONTENT_TYPE, "application/json");
        Body::from(payload.to_string())
    } else {
        Body::empty()
    };
    Ok(builder.body(body)?)
}

fn public_member_request(
    method: &str,
    user_id: Option<&str>,
    payload: Option<Value>,
    idempotency_key: Option<&str>,
    if_match: Option<&str>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let suffix = user_id.map_or_else(String::new, |user_id| format!("/{user_id}"));
    let mut builder = Request::builder()
        .method(method)
        .uri(format!(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/members{suffix}"
        ))
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-is-superuser", "false");
    if let Some(idempotency_key) = idempotency_key {
        builder = builder.header("idempotency-key", idempotency_key);
    }
    if let Some(if_match) = if_match {
        builder = builder.header("if-match", if_match);
    }
    let body = if let Some(payload) = payload {
        builder = builder.header(header::CONTENT_TYPE, "application/json");
        Body::from(payload.to_string())
    } else {
        Body::empty()
    };
    Ok(builder.body(body)?)
}

async fn creation_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = creation_db_without_principal().await?;
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships \
         (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, \
          permissions_json, is_active, identity_authority, source_created_at, source_updated_at) \
         VALUES ('tenant-1', 'project-1', 'owner-1', 'owner-1', 'membership-owner-1', 'owner', \
                 '{}', 1, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    ))
    .await?;
    Ok(db)
}

async fn desktop_creation_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    Ok(db)
}

async fn creation_db_without_principal() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, source_membership_id TEXT NOT NULL, role TEXT NOT NULL, permissions_json TEXT NOT NULL DEFAULT '{}', is_active INTEGER NOT NULL, identity_authority TEXT NOT NULL, source_created_at TEXT NOT NULL, source_updated_at TEXT NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id), UNIQUE (tenant_id, project_id, participant_actor_id), UNIQUE (source_membership_id))",
        "CREATE TABLE bcs_groups (group_id TEXT NOT NULL, label TEXT, status TEXT NOT NULL, driver_bot TEXT NOT NULL, originator TEXT, env TEXT NOT NULL, routing_policy_json TEXT, context TEXT, group_kind TEXT NOT NULL DEFAULT 'normal', version INTEGER NOT NULL DEFAULT 1, record_status TEXT NOT NULL DEFAULT 'active', lifecycle_status TEXT NOT NULL DEFAULT 'active', group_strategy TEXT NOT NULL DEFAULT 'chat', created_by TEXT, visibility TEXT NOT NULL DEFAULT 'private', gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(group_id, env))",
        "CREATE TABLE bcs_group_participants (group_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, role TEXT NOT NULL, env TEXT NOT NULL, actor_kind TEXT NOT NULL DEFAULT 'bot', mode TEXT NOT NULL DEFAULT 'auto', gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(env, group_id, bot_uuid))",
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, is_archived INTEGER NOT NULL DEFAULT 0, office_status TEXT NOT NULL DEFAULT 'inactive', hex_layout_config_json TEXT NOT NULL DEFAULT '{}', default_blocking_categories_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT, deleted_by TEXT, UNIQUE(tenant_id, project_id, workspace_id), UNIQUE(tenant_id, project_id, name))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, invited_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(workspace_id, user_id), UNIQUE(workspace_id, participant_actor_id))",
        "CREATE TABLE workspace_principal_identities (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, email TEXT NOT NULL, display_name TEXT, is_active INTEGER NOT NULL, identity_authority TEXT NOT NULL, source_created_at TEXT NOT NULL, source_updated_at TEXT NOT NULL, PRIMARY KEY(tenant_id, project_id, workspace_id, user_id), UNIQUE(tenant_id, project_id, workspace_id, participant_actor_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    Ok(db)
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows.first().ok_or("missing scalar row")?;
    Ok(row.get_i64("value")?.ok_or("missing scalar value")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows.first().ok_or("missing scalar row")?;
    Ok(row.get_string("value")?.ok_or("missing scalar value")?)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "project_principal_memberships" => {
            "SELECT COUNT(*) AS value FROM project_principal_memberships"
        }
        "workspace_profiles" => "SELECT COUNT(*) AS value FROM workspace_profiles",
        "workspace_members" => "SELECT COUNT(*) AS value FROM workspace_members",
        "workspace_principal_identities" => {
            "SELECT COUNT(*) AS value FROM workspace_principal_identities"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows.first().ok_or("missing count row")?;
    Ok(row.get_i64("value")?.ok_or("missing count")?)
}

async fn outbox_event(db: &dyn DbPlugin) -> Result<Value, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::new(
            "SELECT event_type, payload_json FROM workspace_outbox",
        ))
        .await?;
    let row = rows.first().ok_or("missing outbox row")?;
    let event_type = row.get_string("event_type")?.ok_or("missing event type")?;
    let payload_json = row
        .get_string("payload_json")?
        .ok_or("missing event payload")?;
    Ok(json!({
        "event_type": event_type,
        "payload": serde_json::from_str::<Value>(&payload_json)?,
    }))
}
