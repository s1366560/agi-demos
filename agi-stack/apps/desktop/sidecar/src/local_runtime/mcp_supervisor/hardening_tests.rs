use std::{
    collections::BTreeMap,
    fs,
    net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr},
    str::FromStr,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::Duration,
};

use axum::{
    body::Bytes,
    extract::State,
    http::{HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::post,
    Router,
};
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::{
    net::TcpListener,
    sync::{Barrier, Notify},
    task::JoinHandle,
};
use tokio_tungstenite::{accept_async, tungstenite::Message};
use url::Url;
use uuid::Uuid;

use super::{
    http::HttpRuntime,
    remote_common::{
        decode_json_rpc_messages, is_globally_routable, remote_credential_reference,
        remote_headers, resolve_remote_endpoint, validate_remote_url, validate_resolved_addresses,
        ResolvedEndpoint, SseDecoder,
    },
    store::McpStore,
    tool_call_lease::ToolCallReservation,
    websocket::connect_websocket,
    McpScope, McpServerDefinition, McpServerDefinitionInput, McpSupervisor, McpTransport,
    SupervisorLimits,
};
use crate::{
    application_vault::ApplicationCredentialVault,
    local_runtime::{DesktopSessionStore, LocalRuntimeService},
};

enum WebSocketBehavior {
    Oversized(usize),
    BlockTool {
        entered: Arc<Barrier>,
        release: Arc<Barrier>,
    },
    StallAfterInitialization {
        entered: Arc<Notify>,
    },
}

struct WebSocketHarness {
    url: String,
    calls: Arc<AtomicUsize>,
    task: JoinHandle<()>,
}

impl Drop for WebSocketHarness {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[derive(Clone)]
struct HttpSessionState {
    deletes: Arc<AtomicUsize>,
    delete_delay: Duration,
}

struct HttpSessionHarness {
    url: String,
    deletes: Arc<AtomicUsize>,
    task: JoinHandle<()>,
}

impl Drop for HttpSessionHarness {
    fn drop(&mut self) {
        self.task.abort();
    }
}

impl HttpSessionHarness {
    async fn spawn(delete_delay: Duration) -> Self {
        let deletes = Arc::new(AtomicUsize::new(0));
        let state = HttpSessionState {
            deletes: deletes.clone(),
            delete_delay,
        };
        let app = Router::new()
            .route("/mcp", post(http_session_post).delete(http_session_delete))
            .with_state(state);
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind HTTP session listener");
        let address = listener.local_addr().expect("HTTP session address");
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("serve HTTP session harness");
        });
        Self {
            url: format!("http://{address}/mcp"),
            deletes,
            task,
        }
    }
}

async fn http_session_post(headers: HeaderMap, body: Bytes) -> Response {
    let request: Value = serde_json::from_slice(&body).expect("parse HTTP session request");
    let method = request.get("method").and_then(Value::as_str);
    if method != Some("initialize")
        && headers
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok())
            != Some("session-id")
    {
        return StatusCode::BAD_REQUEST.into_response();
    }
    if request.get("id").is_none() {
        return StatusCode::ACCEPTED.into_response();
    }
    let result = if method == Some("initialize") {
        json!({
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "serverInfo": {"name": "http-session", "version": "1"},
        })
    } else {
        json!({})
    };
    let mut response = (
        StatusCode::OK,
        [("content-type", "application/json")],
        json!({
            "jsonrpc": "2.0",
            "id": request.get("id").cloned().unwrap_or(Value::Null),
            "result": result,
        })
        .to_string(),
    )
        .into_response();
    if method == Some("initialize") {
        response
            .headers_mut()
            .insert("mcp-session-id", HeaderValue::from_static("session-id"));
    }
    response
}

async fn http_session_delete(
    State(state): State<HttpSessionState>,
    headers: HeaderMap,
) -> Response {
    if headers
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
        != Some("session-id")
        || headers
            .get("mcp-protocol-version")
            .and_then(|value| value.to_str().ok())
            != Some("2025-03-26")
    {
        return StatusCode::BAD_REQUEST.into_response();
    }
    state.deletes.fetch_add(1, Ordering::SeqCst);
    tokio::time::sleep(state.delete_delay).await;
    StatusCode::NO_CONTENT.into_response()
}

