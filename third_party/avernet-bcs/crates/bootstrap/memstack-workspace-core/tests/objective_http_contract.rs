use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "objective-http-contract-token";
const OBJECTIVES_PATH: &str =
    "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/objectives";

#[tokio::test]
async fn objective_http_exposes_crud_projection_cas_and_replay() -> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    let create = json!({
        "title": "Replace Workspace Core",
        "description": "Finish the Avernet authority",
        "obj_type": "objective",
        "progress": 0.25
    });

    let created = send_json(
        state.clone(),
        request(
            "POST",
            OBJECTIVES_PATH,
            Some(&create),
            Some("objective-create-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_objective_shape(&created)?;
    assert_eq!(created["title"], "Replace Workspace Core");
    assert_eq!(created["progress"], 0.25);
    let objective_id = created["id"].as_str().ok_or("objective id missing")?;
    let objective_path = format!("{OBJECTIVES_PATH}/{objective_id}");

    let replayed = send_json(
        state.clone(),
        request(
            "POST",
            OBJECTIVES_PATH,
            Some(&create),
            Some("objective-create-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(replayed, created);

    let listed = send_json(
        state.clone(),
        request(
            "GET",
            &format!("{OBJECTIVES_PATH}?obj_type=objective&limit=100&offset=0"),
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(listed["total"], 1);
    assert_eq!(listed["items"][0], created);

    let fetched = send_json(
        state.clone(),
        request("GET", &objective_path, None, None, None)?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(fetched, created);

    let updated = send_json(
        state.clone(),
        request(
            "PATCH",
            &objective_path,
            Some(&json!({"title": "Complete Avernet integration", "progress": 0.5})),
            Some("objective-update-1"),
            Some(1),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(updated["title"], "Complete Avernet integration");
    assert_eq!(updated["progress"], 0.5);

    let projected = send_json(
        state.clone(),
        request(
            "POST",
            &format!("{objective_path}/project-to-task"),
            Some(&json!({"preferred_language": "zh-CN"})),
            Some("objective-project-1"),
            Some(2),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(projected["title"], "Complete Avernet integration");
    assert_eq!(projected["metadata"]["task_role"], "goal_root");
    assert_eq!(projected["metadata"]["objective_id"], objective_id);
    assert_eq!(projected["metadata"]["preferred_language"], "zh-CN");

    let project_replay = send_json(
        state.clone(),
        request(
            "POST",
            &format!("{objective_path}/project-to-task"),
            Some(&json!({"preferred_language": "zh-CN"})),
            Some("objective-project-1"),
            Some(2),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(project_replay, projected);

    let deleted = send_json(
        state,
        request(
            "DELETE",
            &objective_path,
            None,
            Some("objective-delete-1"),
            Some(3),
        )?,
        StatusCode::NO_CONTENT,
    )
    .await?;
    assert_eq!(deleted, Value::Null);
    assert_eq!(authority_revision(db.as_ref()).await?, 4);
    assert_eq!(table_count(db.as_ref(), "workspace_objectives").await?, 0);
    assert_eq!(table_count(db.as_ref(), "workspace_tasks").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_objective_task_projections").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 4);
    Ok(())
}

fn request(
    method: &str,
    path: &str,
    body: Option<&Value>,
    idempotency_key: Option<&str>,
    revision: Option<u64>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut request = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "user-1")
        .header(header::CONTENT_TYPE, "application/json");
    if let Some(idempotency_key) = idempotency_key {
        request = request.header("idempotency-key", idempotency_key);
    }
    if let Some(revision) = revision {
        request = request.header("if-match", revision.to_string());
    }
    Ok(request.body(match body {
        Some(body) => Body::from(serde_json::to_vec(body)?),
        None => Body::empty(),
    })?)
}

async fn send_json(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
    expected: StatusCode,
) -> Result<Value, Box<dyn Error>> {
    let response = workspace_router(state).oneshot(request).await?;
    assert_eq!(response.status(), expected);
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    if bytes.is_empty() {
        return Ok(Value::Null);
    }
    Ok(serde_json::from_slice(&bytes)?)
}

fn assert_objective_shape(value: &Value) -> Result<(), Box<dyn Error>> {
    let fields = value
        .as_object()
        .ok_or("objective response must be an object")?;
    let expected = [
        "created_at",
        "created_by",
        "description",
        "id",
        "obj_type",
        "parent_id",
        "progress",
        "title",
        "updated_at",
        "workspace_id",
    ];
    let actual = fields
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(actual, expected.into_iter().collect());
    Ok(())
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_objectives (objective_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, objective_type TEXT NOT NULL, parent_objective_id TEXT, progress REAL NOT NULL, created_by_actor_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, UNIQUE(tenant_id, project_id, workspace_id, objective_id))",
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, assignee_user_id TEXT, assignee_agent_id TEXT, status TEXT NOT NULL, priority INTEGER NOT NULL, estimated_effort TEXT, blocker_reason TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, archived_at TEXT, UNIQUE(tenant_id, project_id, workspace_id, task_id))",
        "CREATE TABLE workspace_task_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT, actor_id TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, expected_revision INTEGER, committed_revision INTEGER, result_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_objective_task_projections (projection_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, objective_id TEXT NOT NULL, task_id TEXT NOT NULL, created_by_actor_id TEXT NOT NULL, committed_revision INTEGER NOT NULL, outbox_id TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(tenant_id, project_id, workspace_id, objective_id), UNIQUE(tenant_id, project_id, workspace_id, task_id))",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_objectives" => "SELECT COUNT(*) AS value FROM workspace_objectives",
        "workspace_tasks" => "SELECT COUNT(*) AS value FROM workspace_tasks",
        "workspace_objective_task_projections" => {
            "SELECT COUNT(*) AS value FROM workspace_objective_task_projections"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
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
        .query(DbStatement::new(
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
        ))
        .await?
        .first()
        .ok_or("missing authority")?
        .get_i64("value")?
        .ok_or("missing revision")?)
}
