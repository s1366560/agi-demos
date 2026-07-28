use std::{fs, path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Method, Request, StatusCode},
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

fn test_root() -> PathBuf {
    std::env::temp_dir().join(format!("agistack-mcp-route-{}", Uuid::new_v4()))
}

fn python_executable() -> PathBuf {
    std::env::split_paths(&std::env::var_os("PATH").expect("test PATH"))
        .map(|entry| entry.join("python3"))
        .find(|candidate| candidate.is_file())
        .and_then(|candidate| candidate.canonicalize().ok())
        .expect("python3 executable")
}

fn write_mock_server(root: &std::path::Path) -> PathBuf {
    let script = root.join("mock_route_mcp.py");
    fs::write(
        &script,
        r#"import json
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "route-mock", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": [{
            "name": "echo",
            "inputSchema": {"type": "object"},
            "_meta": {"ui/resourceUri": "ui://route-mock/index.html"},
        }]}
    elif method == "tools/call":
        if mode == "malformed_tool":
            result = {"unexpected": []}
        else:
            result = {
                "content": [{"type": "text", "text": "route-ok"}],
                "isError": False,
            }
    elif method == "resources/list":
        result = {"resources": [{
            "uri": "ui://route-mock/index.html",
            "name": "Route App",
            "mimeType": "text/html;profile=mcp-app",
        }]}
    elif method == "resources/read":
        result = {"contents": [{
            "uri": "ui://route-mock/index.html",
            "mimeType": "text/html;profile=mcp-app",
            "text": "<main>route app</main>",
        }]}
    else:
        result = {}
    response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
    print(json.dumps(response, separators=(",", ":")), flush=True)
"#,
    )
    .expect("write route mock MCP server");
    script
}

fn test_state(root: &std::path::Path, credential: &str) -> Arc<LocalRuntimeState> {
    let tool_host = LocalToolHost::new(root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.to_path_buf(),
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated session");
    state
}

fn request(method: Method, uri: &str, credential: &str, body: Value) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .expect("MCP route request")
}

async fn response_json(response: axum::response::Response) -> Value {
    let bytes = axum::body::to_bytes(response.into_body(), 1024 * 1024)
        .await
        .expect("MCP route response");
    serde_json::from_slice(&bytes).expect("MCP route JSON")
}