impl WebSocketHarness {
    async fn spawn(behavior: WebSocketBehavior) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind hardening WebSocket listener");
        let address = listener.local_addr().expect("hardening listener address");
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_for_task = calls.clone();
        let task = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.expect("accept WebSocket client");
            let mut socket = accept_async(stream)
                .await
                .expect("accept WebSocket handshake");
            while let Some(Ok(message)) = socket.next().await {
                let Message::Text(text) = message else {
                    continue;
                };
                let request: Value = serde_json::from_str(&text).expect("parse hardening request");
                let method = request.get("method").and_then(Value::as_str);
                if method == Some("notifications/initialized") {
                    if let WebSocketBehavior::StallAfterInitialization { entered } = &behavior {
                        entered.notify_one();
                        std::future::pending::<()>().await;
                        return;
                    }
                    continue;
                }
                let result = match method {
                    Some("initialize") => json!({
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "hardening", "version": "1"},
                    }),
                    Some("tools/list") => match behavior {
                        WebSocketBehavior::Oversized(size) => json!({
                            "tools": [{
                                "name": "echo",
                                "description": "x".repeat(size),
                                "inputSchema": {"type": "object"},
                            }]
                        }),
                        _ => {
                            json!({"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]})
                        }
                    },
                    Some("tools/call") => {
                        calls_for_task.fetch_add(1, Ordering::SeqCst);
                        if let WebSocketBehavior::BlockTool { entered, release } = &behavior {
                            entered.wait().await;
                            release.wait().await;
                        }
                        json!({
                            "content": [{"type": "text", "text": "ok"}],
                            "isError": false,
                        })
                    }
                    _ => json!({}),
                };
                let response = json!({
                    "jsonrpc": "2.0",
                    "id": request.get("id").cloned().unwrap_or(Value::Null),
                    "result": result,
                });
                if socket
                    .send(Message::Text(response.to_string()))
                    .await
                    .is_err()
                {
                    return;
                }
            }
        });
        Self {
            url: format!("ws://{address}/mcp"),
            calls,
            task,
        }
    }
}

fn root(label: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!("agistack-mcp-hardening-{label}-{}", Uuid::new_v4()))
}

fn scope() -> McpScope {
    McpScope {
        tenant_id: "local".to_string(),
        project_id: "local-project".to_string(),
    }
}

fn limits() -> SupervisorLimits {
    SupervisorLimits {
        request_timeout: Duration::from_millis(300),
        initialize_timeout: Duration::from_millis(500),
        retry_base: Duration::from_millis(5),
        retry_max: Duration::from_millis(10),
        max_request_bytes: 64 * 1024,
        max_response_bytes: 64 * 1024,
        max_frame_bytes: 16 * 1024,
        max_aggregate_bytes: 64 * 1024,
        tool_call_lease_duration: Duration::from_secs(4),
        tool_call_wait_timeout: Duration::from_millis(300),
        tool_call_poll_interval: Duration::from_millis(5),
    }
}

fn websocket_supervisor(
    label: &str,
    harness: &WebSocketHarness,
    limits: SupervisorLimits,
) -> (std::path::PathBuf, Arc<McpSupervisor>, McpScope, String) {
    let root = root(label);
    fs::create_dir_all(&root).expect("create hardening root");
    let supervisor = Arc::new(
        McpSupervisor::new(
            DesktopSessionStore::in_memory().expect("hardening session store"),
            root.clone(),
            None,
            limits,
        )
        .expect("hardening MCP supervisor"),
    );
    let scope = scope();
    let server = supervisor
        .create_server(
            &scope,
            McpServerDefinitionInput {
                name: label.to_string(),
                description: None,
                transport: McpTransport::Websocket,
                command: vec![harness.url.clone()],
                cwd: None,
                vault_env_refs: BTreeMap::new(),
                enabled: true,
            },
            &format!("create-{label}"),
        )
        .expect("create hardening WebSocket server");
    (root, supervisor, scope, server.id)
}

fn remote_server(url: String, revision: u64) -> McpServerDefinition {
    McpServerDefinition {
        id: "http-session-server".to_string(),
        tenant_id: "local".to_string(),
        project_id: "local-project".to_string(),
        name: "http-session".to_string(),
        description: None,
        transport: McpTransport::Http,
        command: vec![url],
        cwd: None,
        vault_env_refs: BTreeMap::new(),
        enabled: true,
        revision,
        runtime_status: "stopped".to_string(),
        reason_code: None,
        discovered_tools: Vec::new(),
        server_info: None,
        created_at: "2026-07-28T00:00:00Z".to_string(),
        updated_at: "2026-07-28T00:00:00Z".to_string(),
    }
}

#[test]
fn literal_remote_policy_rejects_non_global_and_ipv4_mapped_addresses() {
    for endpoint in [
        "https://10.0.0.1/mcp",
        "https://100.64.0.1/mcp",
        "https://169.254.1.1/mcp",
        "https://192.0.2.1/mcp",
        "https://198.18.0.1/mcp",
        "https://224.0.0.1/mcp",
        "https://[::]/mcp",
        "https://[fe80::1]/mcp",
        "https://[2001:db8::1]/mcp",
        "https://[2002:a00:1::1]/mcp",
        "https://[64:ff9b::a00:1]/mcp",
        "https://[::ffff:7f00:1]/mcp",
        "https://[::ffff:6440:1]/mcp",
        "https://127.1/mcp",
        "https://2130706433/mcp",
        "https://0x7f000001/mcp",
    ] {
        let error = validate_remote_url(endpoint, McpTransport::Http, false)
            .expect_err("non-global literal must be rejected");
        assert_eq!(error.reason_code(), "local_mcp_endpoint_policy_rejected");
    }
    validate_remote_url("https://8.8.8.8/mcp", McpTransport::Http, false)
        .expect("public IPv4 literal");
    validate_remote_url(
        "https://[2606:4700:4700::1111]/mcp",
        McpTransport::Http,
        false,
    )
    .expect("public IPv6 literal");
    assert!(is_globally_routable(IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8))));
    assert!(!is_globally_routable(IpAddr::V6(
        Ipv6Addr::from_str("::ffff:100.64.0.1").expect("mapped CGNAT")
    )));
}

