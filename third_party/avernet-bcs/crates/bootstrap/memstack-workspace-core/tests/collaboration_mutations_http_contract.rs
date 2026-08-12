use std::collections::BTreeSet;
use std::error::Error;
use std::path::PathBuf;
use std::sync::Arc;

use async_trait::async_trait;
use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_local::LocalSqliteDbPlugin;
use bcs_storage_api::ByteStream;
use bcs_storage_local::{LocalStorageConfig, LocalStoragePlugin};
use memstack_workspace_core::object_store::StoragePluginObjectStorePort;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use memstack_workspace_service::{
    ObjectStageRequest, ObjectStoreError, ObjectStorePort, ReadyObjectReference,
    StagedObjectReference,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use tempfile::TempDir;
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "collaboration-mutation-contract-token";
const PATH: &str =
    "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration/mutations";
const UPLOAD_PATH: &str = "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration/mutations/files/upload";

#[tokio::test]
async fn collaboration_task_receipt_is_atomic_replayable_and_alias_sensitive()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = workspace_state(db.clone())?;
    let payload = json!({
        "title": "Ship the collaboration façade",
        "description": "Keep the outer authority envelope",
        "metadata": {"source": "collaboration-contract"},
        "preferred_language": "zh-CN",
        "priority": "P1"
    });
    let command = mutation_command(
        "goals",
        "create_task",
        0,
        "collab-task-001",
        payload.clone(),
    );

    let created = send_json(
        state.clone(),
        mutation_request("user-1", &command, 0, "collab-task-001")?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(created["contract_version"], "2.0.0");
    assert_eq!(created["workspace_id"], "workspace-1");
    assert_eq!(created["surface"], "goals");
    assert_eq!(created["action"], "create_task");
    assert_eq!(created["revision"], 1);
    assert_eq!(created["duplicate"], false);
    assert!(created["receipt_id"].is_string());

    let receipt = receipt_row(db.as_ref(), "collab-task-001").await?;
    assert_eq!(
        required_string(&receipt, "receipt_id")?,
        created["receipt_id"]
    );
    assert_eq!(required_string(&receipt, "contract_version")?, "2.0.0");
    assert_eq!(required_string(&receipt, "surface")?, "goals");
    assert_eq!(required_string(&receipt, "action")?, "create_task");
    assert_eq!(required_i64(&receipt, "expected_revision")?, 0);
    assert_eq!(required_i64(&receipt, "committed_revision")?, 1);
    assert_eq!(
        required_string(&receipt, "request_hash")?,
        canonical_request_hash(&command)?
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_task_receipts").await?,
        0
    );
    assert_eq!(table_count(db.as_ref(), "workspace_tasks").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);
    assert_eq!(authority_revision(db.as_ref()).await?, 1);

    let replayed = send_json(
        state.clone(),
        mutation_request("user-1", &command, 0, "collab-task-001")?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(replayed["receipt_id"], created["receipt_id"]);
    assert_eq!(replayed["revision"], 1);
    assert_eq!(replayed["duplicate"], true);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_tasks").await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);

    let alias = mutation_command(
        "collaboration",
        "create_task",
        0,
        "collab-task-001",
        payload,
    );
    let alias_conflict = send_json(
        state.clone(),
        mutation_request("user-1", &alias, 0, "collab-task-001")?,
        StatusCode::CONFLICT,
    )
    .await?;
    assert_eq!(
        alias_conflict["detail"]["reason_code"],
        "workspace_collaboration_idempotency_conflict"
    );

    let stale = mutation_command(
        "goals",
        "create_task",
        0,
        "collab-task-002",
        json!({"title": "Stale command"}),
    );
    let stale_conflict = send_json(
        state,
        mutation_request("user-1", &stale, 0, "collab-task-002")?,
        StatusCode::CONFLICT,
    )
    .await?;
    assert_eq!(
        stale_conflict["detail"]["reason_code"],
        "workspace_collaboration_revision_conflict"
    );
    assert_eq!(stale_conflict["detail"]["expected_revision"], 0);
    assert_eq!(stale_conflict["detail"]["current_revision"], 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    Ok(())
}

#[tokio::test]
async fn collaboration_mutation_rejects_transport_payload_and_acl_drift()
-> Result<(), Box<dyn Error>> {
    let state = workspace_state(Arc::new(seeded_db().await?))?;
    let valid = mutation_command(
        "goals",
        "create_task",
        0,
        "validation-001",
        json!({"title": "Valid command"}),
    );

    let mismatch = send_json(
        state.clone(),
        mutation_request("user-1", &valid, 1, "validation-001")?,
        StatusCode::UNPROCESSABLE_ENTITY,
    )
    .await?;
    assert_eq!(
        mismatch["detail"]["reason_code"],
        "workspace_collaboration_authority_header_mismatch"
    );

    for invalid in [
        json!({
            "contract_version": "1.0.0",
            "surface": "goals",
            "action": "create_task",
            "expected_revision": 0,
            "idempotency_key": "validation-002",
            "payload": {"title": "wrong version"}
        }),
        json!({
            "contract_version": "2.0.0",
            "surface": "notes",
            "action": "create_note",
            "expected_revision": 0,
            "idempotency_key": "validation-003",
            "payload": {}
        }),
        json!({
            "contract_version": "2.0.0",
            "surface": "goals",
            "action": "create_task",
            "expected_revision": 0,
            "idempotency_key": "validation-004",
            "payload": {"title": "unknown payload", "unexpected": true}
        }),
        json!({
            "contract_version": "2.0.0",
            "surface": "goals",
            "action": "create_task",
            "expected_revision": 0,
            "idempotency_key": "validation-005",
            "payload": {"title": "unknown envelope"},
            "unexpected": true
        }),
    ] {
        let revision = invalid["expected_revision"].as_u64().unwrap_or(0);
        let key = invalid["idempotency_key"].as_str().ok_or("missing key")?;
        let response = send_json(
            state.clone(),
            mutation_request("user-1", &invalid, revision, key)?,
            StatusCode::UNPROCESSABLE_ENTITY,
        )
        .await?;
        assert_eq!(
            response["detail"]["reason_code"],
            "workspace_collaboration_payload_invalid"
        );
    }

    let forbidden = send_json(
        state,
        mutation_request("outsider-1", &valid, 0, "validation-001")?,
        StatusCode::FORBIDDEN,
    )
    .await?;
    assert_eq!(
        forbidden["detail"]["reason_code"],
        "workspace_collaboration_access_denied"
    );
    Ok(())
}

#[tokio::test]
async fn collaboration_upload_binds_content_to_receipt_and_rejects_oversized_transport()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let object_dir = TempDir::new()?;
    let state = file_workspace_state(db.clone(), &object_dir)?;
    let boundary = "memstack-collaboration-boundary";
    let content = b"durable upload content";
    let body = multipart_body(boundary, "/", "proof.txt", "text/plain", content);

    let uploaded = send_json(
        state.clone(),
        upload_request(boundary, body.clone(), "upload-key-001", 0, None)?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(uploaded["surface"], "files");
    assert_eq!(uploaded["action"], "upload_file");
    assert_eq!(uploaded["revision"], 1);
    assert_eq!(uploaded["duplicate"], false);
    let receipt = receipt_row(db.as_ref(), "upload-key-001").await?;
    let upload_command = mutation_command(
        "files",
        "upload_file",
        0,
        "upload-key-001",
        json!({
            "parent_path": "/",
            "file_name": "proof.txt",
            "content_type": "text/plain",
            "size_bytes": content.len(),
            "sha256": hex::encode(Sha256::digest(content)),
        }),
    );
    assert_eq!(
        required_string(&receipt, "request_hash")?,
        canonical_request_hash(&upload_command)?
    );
    assert_eq!(table_count(db.as_ref(), "workspace_files").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_file_operations").await?,
        1
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);

    let replayed = send_json(
        state.clone(),
        upload_request(boundary, body, "upload-key-001", 0, None)?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(replayed["receipt_id"], uploaded["receipt_id"]);
    assert_eq!(replayed["duplicate"], true);

    let conflicting_body = multipart_body(
        boundary,
        "/",
        "proof.txt",
        "text/plain",
        b"different content",
    );
    let conflict = send_json(
        state.clone(),
        upload_request(boundary, conflicting_body, "upload-key-001", 0, None)?,
        StatusCode::CONFLICT,
    )
    .await?;
    assert_eq!(
        conflict["detail"]["reason_code"],
        "workspace_collaboration_idempotency_conflict"
    );
    assert_eq!(table_count(db.as_ref(), "workspace_files").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_file_operations").await?,
        1
    );

    let oversized = send_json(
        state,
        upload_request(
            boundary,
            Vec::new(),
            "upload-key-002",
            1,
            Some(102 * 1024 * 1024 + 1),
        )?,
        StatusCode::PAYLOAD_TOO_LARGE,
    )
    .await?;
    assert_eq!(
        oversized["detail"]["reason_code"],
        "workspace_collaboration_upload_too_large"
    );
    Ok(())
}

#[tokio::test]
async fn collaboration_upload_rejects_ambiguous_multipart_without_leaking_staging_files()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let object_dir = TempDir::new()?;
    let state = file_workspace_state(db.clone(), &object_dir)?;
    let boundary = "memstack-collaboration-invalid-boundary";
    let before = temp_upload_files()?;

    for (key, body) in [
        (
            "upload-invalid-001",
            multipart_body_with_unexpected_field(boundary),
        ),
        (
            "upload-invalid-002",
            multipart_body_with_two_files(boundary),
        ),
    ] {
        let response = send_json(
            state.clone(),
            upload_request(boundary, body, key, 0, None)?,
            StatusCode::UNPROCESSABLE_ENTITY,
        )
        .await?;
        assert_eq!(
            response["detail"]["reason_code"],
            "workspace_collaboration_payload_invalid"
        );
    }

    assert_eq!(authority_revision(db.as_ref()).await?, 0);
    assert_eq!(table_count(db.as_ref(), "workspace_files").await?, 0);
    assert_eq!(
        table_count(db.as_ref(), "workspace_file_operations").await?,
        0
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        0
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 0);
    assert_no_new_temp_uploads(&before)?;
    Ok(())
}

#[tokio::test]
async fn collaboration_upload_finalize_failure_records_compensation_without_committing_authority()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = failing_file_workspace_state(db.clone())?;
    let boundary = "memstack-collaboration-failure-boundary";
    let before = temp_upload_files()?;
    let response = send_json(
        state,
        upload_request(
            boundary,
            multipart_body(
                boundary,
                "/",
                "failure.txt",
                "text/plain",
                b"finalize failure",
            ),
            "upload-failure-001",
            0,
            None,
        )?,
        StatusCode::SERVICE_UNAVAILABLE,
    )
    .await?;
    assert_eq!(
        response["detail"]["reason_code"],
        "workspace_collaboration_authority_unavailable"
    );
    assert_eq!(authority_revision(db.as_ref()).await?, 0);
    assert_eq!(table_count(db.as_ref(), "workspace_files").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_file_operations").await?,
        1
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_file_compensations").await?,
        1
    );
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        0
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 0);
    assert_no_new_temp_uploads(&before)?;
    Ok(())
}

fn workspace_state(db: Arc<LocalSqliteDbPlugin>) -> Result<Arc<WorkspaceCoreState>, &'static str> {
    WorkspaceCoreState::new_with_sql_flavor(db, SERVICE_TOKEN.to_string(), DbSqlFlavor::Sqlite)
        .map(Arc::new)
}

