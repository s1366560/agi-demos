use std::{fs, path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    extract::State,
    http::{header, HeaderMap, HeaderValue, Method, Request, StatusCode},
    response::{IntoResponse, Response},
    routing::post,
    Json, Router,
};
use serde_json::{json, Value};
use tokio::{net::TcpListener, task::JoinHandle};
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;
use crate::application_vault::ApplicationCredentialVault;

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
import os
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
if mode == "require_env" and os.environ.get("ROUTE_TOKEN") != "route-env-secret":
    sys.exit(7)

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

async fn authenticated_remote_mcp(
    State(expected_authorization): State<String>,
    headers: HeaderMap,
    Json(request): Json<Value>,
) -> Response {
    if headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        != Some(expected_authorization.as_str())
    {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let method = request.get("method").and_then(Value::as_str);
    if method != Some("initialize")
        && (headers
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok())
            != Some("provisioned-session")
            || headers
                .get("mcp-protocol-version")
                .and_then(|value| value.to_str().ok())
                != Some("2025-03-26"))
    {
        return StatusCode::BAD_REQUEST.into_response();
    }
    if request.get("id").is_none() {
        return StatusCode::ACCEPTED.into_response();
    }
    let result = match method {
        Some("initialize") => json!({
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "provisioned-route", "version": "1"},
        }),
        Some("tools/list") => json!({"tools": []}),
        _ => json!({}),
    };
    let mut response = Json(json!({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": result,
    }))
    .into_response();
    if method == Some("initialize") {
        response.headers_mut().insert(
            "mcp-session-id",
            HeaderValue::from_static("provisioned-session"),
        );
    }
    response
}

async fn spawn_authenticated_remote_mcp(expected_authorization: &str) -> (String, JoinHandle<()>) {
    let app = Router::new()
        .route("/mcp", post(authenticated_remote_mcp))
        .with_state(expected_authorization.to_string());
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind provisioned MCP server");
    let address = listener.local_addr().expect("provisioned MCP address");
    let task = tokio::spawn(async move {
        axum::serve(listener, app)
            .await
            .expect("serve provisioned MCP");
    });
    (format!("http://{address}/mcp"), task)
}

fn persistent_test_state(
    root: &std::path::Path,
    credential: &str,
    vault: ApplicationCredentialVault,
    seed_session: bool,
) -> Arc<LocalRuntimeState> {
    let tool_host = LocalToolHost::new(root).expect("persistent tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("persistent checkpoints"));
    let session_store =
        DesktopSessionStore::open(&root.join("desktop.db")).expect("persistent session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.to_path_buf(),
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("persistent local runtime state"),
    );
    if seed_session {
        state
            .session_store
            .seed_test_session(credential)
            .expect("persistent authenticated session");
    }
    state
        .mcp_supervisor
        .install_credential_vault(vault)
        .expect("install persistent MCP vault");
    state
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
                    "credential_env_names": [],
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
                "idempotency_key": "route-disallowed-tool-call",
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
                    "credential_env_names": [],
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
                "idempotency_key": "route-malformed-tool-call",
            }),
        ))
        .await
        .expect("malformed MCP tool response");
    assert_eq!(malformed_call.status(), StatusCode::CONFLICT);
    assert_eq!(
        response_json(malformed_call).await["reason_code"],
        "local_mcp_tool_call_indeterminate"
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
async fn every_tool_call_route_rejects_a_missing_idempotency_key_before_dispatch() {
    let root = test_root();
    fs::create_dir_all(&root).expect("create idempotency route root");
    let credential = "mcp-idempotency-route-secret";
    let app = local_router(test_state(&root, credential));
    for (uri, body) in [
        (
            "/api/v1/mcp/tools/call",
            json!({
                "server_id": "server-missing",
                "tool_name": "echo",
                "arguments": {},
            }),
        ),
        (
            "/api/v1/mcp/apps/app-missing/tool-call",
            json!({
                "tool_name": "echo",
                "arguments": {},
            }),
        ),
        (
            "/api/v1/mcp/apps/proxy/tool-call",
            json!({
                "project_id": "local-project",
                "server_name": "server-missing",
                "tool_name": "echo",
                "arguments": {},
            }),
        ),
    ] {
        let response = app
            .clone()
            .oneshot(request(Method::POST, uri, credential, body))
            .await
            .expect("missing idempotency response");
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY, "{uri}");
    }
    fs::remove_dir_all(root).expect("remove idempotency route root");
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
    let app = local_router(test_state(&root, credential));
    let arbitrary_reference = app
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp",
            credential,
            json!({
                "name": "unsafe-reference",
                "server_type": "http",
                "transport_config": {
                    "url": "http://127.0.0.1:12345/mcp",
                    "vault_header_refs": {
                        "authorization": "renderer-selected-vault-key"
                    },
                },
                "project_id": "local-project",
                "idempotency_key": "unsafe-reference",
            }),
        ))
        .await
        .expect("arbitrary vault reference response");
    assert_eq!(
        arbitrary_reference.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
    fs::remove_dir_all(root).expect("remove malformed route root");
}

