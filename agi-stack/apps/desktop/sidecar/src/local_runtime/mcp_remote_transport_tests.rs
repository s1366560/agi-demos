use std::{
    collections::BTreeMap,
    convert::Infallible,
    fs,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    },
    time::Duration,
};

use axum::{
    body::{Body, Bytes},
    extract::{
        ws::{Message, WebSocket},
        State, WebSocketUpgrade,
    },
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{
        sse::{Event, Sse},
        IntoResponse, Response,
    },
    routing::{get, post},
    Json, Router,
};
use futures_util::{stream, StreamExt};
use serde_json::{json, Value};
use tokio::{
    net::TcpListener,
    sync::{mpsc, Mutex},
    task::JoinHandle,
};
use uuid::Uuid;

use crate::application_vault::ApplicationCredentialVault;

use super::{
    mcp_supervisor::{
        McpScope, McpServerDefinitionInput, McpSupervisor, McpTransport, SupervisorLimits,
    },
    DesktopSessionStore,
};

const AUTHORIZATION_VALUE: &str = "Bearer remote-mcp-test-secret";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum MockMode {
    Normal,
    Timeout,
    Malformed,
    Oversized,
    HttpStatus,
    Redirect,
    DisconnectOnce,
    Elicitation,
}

#[derive(Clone)]
struct MockState {
    mode: MockMode,
    legacy_events: Arc<Mutex<Option<mpsc::Sender<Value>>>>,
    calls: Arc<AtomicUsize>,
    connections: Arc<AtomicUsize>,
    elicitation_rejected: Arc<AtomicBool>,
}

struct MockRemoteServer {
    origin: String,
    state: MockState,
    task: JoinHandle<()>,
}

impl MockRemoteServer {
    async fn spawn(mode: MockMode) -> Self {
        let state = MockState {
            mode,
            legacy_events: Arc::new(Mutex::new(None)),
            calls: Arc::new(AtomicUsize::new(0)),
            connections: Arc::new(AtomicUsize::new(0)),
            elicitation_rejected: Arc::new(AtomicBool::new(false)),
        };
        let app = Router::new()
            .route("/mcp", post(streamable_http))
            .route("/redirect", post(streamable_http))
            .route("/sse", get(legacy_sse))
            .route("/legacy-message", post(legacy_message))
            .route("/ws", get(websocket_upgrade))
            .with_state(state.clone());
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind mock MCP listener");
        let address = listener.local_addr().expect("mock MCP address");
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("serve mock remote MCP");
        });
        Self {
            origin: format!("http://{address}"),
            state,
            task,
        }
    }

    fn http_url(&self) -> String {
        format!("{}/mcp", self.origin)
    }

    fn redirect_url(&self) -> String {
        format!("{}/redirect", self.origin)
    }

    fn sse_url(&self) -> String {
        format!("{}/sse", self.origin)
    }

    fn websocket_url(&self) -> String {
        self.origin.replacen("http://", "ws://", 1) + "/ws"
    }
}

impl Drop for MockRemoteServer {
    fn drop(&mut self) {
        self.task.abort();
    }
}

fn authorized(headers: &HeaderMap) -> bool {
    headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        == Some(AUTHORIZATION_VALUE)
}

async fn streamable_http(
    State(state): State<MockState>,
    headers: HeaderMap,
    Json(request): Json<Value>,
) -> Response {
    if !authorized(&headers) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    match state.mode {
        MockMode::Timeout => {
            tokio::time::sleep(Duration::from_secs(5)).await;
            return StatusCode::GATEWAY_TIMEOUT.into_response();
        }
        MockMode::HttpStatus => return StatusCode::BAD_GATEWAY.into_response(),
        MockMode::Redirect => {
            return (
                StatusCode::TEMPORARY_REDIRECT,
                [(header::LOCATION, "http://127.0.0.1:9/redirect-target")],
            )
                .into_response();
        }
        MockMode::Malformed => {
            return Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from("{not-json}"))
                .expect("malformed response");
        }
        MockMode::Oversized => {
            return Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from("x".repeat(128 * 1024)))
                .expect("oversized response");
        }
        MockMode::Normal | MockMode::DisconnectOnce | MockMode::Elicitation => {}
    }

    let method = request.get("method").and_then(Value::as_str);
    if method != Some("initialize")
        && (headers
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok())
            != Some("mock-session")
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

    let response = rpc_response(&state, &request, "2025-03-26");
    if state.mode == MockMode::Elicitation {
        let elicitation = json!({
            "jsonrpc": "2.0",
            "id": 900,
            "method": "elicitation/create",
            "params": {
                "message": "Provide a secret",
                "requestedSchema": {
                    "type": "object",
                    "properties": {"secret": {"type": "string"}}
                }
            }
        });
        return sse_response([elicitation, response]);
    }
    if method == Some("resources/read") {
        return open_sse_response(response);
    }

    let mut response = (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "application/json")],
        response.to_string(),
    )
        .into_response();
    if method == Some("initialize") {
        response
            .headers_mut()
            .insert("mcp-session-id", HeaderValue::from_static("mock-session"));
    }
    response
}