fn file_workspace_state(
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

fn failing_file_workspace_state(
    db: Arc<LocalSqliteDbPlugin>,
) -> Result<Arc<WorkspaceCoreState>, Box<dyn Error>> {
    let object_store: Arc<dyn ObjectStorePort> = Arc::new(FinalizeFailingObjectStore);
    Ok(Arc::new(
        WorkspaceCoreState::new_with_sql_flavor(
            db,
            SERVICE_TOKEN.to_string(),
            DbSqlFlavor::Sqlite,
        )?
        .with_object_store(object_store),
    ))
}

fn mutation_command(
    surface: &str,
    action: &str,
    expected_revision: u64,
    idempotency_key: &str,
    payload: Value,
) -> Value {
    json!({
        "contract_version": "2.0.0",
        "surface": surface,
        "action": action,
        "expected_revision": expected_revision,
        "idempotency_key": idempotency_key,
        "payload": payload,
    })
}

fn mutation_request(
    user_id: &str,
    body: &Value,
    header_revision: u64,
    header_key: &str,
) -> Result<Request<Body>, Box<dyn Error>> {
    Ok(Request::builder()
        .method("POST")
        .uri(PATH)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header(header::CONTENT_TYPE, "application/json")
        .header("x-memstack-user-id", user_id)
        .header("x-expected-revision", header_revision.to_string())
        .header("idempotency-key", header_key)
        .body(Body::from(body.to_string()))?)
}

fn upload_request(
    boundary: &str,
    body: Vec<u8>,
    idempotency_key: &str,
    expected_revision: u64,
    content_length: Option<usize>,
) -> Result<Request<Body>, Box<dyn Error>> {
    let content_length = content_length.unwrap_or(body.len());
    Ok(Request::builder()
        .method("POST")
        .uri(UPLOAD_PATH)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={boundary}"),
        )
        .header(header::CONTENT_LENGTH, content_length.to_string())
        .header("x-memstack-user-id", "user-1")
        .header("x-expected-revision", expected_revision.to_string())
        .header("idempotency-key", idempotency_key)
        .body(Body::from(body))?)
}

