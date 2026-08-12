use std::collections::HashMap;
use std::error::Error;
use std::sync::Arc;

use async_trait::async_trait;
use axum::body::{Body, to_bytes};
use axum::http::{Request, Response, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use bcs_domain::BotDeliveryTarget;
use bcs_service_api::{
    BotDeliveryCommand, BotDeliveryPort, BotDeliveryResult, BotRunContext, BotRunContextPort,
    ServiceError, ServiceResult,
};
use memstack_workspace_core::message_delivery::{
    WorkspaceMessageRuntime, WorkspaceMessageRuntimeConfig,
};
use memstack_workspace_core::{WorkspaceCoreState, workspace_router_with_message_runtime};
use serde_json::{Value, json};
use tokio::sync::Mutex;
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "message-http-contract-token";
const MESSAGES_PATH: &str =
    "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/messages";

#[tokio::test]
async fn message_http_commits_replays_lists_and_preserves_event_contract()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let payload = json!({
        "content": "Hello BCS",
        "mentions": ["agent-active"],
        "ignored_legacy_field": {"keep_compatibility": true}
    });

    let first = send(
        state.clone(),
        message_request(
            "POST",
            MESSAGES_PATH,
            "user-owner",
            Some(&payload),
            Some("send-1"),
        )?,
    )
    .await?;
    assert_eq!(first.status(), StatusCode::CREATED);
    let first = response_json(first).await?;
    assert_message_shape(&first)?;
    assert_eq!(first["workspace_id"], "workspace-1");
    assert_eq!(first["sender_id"], "user-owner");
    assert_eq!(first["sender_type"], "human");
    assert_eq!(first["content"], "Hello BCS");
    assert_eq!(first["mentions"], json!(["agent-active"]));
    assert_eq!(
        first["metadata"],
        json!({"sender_name": "owner@example.com"})
    );
    assert!(
        first["created_at"]
            .as_str()
            .is_some_and(|value| value.ends_with('Z'))
    );

    let replay = send(
        state.clone(),
        message_request(
            "POST",
            MESSAGES_PATH,
            "user-owner",
            Some(&payload),
            Some("send-1"),
        )?,
    )
    .await?;
    assert_eq!(replay.status(), StatusCode::OK);
    assert_eq!(response_json(replay).await?, first);

    let listed = send(
        state.clone(),
        message_request("GET", MESSAGES_PATH, "user-owner", None, None)?,
    )
    .await?;
    assert_eq!(listed.status(), StatusCode::OK);
    assert_eq!(
        response_json(listed).await?["items"],
        json!([first.clone()])
    );

    let mentioned = send(
        state,
        message_request(
            "GET",
            &format!("{MESSAGES_PATH}/mentions/agent-active"),
            "user-owner",
            None,
            None,
        )?,
    )
    .await?;
    assert_eq!(mentioned.status(), StatusCode::OK);
    assert_eq!(response_json(mentioned).await?["items"], json!([first]));

    assert_eq!(table_count(db.as_ref(), "bcs_messages").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);
    let event = outbox_event(db.as_ref()).await?;
    assert_eq!(event["event_type"], "workspace_message_created");
    assert_eq!(event["payload"]["message"]["content"], "Hello BCS");
    assert_eq!(
        event["metadata"],
        json!({
            "surface_owner": "workspace-chat",
            "surface_boundary": "hosted",
            "authority_class": "non-authoritative",
            "signal_role": "sensing-capable"
        })
    );
    Ok(())
}

#[tokio::test]
async fn message_http_preserves_validation_and_access_failures() -> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    for (payload, expected) in [
        (json!({"content": ""}), StatusCode::UNPROCESSABLE_ENTITY),
        (json!({"content": "   "}), StatusCode::BAD_REQUEST),
        (
            json!({"content": "spoof", "sender_type": "agent"}),
            StatusCode::BAD_REQUEST,
        ),
        (
            json!({"content": "bad mention", "mentions": ["outside-roster"]}),
            StatusCode::BAD_REQUEST,
        ),
    ] {
        let response = send(
            state.clone(),
            message_request("POST", MESSAGES_PATH, "user-owner", Some(&payload), None)?,
        )
        .await?;
        assert_eq!(response.status(), expected, "payload {payload}");
        if expected == StatusCode::BAD_REQUEST {
            assert_eq!(
                response_json(response).await?,
                json!({"detail": "Invalid workspace chat request"})
            );
        }
    }

    let viewer = send(
        state.clone(),
        message_request(
            "POST",
            MESSAGES_PATH,
            "user-viewer",
            Some(&json!({"content": "viewer write"})),
            None,
        )?,
    )
    .await?;
    assert_eq!(viewer.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        response_json(viewer).await?,
        json!({"detail": "Workspace editor access required"})
    );

    let outsider = send(
        state.clone(),
        message_request("GET", MESSAGES_PATH, "user-outsider", None, None)?,
    )
    .await?;
    assert_eq!(outsider.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        response_json(outsider).await?,
        json!({"detail": "Workspace access required"})
    );

    let missing = send(
        state.clone(),
        message_request(
            "GET",
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/missing/messages",
            "user-owner",
            None,
            None,
        )?,
    )
    .await?;
    assert_eq!(missing.status(), StatusCode::NOT_FOUND);
    assert_eq!(
        response_json(missing).await?,
        json!({"detail": "Workspace not found"})
    );

    for limit in ["0", "201", "not-an-integer"] {
        let response = send(
            state.clone(),
            message_request(
                "GET",
                &format!("{MESSAGES_PATH}?limit={limit}"),
                "user-owner",
                None,
                None,
            )?,
        )
        .await?;
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }
    assert_eq!(table_count(db.as_ref(), "bcs_messages").await?, 0);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 0);
    Ok(())
}