fn sse_response(messages: impl IntoIterator<Item = Value>) -> Response {
    let body = messages
        .into_iter()
        .enumerate()
        .map(|(index, message)| format!("id: {index}\nevent: message\ndata: {message}\n\n"))
        .collect::<String>();
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "text/event-stream")
        .body(Body::from(body))
        .expect("SSE response")
}

fn open_sse_response(message: Value) -> Response {
    let event = Bytes::from(format!("event: message\ndata: {message}\n\n"));
    let first = stream::once(async move { Ok::<Bytes, Infallible>(event) });
    let open = stream::pending::<Result<Bytes, Infallible>>();
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "text/event-stream")
        .body(Body::from_stream(first.chain(open)))
        .expect("open SSE response")
}

async fn legacy_sse(State(state): State<MockState>, headers: HeaderMap) -> Response {
    if !authorized(&headers) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    state.connections.fetch_add(1, Ordering::SeqCst);
    let (sender, receiver) = mpsc::channel::<Value>(16);
    *state.legacy_events.lock().await = Some(sender);
    let endpoint = Event::default()
        .event("endpoint")
        .data("/legacy-message?session=opaque");
    let initial = stream::once(async move { Ok::<Event, Infallible>(endpoint) });
    let events = stream::unfold(receiver, |mut receiver| async move {
        receiver.recv().await.map(|message| {
            (
                Ok::<Event, Infallible>(
                    Event::default().event("message").data(message.to_string()),
                ),
                receiver,
            )
        })
    });
    Sse::new(initial.chain(events)).into_response()
}

async fn legacy_message(
    State(state): State<MockState>,
    headers: HeaderMap,
    Json(request): Json<Value>,
) -> Response {
    if !authorized(&headers) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Some(sender) = state.legacy_events.lock().await.clone() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    if request.get("id").is_some() {
        if state.mode == MockMode::Elicitation {
            let _ = sender
                .send(json!({
                    "jsonrpc": "2.0",
                    "id": 901,
                    "method": "elicitation/create",
                    "params": {
                        "message": "Provide a field",
                        "requestedSchema": {
                            "type": "object",
                            "properties": {"field": {"type": "string"}}
                        }
                    }
                }))
                .await;
        }
        let _ = sender
            .send(rpc_response(&state, &request, "2024-11-05"))
            .await;
    }
    StatusCode::ACCEPTED.into_response()
}

async fn websocket_upgrade(
    ws: WebSocketUpgrade,
    State(state): State<MockState>,
    headers: HeaderMap,
) -> Response {
    if !authorized(&headers) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    ws.on_upgrade(move |socket| websocket_connection(socket, state))
        .into_response()
}

