use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, Response, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use bcs_storage_local::{LocalStorageConfig, LocalStoragePlugin};
use memstack_workspace_core::object_store::StoragePluginObjectStorePort;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use memstack_workspace_service::ObjectStorePort;
use serde_json::{Value, json};
use tempfile::TempDir;
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "file-http-contract-token";
const FILES_PATH: &str =
    "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/blackboard/files";

#[tokio::test]
async fn file_http_streams_objects_and_preserves_cas_replay_contracts() -> Result<(), Box<dyn Error>>
{
    let object_dir = tempfile::tempdir()?;
    let db = Arc::new(seeded_db().await?);
    let state = file_state(db.clone(), &object_dir)?;

    let directory = send_json(
        state.clone(),
        json_request(
            "POST",
            &format!("{FILES_PATH}/mkdir"),
            Some(&json!({"parent_path": "/", "name": "docs"})),
            Some("file-mkdir-1"),
            Some(0),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_file_shape(&directory)?;
    assert_eq!(directory["is_directory"], true);

    let upload_bytes = b"Avernet Workspace File authority\n";
    let uploaded = send_json(
        state.clone(),
        multipart_request(
            &format!("{FILES_PATH}/upload"),
            "/docs/",
            "authority.txt",
            "text/plain",
            upload_bytes,
            "file-upload-1",
            1,
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_file_shape(&uploaded)?;
    assert_eq!(uploaded["parent_path"], "/docs/");
    assert_eq!(uploaded["file_size"], upload_bytes.len());
    assert_eq!(uploaded["uploader_type"], "agent");
    assert_eq!(uploaded["uploader_id"], "agent-file-contract");
    let uploaded_id = uploaded["id"].as_str().ok_or("uploaded file id missing")?;

    let replayed = send_json(
        state.clone(),
        multipart_request(
            &format!("{FILES_PATH}/upload"),
            "/docs/",
            "authority.txt",
            "text/plain",
            upload_bytes,
            "file-upload-1",
            1,
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(replayed, uploaded);
    assert_eq!(authority_revision(db.as_ref()).await?, 2);

    let listed = send_json(
        state.clone(),
        json_request(
            "GET",
            &format!("{FILES_PATH}?parent_path=%2Fdocs%2F"),
            None,
            None,
            None,
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(listed, json!({"items": [uploaded.clone()]}));

    let download_path = format!("{FILES_PATH}/{uploaded_id}/download");
    let response = send_response(
        state.clone(),
        json_request("GET", &download_path, None, None, None)?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(response.headers()[header::CONTENT_TYPE], "text/plain");
    assert_eq!(
        response.headers()[header::CONTENT_LENGTH],
        upload_bytes.len().to_string()
    );
    assert!(
        response.headers()[header::CONTENT_DISPOSITION]
            .to_str()?
            .contains("authority.txt")
    );
    let etag = response
        .headers()
        .get(header::ETAG)
        .ok_or("download ETag missing")?
        .to_str()?
        .to_string();
    assert_eq!(
        to_bytes(response.into_body(), usize::MAX).await?.as_ref(),
        upload_bytes
    );

    let not_modified = send_response(
        state.clone(),
        conditional_get(&download_path, etag.as_str())?,
        StatusCode::NOT_MODIFIED,
    )
    .await?;
    assert!(
        to_bytes(not_modified.into_body(), usize::MAX)
            .await?
            .is_empty()
    );

    let renamed = send_json(
        state.clone(),
        json_request(
            "PATCH",
            &format!("{FILES_PATH}/{uploaded_id}"),
            Some(&json!({"name": "renamed.txt"})),
            Some("file-patch-1"),
            Some(2),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(renamed["name"], "renamed.txt");

    let copied = send_json(
        state.clone(),
        json_request(
            "POST",
            &format!("{FILES_PATH}/{uploaded_id}/copy"),
            Some(&json!({"target_parent_path": "/", "name": "copy.txt"})),
            Some("file-copy-1"),
            Some(3),
        )?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(copied["name"], "copy.txt");
    assert_ne!(copied["id"], uploaded["id"]);

    let deleted = send_json(
        state.clone(),
        json_request(
            "DELETE",
            &format!("{FILES_PATH}/{uploaded_id}"),
            None,
            Some("file-delete-1"),
            Some(4),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(deleted, json!({"deleted": true}));

    let directory_id = directory["id"].as_str().ok_or("directory id missing")?;
    let deleted_directory = send_json(
        state,
        json_request(
            "DELETE",
            &format!("{FILES_PATH}/{directory_id}?recursive=true"),
            None,
            Some("file-delete-directory-1"),
            Some(5),
        )?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(deleted_directory, json!({"deleted": true}));

    assert_eq!(authority_revision(db.as_ref()).await?, 6);
    assert_eq!(table_count(db.as_ref(), "workspace_files").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_file_operations").await?,
        1
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        6
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 6);
    Ok(())
}

fn file_state(
    db: Arc<LocalSqliteDbPlugin>,
    object_dir: &TempDir,
) -> Result<Arc<WorkspaceCoreState>, Box<dyn Error>> {
    let storage = Arc::new(LocalStoragePlugin::new(LocalStorageConfig {
        data_dir: object_dir.path().to_path_buf(),
        max_object_size: 100 * 1024 * 1024,
    }));
    let object_store: Arc<dyn ObjectStorePort> =
        Arc::new(StoragePluginObjectStorePort::new(storage, false));
    Ok(Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db,
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_object_store(object_store),
    ))
}

fn json_request(
    method: &str,
    path: &str,
    body: Option<&Value>,
    idempotency_key: Option<&str>,
    revision: Option<u64>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let mut request = base_request(method, path).header(header::CONTENT_TYPE, "application/json");
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

#[allow(clippy::too_many_arguments)]
fn multipart_request(
    path: &str,
    parent_path: &str,
    filename: &str,
    content_type: &str,
    bytes: &[u8],
    idempotency_key: &str,
    revision: u64,
) -> Result<Request<Body>, Box<dyn Error>> {
    let boundary = "memstack-file-http-contract-boundary";
    let mut body = Vec::new();
    body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
    body.extend_from_slice(b"Content-Disposition: form-data; name=\"parent_path\"\r\n\r\n");
    body.extend_from_slice(parent_path.as_bytes());
    body.extend_from_slice(b"\r\n");
    body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
    body.extend_from_slice(
        format!("Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n")
            .as_bytes(),
    );
    body.extend_from_slice(format!("Content-Type: {content_type}\r\n\r\n").as_bytes());
    body.extend_from_slice(bytes);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());

    Ok(base_request("POST", path)
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={boundary}"),
        )
        .header("idempotency-key", idempotency_key)
        .header("if-match", revision.to_string())
        .header("x-memstack-actor-type", "agent")
        .header("x-memstack-actor-id", "agent-file-contract")
        .body(Body::from(body))?)
}

fn conditional_get(path: &str, etag: &str) -> Result<Request<Body>, Box<dyn Error>> {
    Ok(base_request("GET", path)
        .header(header::IF_NONE_MATCH, etag)
        .body(Body::empty())?)
}

fn base_request(method: &str, path: &str) -> axum::http::request::Builder {
    Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "user-1")
        .header("x-memstack-user-email", "user-1@memstack.test")
}

async fn send_response(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
    expected: StatusCode,
) -> Result<Response<Body>, Box<dyn Error>> {
    let response = workspace_router(state).oneshot(request).await?;
    if response.status() != expected {
        let status = response.status();
        let bytes = to_bytes(response.into_body(), usize::MAX).await?;
        panic!(
            "unexpected File HTTP status: actual={status}, expected={expected}, body={}",
            String::from_utf8_lossy(&bytes)
        );
    }
    Ok(response)
}

async fn send_json(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
    expected: StatusCode,
) -> Result<Value, Box<dyn Error>> {
    let response = send_response(state, request, expected).await?;
    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    if bytes.is_empty() {
        return Ok(Value::Null);
    }
    Ok(serde_json::from_slice(&bytes)?)
}

fn assert_file_shape(value: &Value) -> Result<(), Box<dyn Error>> {
    let fields = value.as_object().ok_or("file response must be an object")?;
    let expected = [
        "content_type",
        "created_at",
        "file_size",
        "id",
        "is_directory",
        "name",
        "parent_path",
        "uploader_id",
        "uploader_name",
        "uploader_type",
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
        "CREATE TABLE workspace_files (file_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, parent_path TEXT NOT NULL, name TEXT NOT NULL, is_directory INTEGER NOT NULL, file_size INTEGER NOT NULL, content_type TEXT NOT NULL, storage_backend TEXT NOT NULL, object_handle TEXT NOT NULL, object_state TEXT NOT NULL, uploader_type TEXT NOT NULL, uploader_id TEXT NOT NULL, uploader_actor_id TEXT NOT NULL, uploader_name TEXT NOT NULL, checksum_sha256 TEXT, detected_mime_type TEXT, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id, parent_path, name))",
        "CREATE TABLE workspace_file_operations (operation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, file_id TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL, staged_handle_json TEXT, ready_handle_json TEXT, checksum_sha256 TEXT, size_bytes INTEGER, last_error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key), UNIQUE(workspace_id, file_id))",
        "CREATE TABLE workspace_file_compensations (compensation_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, file_id TEXT NOT NULL, compensation_kind TEXT NOT NULL, object_handle_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 20, next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT, UNIQUE(operation_id, compensation_kind))",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
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
        "workspace_files" => "SELECT COUNT(*) AS value FROM workspace_files",
        "workspace_file_operations" => "SELECT COUNT(*) AS value FROM workspace_file_operations",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
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
