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

const SERVICE_TOKEN: &str = "topology-http-contract-token";
const NODE_PATH: &str = "/api/v1/workspaces/workspace-1/topology/nodes";
const EDGE_PATH: &str = "/api/v1/workspaces/workspace-1/topology/edges";

#[tokio::test]
async fn all_ten_topology_routes_preserve_crud_and_event_contracts() -> Result<(), Box<dyn Error>> {
    let (db, state) = topology_state().await?;
    let source = send_json(
        Arc::clone(&state),
        topology_request(
            "POST",
            NODE_PATH,
            "user-1",
            Some(&json!({
                "node_type": "corridor",
                "title": "Source",
                "position_x": 10.0,
                "position_y": 20.0,
                "hex_q": 1,
                "hex_r": 0,
                "tags": ["contract"],
            })),
            Some("source-create"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_node_shape(&source)?;
    let source_id = required_id(&source)?;

    let target = send_json(
        Arc::clone(&state),
        topology_request(
            "POST",
            NODE_PATH,
            "user-1",
            Some(&json!({
                "node_type": "objective",
                "title": "Target",
                "hex_q": 2,
                "hex_r": -1,
            })),
            Some("target-create"),
            Some(1),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    let target_id = required_id(&target)?;

    let listed_nodes = send_json(
        Arc::clone(&state),
        topology_request("GET", NODE_PATH, "user-1", None, None, None)?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(listed_nodes.as_array().map(Vec::len), Some(2));
    let fetched_node = send_json(
        Arc::clone(&state),
        topology_request(
            "GET",
            format!("{NODE_PATH}/{source_id}").as_str(),
            "user-1",
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(fetched_node, source);

    let updated_node = send_json(
        Arc::clone(&state),
        topology_request(
            "PATCH",
            format!("{NODE_PATH}/{source_id}").as_str(),
            "user-1",
            Some(&json!({"title": "Moved source", "hex_q": 3, "hex_r": -1})),
            Some("source-update"),
            Some(2),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(updated_node["title"], "Moved source");

    let edge = send_json(
        Arc::clone(&state),
        topology_request(
            "POST",
            EDGE_PATH,
            "user-1",
            Some(&json!({
                "source_node_id": source_id,
                "target_node_id": target_id,
                "label": "depends",
                "data": {"weight": 1},
            })),
            Some("edge-create"),
            Some(3),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_edge_shape(&edge)?;
    assert_eq!(edge["direction"], Value::Null);
    assert_eq!(edge["source_hex_q"], 3);
    let edge_id = required_id(&edge)?;

    let listed_edges = send_json(
        Arc::clone(&state),
        topology_request("GET", EDGE_PATH, "user-1", None, None, None)?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(listed_edges.as_array().map(Vec::len), Some(1));
    let fetched_edge = send_json(
        Arc::clone(&state),
        topology_request(
            "GET",
            format!("{EDGE_PATH}/{edge_id}").as_str(),
            "user-1",
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(fetched_edge, edge);
    let updated_edge = send_json(
        Arc::clone(&state),
        topology_request(
            "PATCH",
            format!("{EDGE_PATH}/{edge_id}").as_str(),
            "user-1",
            Some(&json!({"label": "blocks", "direction": "forward"})),
            Some("edge-update"),
            Some(4),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(updated_edge["label"], "blocks");
    assert_eq!(updated_edge["direction"], "forward");

    assert_eq!(
        send(
            Arc::clone(&state),
            topology_request(
                "DELETE",
                format!("{EDGE_PATH}/{edge_id}").as_str(),
                "user-1",
                None,
                Some("edge-delete"),
                Some(5),
            )?,
        )
        .await?
        .status(),
        StatusCode::NO_CONTENT
    );
    assert_eq!(
        send(
            Arc::clone(&state),
            topology_request(
                "DELETE",
                format!("{NODE_PATH}/{source_id}").as_str(),
                "user-1",
                None,
                Some("node-delete"),
                Some(6),
            )?,
        )
        .await?
        .status(),
        StatusCode::NO_CONTENT
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 7);
    assert_eq!(authority_revision(db.as_ref()).await?, 7);
    Ok(())
}

#[tokio::test]
async fn topology_http_validation_permissions_and_conflicts_are_fail_closed()
-> Result<(), Box<dyn Error>> {
    let (_db, state) = topology_state().await?;
    let created = send_json(
        Arc::clone(&state),
        topology_request(
            "POST",
            NODE_PATH,
            "user-1",
            Some(&json!({"node_type": "note", "title": "First"})),
            Some("first"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    let node_id = required_id(&created)?;

    let stale = send_json(
        Arc::clone(&state),
        topology_request(
            "POST",
            NODE_PATH,
            "user-1",
            Some(&json!({"node_type": "note", "title": "Stale"})),
            Some("stale"),
            Some(0),
        )?,
        StatusCode::CONFLICT,
    )
    .await?;
    assert_eq!(
        stale,
        json!({"detail": "Workspace topology authority conflict"})
    );

    let viewer = send_json(
        Arc::clone(&state),
        topology_request(
            "PATCH",
            format!("{NODE_PATH}/{node_id}").as_str(),
            "viewer-1",
            Some(&json!({"title": "Denied"})),
            Some("viewer"),
            Some(1),
        )?,
        StatusCode::FORBIDDEN,
    )
    .await?;
    assert_eq!(viewer, json!({"detail": "Access denied"}));

    let outsider = send_json(
        Arc::clone(&state),
        topology_request("GET", NODE_PATH, "outsider-1", None, None, None)?,
        StatusCode::FORBIDDEN,
    )
    .await?;
    assert_eq!(
        outsider,
        json!({"detail": "User must be a workspace member"})
    );

    let extra = send_json(
        Arc::clone(&state),
        topology_request(
            "POST",
            NODE_PATH,
            "user-1",
            Some(&json!({"node_type": "note", "unexpected": true})),
            Some("extra"),
            Some(1),
        )?,
        StatusCode::UNPROCESSABLE_ENTITY,
    )
    .await?;
    assert_eq!(extra["detail"][0]["type"], "extra_forbidden");

    let invalid_query = send_json(
        Arc::clone(&state),
        topology_request(
            "GET",
            format!("{NODE_PATH}?limit=invalid").as_str(),
            "user-1",
            None,
            None,
            None,
        )?,
        StatusCode::UNPROCESSABLE_ENTITY,
    )
    .await?;
    assert_eq!(invalid_query["detail"][0]["type"], "int_parsing");
    Ok(())
}

async fn topology_state()
-> Result<(Arc<LocalSqliteDbPlugin>, Arc<WorkspaceCoreState>), Box<dyn Error>> {
    let db = Arc::new(LocalSqliteDbPlugin::new()?);
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, hex_q INTEGER, hex_r INTEGER)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_topology_nodes (node_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, node_type TEXT NOT NULL, ref_id TEXT, title TEXT NOT NULL, position_x REAL NOT NULL, position_y REAL NOT NULL, hex_q INTEGER, hex_r INTEGER, status TEXT NOT NULL, tags_json TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, UNIQUE(workspace_id, hex_q, hex_r))",
        "CREATE TABLE workspace_topology_edges (edge_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, source_node_id TEXT NOT NULL, target_node_id TEXT NOT NULL, edge_type TEXT NOT NULL, label TEXT, source_hex_q INTEGER, source_hex_r INTEGER, target_hex_q INTEGER, target_hex_r INTEGER, direction TEXT, auto_created INTEGER NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, UNIQUE(workspace_id, source_node_id, target_node_id, edge_type))",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    let authority_db: Arc<dyn DbPlugin> = db.clone();
    let state = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        authority_db,
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);
    Ok((db, state))
}

fn topology_request(
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
    status: StatusCode,
) -> Result<Value, Box<dyn Error>> {
    let response = send(state, request).await?;
    assert_eq!(response.status(), status);
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX).await?,
    )?)
}

fn required_id(value: &Value) -> Result<String, Box<dyn Error>> {
    value["id"]
        .as_str()
        .map(str::to_string)
        .ok_or_else(|| "missing id".into())
}

fn assert_node_shape(value: &Value) -> Result<(), Box<dyn Error>> {
    let actual = value
        .as_object()
        .ok_or("node is not an object")?
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let expected = [
        "created_at",
        "data",
        "hex_q",
        "hex_r",
        "id",
        "node_type",
        "position_x",
        "position_y",
        "ref_id",
        "status",
        "tags",
        "title",
        "updated_at",
        "workspace_id",
    ]
    .into_iter()
    .collect();
    assert_eq!(actual, expected);
    Ok(())
}

fn assert_edge_shape(value: &Value) -> Result<(), Box<dyn Error>> {
    let actual = value
        .as_object()
        .ok_or("edge is not an object")?
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let expected = [
        "auto_created",
        "created_at",
        "data",
        "direction",
        "id",
        "label",
        "source_hex_q",
        "source_hex_r",
        "source_node_id",
        "target_hex_q",
        "target_hex_r",
        "target_node_id",
        "updated_at",
        "workspace_id",
    ]
    .into_iter()
    .collect();
    assert_eq!(actual, expected);
    Ok(())
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
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
