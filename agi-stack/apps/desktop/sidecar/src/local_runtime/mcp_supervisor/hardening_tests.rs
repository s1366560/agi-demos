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
use tokio::{net::TcpListener, sync::Barrier, task::JoinHandle};
use tokio_tungstenite::{accept_async, tungstenite::Message};
use url::Url;
use uuid::Uuid;

use super::{
    http::HttpRuntime,
    remote_common::{
        is_globally_routable, validate_remote_url, validate_resolved_addresses, ResolvedEndpoint,
    },
    store::McpStore,
    tool_call_lease::ToolCallReservation,
    websocket::connect_websocket,
    McpScope, McpServerDefinition, McpServerDefinitionInput, McpSupervisor, McpTransport,
    SupervisorLimits,
};
use crate::local_runtime::DesktopSessionStore;

enum WebSocketBehavior {
    Oversized(usize),
    BlockTool {
        entered: Arc<Barrier>,
        release: Arc<Barrier>,
    },
    StallAfterInitialization,
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
                    if matches!(behavior, WebSocketBehavior::StallAfterInitialization) {
                        tokio::time::sleep(Duration::from_secs(5)).await;
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
    let harness = WebSocketHarness::spawn(WebSocketBehavior::StallAfterInitialization).await;
    let mut test_limits = limits();
    test_limits.request_timeout = Duration::from_millis(75);
    test_limits.max_request_bytes = 16 * 1024 * 1024;
    let (root, supervisor, active_scope, server_id) =
        websocket_supervisor("stalled-send", &harness, test_limits);
    let started = tokio::time::Instant::now();
    let error = supervisor
        .call_tool(
            &active_scope,
            &server_id,
            "echo",
            json!({"payload": "x".repeat(8 * 1024 * 1024)}),
            Some("stalled-send-key"),
        )
        .await
        .expect_err("stalled WebSocket send must time out");
    assert_eq!(error.reason_code(), "local_mcp_request_timeout");
    assert!(started.elapsed() < Duration::from_secs(2));
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
                Some("concurrent-key"),
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
                Some("concurrent-key"),
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
                Some("pending-key"),
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
            Some("pending-key"),
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
fn expired_persisted_lease_is_recovered_and_fences_the_stale_owner() {
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
        .complete_tool_call(&stale, &json!({"content": []}))
        .expect_err("stale owner must be fenced");
    assert_eq!(stale_error.reason_code(), "local_mcp_tool_call_lease_lost");
    let response = json!({"content": [{"type": "text", "text": "ok"}], "isError": false});
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