fn multipart_body(
    boundary: &str,
    parent_path: &str,
    filename: &str,
    content_type: &str,
    bytes: &[u8],
) -> Vec<u8> {
    let mut body = Vec::new();
    push_parent_path_part(&mut body, boundary, parent_path);
    push_file_part(&mut body, boundary, filename, content_type, bytes);
    finish_multipart(&mut body, boundary);
    body
}

fn multipart_body_with_unexpected_field(boundary: &str) -> Vec<u8> {
    let mut body = Vec::new();
    push_parent_path_part(&mut body, boundary, "/");
    push_file_part(&mut body, boundary, "first.txt", "text/plain", b"first");
    body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
    body.extend_from_slice(b"Content-Disposition: form-data; name=\"unexpected\"\r\n\r\n");
    body.extend_from_slice(b"unexpected\r\n");
    finish_multipart(&mut body, boundary);
    body
}

fn multipart_body_with_two_files(boundary: &str) -> Vec<u8> {
    let mut body = Vec::new();
    push_parent_path_part(&mut body, boundary, "/");
    push_file_part(&mut body, boundary, "first.txt", "text/plain", b"first");
    push_file_part(&mut body, boundary, "second.txt", "text/plain", b"second");
    finish_multipart(&mut body, boundary);
    body
}