#[tokio::test]
async fn message_http_commits_delivery_job_before_provider_attempt() -> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let payload = json!({
        "content": "Provider can recover later",
        "mentions": ["agent-active"]
    });

    let response = send_with_delivery(
        state,
        message_request(
            "POST",
            MESSAGES_PATH,
            "user-owner",
            Some(&payload),
            Some("send-provider-recovery"),
        )?,
        Arc::new(RejectingDelivery),
    )
    .await?;

    assert_eq!(response.status(), StatusCode::CREATED);
    assert_eq!(
        table_count(db.as_ref(), "workspace_message_delivery_outbox").await?,
        1
    );
    let rows = db
        .query(DbStatement::new(
            "SELECT status, attempt_count FROM workspace_message_delivery_outbox",
        ))
        .await?;
    let job = rows
        .first()
        .ok_or_else(|| std::io::Error::other("delivery job is missing"))?;
    assert_eq!(job.get_string("status")?.as_deref(), Some("pending"));
    assert_eq!(job.get_i64("attempt_count")?, Some(0));
    Ok(())
}

fn message_request(
    method: &str,
    uri: &str,
    user_id: &str,
    payload: Option<&Value>,
    idempotency_key: Option<&str>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", user_id)
        .header("x-memstack-user-is-superuser", "false");
    if let Some(idempotency_key) = idempotency_key {
        builder = builder.header("idempotency-key", idempotency_key);
    }
    let body = match payload {
        Some(payload) => {
            builder = builder.header(header::CONTENT_TYPE, "application/json");
            Body::from(payload.to_string())
        }
        None => Body::empty(),
    };
    Ok(builder.body(body)?)
}

async fn send(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
) -> Result<Response<Body>, Box<dyn Error>> {
    send_with_delivery(state, request, Arc::new(AcceptingDelivery)).await
}

async fn send_with_delivery(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
    delivery: Arc<dyn BotDeliveryPort>,
) -> Result<Response<Body>, Box<dyn Error>> {
    let runtime = Arc::new(WorkspaceMessageRuntime::new(
        delivery,
        Arc::new(TestRunContext::default()),
        WorkspaceMessageRuntimeConfig {
            webhook_url: "https://agent-runtime.example/internal/v1/workspace-core/provider"
                .to_string(),
            webhook_token: "message-http-provider-token".to_string(),
            callback_timeout_ms: 60_000,
        },
    )?);
    Ok(workspace_router_with_message_runtime(state, runtime)
        .oneshot(request)
        .await?)
}

struct AcceptingDelivery;

#[async_trait]
impl BotDeliveryPort for AcceptingDelivery {
    async fn is_available(&self, _target: &BotDeliveryTarget) -> bool {
        true
    }

    async fn deliver(&self, command: BotDeliveryCommand) -> ServiceResult<BotDeliveryResult> {
        Ok(BotDeliveryResult {
            target_bot_id: command.target_bot_id().to_string(),
            delivered: true,
            error: None,
        })
    }
}

struct RejectingDelivery;

#[async_trait]
impl BotDeliveryPort for RejectingDelivery {
    async fn is_available(&self, _target: &BotDeliveryTarget) -> bool {
        true
    }

    async fn deliver(&self, _command: BotDeliveryCommand) -> ServiceResult<BotDeliveryResult> {
        Err(ServiceError::InternalError(
            "injected Provider failure".to_string(),
        ))
    }
}

#[derive(Default)]
struct TestRunContext {
    contexts: Mutex<HashMap<String, BotRunContext>>,
}

#[async_trait]
impl BotRunContextPort for TestRunContext {
    async fn put_context(&self, context: BotRunContext) {
        self.contexts
            .lock()
            .await
            .insert(context.run_id.clone(), context);
    }

    async fn get_context(&self, run_id: &str) -> Option<BotRunContext> {
        self.contexts.lock().await.get(run_id).cloned()
    }

    async fn try_begin_terminal(&self, _run_id: &str) -> bool {
        true
    }

    async fn mark_terminal(&self, run_id: &str) -> bool {
        let mut contexts = self.contexts.lock().await;
        let Some(context) = contexts.get_mut(run_id) else {
            return false;
        };
        context.terminal = true;
        true
    }