async fn websocket_connection(mut socket: WebSocket, state: MockState) {
    let connection = state.connections.fetch_add(1, Ordering::SeqCst);
    while let Some(Ok(message)) = socket.next().await {
        let Message::Text(text) = message else {
            continue;
        };
        let Ok(request) = serde_json::from_str::<Value>(&text) else {
            continue;
        };
        if request.get("method").is_none() && request.get("id").and_then(Value::as_u64) == Some(902)
        {
            if request.get("error").is_some() {
                state.elicitation_rejected.store(true, Ordering::SeqCst);
            }
            continue;
        }
        let method = request.get("method").and_then(Value::as_str);
        if method == Some("notifications/initialized") {
            continue;
        }
        if state.mode == MockMode::DisconnectOnce && connection == 0 && method == Some("tools/list")
        {
            let _ = socket.send(Message::Close(None)).await;
            return;
        }
        if state.mode == MockMode::Elicitation && method == Some("tools/list") {
            let elicitation = json!({
                "jsonrpc": "2.0",
                "id": 902,
                "method": "elicitation/create",
                "params": {
                    "message": "Provide a field",
                    "requestedSchema": {
                        "type": "object",
                        "properties": {"field": {"type": "string"}}
                    }
                }
            });
            let _ = socket.send(Message::Text(elicitation.to_string())).await;
            continue;
        }
        if method == Some("tools/list") {
            let notification = json!({
                "jsonrpc": "2.0",
                "method": "notifications/tools/list_changed",
                "params": {}
            });
            let wrong_id = json!({
                "jsonrpc": "2.0",
                "id": 8_888,
                "result": {"tools": []}
            });
            let _ = socket.send(Message::Text(notification.to_string())).await;
            let _ = socket.send(Message::Text(wrong_id.to_string())).await;
        }
        let response = rpc_response(&state, &request, "2025-03-26");
        let _ = socket.send(Message::Text(response.to_string())).await;
    }
}

fn rpc_response(state: &MockState, request: &Value, protocol_version: &str) -> Value {
    let method = request.get("method").and_then(Value::as_str);
    let result = match method {
        Some("initialize") => json!({
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "remote-mock", "version": "1.0.0"},
        }),
        Some("tools/list") => json!({
            "tools": [{
                "name": "echo",
                "description": "Echo structured input",
                "inputSchema": {"type": "object"},
                "_meta": {"ui/resourceUri": "ui://remote-mock/index.html"},
            }]
        }),
        Some("tools/call") => {
            state.calls.fetch_add(1, Ordering::SeqCst);
            json!({
                "content": [{
                    "type": "text",
                    "text": request.pointer("/params/arguments").cloned().unwrap_or_else(|| json!({})).to_string(),
                }],
                "isError": false,
            })
        }
        Some("resources/list") => json!({
            "resources": [{
                "uri": "ui://remote-mock/index.html",
                "name": "Remote App",
                "mimeType": "text/html;profile=mcp-app",
            }]
        }),
        Some("resources/read") => json!({
            "contents": [{
                "uri": request.pointer("/params/uri").cloned().unwrap_or(Value::Null),
                "mimeType": "text/html;profile=mcp-app",
                "text": "<main>remote app</main>",
            }]
        }),
        _ => json!({}),
    };
    json!({
        "jsonrpc": "2.0",
        "id": request.get("id").cloned().unwrap_or(Value::Null),
        "result": result,
    })
}

fn root(label: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!("agistack-mcp-remote-{label}-{}", Uuid::new_v4()))
}

fn scope() -> McpScope {
    McpScope {
        tenant_id: "local".to_string(),
        project_id: "local-project".to_string(),
    }
}

fn definition(name: &str, transport: McpTransport, endpoint: String) -> McpServerDefinitionInput {
    McpServerDefinitionInput {
        name: name.to_string(),
        description: Some("remote MCP integration test".to_string()),
        transport,
        command: vec![endpoint],
        cwd: None,
        vault_env_refs: BTreeMap::from([(
            "Authorization".to_string(),
            "mcp.remote.authorization".to_string(),
        )]),
        enabled: true,
    }
}

fn limits() -> SupervisorLimits {
    SupervisorLimits {
        request_timeout: Duration::from_millis(500),
        initialize_timeout: Duration::from_millis(500),
        retry_base: Duration::from_millis(10),
        retry_max: Duration::from_millis(20),
        max_request_bytes: 32 * 1024,
        max_response_bytes: 32 * 1024,
        max_frame_bytes: 16 * 1024,
        max_aggregate_bytes: 32 * 1024,
        tool_call_lease_duration: Duration::from_secs(4),
        tool_call_wait_timeout: Duration::from_millis(500),
        tool_call_poll_interval: Duration::from_millis(10),
    }
}

fn vault(root: &std::path::Path) -> ApplicationCredentialVault {
    let vault = ApplicationCredentialVault::open(root).expect("test application vault");
    vault
        .put("mcp.remote.authorization", AUTHORIZATION_VALUE)
        .expect("store remote MCP authorization");
    vault
}

