use std::sync::Arc;

use agistack_adapters_device::SqliteCheckpointStore;
use agistack_adapters_local_tools::LocalToolHost;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
    Router,
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use agistack_adapters_wasmtime::SCORE_V1_WAT;

use super::*;
use crate::local_runtime::session_store::DesktopSessionStore;

fn state() -> Arc<LocalRuntimeState> {
    let root = std::env::temp_dir().join(format!("plugin-snapshots-{}", Uuid::new_v4()));
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    Arc::new(
        LocalRuntimeState::new(
            root,
            tool_host,
            checkpoints,
            "launch-token".to_string(),
            session_store,
        )
        .expect("local runtime state"),
    )
}

async fn request_json(
    app: Router,
    method: &str,
    path: &str,
    token: Option<&str>,
    body: Value,
) -> (StatusCode, Value) {
    let mut builder = Request::builder()
        .method(method)
        .uri(path)
        .header("content-type", "application/json");
    if let Some(token) = token {
        builder = builder.header(AUTHORIZATION, format!("Bearer {token}"));
    }
    let response = app
        .oneshot(builder.body(Body::from(body.to_string())).expect("request"))
        .await
        .expect("response");
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1024 * 1024)
        .await
        .expect("response body");
    let value = if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(&bytes).into_owned()))
    };
    (status, value)
}

fn snapshot(digest: &str) -> Value {
    json!({
        "schema_version": 1,
        "profile_id": "desktop-default",
        "plugins": [],
        "digest": digest
    })
}

fn active_wasm_snapshot(digest: &str, artifact_digest: &str) -> Value {
    json!({
        "schema_version": 1,
        "profile_id": "desktop-default",
        "plugins": [{
            "schema_version": 1,
            "id": "third-party-tool",
            "version": "1.0.0",
            "runtime": "wasm",
            "trust": "signed",
            "provides": [{
                "kind": "tool",
                "id": "demo",
                "contract": "tool:demo",
                "permissions": ["tools.execute"]
            }],
            "config": {"artifact": {"layer_sha256": artifact_digest}}
        }],
        "digest": digest
    })
}

fn active_frontend_snapshot(digest: &str, artifact_digest: &str) -> Value {
    json!({
        "schema_version": 1,
        "profile_id": "desktop-default",
        "plugins": [{
            "schema_version": 1,
            "id": "third-party-ui",
            "version": "1.0.0",
            "runtime": "frontend",
            "trust": "signed",
            "provides": [{
                "kind": "ui_renderer",
                "id": "tool_result_renderer",
                "contract": "ui_renderer:tool-result",
                "permissions": ["ui.render"]
            }],
            "config": {"artifact": {"layer_sha256": artifact_digest}}
        }],
        "digest": digest
    })
}

#[tokio::test]
async fn platform_plugin_snapshot_reconcile_requires_auth_and_persists_last_good() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let app = router(state);
    let mut payload = snapshot("placeholder");
    payload.as_object_mut().expect("payload").remove("digest");
    let digest = platform_plugin_payload_digest(&payload).expect("canonical digest");
    payload["digest"] = json!(digest);

    let unauthorized = request_json(
        app.clone(),
        "GET",
        "/api/v1/platform-plugins/snapshot",
        None,
        json!({}),
    )
    .await;
    let submitted = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/snapshot",
        Some("desktop-session"),
        json!({
            "version": 4,
            "nonce": "nonce-4",
            "digest": digest,
            "payload": payload
        }),
    )
    .await;
    let acknowledged = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/ack",
        Some("desktop-session"),
        json!({"version": 4, "digest": digest}),
    )
    .await;
    let active = request_json(
        app.clone(),
        "GET",
        "/api/v1/platform-plugins/snapshot",
        Some("desktop-session"),
        json!({}),
    )
    .await;
    let apply_state = request_json(
        app,
        "GET",
        "/api/v1/platform-plugins/apply-state",
        Some("desktop-session"),
        json!({}),
    )
    .await;

    assert_eq!(unauthorized.0, StatusCode::UNAUTHORIZED);
    assert_eq!(submitted.0, StatusCode::OK);
    assert_eq!(submitted.1["status"], "ack");
    assert_eq!(acknowledged.0, StatusCode::OK);
    assert_eq!(acknowledged.1["status"], "ack");
    assert_eq!(active.0, StatusCode::OK);
    assert_eq!(active.1["source"], "last_good");
    assert_eq!(active.1["snapshot"], payload);
    assert_eq!(apply_state.0, StatusCode::OK);
    assert_eq!(apply_state.1["status"], "ack");
    assert_eq!(apply_state.1["requested_version"], 4);
    assert_eq!(apply_state.1["applied_version"], 4);
}