#[test]
fn resolved_remote_policy_rejects_mixed_or_non_global_dns_answers() {
    let public_url = Url::parse("https://mcp.example.com/rpc").expect("public URL");
    let public = SocketAddr::from_str("8.8.8.8:443").expect("public address");
    for rejected in [
        "10.0.0.1:443",
        "100.64.0.1:443",
        "192.0.2.1:443",
        "[2001:db8::1]:443",
        "[::ffff:127.0.0.1]:443",
    ] {
        let address = SocketAddr::from_str(rejected).expect("rejected address");
        let error = validate_resolved_addresses(&public_url, &[address])
            .expect_err("non-global DNS answer must be rejected");
        assert_eq!(
            error.reason_code(),
            "local_mcp_endpoint_resolution_rejected"
        );
        assert!(validate_resolved_addresses(&public_url, &[public, address]).is_err());
    }
    validate_resolved_addresses(
        &public_url,
        &[
            public,
            SocketAddr::from_str("[2606:4700:4700::1111]:443").expect("public IPv6"),
        ],
    )
    .expect("all-global DNS answers");
    let localhost = Url::parse("http://localhost:1234/mcp").expect("localhost URL");
    validate_resolved_addresses(
        &localhost,
        &[
            SocketAddr::from_str("127.0.0.1:1234").expect("IPv4 loopback"),
            SocketAddr::from_str("[::1]:1234").expect("IPv6 loopback"),
        ],
    )
    .expect("canonical localhost answers");
}

#[test]
fn remote_credentials_are_bound_to_mcp_scope_server_origin_and_header() {
    let root = root("credential-scope");
    fs::create_dir_all(&root).expect("create credential scope root");
    let vault = ApplicationCredentialVault::open(&root).expect("open credential scope vault");
    vault
        .put("trusted-session.v1", "must-not-be-reused")
        .expect("store trusted-session fixture");
    let mut server = remote_server("http://127.0.0.1:12345/mcp".to_string(), 1);
    server.vault_env_refs = BTreeMap::from([(
        "authorization".to_string(),
        "trusted-session.v1".to_string(),
    )]);
    let supervisor = McpSupervisor::new(
        DesktopSessionStore::in_memory().expect("credential scope session store"),
        root.clone(),
        Some(vault.clone()),
        limits(),
    )
    .expect("credential scope supervisor");
    let registration_error = supervisor
        .create_server(
            &scope(),
            McpServerDefinitionInput {
                name: server.name.clone(),
                description: None,
                transport: server.transport,
                command: server.command.clone(),
                cwd: None,
                vault_env_refs: server.vault_env_refs.clone(),
                enabled: true,
            },
            "create-unscoped-credential",
        )
        .expect_err("unscoped credential must be rejected during registration");
    assert_eq!(
        registration_error.reason_code(),
        "local_mcp_remote_credential_scope_invalid"
    );
    let general_error = remote_headers(&server, Some(&vault))
        .expect_err("general vault record must not be accepted as MCP credential");
    assert_eq!(
        general_error.reason_code(),
        "local_mcp_remote_credential_scope_invalid"
    );

    let wrong_scope = McpScope {
        tenant_id: server.tenant_id.clone(),
        project_id: "another-project".to_string(),
    };
    let wrong_reference = remote_credential_reference(
        &wrong_scope,
        &server.name,
        server.transport,
        &server.command[0],
        "authorization",
    )
    .expect("derive wrong-scope reference");
    vault
        .put(&wrong_reference, "wrong-scope-secret")
        .expect("store wrong-scope fixture");
    server
        .vault_env_refs
        .insert("authorization".to_string(), wrong_reference);
    let scope_error = remote_headers(&server, Some(&vault))
        .expect_err("cross-project MCP credential must be rejected");
    assert_eq!(
        scope_error.reason_code(),
        "local_mcp_remote_credential_scope_invalid"
    );

    let reference = remote_credential_reference(
        &scope(),
        &server.name,
        server.transport,
        &server.command[0],
        "authorization",
    )
    .expect("derive scoped MCP credential reference");
    vault
        .put(&reference, "Bearer scoped-secret")
        .expect("store scoped MCP credential");
    server
        .vault_env_refs
        .insert("authorization".to_string(), reference.clone());
    let mut wrong_server = server.clone();
    wrong_server.name = "another-server".to_string();
    assert_eq!(
        remote_headers(&wrong_server, Some(&vault))
            .expect_err("credential must not cross server bindings")
            .reason_code(),
        "local_mcp_remote_credential_scope_invalid"
    );
    let mut wrong_origin = server.clone();
    wrong_origin.command = vec!["http://127.0.0.1:12346/mcp".to_string()];
    assert_eq!(
        remote_headers(&wrong_origin, Some(&vault))
            .expect_err("credential must not cross remote origins")
            .reason_code(),
        "local_mcp_remote_credential_scope_invalid"
    );
    let headers = remote_headers(&server, Some(&vault)).expect("resolve scoped MCP credential");
    assert_eq!(
        headers
            .get("authorization")
            .and_then(|value| value.to_str().ok()),
        Some("Bearer scoped-secret")
    );
    fs::remove_dir_all(root).expect("remove credential scope root");
}

