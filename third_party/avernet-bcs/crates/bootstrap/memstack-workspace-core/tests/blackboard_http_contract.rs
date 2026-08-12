use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, Response, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "blackboard-http-contract-token";
const POSTS_PATH: &str =
    "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/blackboard/posts";

#[tokio::test]
async fn blackboard_http_preserves_post_reply_replay_and_event_contracts()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_blackboard_db().await?);
    let state = blackboard_state(db.clone())?;
    let create_payload = json!({
        "title": "Blackboard authority",
        "content": "Durable post",
        "metadata": {"source": "http-contract"}
    });
    let created = send_json(
        state.clone(),
        blackboard_request(
            "POST",
            POSTS_PATH,
            "user-1",
            Some(&create_payload),
            Some("post-create-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(created["workspace_id"], "workspace-1");
    assert_eq!(created["author_id"], "user-1");
    assert_eq!(created["metadata"]["surface_boundary"], "owned");
    let post_id = created["id"].as_str().ok_or("post id missing")?;
    let post_path = format!("{POSTS_PATH}/{post_id}");

    let replayed = send_json(
        state.clone(),
        blackboard_request(
            "POST",
            POSTS_PATH,
            "user-1",
            Some(&create_payload),
            Some("post-create-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(replayed, created);

    let listed = send_json(
        state.clone(),
        blackboard_request(
            "GET",
            &format!("{POSTS_PATH}?limit=50&offset=0"),
            "viewer-1",
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(listed, json!({"items": [created.clone()]}));

    let updated = send_json(
        state.clone(),
        blackboard_request(
            "PATCH",
            &post_path,
            "user-1",
            Some(&json!({"title": "Updated authority", "status": "archived"})),
            Some("post-update-1"),
            Some(1),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(updated["title"], "Updated authority");
    assert_eq!(updated["status"], "archived");

    let pinned = send_json(
        state.clone(),
        blackboard_request(
            "POST",
            &format!("{post_path}/pin"),
            "user-1",
            None,
            Some("post-pin-1"),
            Some(2),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(pinned["is_pinned"], true);
    let unpinned = send_json(
        state.clone(),
        blackboard_request(
            "POST",
            &format!("{post_path}/unpin"),
            "user-1",
            None,
            Some("post-unpin-1"),
            Some(3),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(unpinned["is_pinned"], false);

    let replies_path = format!("{post_path}/replies");
    let reply = send_json(
        state.clone(),
        blackboard_request(
            "POST",
            &replies_path,
            "user-1",
            Some(&json!({"content": "First reply"})),
            Some("reply-create-1"),
            Some(4),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(reply["post_id"], post_id);
    let reply_id = reply["id"].as_str().ok_or("reply id missing")?;
    let reply_path = format!("{replies_path}/{reply_id}");
    let replies = send_json(
        state.clone(),
        blackboard_request(
            "GET",
            &format!("{replies_path}?limit=200&offset=0"),
            "viewer-1",
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(replies, json!({"items": [reply.clone()]}));

    let updated_reply = send_json(
        state.clone(),
        blackboard_request(
            "PATCH",
            &reply_path,
            "user-1",
            Some(&json!({"content": "Verified reply", "metadata": {"verified": true}})),
            Some("reply-update-1"),
            Some(5),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(updated_reply["content"], "Verified reply");

    assert_eq!(
        send_json(
            state.clone(),
            blackboard_request(
                "DELETE",
                &reply_path,
                "user-1",
                None,
                Some("reply-delete-1"),
                Some(6),
            )?,
            StatusCode::OK,
        )
        .await?,
        json!({"success": true})
    );
    assert_eq!(
        send_json(
            state.clone(),
            blackboard_request(
                "DELETE",
                &post_path,
                "user-1",
                None,
                Some("post-delete-1"),
                Some(7),
            )?,
            StatusCode::OK,
        )
        .await?,
        json!({"success": true})
    );
    assert_eq!(authority_revision(db.as_ref()).await?, 8);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        8
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 8);
    Ok(())
}

#[tokio::test]
async fn blackboard_http_rejects_invalid_scope_role_body_and_revision() -> Result<(), Box<dyn Error>>
{
    let db = Arc::new(seeded_blackboard_db().await?);
    let state = blackboard_state(db)?;
    let payload = json!({"title": "Denied", "content": "Denied"});
    let denied = send_json(
        state.clone(),
        blackboard_request(
            "POST",
            POSTS_PATH,
            "viewer-1",
            Some(&payload),
            Some("viewer-create"),
            Some(0),
        )?,
        StatusCode::FORBIDDEN,
    )
    .await?;
    assert_eq!(denied, json!({"detail": "Access denied"}));

    let wrong_scope = POSTS_PATH.replacen("tenant-1", "tenant-2", 1);
    let not_found = send_json(
        state.clone(),
        blackboard_request("GET", &wrong_scope, "user-1", None, None, None)?,
        StatusCode::NOT_FOUND,
    )
    .await?;
    assert_eq!(not_found, json!({"detail": "Blackboard item not found"}));

    let invalid = send_json(
        state.clone(),
        blackboard_request(
            "POST",
            POSTS_PATH,
            "user-1",
            Some(&json!({"title": "", "content": "ok"})),
            Some("invalid-body"),
            Some(0),
        )?,
        StatusCode::UNPROCESSABLE_ENTITY,
    )
    .await?;
    assert_eq!(invalid["detail"][0]["loc"], json!(["body", "title"]));

    let stale = send_json(
        state.clone(),
        blackboard_request(
            "POST",
            POSTS_PATH,
            "user-1",
            Some(&payload),
            Some("stale-create"),
            Some(9),
        )?,
        StatusCode::CONFLICT,
    )
    .await?;
    assert_eq!(
        stale,
        json!({"detail": "Workspace blackboard authority conflict"})
    );
    Ok(())
}

fn blackboard_state(db: Arc<LocalSqliteDbPlugin>) -> Result<Arc<WorkspaceCoreState>, &'static str> {
    WorkspaceCoreState::new_with_sql_flavor(db, SERVICE_TOKEN.to_string(), DbSqlFlavor::Sqlite)
        .map(Arc::new)
}

fn blackboard_request(
    method: &str,
    path: &str,
    user_id: &str,
    body: Option<&Value>,
    idempotency_key: Option<&str>,
    revision: Option<u64>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut request = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", user_id);
    if let Some(idempotency_key) = idempotency_key {
        request = request.header("idempotency-key", idempotency_key);
    }
    if let Some(revision) = revision {
        request = request.header("if-match", revision.to_string());
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

async fn seeded_blackboard_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_blackboard_posts (post_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, author_actor_id TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, is_pinned INTEGER NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT)",
        "CREATE TABLE workspace_blackboard_replies (reply_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, post_id TEXT NOT NULL, author_actor_id TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT)",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let statement = match table {
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    Ok(db
        .query(DbStatement::new(statement))
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