#[tokio::test]
async fn platform_plugin_snapshot_reconcile_rejects_stale_and_mismatched_receipts() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let app = router(state);
    let mut payload = snapshot("placeholder");
    payload.as_object_mut().expect("payload").remove("digest");
    let digest = platform_plugin_payload_digest(&payload).expect("canonical digest");
    payload["digest"] = json!(digest);
    let submit = |app: Router, version: u64, digest: String, payload: Value| {
        request_json(
            app,
            "POST",
            "/api/v1/platform-plugins/snapshot",
            Some("desktop-session"),
            json!({
                "version": version,
                "nonce": format!("nonce-{version}"),
                "digest": digest,
                "payload": payload
            }),
        )
    };

    let first = submit(app.clone(), 4, digest.clone(), payload.clone()).await;
    let acknowledged = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/ack",
        Some("desktop-session"),
        json!({"version": 4, "digest": digest}),
    )
    .await;
    let idempotent = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/snapshot",
        Some("desktop-session"),
        json!({
            "version": 4,
            "nonce": "nonce-4",
            "digest": digest,
            "payload": payload
        }),
    )
    .await;
    let stale = submit(app.clone(), 3, digest.clone(), payload.clone()).await;
    let mismatched = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/ack",
        Some("desktop-session"),
        json!({"version": 4, "digest": "0".repeat(64)}),
    )
    .await;
    let missing_reason = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/nack",
        Some("desktop-session"),
        json!({"reason": " "}),
    )
    .await;
    let nacked = request_json(
        app,
        "POST",
        "/api/v1/platform-plugins/nack",
        Some("desktop-session"),
        json!({"reason": "plugin preparation failed"}),
    )
    .await;

    assert_eq!(first.0, StatusCode::OK);
    assert_eq!(acknowledged.0, StatusCode::OK);
    assert_eq!(idempotent.0, StatusCode::OK);
    assert_eq!(idempotent.1["status"], "ack");
    assert_eq!(idempotent.1["idempotent"], true);
    assert_eq!(stale.0, StatusCode::CONFLICT);
    assert_eq!(mismatched.0, StatusCode::CONFLICT);
    assert_eq!(missing_reason.0, StatusCode::BAD_REQUEST);
    assert_eq!(nacked.0, StatusCode::OK);
}

#[tokio::test]
async fn active_untrusted_wasm_tool_invocation_is_quota_bounded() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let app = router(state.clone());
    let runtime = SCORE_V1_WAT.as_bytes().to_vec();
    let artifact_digest = {
        use sha2::{Digest, Sha256};
        let digest = Sha256::digest(&runtime);
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    };
    let mut payload = active_wasm_snapshot("placeholder", &artifact_digest);
    payload.as_object_mut().expect("payload").remove("digest");
    let digest = platform_plugin_payload_digest(&payload).expect("digest");
    payload["digest"] = json!(digest.clone());
    {
        let connection = state.session_store.connection().expect("connection");
        crate::plugin_snapshots::initialize_schema(&connection).expect("schema");
        crate::plugin_snapshots::store_runtime_artifact(
            &connection,
            &crate::plugin_snapshots::RuntimeArtifact {
                plugin_id: "third-party-tool".to_string(),
                digest: artifact_digest.clone(),
                runtime: "wasm".to_string(),
                path: "runtime/plugin.wasm".to_string(),
                bytes: runtime,
            },
        )
        .expect("artifact");
    }

    let submitted = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/snapshot",
        Some("desktop-session"),
        json!({
            "version": 9,
            "nonce": "nonce-9",
            "digest": digest,
            "payload": payload
        }),
    )
    .await;
    let invoked = request_json(
        app,
        "POST",
        "/api/v1/platform-plugins/tools/invoke",
        Some("desktop-session"),
        json!({"plugin_id": "third-party-tool", "tool_id": "demo", "input": {"text": "hello"}}),
    )
    .await;

    assert_eq!(submitted.0, StatusCode::OK);
    assert_eq!(submitted.1["status"], "ack");
    assert_eq!(invoked.0, StatusCode::OK);
    assert_eq!(invoked.1["score"], 22);
    assert_eq!(invoked.1["tool"], "demo");
}

#[tokio::test]
async fn signed_frontend_module_is_served_only_after_activation() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let app = router(state.clone());
    let runtime = json!({
        "html": "<main id=\"plugin-root\">signed module</main>",
        "slots": ["tool_result_renderer"]
    })
    .to_string();
    let runtime = runtime.into_bytes();
    let artifact_digest = {
        use sha2::{Digest, Sha256};
        let digest = Sha256::digest(&runtime);
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    };
    let mut payload = active_frontend_snapshot("placeholder", &artifact_digest);
    payload.as_object_mut().expect("payload").remove("digest");
    let digest = platform_plugin_payload_digest(&payload).expect("digest");
    payload["digest"] = json!(digest.clone());
    {
        let connection = state.session_store.connection().expect("connection");
        crate::plugin_snapshots::initialize_schema(&connection).expect("schema");
        crate::plugin_snapshots::store_runtime_artifact(
            &connection,
            &crate::plugin_snapshots::RuntimeArtifact {
                plugin_id: "third-party-ui".to_string(),
                digest: artifact_digest.clone(),
                runtime: "frontend".to_string(),
                path: "runtime/plugin.json".to_string(),
                bytes: runtime,
            },
        )
        .expect("artifact");
    }

    let before_activation = request_json(
        app.clone(),
        "GET",
        "/api/v1/platform-plugins/frontend/third-party-ui/module",
        Some("desktop-session"),
        json!({}),
    )
    .await;
    let submitted = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/snapshot",
        Some("desktop-session"),
        json!({
            "version": 10,
            "nonce": "nonce-10",
            "digest": digest,
            "payload": payload
        }),
    )
    .await;
    let module = request_json(
        app,
        "GET",
        "/api/v1/platform-plugins/frontend/third-party-ui/module",
        Some("desktop-session"),
        json!({}),
    )
    .await;

    assert_eq!(before_activation.0, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(submitted.0, StatusCode::OK);
    assert_eq!(module.0, StatusCode::OK);
    assert_eq!(module.1["plugin_id"], "third-party-ui");
    assert_eq!(module.1["digest"], artifact_digest);
    assert_eq!(module.1["trust"], "signed");
    assert_eq!(
        module.1["html"],
        "<main id=\"plugin-root\">signed module</main>"
    );
}
