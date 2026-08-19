use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{
    WorkspaceCoreAuthority, WorkspaceCoreState,
    desktop_schema::run_desktop_workspace_schema_migrations, workspace_router,
};
use memstack_workspace_service_api::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, ProviderRegistryRoute,
    TenantId,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "task-session-http-contract-token";
const MESSAGE_EVENT_SEQUENCE_BASE: i64 = 1_i64 << 62;

struct StaticProviderRegistry;
struct StaticAgentRegistry;

#[async_trait::async_trait]
impl AgentRegistryPort for StaticAgentRegistry {
    async fn resolve(
        &self,
        _lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError> {
        Ok(None)
    }
}

#[async_trait::async_trait]
impl ProviderRegistryPort for StaticProviderRegistry {
    async fn resolve(
        &self,
        lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        ProviderRegistryRoute::parse(lookup.provider_id().as_str(), lookup.model_id().as_str())
            .map(Some)
            .map_err(|_| ProviderRegistryPortError::Unavailable)
    }

    async fn tenant_default(
        &self,
        _tenant_id: &TenantId,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        Ok(None)
    }
}

#[tokio::test]
async fn desktop_local_task_session_create_mirrors_the_authenticated_project_principal()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(task_session_db().await?);
    db.execute(DbStatement::new(
        "DELETE FROM project_principal_memberships WHERE user_id = 'owner-1'",
    ))
    .await?;
    let state = Arc::new(
        WorkspaceCoreState::new_with_registries(
            db.clone(),
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
            Arc::new(StaticAgentRegistry),
            Arc::new(StaticProviderRegistry),
        )?
        .with_authority(WorkspaceCoreAuthority::Local),
    );

    let mut request = task_session_request("Initial objective")?;
    request
        .headers_mut()
        .insert("x-memstack-project-membership-role", "owner".parse()?);
    let response = workspace_router(state).oneshot(request).await?;

    assert_eq!(response.status(), StatusCode::CREATED);
    let rows = db
        .query(DbStatement::new(
            "SELECT user_id, participant_actor_id, source_membership_id, role, is_active, \
             identity_authority FROM project_principal_memberships",
        ))
        .await?;
    let principal = rows.first().ok_or("missing Desktop principal mirror")?;
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
    assert_eq!(principal.get_i64("is_active")?, Some(1));
    assert_eq!(
        principal.get_string("identity_authority")?.as_deref(),
        Some("desktop-sidecar")
    );
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 1);
    Ok(())
}

#[tokio::test]
async fn cloud_task_session_create_mirrors_the_vouched_project_principal()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(task_session_db().await?);
    db.execute(DbStatement::new(
        "DELETE FROM project_principal_memberships WHERE user_id = 'owner-1'",
    ))
    .await?;
    let state = Arc::new(WorkspaceCoreState::new_with_registries(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(StaticAgentRegistry),
        Arc::new(StaticProviderRegistry),
    )?);

    let mut request = task_session_request("Initial objective")?;
    request
        .headers_mut()
        .insert("x-memstack-project-membership-role", "owner".parse()?);
    let response = workspace_router(state).oneshot(request).await?;

    assert_eq!(response.status(), StatusCode::CREATED);
    let rows = db
        .query(DbStatement::new(
            "SELECT user_id, participant_actor_id, source_membership_id, role, is_active, \
             identity_authority FROM project_principal_memberships",
        ))
        .await?;
    let principal = rows.first().ok_or("missing Cloud principal mirror")?;
    assert_eq!(principal.get_string("user_id")?.as_deref(), Some("owner-1"));
    assert_eq!(
        principal.get_string("participant_actor_id")?.as_deref(),
        Some("owner-1")
    );
    assert!(
        principal
            .get_string("source_membership_id")?
            .is_some_and(|value| value.starts_with("memstack:"))
    );
    assert_eq!(principal.get_string("role")?.as_deref(), Some("owner"));
    assert_eq!(principal.get_i64("is_active")?, Some(1));
    assert_eq!(
        principal.get_string("identity_authority")?.as_deref(),
        Some("memstack")
    );
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 1);
    Ok(())
}