#[tokio::test]
async fn remote_transports_round_trip_tools_resources_health_and_restart_recovery() {
    let root = root("round-trip");
    fs::create_dir_all(&root).expect("create remote MCP root");
    let database = root.join("desktop.db");
    let mock = MockRemoteServer::spawn(MockMode::Normal).await;
    let active_scope = scope();
    let mut server_ids = Vec::new();

    {
        let store = DesktopSessionStore::open(&database).expect("session store");
        let supervisor = McpSupervisor::new(store, root.clone(), Some(vault(&root)), limits())
            .expect("remote MCP supervisor");
        for (name, transport, endpoint) in [
            ("http", McpTransport::Http, mock.http_url()),
            ("sse", McpTransport::Sse, mock.sse_url()),
            ("websocket", McpTransport::Websocket, mock.websocket_url()),
        ] {
            let server = supervisor
                .create_server(
                    &active_scope,
                    definition(name, transport, endpoint),
                    &format!("create-{name}"),
                )
                .expect("create remote MCP server");
            server_ids.push(server.id.clone());
            let tools = supervisor
                .list_tools(&active_scope, &server.id)
                .await
                .expect("list remote MCP tools");
            assert_eq!(tools[0]["name"], "echo");
            let call = supervisor
                .call_tool(
                    &active_scope,
                    &server.id,
                    "echo",
                    json!({"transport": name}),
                    Some(&format!("call-{name}")),
                )
                .await
                .expect("call remote MCP tool");
            assert!(!call.duplicate);
            assert_eq!(call.result["isError"], false);
            let resources = supervisor
                .list_resources(&active_scope, Some(&server.id))
                .await
                .expect("list remote MCP resources");
            assert_eq!(resources[0]["uri"], "ui://remote-mock/index.html");
            let contents = supervisor
                .read_resource(&active_scope, &server.id, "ui://remote-mock/index.html")
                .await
                .expect("read remote MCP resource");
            assert_eq!(contents[0]["text"], "<main>remote app</main>");
            let health = supervisor
                .health(&active_scope, &server.id)
                .expect("remote MCP health");
            assert_eq!(health.status, "healthy");
        }
    }

    let reopened = DesktopSessionStore::open(&database).expect("reopen session store");
    let supervisor = McpSupervisor::new(reopened, root.clone(), Some(vault(&root)), limits())
        .expect("reopened remote MCP supervisor");
    supervisor
        .recover_all_enabled()
        .await
        .expect("recover persisted remote MCP definitions");
    for server_id in server_ids {
        assert!(!supervisor
            .list_tools(&active_scope, &server_id)
            .await
            .expect("list tools after restart")
            .is_empty());
    }

    fs::remove_dir_all(root).expect("remove remote MCP root");
}

#[tokio::test]
async fn remote_transports_fail_closed_for_timeout_status_redirect_malformed_and_oversized() {
    let root = root("failures");
    fs::create_dir_all(&root).expect("create remote MCP root");
    let active_scope = scope();
    let supervisor = McpSupervisor::new(
        DesktopSessionStore::in_memory().expect("session store"),
        root.clone(),
        Some(vault(&root)),
        limits(),
    )
    .expect("remote MCP supervisor");

    for (name, mode, expected_reason) in [
        ("timeout", MockMode::Timeout, "local_mcp_request_timeout"),
        (
            "status",
            MockMode::HttpStatus,
            "local_mcp_http_status_error",
        ),
        (
            "malformed",
            MockMode::Malformed,
            "local_mcp_malformed_response",
        ),
        (
            "oversized",
            MockMode::Oversized,
            "local_mcp_response_too_large",
        ),
    ] {
        let mock = MockRemoteServer::spawn(mode).await;
        let server = supervisor
            .create_server(
                &active_scope,
                definition(name, McpTransport::Http, mock.http_url()),
                &format!("create-{name}"),
            )
            .expect("create failing remote MCP server");
        let error = supervisor
            .list_tools(&active_scope, &server.id)
            .await
            .expect_err("remote MCP request must fail closed");
        assert_eq!(error.reason_code(), expected_reason);
    }

    let redirect = MockRemoteServer::spawn(MockMode::Redirect).await;
    let server = supervisor
        .create_server(
            &active_scope,
            definition("redirect", McpTransport::Http, redirect.redirect_url()),
            "create-redirect",
        )
        .expect("create redirecting MCP server");
    let error = supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .expect_err("remote MCP redirect must not be followed");
    assert_eq!(error.reason_code(), "local_mcp_redirect_rejected");

    let insecure = supervisor.create_server(
        &active_scope,
        definition(
            "insecure",
            McpTransport::Http,
            "http://example.com/mcp".to_string(),
        ),
        "create-insecure",
    );
    assert_eq!(
        insecure
            .expect_err("non-loopback cleartext MCP endpoint")
            .reason_code(),
        "local_mcp_endpoint_policy_rejected"
    );
    fs::remove_dir_all(root).expect("remove remote MCP root");
}

