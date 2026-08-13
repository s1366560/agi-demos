use std::collections::BTreeSet;
use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, Response, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "task-http-contract-token";
const TASKS_PATH: &str = "/api/v1/workspaces/workspace-1/tasks";

#[tokio::test]
async fn task_http_exposes_all_routes_with_atomic_replayable_authority()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_task_db().await?);
    let state = task_state(db.clone())?;
    let create_payload = json!({
        "title": "Ship Task HTTP authority",
        "description": "Preserve the legacy contract",
        "metadata": {"source": "http-contract"},
        "preferred_language": "zh-CN",
        "priority": "P2",
        "estimated_effort": "2h"
    });

    let created = send_json(
        state.clone(),
        task_request(
            "POST",
            TASKS_PATH,
            "user-1",
            Some(&create_payload),
            Some("create-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_task_shape(&created)?;
    assert_eq!(created["workspace_id"], "workspace-1");
    assert_eq!(created["created_by"], "user-1");
    assert_eq!(created["priority"], "P2");
    assert_eq!(created["metadata"]["preferred_language"], "zh-CN");
    let task_id = created["id"].as_str().ok_or("task id is missing")?;
    let task_path = format!("{TASKS_PATH}/{task_id}");

    let replayed = send_json(
        state.clone(),
        task_request(
            "POST",
            TASKS_PATH,
            "user-1",
            Some(&create_payload),
            Some("create-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(replayed, created);

    let listed = send_json(
        state.clone(),
        task_request(
            "GET",
            &format!("{TASKS_PATH}?status=todo&limit=100&offset=0"),
            "user-1",
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(listed, json!([created.clone()]));

    let fetched = send_json(
        state.clone(),
        task_request("GET", &task_path, "user-1", None, None, None)?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(fetched, created);

    let updated = send_json(
        state.clone(),
        task_request(
            "PATCH",
            &task_path,
            "user-1",
            Some(&json!({"title": "Updated Task authority", "priority": "P1"})),
            Some("update-1"),
            Some(1),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(updated["title"], "Updated Task authority");
    assert_eq!(updated["priority"], "P1");

    let assigned = send_json(
        state.clone(),
        task_request(
            "POST",
            &format!("{task_path}/assign-agent"),
            "user-1",
            Some(&json!({"workspace_agent_id": "binding-1", "preferred_language": "en-US"})),
            Some("assign-1"),
            Some(2),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(assigned["assignee_agent_id"], "agent-1");
    assert_eq!(assigned["workspace_agent_id"], "binding-1");

    let unassigned = send_json(
        state.clone(),
        task_request(
            "POST",
            &format!("{task_path}/unassign-agent"),
            "user-1",
            None,
            Some("unassign-1"),
            Some(3),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(unassigned["assignee_agent_id"], Value::Null);
    assert_eq!(unassigned["workspace_agent_id"], Value::Null);

    let claimed = send_json(
        state.clone(),
        task_request(
            "POST",
            &format!("{task_path}/claim"),
            "user-1",
            None,
            Some("claim-1"),
            Some(4),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(claimed["assignee_user_id"], "user-1");

    for (action, revision, key, status) in [
        ("start", 5, "start-1", "in_progress"),
        ("block", 6, "block-1", "blocked"),
        ("complete", 7, "complete-1", "done"),
    ] {
        let transitioned = send_json(
            state.clone(),
            task_request(
                "POST",
                &format!("{task_path}/{action}"),
                "user-1",
                None,
                Some(key),
                Some(revision),
            )?,
            StatusCode::OK,
        )
        .await?;
        assert_eq!(transitioned["status"], status);
    }

    let experience = send_json(
        state.clone(),
        task_request(
            "GET",
            &format!("{task_path}/experience"),
            "user-1",
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(experience["task_id"], task_id);
    assert_eq!(
        experience["readiness"]["transition_gates"]["judgment"],
        "agent_judgment_required"
    );

    let execution = send_json(
        state.clone(),
        task_request(
            "GET",
            &format!("{task_path}/execution-session"),
            "user-1",
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(execution["session_status"], "not_started");
    assert_eq!(
        execution["available_interventions"]
            .as_array()
            .map(Vec::len),
        Some(5)
    );

    let recovery = send_json(
        state.clone(),
        task_request(
            "POST",
            &format!("{task_path}/recovery-actions"),
            "user-1",
            Some(&json!({"action": "new_attempt", "reason": "Explicit operator retry"})),
            Some("recovery-1"),
            Some(8),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(recovery["status"], "queued");
    assert!(recovery["attempt_id"].is_string());
    assert!(recovery["outbox_id"].is_string());

    let deleted = send(
        state.clone(),
        task_request(
            "DELETE",
            &task_path,
            "user-1",
            None,
            Some("delete-1"),
            Some(12),
        )?,
    )
    .await?;
    assert_eq!(deleted.status(), StatusCode::NO_CONTENT);
    assert!(to_bytes(deleted.into_body(), usize::MAX).await?.is_empty());

    let missing = send_json(
        state,
        task_request("GET", &task_path, "user-1", None, None, None)?,
        StatusCode::NOT_FOUND,
    )
    .await?;
    assert_eq!(missing, json!({"detail": "Workspace task not found"}));

    assert_eq!(
        table_count(db.as_ref(), "workspace_task_receipts").await?,
        10
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 13);
    assert_eq!(
        table_count(db.as_ref(), "workspace_task_attempts").await?,
        1
    );
    assert_eq!(authority_revision(db.as_ref()).await?, 13);
    Ok(())
}

#[tokio::test]
async fn task_http_resolves_scope_from_workspace_and_rejects_invalid_or_unauthorized_requests()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_task_db().await?);
    let state = task_state(db)?;

    let missing_user = Request::builder()
        .method("GET")
        .uri(TASKS_PATH)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .body(Body::empty())?;
    let response = send_json(state.clone(), missing_user, StatusCode::BAD_REQUEST).await?;
    assert_eq!(
        response,
        json!({"detail": "missing x-memstack-user-id header"})
    );

    let outsider = send_json(
        state.clone(),
        task_request("GET", TASKS_PATH, "user-outsider", None, None, None)?,
        StatusCode::FORBIDDEN,
    )
    .await?;
    assert_eq!(outsider, json!({"detail": "Access denied"}));

    let missing_workspace = send_json(
        state.clone(),
        task_request(
            "GET",
            "/api/v1/workspaces/missing/tasks",
            "user-1",
            None,
            None,
            None,
        )?,
        StatusCode::NOT_FOUND,
    )
    .await?;
    assert_eq!(
        missing_workspace,
        json!({"detail": "Workspace task not found"})
    );

    for path in [
        format!("{TASKS_PATH}?limit=501"),
        format!("{TASKS_PATH}?offset=-1"),
        format!("{TASKS_PATH}?status=unknown"),
    ] {
        let invalid = send_json(
            state.clone(),
            task_request("GET", &path, "user-1", None, None, None)?,
            StatusCode::UNPROCESSABLE_ENTITY,
        )
        .await?;
        assert!(invalid["detail"].is_array());
    }

    let invalid_title = send_json(
        state.clone(),
        task_request(
            "POST",
            TASKS_PATH,
            "user-1",
            Some(&json!({"title": ""})),
            Some("invalid-title"),
            Some(0),
        )?,
        StatusCode::UNPROCESSABLE_ENTITY,
    )
    .await?;
    assert_eq!(invalid_title["detail"][0]["loc"], json!(["body", "title"]));

    let invalid_revision = send_json(
        state,
        task_request_with_if_match(
            "POST",
            TASKS_PATH,
            "user-1",
            Some(&json!({"title": "valid"})),
            Some("invalid-revision"),
            Some("not-a-revision"),
        )?,
        StatusCode::BAD_REQUEST,
    )
    .await?;
    assert_eq!(
        invalid_revision,
        json!({"detail": "If-Match must contain a non-negative Workspace revision"})
    );
    Ok(())
}

fn task_state(db: Arc<LocalSqliteDbPlugin>) -> Result<Arc<WorkspaceCoreState>, &'static str> {
    WorkspaceCoreState::new_with_sql_flavor(db, SERVICE_TOKEN.to_string(), DbSqlFlavor::Sqlite)
        .map(Arc::new)
}

fn task_request(
    method: &str,
    path: &str,
    user_id: &str,
    body: Option<&Value>,
    idempotency_key: Option<&str>,
    revision: Option<u64>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let if_match = revision.map(|value| value.to_string());
    task_request_with_if_match(
        method,
        path,
        user_id,
        body,
        idempotency_key,
        if_match.as_deref(),
    )
}

fn task_request_with_if_match(
    method: &str,
    path: &str,
    user_id: &str,
    body: Option<&Value>,
    idempotency_key: Option<&str>,
    if_match: Option<&str>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut request = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", user_id);
    if let Some(idempotency_key) = idempotency_key {
        request = request.header("idempotency-key", idempotency_key);
    }
    if let Some(if_match) = if_match {
        request = request.header("if-match", if_match);
    }
    if body.is_some() {
        request = request.header(header::CONTENT_TYPE, "application/json");
    }
    Ok(request.body(body.map_or_else(Body::empty, |value| Body::from(value.to_string())))?)
}

async fn send(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
) -> Result<Response<Body>, Box<dyn Error>> {
    Ok(workspace_router(state).oneshot(request).await?)
}

async fn send_json(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
    expected_status: StatusCode,
) -> Result<Value, Box<dyn Error>> {
    let response = send(state, request).await?;
    assert_eq!(response.status(), expected_status);
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX).await?,
    )?)
}

fn assert_task_shape(task: &Value) -> Result<(), Box<dyn Error>> {
    let fields = task.as_object().ok_or("task response is not an object")?;
    let actual = fields.keys().map(String::as_str).collect::<BTreeSet<_>>();
    let expected = [
        "archived_at",
        "assignee_agent_id",
        "assignee_user_id",
        "blocker_reason",
        "completed_at",
        "created_at",
        "created_by",
        "current_attempt_conversation_id",
        "current_attempt_id",
        "current_attempt_number",
        "current_attempt_worker_agent_id",
        "current_attempt_worker_binding_id",
        "description",
        "estimated_effort",
        "id",
        "last_attempt_status",
        "last_worker_report_artifacts",
        "last_worker_report_summary",
        "last_worker_report_type",
        "last_worker_report_verifications",
        "metadata",
        "pending_leader_adjudication",
        "priority",
        "status",
        "title",
        "updated_at",
        "workspace_agent_id",
        "workspace_id",
    ]
    .into_iter()
    .collect::<BTreeSet<_>>();
    if actual != expected {
        return Err(format!("task response keys differ: {actual:?}").into());
    }
    Ok(())
}

async fn seeded_task_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, is_active INTEGER NOT NULL)",
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, assignee_user_id TEXT, assignee_agent_id TEXT, status TEXT NOT NULL, priority INTEGER NOT NULL, estimated_effort TEXT, blocker_reason TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, archived_at TEXT)",
        "CREATE TABLE workspace_task_attempts (attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT NOT NULL, root_goal_task_id TEXT NOT NULL, attempt_number INTEGER NOT NULL, status TEXT NOT NULL, conversation_id TEXT, worker_agent_id TEXT, leader_agent_id TEXT, candidate_summary TEXT, candidate_artifacts_json TEXT NOT NULL, candidate_verifications_json TEXT NOT NULL, leader_feedback TEXT, adjudication_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, UNIQUE(task_id, attempt_number))",
        "CREATE TABLE workspace_task_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT, actor_id TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, expected_revision INTEGER, committed_revision INTEGER, result_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_agent_runtime_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT, attempt_id TEXT, conversation_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_execution_terminals (terminal_id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL, execution_status TEXT NOT NULL)",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_agent_bindings VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', 'agent-1', 1)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_task_receipts" => "SELECT COUNT(*) AS value FROM workspace_task_receipts",
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        "workspace_task_attempts" => "SELECT COUNT(*) AS value FROM workspace_task_attempts",
        _ => return Err("unsupported table".into()),
    };
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing count")?
        .get_i64("value")?
        .ok_or("missing count value")?)
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new("SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'"))
        .await?
        .first()
        .ok_or("missing authority")?
        .get_i64("value")?
        .ok_or("missing revision")?)
}