    async fn release_terminal(&self, _run_id: &str) {}
}

async fn response_json(response: Response<Body>) -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX).await?,
    )?)
}

fn assert_message_shape(message: &Value) -> Result<(), Box<dyn Error>> {
    let fields = message.as_object().ok_or("message is not an object")?;
    assert_eq!(
        fields.keys().map(String::as_str).collect::<Vec<_>>(),
        vec![
            "content",
            "created_at",
            "id",
            "mentions",
            "metadata",
            "parent_message_id",
            "sender_id",
            "sender_type",
            "workspace_id",
        ]
    );
    Ok(())
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL, deleted_at TEXT, UNIQUE(tenant_id, project_id, workspace_id))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_principal_identities (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, email TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY(tenant_id, project_id, workspace_id, user_id))",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, display_name TEXT, is_active INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(workspace_id, agent_id))",
        "CREATE TABLE bcs_group_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, group_id TEXT NOT NULL, env TEXT NOT NULL, status TEXT NOT NULL, session_kind TEXT NOT NULL, caller_id TEXT, caller_principal TEXT, created_by TEXT, participants TEXT NOT NULL, current_msg_seq INTEGER NOT NULL DEFAULT 0, meta TEXT, UNIQUE(env, session_id))",
        "CREATE TABLE bcs_messages (message_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, session_id TEXT NOT NULL, session_seq INTEGER NOT NULL, env TEXT NOT NULL, sender_id TEXT NOT NULL, sender_type TEXT NOT NULL, message_type TEXT NOT NULL, content TEXT NOT NULL, client_msg_id TEXT, status TEXT NOT NULL, created_at INTEGER NOT NULL, run_id TEXT NOT NULL, workspace_id TEXT, mentions_json TEXT NOT NULL, parent_message_id TEXT, metadata_json TEXT NOT NULL, source_hash TEXT, UNIQUE(session_id, session_seq))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_message_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, legacy_message_id TEXT NOT NULL, conversation_id TEXT NOT NULL, bcs_session_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, message_kind TEXT NOT NULL, is_terminal INTEGER NOT NULL, idempotency_key TEXT, request_hash TEXT, event_outbox_id TEXT, UNIQUE(workspace_id, legacy_message_id), UNIQUE(bcs_session_id, bcs_message_id), UNIQUE(workspace_id, idempotency_key))",
        "CREATE TABLE workspace_message_delivery_outbox (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, group_id TEXT NOT NULL, target_order INTEGER NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, display_name TEXT, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 8, next_attempt_at_ms INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_expires_at_ms INTEGER, last_error TEXT, delivered_at_ms INTEGER, created_at_ms INTEGER NOT NULL, PRIMARY KEY(workspace_id, bcs_message_id, agent_id), UNIQUE(workspace_id, bcs_message_id, target_order))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    for insert in [
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1')",
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, role) VALUES ('member-owner', 'tenant-1', 'project-1', 'workspace-1', 'user-owner', 'owner'), ('member-viewer', 'tenant-1', 'project-1', 'workspace-1', 'user-viewer', 'viewer')",
        "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, email, is_active) VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-owner', 'owner@example.com', 1), ('tenant-1', 'project-1', 'workspace-1', 'user-viewer', 'viewer@example.com', 1)",
        "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, agent_id, bot_uuid, display_name, is_active, created_at) VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', 'agent-active', 'bot-agent-active', 'Active Agent', 1, '2026-01-01T00:00:00Z')",
    ] {
        db.execute(DbStatement::new(insert)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "bcs_messages" => "SELECT COUNT(*) AS value FROM bcs_messages",
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        "workspace_message_delivery_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_message_delivery_outbox"
        }
        _ => return Err(std::io::Error::other("unsupported table").into()),
    };
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows
        .first()
        .ok_or_else(|| std::io::Error::other("count returned no rows"))?;
    Ok(row
        .get_i64("value")?
        .ok_or_else(|| std::io::Error::other("count is NULL"))?)
}

async fn outbox_event(db: &dyn DbPlugin) -> Result<Value, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::new(
            "SELECT event_type, payload_json, metadata_json FROM workspace_outbox LIMIT 1",
        ))
        .await?;
    let row = rows
        .first()
        .ok_or_else(|| std::io::Error::other("outbox event is missing"))?;
    let event_type = row
        .get_string("event_type")?
        .ok_or_else(|| std::io::Error::other("event_type is NULL"))?;
    let payload = row
        .get_string("payload_json")?
        .ok_or_else(|| std::io::Error::other("payload_json is NULL"))?;
    let metadata = row
        .get_string("metadata_json")?
        .ok_or_else(|| std::io::Error::other("metadata_json is NULL"))?;
    Ok(json!({
        "event_type": event_type,
        "payload": serde_json::from_str::<Value>(&payload)?,
        "metadata": serde_json::from_str::<Value>(&metadata)?,
    }))
}