#[tokio::test]
async fn task_session_create_is_atomic_and_replay_safe() -> Result<(), Box<dyn Error>> {
    let db = Arc::new(task_session_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_registries(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(StaticAgentRegistry),
        Arc::new(StaticProviderRegistry),
    )?);

    let first = workspace_router(state.clone())
        .oneshot(task_session_request("Initial objective")?)
        .await?;
    let replay = workspace_router(state.clone())
        .oneshot(task_session_request("Initial objective")?)
        .await?;

    assert_eq!(first.status(), StatusCode::CREATED);
    assert_eq!(replay.status(), StatusCode::OK);
    let first: Value = serde_json::from_slice(&to_bytes(first.into_body(), usize::MAX).await?)?;
    let replay: Value = serde_json::from_slice(&to_bytes(replay.into_body(), usize::MAX).await?)?;
    assert_eq!(first["replayed"], false);
    assert_eq!(replay["replayed"], true);
    assert_eq!(first["workspace"]["id"], "workspace-task-session-1");
    assert_eq!(first["initial_message"]["id"], "message-task-session-1");
    assert_eq!(first["initial_message"]["content"], "Initial objective");
    assert_eq!(first["policy"]["revision"], 1);
    assert_eq!(replay["receipt_id"], first["receipt_id"]);
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_members").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_principal_identities").await?,
        1
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_agent_policies").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "bcs_messages").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_task_receipts").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 2);

    db.execute(DbStatement::new(format!(
        "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, \
         aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, \
         metadata_json, correlation_id, idempotency_key) VALUES \
         ('ordinary-message-outbox', 'tenant-1', 'project-1', 'workspace-task-session-1', \
          'workspace_message', 'ordinary-message', 'workspace_message_created', \
          'workspace:workspace-task-session-1:events', {}, '{{}}', '{{}}', \
          'ordinary-message-correlation', 'ordinary-message-key')",
        MESSAGE_EVENT_SEQUENCE_BASE + 2
    )))
    .await?;

    let existing = workspace_router(state.clone())
        .oneshot(task_session_request_for_existing("Follow-up objective")?)
        .await?;
    assert_eq!(existing.status(), StatusCode::CREATED);
    let existing: Value =
        serde_json::from_slice(&to_bytes(existing.into_body(), usize::MAX).await?)?;
    assert_eq!(existing["workspace"]["id"], "workspace-task-session-1");
    assert_eq!(existing["initial_message"]["id"], "message-task-session-2");
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 1);
    assert_eq!(table_count(db.as_ref(), "bcs_messages").await?, 2);
    assert_eq!(
        table_count(db.as_ref(), "workspace_task_receipts").await?,
        2
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 4);

    let conflict = workspace_router(state)
        .oneshot(task_session_request("Changed objective")?)
        .await?;
    assert_eq!(conflict.status(), StatusCode::CONFLICT);
    let conflict: Value =
        serde_json::from_slice(&to_bytes(conflict.into_body(), usize::MAX).await?)?;
    assert_eq!(conflict["code"], "TASK_SESSION_IDEMPOTENCY_CONFLICT");
    assert_eq!(table_count(db.as_ref(), "bcs_messages").await?, 2);
    assert_eq!(
        table_count(db.as_ref(), "workspace_task_receipts").await?,
        2
    );
    Ok(())
}

#[tokio::test]
async fn task_session_create_fails_closed_without_project_authority() -> Result<(), Box<dyn Error>>
{
    let db = Arc::new(task_session_db().await?);
    db.execute(DbStatement::new(
        "DELETE FROM project_principal_memberships WHERE user_id = 'owner-1'",
    ))
    .await?;
    let state = Arc::new(WorkspaceCoreState::new_with_registries(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(StaticAgentRegistry),
        Arc::new(StaticProviderRegistry),
    )?);

    let response = workspace_router(state)
        .oneshot(task_session_request("Initial objective")?)
        .await?;

    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        table_count(db.as_ref(), "project_principal_memberships").await?,
        0
    );
    assert_eq!(table_count(db.as_ref(), "workspace_profiles").await?, 0);
    assert_eq!(table_count(db.as_ref(), "bcs_messages").await?, 0);
    assert_eq!(
        table_count(db.as_ref(), "workspace_task_receipts").await?,
        0
    );
    Ok(())
}

fn task_session_request(content: &str) -> Result<Request<Body>, Box<dyn Error>> {
    Ok(Request::builder()
        .method("POST")
        .uri("/internal/v1/tenants/tenant-1/projects/project-1/task-sessions")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-email", "owner-1@example.com")
        .header("x-memstack-user-is-superuser", "false")
        .header("x-idempotency-key", "task-session-intent-1")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "workspace": {
                    "kind": "create",
                    "workspace_id": "workspace-task-session-1",
                    "name": "Task session workspace",
                    "description": "Created atomically",
                    "metadata": {"source": "task_session"},
                    "use_case": "general",
                    "collaboration_mode": "single_agent",
                    "sandbox_code_root": null
                },
                "conversation_id": "conversation-task-session-1",
                "initial_message": {
                    "message_id": "message-task-session-1",
                    "content": content,
                    "context_items": [{
                        "kind": "attachment",
                        "resource_id": "artifact-1",
                        "label": "Requirements",
                        "metadata": {"mime": "text/plain"}
                    }]
                },
                "workspace_policy": {
                    "expected_revision": 0,
                    "route": {"provider_id": "provider-1", "model_id": "model-1"},
                    "reasoning_effort": "medium",
                    "permission_mode": "ask"
                },
                "capability_mode": "work"
            })
            .to_string(),
        ))?)
}

fn task_session_request_for_existing(content: &str) -> Result<Request<Body>, Box<dyn Error>> {
    Ok(Request::builder()
        .method("POST")
        .uri("/internal/v1/tenants/tenant-1/projects/project-1/task-sessions")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "owner-1")
        .header("x-memstack-user-email", "owner-1@example.com")
        .header("x-memstack-user-is-superuser", "false")
        .header("x-idempotency-key", "task-session-intent-2")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "workspace": {
                    "kind": "existing",
                    "workspace_id": "workspace-task-session-1"
                },
                "conversation_id": "conversation-task-session-2",
                "initial_message": {
                    "message_id": "message-task-session-2",
                    "content": content,
                    "context_items": []
                },
                "workspace_policy": null,
                "capability_mode": "work"
            })
            .to_string(),
        ))?)
}

async fn task_session_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
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

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::new(format!(
            "SELECT COUNT(*) AS row_count FROM {table}"
        )))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing count row")?
        .get_i64("row_count")?
        .ok_or("missing count")?)
}
