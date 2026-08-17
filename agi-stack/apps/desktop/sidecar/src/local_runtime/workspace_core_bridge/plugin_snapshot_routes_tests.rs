use std::{fs, path::PathBuf, sync::Arc};

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

fn active_mcp_snapshot(digest: &str, artifact_digest: &str) -> Value {
    json!({
        "schema_version": 1,
        "profile_id": "desktop-default",
        "plugins": [{
            "schema_version": 1,
            "id": "third-party-mcp",
            "version": "1.0.0",
            "runtime": "mcp",
            "trust": "signed",
            "provides": [{
                "kind": "tool",
                "id": "echo",
                "contract": "tool:echo",
                "permissions": ["tools.execute"]
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
    let app = platform_plugin_router(state.clone()).with_state(state.clone());
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
    let app = platform_plugin_router(state.clone()).with_state(state.clone());
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
async fn active_mcp_plugin_tool_is_invoked_through_the_supervisor() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let workspace_root = state.workspace_root.lock().expect("workspace root").clone();
    fs::create_dir_all(&workspace_root).expect("workspace root");
    let script = workspace_root.join("platform_plugin_mcp.py");
    fs::write(
        &script,
        r#"import json
import sys

for raw_line in sys.stdin:
    request = json.loads(raw_line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "platform-plugin-mcp", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        arguments = request.get("params", {}).get("arguments", {})
        result = {
            "content": [{"type": "text", "text": json.dumps(arguments, sort_keys=True)}],
            "isError": False,
        }
    else:
        result = None
    if result is None:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method not found"},
        }
    else:
        response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    sys.stdout.flush()
"#,
    )
    .expect("MCP script");
    let python = std::env::split_paths(&std::env::var_os("PATH").expect("test PATH"))
        .map(|entry| entry.join("python3"))
        .find(|candidate| candidate.is_file())
        .and_then(|candidate| candidate.canonicalize().ok())
        .unwrap_or_else(|| PathBuf::from("/usr/bin/python3"));
    let runtime_definition = json!({
        "transport": "stdio",
        "command": [python.to_string_lossy(), script.to_string_lossy()],
        "cwd": ".",
        "enabled": true
    });
    let runtime_bytes = serde_json::to_vec(&runtime_definition).expect("MCP runtime");
    let artifact_digest = {
        use sha2::{Digest, Sha256};
        let digest = Sha256::digest(&runtime_bytes);
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    };
    let mut payload = active_mcp_snapshot("placeholder", &artifact_digest);
    payload.as_object_mut().expect("payload").remove("digest");
    let digest = platform_plugin_payload_digest(&payload).expect("digest");
    payload["digest"] = json!(digest.clone());
    {
        let connection = state.session_store.connection().expect("connection");
        crate::plugin_snapshots::initialize_schema(&connection).expect("schema");
        crate::plugin_snapshots::store_runtime_artifact(
            &connection,
            &crate::plugin_snapshots::RuntimeArtifact {
                plugin_id: "third-party-mcp".to_string(),
                digest: artifact_digest.clone(),
                runtime: "mcp".to_string(),
                path: "runtime/plugin.json".to_string(),
                bytes: runtime_bytes,
            },
        )
        .expect("artifact");
    }
    let scope = McpScope {
        tenant_id: "local".to_string(),
        project_id: "local-project".to_string(),
    };
    state
        .mcp_supervisor
        .ensure_platform_plugin_server(
            &scope,
            "third-party-mcp",
            &runtime_definition,
            &artifact_digest,
        )
        .expect("MCP server");
    let app = platform_plugin_router(state.clone()).with_state(state.clone());
    let submitted = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/snapshot",
        Some("desktop-session"),
        json!({
            "version": 13,
            "nonce": "nonce-13",
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
        json!({"plugin_id": "third-party-mcp", "tool_id": "echo", "input": {"message": "hello"}}),
    )
    .await;

    assert_eq!(submitted.0, StatusCode::OK);
    assert_eq!(submitted.1["status"], "ack");
    assert_eq!(invoked.0, StatusCode::OK);
    assert_eq!(invoked.1["content"][0]["type"], "text");
    assert_eq!(invoked.1["content"][0]["text"], r#"{"message": "hello"}"#);
}

#[tokio::test]
async fn active_untrusted_wasm_tool_invocation_is_quota_bounded() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let app = platform_plugin_router(state.clone()).with_state(state.clone());
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

fn active_subprocess_snapshot(digest: &str, artifact_digest: &str) -> Value {
    json!({
        "schema_version": 1,
        "profile_id": "desktop-default",
        "plugins": [{
            "schema_version": 1,
            "id": "third-party-subprocess",
            "version": "1.0.0",
            "runtime": "subprocess",
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

#[tokio::test]
async fn signed_frontend_module_is_served_only_after_activation() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let app = platform_plugin_router(state.clone()).with_state(state.clone());
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

#[tokio::test]
async fn subprocess_plugin_enforces_process_group_wall_time_and_output_quotas() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let app = platform_plugin_router(state.clone()).with_state(state.clone());
    let runtime = json!({
        "command": ["/bin/sh", "-c", "printf subprocess-ok"],
        "timeout_ms": 1000
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
    let mut payload = active_subprocess_snapshot("placeholder", &artifact_digest);
    payload.as_object_mut().expect("payload").remove("digest");
    let digest = platform_plugin_payload_digest(&payload).expect("digest");
    payload["digest"] = json!(digest.clone());
    {
        let connection = state.session_store.connection().expect("connection");
        crate::plugin_snapshots::initialize_schema(&connection).expect("schema");
        crate::plugin_snapshots::store_runtime_artifact(
            &connection,
            &crate::plugin_snapshots::RuntimeArtifact {
                plugin_id: "third-party-subprocess".to_string(),
                digest: artifact_digest.clone(),
                runtime: "subprocess".to_string(),
                path: "runtime/plugin.json".to_string(),
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
            "version": 11,
            "nonce": "nonce-11",
            "digest": digest,
            "payload": payload
        }),
    )
    .await;
    let invoked = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/tools/invoke",
        Some("desktop-session"),
        json!({
            "plugin_id": "third-party-subprocess",
            "tool_id": "demo",
            "input": {}
        }),
    )
    .await;

    assert_eq!(submitted.0, StatusCode::OK);
    assert_eq!(invoked.0, StatusCode::OK);
    assert_eq!(invoked.1["exit_code"], 0);
    assert_eq!(invoked.1["stdout"], "subprocess-ok");

    let slow_runtime = json!({
        "command": ["/bin/sleep", "2"],
        "timeout_ms": 20
    })
    .to_string();
    let slow_runtime = slow_runtime.into_bytes();
    let slow_digest = {
        use sha2::{Digest, Sha256};
        let digest = Sha256::digest(&slow_runtime);
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    };
    let mut slow_payload = active_subprocess_snapshot("placeholder", &slow_digest);
    slow_payload
        .as_object_mut()
        .expect("payload")
        .remove("digest");
    let slow_snapshot_digest =
        platform_plugin_payload_digest(&slow_payload).expect("slow snapshot digest");
    slow_payload["digest"] = json!(slow_snapshot_digest.clone());
    {
        let connection = state.session_store.connection().expect("connection");
        crate::plugin_snapshots::store_runtime_artifact(
            &connection,
            &crate::plugin_snapshots::RuntimeArtifact {
                plugin_id: "third-party-subprocess".to_string(),
                digest: slow_digest,
                runtime: "subprocess".to_string(),
                path: "runtime/plugin.json".to_string(),
                bytes: slow_runtime,
            },
        )
        .expect("slow artifact");
    }

    let slow_submitted = request_json(
        app.clone(),
        "POST",
        "/api/v1/platform-plugins/snapshot",
        Some("desktop-session"),
        json!({
            "version": 12,
            "nonce": "nonce-12",
            "digest": slow_snapshot_digest,
            "payload": slow_payload
        }),
    )
    .await;
    let slow_invoked = request_json(
        app,
        "POST",
        "/api/v1/platform-plugins/tools/invoke",
        Some("desktop-session"),
        json!({
            "plugin_id": "third-party-subprocess",
            "tool_id": "demo",
            "input": {}
        }),
    )
    .await;

    assert_eq!(slow_submitted.0, StatusCode::OK);
    assert_eq!(slow_invoked.0, StatusCode::CONFLICT);
    assert_eq!(
        slow_invoked.1["detail"],
        "subprocess plugin exceeded its wall-time quota"
    );
}
