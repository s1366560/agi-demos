use std::{
    path::{Path, PathBuf},
    sync::Arc,
};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    response::Response,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

struct ArtifactFixture {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
    authority_id: String,
}

impl Drop for ArtifactFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn artifact_fixture(credential: &str) -> ArtifactFixture {
    let root = std::env::temp_dir().join(format!("agistack-artifact-content-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create artifact workspace");
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = local_state(&root, credential, session_store);
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    let authority_id = seed_artifact(&state, &root);
    ArtifactFixture {
        root,
        state,
        authority_id,
    }
}

fn local_state(
    root: &Path,
    credential: &str,
    session_store: DesktopSessionStore,
) -> Arc<LocalRuntimeState> {
    let tool_host = LocalToolHost::new(root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    Arc::new(
        LocalRuntimeState::new(
            root.to_path_buf(),
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    )
}

fn seed_artifact(state: &Arc<LocalRuntimeState>, root: &Path) -> String {
    let conversation_id = "conversation-artifact-content";
    state
        .session_store
        .insert_conversation(&LocalConversation {
            id: conversation_id.to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Artifact content".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Build,
            created_at: now_iso(),
            updated_at: now_iso(),
        })
        .expect("insert artifact conversation");
    let artifact_path = root.join(".agistack/artifacts/report/artifact-version-content/report.md");
    std::fs::create_dir_all(artifact_path.parent().expect("artifact parent"))
        .expect("create artifact parent");
    std::fs::write(&artifact_path, "# Authority\n").expect("write artifact");
    let version = state
        .session_store
        .record_artifact_version(
            conversation_id,
            None,
            &json!({
                "artifact_id": "report",
                "artifact_version_id": "artifact-version-content",
                "filename": "report.md",
                "path": artifact_path,
                "relative_path":
                    ".agistack/artifacts/report/artifact-version-content/report.md",
                "bytes": 12,
                "mime_type": "text/markdown",
                "sources": [],
                "checks": [],
            }),
            &now_iso(),
        )
        .expect("record artifact");
    version.artifact_id
}

fn request(method: &str, uri: &str, credential: &str, body: Option<Value>) -> Request<Body> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential);
    if body.is_some() {
        builder = builder.header("content-type", "application/json");
    }
    builder
        .body(body.map_or_else(Body::empty, |value| Body::from(value.to_string())))
        .expect("artifact content request")
}

fn save_request(
    uri: &str,
    credential: &str,
    expected_revision: u64,
    idempotency_key: &str,
    content: &str,
) -> Request<Body> {
    let body = json!({
        "contract_version": 2,
        "expected_revision": expected_revision,
        "content_hash": content_hash(content.as_bytes()),
        "idempotency_key": idempotency_key,
        "content": content,
    });
    Request::builder()
        .method("PUT")
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .header("content-type", "application/json")
        .header("x-expected-revision", expected_revision)
        .header("idempotency-key", idempotency_key)
        .body(Body::from(body.to_string()))
        .expect("artifact save request")
}

async fn response_json(response: Response) -> Value {
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("artifact response body");
    serde_json::from_slice(&bytes).expect("artifact response JSON")
}

async fn response_bytes(response: Response) -> Vec<u8> {
    axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("artifact response body")
        .to_vec()
}

fn content_hash(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

#[tokio::test]
async fn local_artifact_content_route_uses_the_scoped_persisted_authority_id() {
    let credential = "artifact-content-secret";
    let fixture = artifact_fixture(credential);
    let app = local_router(Arc::clone(&fixture.state));

    let response = app
        .clone()
        .oneshot(request(
            "GET",
            &format!("/api/v1/artifacts/{}/content", fixture.authority_id),
            credential,
            None,
        ))
        .await
        .expect("artifact content response");
    assert_eq!(response.status(), StatusCode::OK);
    let payload = response_json(response).await;
    assert_eq!(payload["contract_version"], 2);
    assert_eq!(payload["artifact_id"], fixture.authority_id);
    assert_eq!(payload["revision"], 0);
    assert_eq!(payload["mime_type"], "text/markdown");
    assert_eq!(payload["content"], "# Authority\n");

    let bare_source_id = app
        .oneshot(request(
            "GET",
            "/api/v1/artifacts/report/content",
            credential,
            None,
        ))
        .await
        .expect("bare artifact id response");
    assert_eq!(bare_source_id.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn local_artifact_content_save_is_revisioned_and_idempotent() {
    let credential = "artifact-content-save-secret";
    let fixture = artifact_fixture(credential);
    let app = local_router(Arc::clone(&fixture.state));
    let uri = format!("/api/v1/artifacts/{}/content", fixture.authority_id);

    let initial = app
        .clone()
        .oneshot(request("GET", &uri, credential, None))
        .await
        .expect("initial artifact content");
    assert_eq!(initial.status(), StatusCode::OK);

    let stale = app
        .clone()
        .oneshot(save_request(
            &uri,
            credential,
            7,
            "artifact-save-stale",
            "# Stale\n",
        ))
        .await
        .expect("stale artifact save");
    assert_eq!(stale.status(), StatusCode::CONFLICT);
    let stale_payload = response_json(stale).await;
    assert_eq!(
        stale_payload["reason_code"],
        "artifact_content_revision_conflict"
    );
    assert_eq!(stale_payload["server_revision"], 0);
    assert_eq!(
        std::fs::read_to_string(
            &fixture
                .state
                .session_store
                .current_artifact_version(&fixture.authority_id)
                .expect("artifact query")
                .expect("artifact version")
                .path
        )
        .expect("read unchanged artifact"),
        "# Authority\n"
    );

    let saved = app
        .clone()
        .oneshot(save_request(
            &uri,
            credential,
            0,
            "artifact-save-authority",
            "# Saved\n",
        ))
        .await
        .expect("artifact save");
    assert_eq!(saved.status(), StatusCode::OK);
    let saved_payload = response_json(saved).await;
    assert_eq!(saved_payload["revision"], 1);
    assert_eq!(saved_payload["duplicate"], false);
    assert_eq!(saved_payload["content_hash"], content_hash(b"# Saved\n"));

    let duplicate = app
        .clone()
        .oneshot(save_request(
            &uri,
            credential,
            0,
            "artifact-save-authority",
            "# Saved\n",
        ))
        .await
        .expect("duplicate artifact save");
    assert_eq!(duplicate.status(), StatusCode::OK);
    let duplicate_payload = response_json(duplicate).await;
    assert_eq!(duplicate_payload["revision"], 1);
    assert_eq!(duplicate_payload["duplicate"], true);

    let conflicting_reuse = app
        .clone()
        .oneshot(save_request(
            &uri,
            credential,
            1,
            "artifact-save-authority",
            "# Different\n",
        ))
        .await
        .expect("conflicting idempotency reuse");
    assert_eq!(conflicting_reuse.status(), StatusCode::CONFLICT);
    let conflicting_payload = response_json(conflicting_reuse).await;
    assert_eq!(
        conflicting_payload["reason_code"],
        "artifact_content_idempotency_conflict"
    );
    assert_eq!(conflicting_payload["server_revision"], 1);

    let current = app
        .oneshot(request("GET", &uri, credential, None))
        .await
        .expect("current artifact content");
    let current_payload = response_json(current).await;
    assert_eq!(current_payload["revision"], 1);
    assert_eq!(current_payload["content"], "# Saved\n");
}

#[tokio::test]
async fn local_artifact_content_bytes_are_authenticated_and_inline() {
    let credential = "artifact-content-bytes-secret";
    let fixture = artifact_fixture(credential);
    let app = local_router(Arc::clone(&fixture.state));
    let uri = format!("/api/v1/artifacts/{}/content/bytes", fixture.authority_id);

    let response = app
        .oneshot(request("GET", &uri, credential, None))
        .await
        .expect("artifact bytes response");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(response.headers()["content-type"], "text/markdown");
    assert_eq!(response.headers()["cache-control"], "no-store");
    assert_eq!(response.headers()["x-content-type-options"], "nosniff");
    assert_eq!(
        response.headers()["content-disposition"],
        "inline; filename=\"report.md\""
    );
    assert_eq!(response_bytes(response).await, b"# Authority\n");
}

#[cfg(unix)]
#[tokio::test]
async fn local_artifact_content_rejects_symbolic_link_authority_paths() {
    use std::os::unix::fs::symlink;

    let credential = "artifact-content-symlink-secret";
    let fixture = artifact_fixture(credential);
    let version = fixture
        .state
        .session_store
        .current_artifact_version(&fixture.authority_id)
        .expect("artifact query")
        .expect("artifact version");
    let target = fixture.root.join("outside-artifact.md");
    std::fs::write(&target, "# Outside\n").expect("write symlink target");
    std::fs::remove_file(&version.path).expect("remove original artifact");
    symlink(&target, &version.path).expect("create artifact symlink");
    let app = local_router(Arc::clone(&fixture.state));

    let response = app
        .oneshot(request(
            "GET",
            &format!("/api/v1/artifacts/{}/content", fixture.authority_id),
            credential,
            None,
        ))
        .await
        .expect("symlink artifact response");
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    let payload = response_json(response).await;
    assert_eq!(payload["reason_code"], "artifact_symlink_not_allowed");
}

#[tokio::test]
async fn local_artifact_content_receipt_survives_runtime_restart() {
    let credential = "artifact-content-restart-secret";
    let root = std::env::temp_dir().join(format!("agistack-artifact-restart-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create restart workspace");
    let store_path = root.join("desktop-session.sqlite3");
    let authority_id;
    {
        let state = local_state(
            &root,
            credential,
            DesktopSessionStore::open(&store_path).expect("open session store"),
        );
        state
            .session_store
            .seed_test_session(credential)
            .expect("authenticated test session");
        authority_id = seed_artifact(&state, &root);
        let app = local_router(Arc::clone(&state));
        let uri = format!("/api/v1/artifacts/{authority_id}/content");
        let initial = app
            .clone()
            .oneshot(request("GET", &uri, credential, None))
            .await
            .expect("initialize artifact authority");
        assert_eq!(initial.status(), StatusCode::OK);
        let saved = app
            .oneshot(save_request(
                &uri,
                credential,
                0,
                "artifact-save-restart",
                "# Restarted\n",
            ))
            .await
            .expect("save before restart");
        assert_eq!(saved.status(), StatusCode::OK);
    }

    let restored = local_state(
        &root,
        credential,
        DesktopSessionStore::open(&store_path).expect("reopen session store"),
    );
    let app = local_router(Arc::clone(&restored));
    let uri = format!("/api/v1/artifacts/{authority_id}/content");
    let replay = app
        .clone()
        .oneshot(save_request(
            &uri,
            credential,
            0,
            "artifact-save-restart",
            "# Restarted\n",
        ))
        .await
        .expect("replay save after restart");
    assert_eq!(replay.status(), StatusCode::OK);
    let replay_payload = response_json(replay).await;
    assert_eq!(replay_payload["revision"], 1);
    assert_eq!(replay_payload["duplicate"], true);

    let current = app
        .oneshot(request("GET", &uri, credential, None))
        .await
        .expect("load after restart");
    let current_payload = response_json(current).await;
    assert_eq!(current_payload["revision"], 1);
    assert_eq!(current_payload["content"], "# Restarted\n");
    drop(restored);
    std::fs::remove_dir_all(root).expect("remove restart workspace");
}