fn push_parent_path_part(body: &mut Vec<u8>, boundary: &str, parent_path: &str) {
    body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
    body.extend_from_slice(b"Content-Disposition: form-data; name=\"parent_path\"\r\n\r\n");
    body.extend_from_slice(parent_path.as_bytes());
    body.extend_from_slice(b"\r\n");
}

fn push_file_part(
    body: &mut Vec<u8>,
    boundary: &str,
    filename: &str,
    content_type: &str,
    bytes: &[u8],
) {
    body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
    body.extend_from_slice(
        format!("Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n")
            .as_bytes(),
    );
    body.extend_from_slice(format!("Content-Type: {content_type}\r\n\r\n").as_bytes());
    body.extend_from_slice(bytes);
    body.extend_from_slice(b"\r\n");
}

fn finish_multipart(body: &mut Vec<u8>, boundary: &str) {
    body.extend_from_slice(format!("--{boundary}--\r\n").as_bytes());
}

fn temp_upload_files() -> Result<BTreeSet<PathBuf>, Box<dyn Error>> {
    let mut files = BTreeSet::new();
    for entry in std::fs::read_dir(std::env::temp_dir())? {
        let entry = entry?;
        if entry
            .file_name()
            .to_string_lossy()
            .starts_with("memstack-workspace-upload-")
        {
            files.insert(entry.path());
        }
    }
    Ok(files)
}

fn assert_no_new_temp_uploads(before: &BTreeSet<PathBuf>) -> Result<(), Box<dyn Error>> {
    let after = temp_upload_files()?;
    let leaked = after.difference(before).collect::<Vec<_>>();
    if leaked.is_empty() {
        Ok(())
    } else {
        Err(format!("Workspace upload staging files leaked: {leaked:?}").into())
    }
}