#[tokio::test]
async fn authenticated_routes_drive_real_stdio_tools_resources_and_receipts() {
    let root = test_root();
    fs::create_dir_all(&root).expect("create route test root");
    let script = write_mock_server(&root);
    let python = python_executable();
    let credential = "mcp-route-secret";
    let app = local_router(test_state(&root, credential));

    let create = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp",
            credential,
            json!({
                "name": "route-mock",
                "server_type": "stdio",
                "transport_config": {
                    "command": python,
                    "args": [script, "normal"],
                    "cwd": ".",
                    "vault_env_refs": {},
                },
                "enabled": true,
                "project_id": "local-project",
                "idempotency_key": "create-route-mock",
            }),
        ))
        .await
        .expect("create route MCP response");
    assert_eq!(create.status(), StatusCode::OK);
    let server = response_json(create).await;
    let server_id = server["id"].as_str().expect("server id");
    assert_eq!(server["transport_config"]["arguments_redacted"], true);

    let sync = app
        .clone()
        .oneshot(request(
            Method::POST,
            &format!("/api/v1/mcp/{server_id}/sync"),
            credential,
            json!({}),
        ))
        .await
        .expect("sync route MCP response");
    assert_eq!(sync.status(), StatusCode::OK);

    let apps = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/mcp/apps?project_id=local-project",
            credential,
            json!({}),
        ))
        .await
        .expect("list MCP Apps response");
    assert_eq!(apps.status(), StatusCode::OK);
    let apps = response_json(apps).await;
    let app_id = apps[0]["id"].as_str().expect("MCP App id");

    for duplicate in [false, true] {
        let call = app
            .clone()
            .oneshot(request(
                Method::POST,
                &format!("/api/v1/mcp/apps/{app_id}/tool-call"),
                credential,
                json!({
                    "tool_name": "echo",
                    "arguments": {"value": 1},
                    "idempotency_key": "route-tool-call",
                }),
            ))
            .await
            .expect("MCP App tool response");
        assert_eq!(call.status(), StatusCode::OK);
        let call = response_json(call).await;
        assert_eq!(call["content"][0]["text"], "route-ok");
        assert_eq!(call["duplicate"], duplicate);
    }

    let disallowed = app
        .clone()
        .oneshot(request(
            Method::POST,
            &format!("/api/v1/mcp/apps/{app_id}/tool-call"),
            credential,
            json!({
                "tool_name": "not-visible-through-this-app",
                "arguments": {},
            }),
        ))
        .await
        .expect("MCP App allow-list response");
    assert_eq!(disallowed.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(disallowed).await["reason_code"],
        "local_mcp_app_tool_not_allowed"
    );

    let resources = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/apps/resources/list",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "route-mock",
            }),
        ))
        .await
        .expect("MCP resource list response");
    assert_eq!(resources.status(), StatusCode::OK);
    assert_eq!(
        response_json(resources).await["resources"][0]["uri"],
        "ui://route-mock/index.html"
    );

    let content = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/apps/resources/read",
            credential,
            json!({
                "project_id": "local-project",
                "uri": "ui://route-mock/index.html",
            }),
        ))
        .await
        .expect("MCP resource read response");
    assert_eq!(content.status(), StatusCode::OK);
    assert_eq!(
        response_json(content).await["contents"][0]["text"],
        "<main>route app</main>"
    );

    let malformed_create = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp",
            credential,
            json!({
                "name": "malformed-tool",
                "server_type": "stdio",
                "transport_config": {
                    "command": python,
                    "args": [script, "malformed_tool"],
                    "cwd": ".",
                    "vault_env_refs": {},
                },
                "enabled": true,
                "project_id": "local-project",
                "idempotency_key": "create-malformed-tool",
            }),
        ))
        .await
        .expect("create malformed MCP response");
    assert_eq!(malformed_create.status(), StatusCode::OK);

    let malformed_call = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/apps/proxy/tool-call",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "malformed-tool",
                "tool_name": "echo",
                "arguments": {},
            }),
        ))
        .await
        .expect("malformed MCP tool response");
    assert_eq!(malformed_call.status(), StatusCode::BAD_GATEWAY);
    assert_eq!(
        response_json(malformed_call).await["reason_code"],
        "local_mcp_malformed_response"
    );

    let wrong_scope = app
        .oneshot(request(
            Method::GET,
            "/api/v1/mcp/apps?project_id=desktop-client",
            credential,
            json!({}),
        ))
        .await
        .expect("wrong MCP scope response");
    assert_eq!(wrong_scope.status(), StatusCode::FORBIDDEN);

    fs::remove_dir_all(root).expect("remove route MCP root");
}

#[tokio::test]
async fn server_registration_rejects_plaintext_environment_and_unknown_payload_fields() {
    let root = test_root();
    fs::create_dir_all(&root).expect("create malformed route root");
    let credential = "mcp-malformed-route-secret";
    let app = local_router(test_state(&root, credential));
    let rejected = app
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp",
            credential,
            json!({
                "name": "unsafe",
                "server_type": "stdio",
                "transport_config": {
                    "command": "/bin/false",
                    "environment": {"TOKEN": "plaintext"},
                },
                "project_id": "local-project",
                "idempotency_key": "unsafe-environment",
            }),
        ))
        .await
        .expect("plaintext environment response");
    assert_eq!(rejected.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(rejected).await["reason_code"],
        "local_mcp_plaintext_environment_rejected"
    );
    fs::remove_dir_all(root).expect("remove malformed route root");
}

