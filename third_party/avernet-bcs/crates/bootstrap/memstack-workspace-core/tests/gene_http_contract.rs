use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, Response, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "gene-http-contract-token";
const GENES_PATH: &str =
    "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/genes";

#[tokio::test]
async fn gene_http_preserves_semantic_version_replay_filters_and_atomic_events()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_gene_db().await?);
    let state = gene_state(db.clone())?;
    let create_payload = json!({
        "name": "Planner",
        "category": "skill",
        "description": "Plans structured work",
        "config_json": "{\"temperature\":0.2,\"tools\":[\"plan\"]}",
        "version": "1.2.0",
        "is_active": true
    });
    let created = send_json(
        state.clone(),
        gene_request(
            "POST",
            GENES_PATH,
            "user-1",
            Some(&create_payload),
            Some("gene-create-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(created["workspace_id"], "workspace-1");
    assert_eq!(created["version"], "1.2.0");
    assert_eq!(created["created_by"], "user-1");
    let gene_id = created["id"].as_str().ok_or("gene id missing")?;
    let gene_path = format!("{GENES_PATH}/{gene_id}");

    let replayed = send_json(
        state.clone(),
        gene_request(
            "POST",
            GENES_PATH,
            "user-1",
            Some(&create_payload),
            Some("gene-create-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(replayed, created);

    let listed = send_json(
        state.clone(),
        gene_request(
            "GET",
            &format!("{GENES_PATH}?category=skill&is_active=true&limit=100&offset=0"),
            "viewer-1",
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(listed, json!({"items": [created.clone()], "total": 1}));

    let fetched = send_json(
        state.clone(),
        gene_request("GET", &gene_path, "viewer-1", None, None, None)?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(fetched, created);

    let updated = send_json(
        state.clone(),
        gene_request(
            "PATCH",
            &gene_path,
            "user-1",
            Some(&json!({
                "name": "Planner v2",
                "version": "2.0.0",
                "config_json": "{\"tools\":[\"plan\"],\"temperature\":0.1}",
                "is_active": false
            })),
            Some("gene-update-1"),
            Some(1),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(updated["name"], "Planner v2");
    assert_eq!(updated["version"], "2.0.0");
    assert_eq!(updated["is_active"], false);
    assert_eq!(scalar_i64(db.as_ref(), "SELECT version AS value FROM workspace_genes").await?, 2);
    assert_eq!(
        scalar_string(db.as_ref(), "SELECT source_version AS value FROM workspace_genes").await?,
        "2.0.0"
    );

    let response = send(
        state.clone(),
        gene_request(
            "DELETE",
            &gene_path,
            "user-1",
            None,
            Some("gene-delete-1"),
            Some(2),
        )?,
    )
    .await?;
    assert_eq!(response.status(), StatusCode::NO_CONTENT);
    assert!(to_bytes(response.into_body(), usize::MAX).await?.is_empty());
    let replayed_delete = send(
        state,
        gene_request(
            "DELETE",
            &gene_path,
            "user-1",
            None,
            Some("gene-delete-1"),
            Some(2),
        )?,
    )
    .await?;
    assert_eq!(replayed_delete.status(), StatusCode::NO_CONTENT);
    assert_eq!(authority_revision(db.as_ref()).await?, 3);
    assert_eq!(table_count(db.as_ref(), "workspace_genes").await?, 0);
    assert_eq!(table_count(db.as_ref(), "workspace_mutation_receipts").await?, 3);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 3);
    Ok(())
}

#[tokio::test]
async fn gene_http_rejects_non_object_config_viewer_write_and_stale_revision()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_gene_db().await?);
    let state = gene_state(db)?;
    let invalid = send_json(
        state.clone(),
        gene_request(
            "POST",
            GENES_PATH,
            "user-1",
            Some(&json!({"name": "Invalid", "config_json": "[]"})),
            Some("invalid-config"),
            Some(0),
        )?,
        StatusCode::UNPROCESSABLE_ENTITY,
    )
    .await?;
    assert_eq!(invalid, json!({"detail": "config_json must be a JSON object"}));

    let denied = send_json(
        state.clone(),
        gene_request(
            "POST",
            GENES_PATH,
            "viewer-1",
            Some(&json!({"name": "Denied"})),
            Some("viewer-create"),
            Some(0),
        )?,
        StatusCode::FORBIDDEN,
    )
    .await?;
    assert_eq!(denied, json!({"detail": "Access denied"}));

    let mut superuser_request = gene_request(
        "POST",
        GENES_PATH,
        "superuser-1",
        Some(&json!({"name": "Superuser Gene"})),
        Some("superuser-create"),
        Some(0),
    )?;
    superuser_request.headers_mut().insert(
        "x-memstack-user-is-superuser",
        "true".parse()?,
    );
    let superuser_created = send_json(
        state.clone(),
        superuser_request,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(superuser_created["created_by"], "superuser-1");

    let stale = send_json(
        state,
        gene_request(
            "POST",
            GENES_PATH,
            "user-1",
            Some(&json!({"name": "Stale"})),
            Some("stale-create"),
            Some(9),
        )?,
        StatusCode::CONFLICT,
    )
    .await?;
    assert_eq!(stale, json!({"detail": "Workspace Gene authority conflict"}));
    Ok(())
}

fn gene_state(db: Arc<LocalSqliteDbPlugin>) -> Result<Arc<WorkspaceCoreState>, &'static str> {
    WorkspaceCoreState::new_with_sql_flavor(db, SERVICE_TOKEN.to_string(), DbSqlFlavor::Sqlite)
        .map(Arc::new)
}

fn gene_request(
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

async fn seeded_gene_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_genes (gene_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT, category TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL, source_version TEXT NOT NULL, is_active INTEGER NOT NULL, config_text TEXT, content_json TEXT NOT NULL, content_hash TEXT NOT NULL, source_objective_id TEXT, created_by_actor_id TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT)",
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
        "workspace_genes" => "SELECT COUNT(*) AS value FROM workspace_genes",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    scalar_i64(db, statement).await
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    scalar_i64(
        db,
        "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
    )
    .await
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing scalar")?
        .get_i64("value")?
        .ok_or("missing scalar value")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing scalar")?
        .get_string("value")?
        .ok_or("missing scalar value")?)
}