#[test]
fn server_and_app_runtime_health_transitions_are_atomic_and_clear_errors() {
    let root = root("health-truth");
    fs::create_dir_all(&root).expect("create health truth root");
    let supervisor = McpSupervisor::new(
        DesktopSessionStore::in_memory().expect("health truth session store"),
        root.clone(),
        None,
        limits(),
    )
    .expect("health truth supervisor");
    let active_scope = scope();
    let server = supervisor
        .create_server(
            &active_scope,
            McpServerDefinitionInput {
                name: "health-truth".to_string(),
                description: None,
                transport: McpTransport::Stdio,
                command: vec!["/bin/false".to_string()],
                cwd: None,
                vault_env_refs: BTreeMap::new(),
                enabled: true,
            },
            "create-health-truth",
        )
        .expect("create health truth server");
    supervisor
        .store
        .record_tools_and_apps(
            &server,
            &[json!({
                "name": "render",
                "_meta": {"ui/resourceUri": "ui://health-truth/index.html"},
            })],
        )
        .expect("record healthy app");
    assert_eq!(
        supervisor
            .list_apps(&active_scope)
            .expect("list healthy apps")[0]
            .status,
        "healthy"
    );

    supervisor
        .store
        .record_runtime_error(&server, "local_mcp_connection_closed")
        .expect("record runtime failure");
    assert_eq!(
        supervisor
            .health(&active_scope, &server.id)
            .expect("failed server health")
            .status,
        "error"
    );
    assert_eq!(
        supervisor
            .list_apps(&active_scope)
            .expect("list failed apps")[0]
            .status,
        "error"
    );

    supervisor
        .store
        .record_runtime_ready(&server, &json!({"name": "health-truth", "version": "1"}))
        .expect("record runtime recovery");
    let health = supervisor
        .health(&active_scope, &server.id)
        .expect("recovered server health");
    assert_eq!(health.status, "healthy");
    assert_eq!(health.reason_code, None);
    assert_eq!(
        supervisor
            .list_apps(&active_scope)
            .expect("list recovered apps")[0]
            .status,
        "healthy"
    );
    fs::remove_dir_all(root).expect("remove health truth root");
}

#[test]
fn sse_decoder_accepts_cr_lf_crlf_and_chunk_split_newlines() {
    let mut decoder = SseDecoder::default();
    let mut events = decoder
        .push(b"event: message\rdata: first\r\n\r", 1024, 4096)
        .expect("decode mixed first chunk");
    events.extend(
        decoder
            .push(b"\ndata: second\n\n", 1024, 4096)
            .expect("decode split CRLF and LF event"),
    );
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].event.as_deref(), Some("message"));
    assert_eq!(events[0].data, b"first");
    assert_eq!(events[1].event, None);
    assert_eq!(events[1].data, b"second");
}

#[test]
fn sse_decoder_rejects_chunk_event_flood_and_total_allocation_growth() {
    let mut decoder = SseDecoder::default();
    let flood = "data: x\n\n".repeat(65);
    let flood_error = decoder
        .push(flood.as_bytes(), flood.len(), flood.len().saturating_mul(2))
        .expect_err("event flood must be rejected");
    assert_eq!(flood_error.reason_code(), "local_mcp_response_too_large");

    let mut decoder = SseDecoder::default();
    let chunk_error = decoder
        .push(b"data: oversized chunk", 8, 64)
        .expect_err("oversized chunk must be rejected before buffering");
    assert_eq!(chunk_error.reason_code(), "local_mcp_response_too_large");

    let mut decoder = SseDecoder::default();
    let allocation_error = decoder
        .push(b"data: 012345678901234567890123456789", 64, 16)
        .expect_err("aggregate decoder allocation must be bounded");
    assert_eq!(
        allocation_error.reason_code(),
        "local_mcp_response_too_large"
    );
}