#[tokio::test]
async fn remote_registration_accepts_only_header_vault_refs_and_never_exposes_reference_values() {
    let root = test_root();
    fs::create_dir_all(&root).expect("create remote route root");
    let credential = "mcp-remote-route-secret";
    let reference = mcp_supervisor::remote_credential_reference(
        &mcp_supervisor::McpScope {
            tenant_id: "local".to_string(),
            project_id: "local-project".to_string(),
        },
        "remote-route",
        mcp_supervisor::McpTransport::Http,
        "http://127.0.0.1:12345/mcp",
        "authorization",
    )
    .expect("derive scoped route credential reference");
    let app = local_router(test_state(&root, credential));
    let response = app
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp",
            credential,
            json!({
                "name": "remote-route",
                "server_type": "http",
                "transport_config": {
                    "url": "http://127.0.0.1:12345/mcp",
                    "vault_header_refs": {
                        "authorization": reference
                    },
                },
                "enabled": false,
                "project_id": "local-project",
                "idempotency_key": "create-remote-route",
            }),
        ))
        .await
        .expect("create remote MCP response");
    assert_eq!(response.status(), StatusCode::OK);
    let server = response_json(response).await;
    assert_eq!(
        server["transport_config"]["url"],
        "http://127.0.0.1:12345/mcp"
    );
    assert_eq!(
        server["transport_config"]["vault_header_names"],
        json!(["authorization"])
    );
    assert_eq!(server["transport_config"]["vault_env_names"], json!([]));
    assert!(!server.to_string().contains(&reference));
    fs::remove_dir_all(root).expect("remove remote route root");
}

#[tokio::test]
async fn capability_snapshot_only_advertises_live_transports_and_fails_closed_for_elicitation() {
    let root = test_root();
    fs::create_dir_all(&root).expect("create capability route root");
    let credential = "mcp-capability-route-secret";
    let app = local_router(test_state(&root, credential));
    let response = app
        .oneshot(request(
            Method::GET,
            "/api/v1/mcp/capabilities?project_id=local-project",
            credential,
            json!({}),
        ))
        .await
        .expect("MCP capability response");
    assert_eq!(response.status(), StatusCode::OK);
    let snapshot = response_json(response).await;
    assert_eq!(snapshot["contract_version"], "desktop-local-mcp-v2");
    assert_eq!(snapshot["availability"], "available");
    for transport in ["stdio", "http", "sse", "websocket"] {
        assert_eq!(
            snapshot["transports"][transport]["availability"],
            "available"
        );
        assert!(snapshot["transports"][transport]["reason_code"].is_null());
        assert!(
            snapshot["transports"][transport]["protocol_version"].is_null(),
            "fixed protocol_version must not imply negotiation is unavailable"
        );
    }
    assert_eq!(
        snapshot["transports"]["http"]["protocol_negotiation"]["accepted"],
        json!(["2025-03-26"])
    );
    assert_eq!(
        snapshot["transports"]["websocket"]["protocol_negotiation"]["accepted"],
        json!(["2025-03-26", "2024-11-05"])
    );
    assert_eq!(snapshot["elicitation"]["availability"], "unavailable");
    assert_eq!(
        snapshot["elicitation"]["reason_code"],
        "local_mcp_elicitation_bridge_unavailable"
    );
    assert_eq!(snapshot["credential_authority"], "application_vault");
    assert_eq!(snapshot["redirect_policy"], "deny");
    fs::remove_dir_all(root).expect("remove capability route root");
}

#[test]
fn indeterminate_tool_call_is_a_stable_unavailable_conflict() {
    let (status, Json(body)) =
        super::mcp_apps::mcp_error_tuple_for(mcp_supervisor::McpSupervisorError::new(
            "local_mcp_tool_call_indeterminate",
            "MCP tool call dispatch completed without a verifiable local receipt",
        ));
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(body["availability"], "unavailable");
    assert_eq!(body["reason_code"], "local_mcp_tool_call_indeterminate");
}