#[tokio::test]
async fn websocket_reconnects_after_disconnect_and_correlates_notifications_by_request_id() {
    let root = root("websocket-reconnect");
    fs::create_dir_all(&root).expect("create remote MCP root");
    let mock = MockRemoteServer::spawn(MockMode::DisconnectOnce).await;
    let active_scope = scope();
    let supervisor = McpSupervisor::new(
        DesktopSessionStore::in_memory().expect("session store"),
        root.clone(),
        Some(vault(&root)),
        limits(),
    )
    .expect("remote MCP supervisor");
    let server = supervisor
        .create_server(
            &active_scope,
            definition(
                "websocket-reconnect",
                McpTransport::Websocket,
                mock.websocket_url(),
            ),
            "create-websocket-reconnect",
        )
        .expect("create WebSocket MCP server");

    let first = supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .expect_err("first disconnected request");
    assert_eq!(first.reason_code(), "local_mcp_connection_closed");
    tokio::time::sleep(Duration::from_millis(25)).await;
    let tools = supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .expect("reconnect WebSocket MCP server");
    assert_eq!(tools[0]["name"], "echo");
    assert!(mock.state.connections.load(Ordering::SeqCst) >= 2);

    let first = supervisor
        .call_tool(
            &active_scope,
            &server.id,
            "echo",
            json!({"value": 1}),
            Some("same-remote-key"),
        )
        .await
        .expect("first idempotent remote call");
    assert!(!first.duplicate);
    let replay = supervisor
        .call_tool(
            &active_scope,
            &server.id,
            "echo",
            json!({"value": 1}),
            Some("same-remote-key"),
        )
        .await
        .expect("replay remote call");
    assert!(replay.duplicate);
    assert_eq!(mock.state.calls.load(Ordering::SeqCst), 1);
    let conflict = supervisor
        .call_tool(
            &active_scope,
            &server.id,
            "echo",
            json!({"value": 2}),
            Some("same-remote-key"),
        )
        .await
        .expect_err("conflicting remote replay");
    assert_eq!(conflict.reason_code(), "local_mcp_idempotency_conflict");
    fs::remove_dir_all(root).expect("remove remote MCP root");
}

#[tokio::test]
async fn remote_elicitation_is_rejected_when_no_authoritative_user_response_bridge_exists() {
    let root = root("elicitation");
    fs::create_dir_all(&root).expect("create remote MCP root");
    let mock = MockRemoteServer::spawn(MockMode::Elicitation).await;
    let active_scope = scope();
    let supervisor = McpSupervisor::new(
        DesktopSessionStore::in_memory().expect("session store"),
        root.clone(),
        Some(vault(&root)),
        limits(),
    )
    .expect("remote MCP supervisor");
    let server = supervisor
        .create_server(
            &active_scope,
            definition("elicitation", McpTransport::Websocket, mock.websocket_url()),
            "create-elicitation",
        )
        .expect("create elicitation MCP server");
    let error = supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .expect_err("elicitation must fail closed");
    assert_eq!(
        error.reason_code(),
        "local_mcp_elicitation_bridge_unavailable"
    );
    tokio::time::sleep(Duration::from_millis(25)).await;
    assert!(mock.state.elicitation_rejected.load(Ordering::SeqCst));
    let health = supervisor
        .health(&active_scope, &server.id)
        .expect("elicitation health");
    assert_eq!(
        health.reason_code.as_deref(),
        Some("local_mcp_elicitation_bridge_unavailable")
    );
    fs::remove_dir_all(root).expect("remove remote MCP root");
}