#[tokio::test]
async fn remote_registration_derives_header_refs_and_never_exposes_reference_values() {
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
                    "credential_header_names": ["authorization"],
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
async fn credential_provisioning_survives_restart_and_authenticates_without_exposing_secret_refs() {
    let root = test_root();
    fs::create_dir_all(&root).expect("create provisioned route root");
    let credential = "mcp-provision-route-secret";
    let remote_secret = "Bearer provisioned-route-auth";
    let (endpoint, remote_task) = spawn_authenticated_remote_mcp(remote_secret).await;
    let vault_root = root.join("app-data");
    let first_vault =
        ApplicationCredentialVault::open(&vault_root).expect("open first provisioned vault");
    let first_vault_probe = first_vault.clone();
    let first_state = persistent_test_state(&root, credential, first_vault, true);
    let first_app = local_router(Arc::clone(&first_state));

    let provision = first_app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/credentials/provision",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "provisioned-route",
                "server_type": "http",
                "transport_config": {"url": endpoint},
                "credential_kind": "header",
                "credential_name": "authorization",
                "secret": remote_secret,
                "idempotency_key": "provision-route-authorization",
            }),
        ))
        .await
        .expect("provision MCP credential response");
    assert_eq!(provision.status(), StatusCode::OK);
    let provision = response_json(provision).await;
    assert_eq!(provision["stored"], true);
    assert_eq!(provision["credential_kind"], "header");
    assert_eq!(provision["credential_name"], "authorization");
    assert_eq!(provision["duplicate"], false);
    assert!(!provision.to_string().contains(remote_secret));
    assert!(!provision.to_string().contains("mcp-remote-credential"));

    let duplicate = first_app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/credentials/provision",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "provisioned-route",
                "server_type": "http",
                "transport_config": {"url": endpoint},
                "credential_kind": "header",
                "credential_name": "authorization",
                "secret": remote_secret,
                "idempotency_key": "provision-route-authorization",
            }),
        ))
        .await
        .expect("replay MCP credential provisioning");
    assert_eq!(duplicate.status(), StatusCode::OK);
    assert_eq!(response_json(duplicate).await["duplicate"], true);

    let conflict = first_app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/credentials/provision",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "provisioned-route",
                "server_type": "http",
                "transport_config": {"url": endpoint},
                "credential_kind": "header",
                "credential_name": "authorization",
                "secret": "Bearer conflicting-secret",
                "idempotency_key": "provision-route-authorization",
            }),
        ))
        .await
        .expect("conflicting MCP credential provisioning");
    assert_eq!(conflict.status(), StatusCode::CONFLICT);
    assert_eq!(
        response_json(conflict).await["reason_code"],
        "local_mcp_idempotency_conflict"
    );

    let replacement_secret = "Bearer replacement-route-auth";
    let replacement = first_app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/credentials/provision",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "provisioned-route",
                "server_type": "http",
                "transport_config": {"url": endpoint},
                "credential_kind": "header",
                "credential_name": "authorization",
                "secret": replacement_secret,
                "idempotency_key": "replace-route-authorization",
            }),
        ))
        .await
        .expect("replace MCP credential");
    assert_eq!(replacement.status(), StatusCode::OK);

    let stale_replay = first_app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/credentials/provision",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "provisioned-route",
                "server_type": "http",
                "transport_config": {"url": endpoint},
                "credential_kind": "header",
                "credential_name": "authorization",
                "secret": remote_secret,
                "idempotency_key": "provision-route-authorization",
            }),
        ))
        .await
        .expect("replay stale MCP credential receipt");
    assert_eq!(stale_replay.status(), StatusCode::OK);
    assert_eq!(response_json(stale_replay).await["duplicate"], true);
    let reference = mcp_supervisor::remote_credential_reference(
        &mcp_supervisor::McpScope {
            tenant_id: "local".to_string(),
            project_id: "local-project".to_string(),
        },
        "provisioned-route",
        mcp_supervisor::McpTransport::Http,
        &endpoint,
        "authorization",
    )
    .expect("derive provisioned credential reference");
    assert_eq!(
        first_vault_probe
            .get(&reference)
            .expect("read current replacement credential")
            .as_deref(),
        Some(replacement_secret),
        "a stale receipt replay must not roll back a newer credential mutation",
    );

    let restore = first_app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/credentials/provision",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "provisioned-route",
                "server_type": "http",
                "transport_config": {"url": endpoint},
                "credential_kind": "header",
                "credential_name": "authorization",
                "secret": remote_secret,
                "idempotency_key": "restore-route-authorization",
            }),
        ))
        .await
        .expect("restore authenticated MCP credential");
    assert_eq!(restore.status(), StatusCode::OK);

    let create = first_app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp",
            credential,
            json!({
                "name": "provisioned-route",
                "server_type": "http",
                "transport_config": {
                    "url": endpoint,
                    "credential_header_names": ["authorization"],
                },
                "enabled": true,
                "project_id": "local-project",
                "idempotency_key": "create-provisioned-route",
            }),
        ))
        .await
        .expect("create provisioned MCP response");
    assert_eq!(create.status(), StatusCode::OK);
    let server = response_json(create).await;
    let server_id = server["id"]
        .as_str()
        .expect("provisioned server id")
        .to_string();
    assert!(!server.to_string().contains(remote_secret));
    assert!(!server.to_string().contains("mcp-remote-credential"));

    drop(first_app);
    drop(first_state);

    let reopened_vault =
        ApplicationCredentialVault::open(&vault_root).expect("reopen provisioned vault");
    let reopened_state = persistent_test_state(&root, credential, reopened_vault, false);
    reopened_state
        .mcp_supervisor
        .prepare_startup_recovery()
        .expect("mark provisioned server recovery pending");
    reopened_state
        .mcp_supervisor
        .recover_all_enabled()
        .await
        .expect("schedule provisioned server recovery");
    let mut recovered = false;
    for _ in 0..100 {
        let health = reopened_state
            .mcp_supervisor
            .health(
                &mcp_supervisor::McpScope {
                    tenant_id: "local".to_string(),
                    project_id: "local-project".to_string(),
                },
                &server_id,
            )
            .expect("provisioned server recovery health");
        if health.status == "healthy" {
            recovered = true;
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    assert!(
        recovered,
        "restart recovery must authenticate with the persisted vault binding"
    );
    let reopened_app = local_router(reopened_state);
    let sync = reopened_app
        .oneshot(request(
            Method::POST,
            &format!("/api/v1/mcp/{server_id}/sync"),
            credential,
            json!({}),
        ))
        .await
        .expect("sync provisioned MCP after restart");
    assert_eq!(sync.status(), StatusCode::OK);

    remote_task.abort();
    fs::remove_dir_all(root).expect("remove provisioned route root");
}

#[tokio::test]
async fn stdio_environment_credential_is_scope_derived_and_injected_only_by_the_sidecar() {
    let root = test_root();
    fs::create_dir_all(&root).expect("create stdio credential route root");
    let script = write_mock_server(&root);
    let python = python_executable();
    let credential = "mcp-stdio-credential-route-secret";
    let vault_root = root.join("app-data");
    let vault = ApplicationCredentialVault::open(&vault_root).expect("open stdio route vault");
    let state = persistent_test_state(&root, credential, vault, true);
    let app = local_router(state);

    let provision = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp/credentials/provision",
            credential,
            json!({
                "project_id": "local-project",
                "server_name": "stdio-with-env",
                "server_type": "stdio",
                "transport_config": {
                    "command": python,
                    "args": [script, "require_env"],
                    "cwd": ".",
                },
                "credential_kind": "env",
                "credential_name": "ROUTE_TOKEN",
                "secret": "route-env-secret",
                "idempotency_key": "provision-stdio-route-token",
            }),
        ))
        .await
        .expect("provision stdio environment credential");
    assert_eq!(provision.status(), StatusCode::OK);
    let provision = response_json(provision).await;
    assert_eq!(provision["credential_kind"], "env");
    assert!(!provision.to_string().contains("route-env-secret"));
    assert!(!provision.to_string().contains("mcp-stdio-credential"));

    let create = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/mcp",
            credential,
            json!({
                "name": "stdio-with-env",
                "server_type": "stdio",
                "transport_config": {
                    "command": python,
                    "args": [script, "require_env"],
                    "cwd": ".",
                    "credential_env_names": ["ROUTE_TOKEN"],
                },
                "enabled": true,
                "project_id": "local-project",
                "idempotency_key": "create-stdio-with-env",
            }),
        ))
        .await
        .expect("create stdio server with provisioned environment");
    assert_eq!(create.status(), StatusCode::OK);
    let create = response_json(create).await;
    assert_eq!(
        create["transport_config"]["vault_env_names"],
        json!(["ROUTE_TOKEN"])
    );
    assert!(!create.to_string().contains("route-env-secret"));
    assert!(!create.to_string().contains("mcp-stdio-credential"));
    let server_id = create["id"].as_str().expect("stdio credential server id");

    let sync = app
        .oneshot(request(
            Method::POST,
            &format!("/api/v1/mcp/{server_id}/sync"),
            credential,
            json!({}),
        ))
        .await
        .expect("sync stdio MCP with provisioned environment");
    assert_eq!(sync.status(), StatusCode::OK);
    fs::remove_dir_all(root).expect("remove stdio credential route root");
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
    assert_eq!(
        snapshot["credential_provisioning"]["availability"],
        "available"
    );
    assert_eq!(
        snapshot["credential_provisioning"]["renderer_receives_reference"],
        false
    );
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