async fn send_json(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
    expected_status: StatusCode,
) -> Result<Value, Box<dyn Error>> {
    let response = workspace_router(state).oneshot(request).await?;
    assert_eq!(response.status(), expected_status);
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX).await?,
    )?)
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, assignee_user_id TEXT, assignee_agent_id TEXT, status TEXT NOT NULL, priority INTEGER NOT NULL, estimated_effort TEXT, blocker_reason TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, archived_at TEXT)",
        "CREATE TABLE workspace_task_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT, actor_id TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, expected_revision INTEGER, committed_revision INTEGER, result_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_files (file_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, parent_path TEXT NOT NULL, name TEXT NOT NULL, is_directory INTEGER NOT NULL, file_size INTEGER NOT NULL, content_type TEXT NOT NULL, storage_backend TEXT NOT NULL, object_handle TEXT NOT NULL, object_state TEXT NOT NULL, uploader_type TEXT NOT NULL, uploader_id TEXT NOT NULL, uploader_actor_id TEXT NOT NULL, uploader_name TEXT NOT NULL, checksum_sha256 TEXT, detected_mime_type TEXT, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id, parent_path, name))",
        "CREATE TABLE workspace_file_operations (operation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, file_id TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL, staged_handle_json TEXT, ready_handle_json TEXT, checksum_sha256 TEXT, size_bytes INTEGER, last_error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key), UNIQUE(workspace_id, file_id))",
        "CREATE TABLE workspace_file_compensations (compensation_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, file_id TEXT NOT NULL, compensation_kind TEXT NOT NULL, object_handle_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 20, next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT, UNIQUE(operation_id, compensation_kind))",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn receipt_row(db: &dyn DbPlugin, idempotency_key: &str) -> Result<DbRow, Box<dyn Error>> {
    let rows = db
        .query(
            DbStatementBuilder::new(DbSqlFlavor::Sqlite)
                .push_static("SELECT * FROM workspace_mutation_receipts WHERE idempotency_key = ")
                .bind(idempotency_key)
                .build(),
        )
        .await?;
    rows.into_iter()
        .next()
        .ok_or_else(|| "missing receipt".into())
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_task_receipts" => "SELECT COUNT(*) AS value FROM workspace_task_receipts",
        "workspace_tasks" => "SELECT COUNT(*) AS value FROM workspace_tasks",
        "workspace_files" => "SELECT COUNT(*) AS value FROM workspace_files",
        "workspace_file_operations" => "SELECT COUNT(*) AS value FROM workspace_file_operations",
        "workspace_file_compensations" => {
            "SELECT COUNT(*) AS value FROM workspace_file_compensations"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    required_i64(
        db.query(DbStatement::new(sql))
            .await?
            .first()
            .ok_or("missing count")?,
        "value",
    )
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    required_i64(
        db.query(DbStatement::new(
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
        ))
        .await?
        .first()
        .ok_or("missing authority")?,
        "value",
    )
}

fn canonical_request_hash(command: &Value) -> Result<String, Box<dyn Error>> {
    let canonical = json!({
        "contract_version": &command["contract_version"],
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "surface": &command["surface"],
        "action": &command["action"],
        "expected_revision": &command["expected_revision"],
        "payload": &command["payload"],
    });
    Ok(hex::encode(Sha256::digest(serde_json::to_vec(&canonical)?)))
}

fn required_string(row: &DbRow, column: &str) -> Result<String, Box<dyn Error>> {
    row.get_string(column)?
        .ok_or_else(|| format!("missing {column}").into())
}

fn required_i64(row: &DbRow, column: &str) -> Result<i64, Box<dyn Error>> {
    row.get_i64(column)?
        .ok_or_else(|| format!("missing {column}").into())
}

struct FinalizeFailingObjectStore;

#[async_trait]
impl ObjectStorePort for FinalizeFailingObjectStore {
    fn backend_name(&self) -> &str {
        "failing-contract"
    }

    fn max_object_size(&self) -> u64 {
        100 * 1024 * 1024
    }

    async fn stage(
        &self,
        request: &ObjectStageRequest,
        _body: ByteStream,
    ) -> Result<StagedObjectReference, ObjectStoreError> {
        Ok(StagedObjectReference {
            backend: self.backend_name().to_string(),
            key: request.key.clone(),
            handle: json!({"key": request.key}),
            size_bytes: request.size_bytes,
            checksum_sha256: request.checksum_sha256.clone(),
        })
    }

    async fn finalize(
        &self,
        _staged: &StagedObjectReference,
    ) -> Result<ReadyObjectReference, ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "injected finalize failure".to_string(),
        ))
    }

    async fn abort(&self, _staged: &StagedObjectReference) -> Result<(), ObjectStoreError> {
        Ok(())
    }

    async fn open(&self, _object: &ReadyObjectReference) -> Result<ByteStream, ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "open is not supported by this contract store".to_string(),
        ))
    }

    async fn delete(&self, _object: &ReadyObjectReference) -> Result<(), ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "delete is not supported by this contract store".to_string(),
        ))
    }

    async fn copy(
        &self,
        _source: &ReadyObjectReference,
        _request: &ObjectStageRequest,
    ) -> Result<ReadyObjectReference, ObjectStoreError> {
        Err(ObjectStoreError::Unavailable(
            "copy is not supported by this contract store".to_string(),
        ))
    }
}