#[test]
fn json_rpc_batch_decoder_accepts_bounded_members_and_rejects_empty_or_invalid_batches() {
    let messages = decode_json_rpc_messages(
        br#"[
          {"jsonrpc":"2.0","method":"notifications/tools/list_changed","params":{}},
          {"jsonrpc":"2.0","id":7,"result":{"tools":[]}}
        ]"#,
        8,
    )
    .expect("decode bounded JSON-RPC batch");
    assert_eq!(messages.len(), 2);
    assert_eq!(messages[1]["id"], 7);

    for invalid in [
        br#"[]"#.as_slice(),
        br#"[null]"#.as_slice(),
        br#"[{"jsonrpc":"2.0","id":1}]"#.as_slice(),
        br#"[{"jsonrpc":"1.0","id":1,"result":{}}]"#.as_slice(),
        br#"[[{"jsonrpc":"2.0","id":1,"result":{}}]]"#.as_slice(),
        br#"[{"jsonrpc":"2.0","id":1,"result":{},"error":null}]"#.as_slice(),
        br#"[{"jsonrpc":"2.0","id":1,"error":{"code":1.5,"message":"bad"}}]"#.as_slice(),
    ] {
        let error =
            decode_json_rpc_messages(invalid, 8).expect_err("invalid JSON-RPC batch must fail");
        assert_eq!(error.reason_code(), "local_mcp_malformed_response");
    }

    let oversized = format!(
        "[{}]",
        (0..9)
            .map(|index| format!(r#"{{"jsonrpc":"2.0","id":{index},"result":{{}}}}"#))
            .collect::<Vec<_>>()
            .join(",")
    );
    let error = decode_json_rpc_messages(oversized.as_bytes(), 8)
        .expect_err("oversized JSON-RPC batch must fail");
    assert_eq!(error.reason_code(), "local_mcp_response_too_large");
}

#[tokio::test]
async fn dns_lookup_is_bounded_by_its_deadline() {
    let server = remote_server("https://example.com/mcp".to_string(), 1);
    let started = tokio::time::Instant::now();
    let error = match resolve_remote_endpoint(&server, Duration::ZERO).await {
        Err(error) => error,
        Ok(_) => panic!("zero DNS deadline must fail closed"),
    };
    assert_eq!(error.reason_code(), "local_mcp_request_timeout");
    assert!(started.elapsed() < Duration::from_millis(100));
}

#[tokio::test]
async fn per_server_mutex_wait_is_inside_the_total_request_deadline() {
    let root = root("mutex-deadline");
    fs::create_dir_all(&root).expect("create mutex deadline root");
    let mut test_limits = limits();
    test_limits.initialize_timeout = Duration::from_millis(30);
    test_limits.request_timeout = Duration::from_millis(30);
    let supervisor = McpSupervisor::new(
        DesktopSessionStore::in_memory().expect("mutex deadline session store"),
        root.clone(),
        None,
        test_limits,
    )
    .expect("mutex deadline supervisor");
    let active_scope = scope();
    let server = supervisor
        .create_server(
            &active_scope,
            McpServerDefinitionInput {
                name: "mutex-deadline".to_string(),
                description: None,
                transport: McpTransport::Websocket,
                command: vec!["ws://127.0.0.1:9/mcp".to_string()],
                cwd: None,
                vault_env_refs: BTreeMap::new(),
                enabled: true,
            },
            "create-mutex-deadline",
        )
        .expect("create mutex deadline server");
    let runtime = supervisor
        .runtime(&server)
        .expect("resolve mutex deadline runtime");
    let _guard = runtime.lock().await;
    let started = tokio::time::Instant::now();
    let error = supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .expect_err("runtime mutex wait must time out");
    assert_eq!(error.reason_code(), "local_mcp_request_timeout");
    assert!(started.elapsed() < Duration::from_millis(250));
    fs::remove_dir_all(root).expect("remove mutex deadline root");
}

#[tokio::test]
async fn enabled_server_recovery_is_bounded_background_work() {
    let root = root("background-recovery");
    fs::create_dir_all(&root).expect("create background recovery root");
    let mut test_limits = limits();
    test_limits.initialize_timeout = Duration::from_millis(25);
    test_limits.request_timeout = Duration::from_millis(25);
    let supervisor = McpSupervisor::new(
        DesktopSessionStore::in_memory().expect("background recovery session store"),
        root.clone(),
        None,
        test_limits,
    )
    .expect("background recovery supervisor");
    let active_scope = scope();
    supervisor
        .create_server(
            &active_scope,
            McpServerDefinitionInput {
                name: "bad-recovery".to_string(),
                description: None,
                transport: McpTransport::Http,
                command: vec!["http://127.0.0.1:9/mcp".to_string()],
                cwd: None,
                vault_env_refs: BTreeMap::new(),
                enabled: true,
            },
            "create-bad-recovery",
        )
        .expect("create bad recovery server");
    let started = tokio::time::Instant::now();
    supervisor
        .recover_all_enabled()
        .await
        .expect("schedule enabled server recovery");
    assert!(started.elapsed() < Duration::from_millis(20));
    tokio::time::sleep(Duration::from_millis(100)).await;
    fs::remove_dir_all(root).expect("remove background recovery root");
}

#[tokio::test]
async fn local_runtime_listener_starts_before_bad_remote_recovery_finishes() {
    let root = root("listener-before-recovery");
    let app_data = root.join("app-data");
    let workspace = root.join("workspace");
    fs::create_dir_all(&app_data).expect("create listener app data");
    fs::create_dir_all(&workspace).expect("create listener workspace");
    let stalled_remote = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind stalled startup remote");
    let stalled_address = stalled_remote
        .local_addr()
        .expect("stalled startup remote address");
    let stalled_task = tokio::spawn(async move {
        let (_stream, _) = stalled_remote
            .accept()
            .await
            .expect("accept stalled startup remote");
        std::future::pending::<()>().await;
    });
    let database = app_data.join("agistack-desktop-sessions.db");
    let seeder = McpSupervisor::new(
        DesktopSessionStore::open(&database).expect("listener seed session store"),
        workspace.clone(),
        None,
        limits(),
    )
    .expect("listener seed supervisor");
    let server = seeder
        .create_server(
            &scope(),
            McpServerDefinitionInput {
                name: "bad-startup-remote".to_string(),
                description: None,
                transport: McpTransport::Http,
                command: vec![format!("http://{stalled_address}/mcp")],
                cwd: None,
                vault_env_refs: BTreeMap::new(),
                enabled: true,
            },
            "create-bad-startup-remote",
        )
        .expect("seed bad startup remote");
    seeder
        .store
        .record_tools_and_apps(
            &server,
            &[json!({
                "name": "render",
                "_meta": {"ui/resourceUri": "ui://bad-startup-remote/index.html"},
            })],
        )
        .expect("seed previously healthy startup app");
    drop(seeder);

    let vault = ApplicationCredentialVault::open(&app_data).expect("listener application vault");
    let started = tokio::time::Instant::now();
    let runtime = tokio::time::timeout(
        Duration::from_secs(2),
        LocalRuntimeService::start(app_data, workspace, vault),
    )
    .await
    .expect("local runtime startup deadline")
    .expect("start local runtime with bad remote");
    assert!(started.elapsed() < Duration::from_secs(5));
    let url = Url::parse(&runtime.status().api_base_url).expect("parse local runtime URL");
    let address = (
        url.host_str().expect("local runtime host"),
        url.port().expect("local runtime port"),
    );
    tokio::net::TcpStream::connect(address)
        .await
        .expect("listener must accept connections before recovery completes");
    let health = runtime
        .state
        .mcp_supervisor
        .health(&scope(), &server.id)
        .expect("startup recovery health");
    assert_eq!(health.status, "starting");
    assert_eq!(
        health.reason_code.as_deref(),
        Some("local_mcp_recovery_pending")
    );
    assert_eq!(
        runtime
            .state
            .mcp_supervisor
            .list_apps(&scope())
            .expect("startup recovery apps")[0]
            .status,
        "starting"
    );
    stalled_task.abort();
    let mut failed_health = None;
    for _ in 0..50 {
        let health = runtime
            .state
            .mcp_supervisor
            .health(&scope(), &server.id)
            .expect("failed startup recovery health");
        if health.status == "error" {
            failed_health = Some(health);
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let failed_health = failed_health.expect("failed recovery must become a structured error");
    assert!(failed_health.reason_code.is_some());
    assert_ne!(
        failed_health.reason_code.as_deref(),
        Some("local_mcp_recovery_pending")
    );
    assert_eq!(
        runtime
            .state
            .mcp_supervisor
            .list_apps(&scope())
            .expect("failed startup recovery apps")[0]
            .status,
        "error"
    );
    runtime.shutdown().await;
    fs::remove_dir_all(root).expect("remove listener startup root");
}

#[tokio::test]
async fn websocket_connection_falls_back_across_ordered_dual_stack_addresses() {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind fallback listener");
    let live_address = listener.local_addr().expect("fallback address");
    let unused_v6 = SocketAddr::from_str("[::1]:9").expect("unavailable IPv6 address");
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.expect("accept fallback client");
        accept_async(stream).await.expect("fallback handshake")
    });
    let endpoint = ResolvedEndpoint {
        url: Url::parse(&format!("ws://localhost:{}/mcp", live_address.port()))
            .expect("fallback URL"),
        host: "localhost".to_string(),
        addresses: vec![unused_v6, live_address],
    };
    let socket = connect_websocket(&endpoint, &reqwest::header::HeaderMap::new(), limits())
        .await
        .expect("fall back to reachable address");
    drop(socket);
    server.await.expect("fallback server task");
}

#[tokio::test]
async fn streamable_http_reset_deletes_session_and_does_not_block_on_delete_failure() {
    for (label, delete_delay) in [
        ("delete-success", Duration::ZERO),
        ("delete-timeout", Duration::from_millis(500)),
    ] {
        let harness = HttpSessionHarness::spawn(delete_delay).await;
        let mut runtime = HttpRuntime::new();
        let mut test_limits = limits();
        test_limits.request_timeout = Duration::from_millis(50);
        let first = remote_server(harness.url.clone(), 1);
        runtime
            .ensure_initialized(&first, None, test_limits)
            .await
            .expect("initialize HTTP session");
        let second = remote_server(harness.url.clone(), 2);
        let started = tokio::time::Instant::now();
        runtime
            .ensure_initialized(&second, None, test_limits)
            .await
            .expect("reinitialize after bounded DELETE");
        assert_eq!(harness.deletes.load(Ordering::SeqCst), 1, "{label}");
        assert!(started.elapsed() < Duration::from_millis(300), "{label}");
    }
}

#[tokio::test]
async fn websocket_enforces_frame_and_message_limits_in_the_protocol_layer() {
    for (label, frame_limit, message_limit) in
        [("frame-limit", 512, 4096), ("message-limit", 4096, 512)]
    {
        let harness = WebSocketHarness::spawn(WebSocketBehavior::Oversized(2048)).await;
        let mut test_limits = limits();
        test_limits.max_frame_bytes = frame_limit;
        test_limits.max_aggregate_bytes = message_limit;
        let (root, supervisor, active_scope, server_id) =
            websocket_supervisor(label, &harness, test_limits);
        let error = supervisor
            .list_tools(&active_scope, &server_id)
            .await
            .expect_err("oversized WebSocket payload");
        assert_eq!(error.reason_code(), "local_mcp_response_too_large");
        drop(supervisor);
        fs::remove_dir_all(root).expect("remove WebSocket limit root");
    }
}

#[tokio::test]
async fn websocket_request_timeout_bounds_a_stalled_send_and_receive_cycle() {
    let entered = Arc::new(Notify::new());
    let harness = WebSocketHarness::spawn(WebSocketBehavior::StallAfterInitialization {
        entered: Arc::clone(&entered),
    })
    .await;
    let mut test_limits = limits();
    test_limits.request_timeout = Duration::from_millis(75);
    test_limits.max_request_bytes = 16 * 1024 * 1024;
    let request_timeout = test_limits.request_timeout;
    let (root, supervisor, active_scope, server_id) =
        websocket_supervisor("stalled-send", &harness, test_limits);
    let call_supervisor = Arc::clone(&supervisor);
    let call_scope = active_scope.clone();
    let call_server_id = server_id.clone();
    let call = tokio::spawn(async move {
        call_supervisor
            .call_tool(
                &call_scope,
                &call_server_id,
                "echo",
                json!({"payload": "x".repeat(8 * 1024 * 1024)}),
                "stalled-send-key",
            )
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), entered.notified())
        .await
        .expect("WebSocket harness must enter the protocol stall");
    tokio::time::pause();
    tokio::task::yield_now().await;
    tokio::time::advance(request_timeout.saturating_add(Duration::from_millis(1))).await;
    let error = call
        .await
        .expect("stalled tool-call task")
        .expect_err("stalled WebSocket send must time out");
    assert_eq!(error.reason_code(), "local_mcp_tool_call_indeterminate");
    let replay_error = supervisor
        .call_tool(
            &active_scope,
            &server_id,
            "echo",
            json!({"payload": "x".repeat(8 * 1024 * 1024)}),
            "stalled-send-key",
        )
        .await
        .expect_err("indeterminate tool call must never be replayed");
    assert_eq!(
        replay_error.reason_code(),
        "local_mcp_tool_call_indeterminate"
    );
    assert_eq!(
        harness.calls.load(Ordering::SeqCst),
        0,
        "an indeterminate call must not reach or replay tools/call after the protocol stall"
    );
    drop(supervisor);
    fs::remove_dir_all(root).expect("remove stalled-send root");
}

#[tokio::test]
async fn concurrent_idempotent_tool_calls_reserve_once_and_replay_the_receipt() {
    let entered = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let harness = WebSocketHarness::spawn(WebSocketBehavior::BlockTool {
        entered: entered.clone(),
        release: release.clone(),
    })
    .await;
    let (root, supervisor, active_scope, server_id) =
        websocket_supervisor("concurrent-reserve", &harness, limits());
    let first_supervisor = supervisor.clone();
    let first_scope = active_scope.clone();
    let first_server_id = server_id.clone();
    let first = tokio::spawn(async move {
        first_supervisor
            .call_tool(
                &first_scope,
                &first_server_id,
                "echo",
                json!({"value": 1}),
                "concurrent-key",
            )
            .await
    });
    entered.wait().await;
    let second_supervisor = supervisor.clone();
    let second_scope = active_scope.clone();
    let second_server_id = server_id.clone();
    let second = tokio::spawn(async move {
        second_supervisor
            .call_tool(
                &second_scope,
                &second_server_id,
                "echo",
                json!({"value": 1}),
                "concurrent-key",
            )
            .await
    });
    tokio::time::sleep(Duration::from_millis(30)).await;
    release.wait().await;
    let first = first.await.expect("first call task").expect("first call");
    let second = second
        .await
        .expect("second call task")
        .expect("second replay");
    assert!(!first.duplicate);
    assert!(second.duplicate);
    assert_eq!(harness.calls.load(Ordering::SeqCst), 1);
    drop(supervisor);
    fs::remove_dir_all(root).expect("remove concurrent reserve root");
}

#[tokio::test]
async fn pending_tool_call_returns_structured_in_progress_without_remote_reexecution() {
    let entered = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let harness = WebSocketHarness::spawn(WebSocketBehavior::BlockTool {
        entered: entered.clone(),
        release: release.clone(),
    })
    .await;
    let mut test_limits = limits();
    test_limits.tool_call_wait_timeout = Duration::from_millis(40);
    let (root, supervisor, active_scope, server_id) =
        websocket_supervisor("pending-call", &harness, test_limits);
    let first_supervisor = supervisor.clone();
    let first_scope = active_scope.clone();
    let first_server_id = server_id.clone();
    let first = tokio::spawn(async move {
        first_supervisor
            .call_tool(
                &first_scope,
                &first_server_id,
                "echo",
                json!({"value": 1}),
                "pending-key",
            )
            .await
    });
    entered.wait().await;
    let error = supervisor
        .call_tool(
            &active_scope,
            &server_id,
            "echo",
            json!({"value": 1}),
            "pending-key",
        )
        .await
        .expect_err("pending duplicate must be bounded");
    assert_eq!(error.reason_code(), "local_mcp_tool_call_in_progress");
    assert_eq!(harness.calls.load(Ordering::SeqCst), 1);
    release.wait().await;
    first
        .await
        .expect("first pending task")
        .expect("first call");
    drop(supervisor);
    fs::remove_dir_all(root).expect("remove pending call root");
}

#[test]
fn expired_pre_dispatch_lease_is_recovered_and_fences_the_stale_owner() {
    let root = root("lease-recovery");
    fs::create_dir_all(&root).expect("create lease recovery root");
    let database = root.join("desktop.db");
    let active_scope = scope();
    let first_store =
        McpStore::new(DesktopSessionStore::open(&database).expect("first lease session store"))
            .expect("first MCP store");
    let stale = match first_store
        .reserve_tool_call(
            &active_scope,
            "recovery-key",
            "request-hash",
            "server-id",
            1_000,
            Duration::from_millis(10),
        )
        .expect("reserve first lease")
    {
        ToolCallReservation::Acquired(lease) => lease,
        _ => panic!("first lease must be acquired"),
    };
    drop(first_store);

    let reopened =
        McpStore::new(DesktopSessionStore::open(&database).expect("reopened lease store"))
            .expect("reopened MCP store");
    let current = match reopened
        .reserve_tool_call(
            &active_scope,
            "recovery-key",
            "request-hash",
            "server-id",
            1_011,
            Duration::from_millis(10),
        )
        .expect("recover expired lease")
    {
        ToolCallReservation::Acquired(lease) => lease,
        _ => panic!("expired lease must be acquired"),
    };
    let stale_error = reopened
        .mark_tool_call_dispatched(&stale, 1_012)
        .expect_err("stale owner must be fenced");
    assert_eq!(stale_error.reason_code(), "local_mcp_tool_call_lease_lost");
    let response = json!({"content": [{"type": "text", "text": "ok"}], "isError": false});
    reopened
        .mark_tool_call_dispatched(&current, 1_012)
        .expect("mark current lease dispatched");
    reopened
        .complete_tool_call(&current, &response)
        .expect("complete current lease");
    match reopened
        .reserve_tool_call(
            &active_scope,
            "recovery-key",
            "request-hash",
            "server-id",
            1_012,
            Duration::from_millis(10),
        )
        .expect("replay completed lease")
    {
        ToolCallReservation::Replay(value) => assert_eq!(value, response),
        _ => panic!("completed lease must replay"),
    }
    drop(reopened);
    fs::remove_dir_all(root).expect("remove lease recovery root");
}

#[test]
fn dispatched_tool_call_is_indeterminate_after_restart_and_never_taken_over() {
    let root = root("indeterminate-restart");
    fs::create_dir_all(&root).expect("create indeterminate restart root");
    let database = root.join("desktop.db");
    let active_scope = scope();
    let first_store = McpStore::new(
        DesktopSessionStore::open(&database).expect("first indeterminate session store"),
    )
    .expect("first MCP store");
    let dispatched = match first_store
        .reserve_tool_call(
            &active_scope,
            "indeterminate-key",
            "request-hash",
            "server-id",
            1_000,
            Duration::from_millis(10),
        )
        .expect("reserve pre-dispatch lease")
    {
        ToolCallReservation::Acquired(lease) => lease,
        _ => panic!("first lease must be acquired"),
    };
    first_store
        .mark_tool_call_dispatched(&dispatched, 1_001)
        .expect("mark persisted call dispatched");
    drop(first_store);

    let reopened = McpStore::new(
        DesktopSessionStore::open(&database).expect("reopened indeterminate session store"),
    )
    .expect("reopened MCP store");
    match reopened
        .reserve_tool_call(
            &active_scope,
            "indeterminate-key",
            "request-hash",
            "server-id",
            2_000,
            Duration::from_millis(10),
        )
        .expect("read dispatched lease after restart")
    {
        ToolCallReservation::Indeterminate => {}
        _ => panic!("dispatched lease must be indeterminate after owner expiry"),
    }
    match reopened
        .reserve_tool_call(
            &active_scope,
            "indeterminate-key",
            "request-hash",
            "server-id",
            3_000,
            Duration::from_millis(10),
        )
        .expect("repeat indeterminate reservation")
    {
        ToolCallReservation::Indeterminate => {}
        _ => panic!("indeterminate lease must never be taken over"),
    }
    drop(reopened);
    fs::remove_dir_all(root).expect("remove indeterminate restart root");
}
