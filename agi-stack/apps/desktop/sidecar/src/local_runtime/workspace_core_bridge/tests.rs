use std::sync::{atomic::Ordering, Arc};

use agistack_adapters_device::SqliteCheckpointStore;
use agistack_adapters_local_tools::LocalToolHost;
use agistack_core::agent::react::{ReActControl, RunDirective};
use axum::{
    body::{to_bytes, Body},
    extract::State,
    http::{HeaderMap, Request, StatusCode},
    routing::post,
    Json, Router,
};
use serde_json::{json, Value};
use tokio::sync::{mpsc, Mutex};
use tower::ServiceExt;
use uuid::Uuid;

use super::*;
use crate::local_runtime::{
    local_router, now_iso, resource_registry::ManagedResourceKind,
    session_store::DesktopSessionStore, ConversationCapabilityMode, ConversationRunMode,
    LocalConversation, LocalRuntimeState,
};

fn state() -> Arc<LocalRuntimeState> {
    let root = std::env::temp_dir().join(format!("workspace-core-bridge-{}", Uuid::new_v4()));
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root,
            tool_host,
            checkpoints,
            "launch-token".to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .mock_llm_enabled
        .store(1, std::sync::atomic::Ordering::Release);
    state
}

async fn post_json(app: Router, path: &str, token: &str, body: Value) -> (StatusCode, Value) {
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header(AUTHORIZATION, format!("Bearer {token}"))
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .expect("request"),
        )
        .await
        .expect("response");
    let status = response.status();
    let body = to_bytes(response.into_body(), 1024 * 1024)
        .await
        .expect("response body");
    let value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(&body).into_owned()))
    };
    (status, value)
}

fn install(state: &LocalRuntimeState, core_url: &str) -> u64 {
    install_authority(
        state,
        core_url.to_string(),
        "service-token".to_string(),
        "registry-token".to_string(),
        "provider-token".to_string(),
        "event-token".to_string(),
    )
    .expect("install authority")
}

async fn create_workspace_proxy_server() -> (String, mpsc::Receiver<(HeaderMap, Vec<u8>)>) {
    let (sender, receiver) = mpsc::channel(4);
    async fn respond(
        State(sender): State<mpsc::Sender<(HeaderMap, Vec<u8>)>>,
        headers: HeaderMap,
        body: axum::body::Bytes,
    ) -> Json<Value> {
        sender
            .send((headers, body.to_vec()))
            .await
            .expect("proxy observation receiver");
        Json(json!({
            "id": "local-workspace",
            "service_version": "0.2.0",
            "contract_version": "2.0.0",
            "authority": "local",
            "tenant_id": "local",
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "status": "available",
            "reason_code": null,
            "canonical_read": true,
            "read_surfaces": ["goals", "discussion", "status", "collaboration", "members", "genes", "files", "notes", "topology", "settings"],
            "mutations": {"allowed": true, "revision_guarded": true, "idempotency_guarded": true, "actions": {}},
            "allowed_actions": {}
        }))
    }
    let app = Router::new()
        .fallback(axum::routing::any(respond))
        .with_state(sender);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind proxy server");
    let url = format!("http://{}", listener.local_addr().expect("address"));
    tokio::spawn(async move { axum::serve(listener, app).await.expect("proxy server") });
    (url, receiver)
}

async fn create_status_proxy_server(status: StatusCode) -> String {
    let app = Router::new().fallback(axum::routing::any(move || async move { status }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind status proxy server");
    let url = format!("http://{}", listener.local_addr().expect("address"));
    tokio::spawn(async move {
        axum::serve(listener, app)
            .await
            .expect("status proxy server")
    });
    url
}

type TaskSessionObservation = (String, HeaderMap, Vec<u8>);

#[derive(Clone, Copy)]
enum TaskSessionProxyBehavior {
    Success,
    Failure(StatusCode),
    IdempotencyConflict,
    MalformedSuccess,
}

async fn create_task_session_proxy_server_with(
    behavior: TaskSessionProxyBehavior,
) -> (String, mpsc::Receiver<TaskSessionObservation>) {
    let (sender, receiver) = mpsc::channel(1);
    async fn respond(
        State((sender, behavior)): State<(
            mpsc::Sender<TaskSessionObservation>,
            TaskSessionProxyBehavior,
        )>,
        request: Request<Body>,
    ) -> Response {
        let path = request.uri().path().to_string();
        let headers = request.headers().clone();
        let body = to_bytes(request.into_body(), 1024 * 1024)
            .await
            .expect("task-session body")
            .to_vec();
        let command: Value = serde_json::from_slice(&body).expect("task-session command JSON");
        sender
            .send((path, headers, body.clone()))
            .await
            .expect("proxy observation receiver");
        if let TaskSessionProxyBehavior::Failure(status) = behavior {
            return (status, Json(json!({ "detail": "Core failure" }))).into_response();
        }
        if matches!(behavior, TaskSessionProxyBehavior::IdempotencyConflict) {
            return (
                StatusCode::CONFLICT,
                Json(json!({
                    "code": "TASK_SESSION_IDEMPOTENCY_CONFLICT",
                    "detail": "Core failure",
                })),
            )
                .into_response();
        }
        let mut response = json!({
            "receipt_id": "core-receipt-1",
            "replayed": false,
            "workspace": {
                "id": "local-workspace",
                "tenant_id": "local",
                "project_id": "local-project",
                "name": "Existing workspace",
                "description": null,
                "status": "open",
                "is_archived": false,
                "created_at": "2026-08-13T00:00:00Z",
                "updated_at": "2026-08-13T00:00:00Z",
                "metadata": { "runtime": "local" }
            },
            "initial_message": {
                "id": command["initial_message"]["message_id"],
                "workspace_id": "local-workspace",
                "sender_id": "local-user",
                "sender_type": "human",
                "content": command["initial_message"]["content"],
                "mentions": [],
                "parent_message_id": null,
                "metadata": {
                    "source": "task_session",
                    "conversation_id": command["conversation_id"],
                    "runtime": "workspace_core",
                    "context_items": []
                },
                "created_at": "2026-08-13T00:00:00Z"
            },
            "policy": null,
            "capability_version": "avernet-task-session-v1"
        });
        if matches!(behavior, TaskSessionProxyBehavior::MalformedSuccess) {
            response["initial_message"]["content"] = json!("Unexpected objective");
        }
        Json(response).into_response()
    }
    let app = Router::new()
        .fallback(axum::routing::any(respond))
        .with_state((sender, behavior));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind path proxy server");
    let url = format!("http://{}", listener.local_addr().expect("address"));
    tokio::spawn(async move { axum::serve(listener, app).await.expect("path proxy server") });
    (url, receiver)
}

async fn create_task_session_proxy_server() -> (String, mpsc::Receiver<TaskSessionObservation>) {
    create_task_session_proxy_server_with(TaskSessionProxyBehavior::Success).await
}

type RoutingPolicyObservation = (String, String, HeaderMap, Vec<u8>);

async fn create_routing_policy_proxy_server() -> (String, mpsc::Receiver<RoutingPolicyObservation>)
{
    let (sender, receiver) = mpsc::channel(2);
    async fn respond(
        State(sender): State<mpsc::Sender<RoutingPolicyObservation>>,
        request: Request<Body>,
    ) -> Json<Value> {
        let method = request.method().to_string();
        let uri = request.uri().to_string();
        let headers = request.headers().clone();
        let body = to_bytes(request.into_body(), 1024 * 1024)
            .await
            .expect("routing policy body")
            .to_vec();
        sender
            .send((method, uri, headers, body))
            .await
            .expect("routing policy observation receiver");
        Json(json!({ "proxied": true }))
    }
    let app = Router::new()
        .fallback(axum::routing::any(respond))
        .with_state(sender);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind routing policy proxy server");
    let url = format!("http://{}", listener.local_addr().expect("address"));
    tokio::spawn(async move {
        axum::serve(listener, app)
            .await
            .expect("routing policy server")
    });
    (url, receiver)
}

async fn create_policy_read_server() -> (String, mpsc::Receiver<(String, HeaderMap)>) {
    let (sender, receiver) = mpsc::channel(1);
    async fn respond(
        State(sender): State<mpsc::Sender<(String, HeaderMap)>>,
        request: Request<Body>,
    ) -> Json<Value> {
        sender
            .send((request.uri().path().to_string(), request.headers().clone()))
            .await
            .expect("policy observation receiver");
        Json(json!({
            "tenant_id": "local",
            "project_id": "local-project",
            "workspace_id": "core-only-workspace",
            "revision": 7,
            "roles": { "default": { "provider_id": "provider-1", "model_id": "model-1" } },
            "fallbacks": [],
            "reasoning_effort": "high",
            "permission_mode": "ask",
            "capability_version": "workspace-agent-policy-v1",
            "updated_at": "2026-08-13T00:00:00Z"
        }))
    }
    let app = Router::new()
        .fallback(axum::routing::any(respond))
        .with_state(sender);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind policy read server");
    let url = format!("http://{}", listener.local_addr().expect("address"));
    tokio::spawn(async move {
        axum::serve(listener, app)
            .await
            .expect("policy read server")
    });
    (url, receiver)
}

#[tokio::test]
async fn workspace_proxy_requires_desktop_auth_and_forwards_scope_without_service_token_leak() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_workspace_proxy_server().await;
    install(&state, &core_url);
    let app = local_router(state);
    let path = "/api/v1/tenants/local/projects/local-project/workspaces/local-workspace/collaboration/capabilities";

    let missing_launch = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(path)
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    let missing_session = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(path)
                .header("x-agistack-launch", "launch-token")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    let response = app
        .oneshot(
            Request::builder()
                .uri(path)
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(missing_launch.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(missing_session.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(response.status(), StatusCode::OK);
    let response_text = String::from_utf8(
        to_bytes(response.into_body(), 1024 * 1024)
            .await
            .expect("body")
            .to_vec(),
    )
    .expect("utf8");
    assert!(!response_text.contains("service-token"));
    let (headers, _) = observations.recv().await.expect("forwarded request");
    assert_eq!(
        headers
            .get(AUTHORIZATION)
            .and_then(|value| value.to_str().ok()),
        Some("Bearer service-token")
    );
    assert_eq!(
        headers
            .get("x-memstack-user-id")
            .and_then(|value| value.to_str().ok()),
        Some("local-user")
    );
    assert_eq!(
        headers
            .get("x-memstack-tenant-id")
            .and_then(|value| value.to_str().ok()),
        Some("local")
    );
    assert_eq!(
        headers
            .get("x-memstack-project-membership-role")
            .and_then(|value| value.to_str().ok()),
        Some("owner")
    );
}

#[tokio::test]
async fn workspace_proxy_classifies_transport_failures_without_exposing_request_details() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("reserve closed Workspace Core port");
    let address = listener
        .local_addr()
        .expect("closed Workspace Core address");
    drop(listener);
    let error = reqwest::Client::new()
        .get(format!("http://{address}/workspace"))
        .send()
        .await
        .expect_err("closed port must fail transport");

    assert_eq!(workspace_core_transport_error_kind(&error), "connect");
}

#[tokio::test]
async fn workspace_proxy_forwards_core_only_workspaces_and_rejects_cross_context_paths() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_workspace_proxy_server().await;
    install(&state, &core_url);
    let app = local_router(state);

    let core_only = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/v1/tenants/local/projects/local-project/workspaces/core-only-workspace")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    let workspace_only = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/v1/workspaces/core-only-workspace/tasks")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    let cross_context = app
        .oneshot(
            Request::builder()
                .uri(
                    "/api/v1/tenants/another-tenant/projects/another-project/workspaces/core-only-workspace",
                )
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(core_only.status(), StatusCode::OK);
    assert_eq!(workspace_only.status(), StatusCode::OK);
    assert_eq!(cross_context.status(), StatusCode::FORBIDDEN);
    assert!(observations.recv().await.is_some());
    assert!(observations.recv().await.is_some());
    assert!(observations.try_recv().is_err());
}

#[tokio::test]
async fn agent_conversation_list_accepts_core_only_workspace_scope() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, _observations) = create_workspace_proxy_server().await;
    install(&state, &core_url);
    let app = local_router(state);

    let response = app
        .oneshot(
            Request::builder()
                .uri(
                    "/api/v1/agent/conversations?project_id=local-project&workspace_id=core-only-workspace",
                )
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), 1024 * 1024)
        .await
        .expect("response body");
    let payload: Value = serde_json::from_slice(&body).expect("response JSON");
    assert_eq!(payload["items"], json!([]));
}

#[tokio::test]
async fn conversation_binding_uses_core_workspace_authority_without_legacy_rows() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let timestamp = now_iso();
    state
        .session_store
        .insert_conversation(&LocalConversation {
            id: "core-binding-conversation".to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Core binding".to_string(),
            workspace_id: None,
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: timestamp.clone(),
            updated_at: timestamp,
        })
        .expect("insert conversation");
    let (core_url, mut observations) = create_workspace_proxy_server().await;
    install(&state, &core_url);

    let response = local_router(state)
        .oneshot(
            Request::builder()
                .method("PATCH")
                .uri("/api/v1/agent/conversations/core-binding-conversation/mode")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({ "workspace_id": "local-workspace" }).to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(response.status(), StatusCode::OK);
    let (_, body) = observations
        .recv()
        .await
        .expect("Core workspace validation");
    assert!(body.is_empty());
}

#[tokio::test]
async fn workspace_proxy_owns_exact_roster_routes_when_core_authority_is_installed() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_workspace_proxy_server().await;
    install(&state, &core_url);
    let app = local_router(state);

    for resource in ["members", "agents"] {
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/tenants/local/projects/local-project/workspaces/core-only-workspace/{resource}"
                    ))
                    .header("x-agistack-launch", "launch-token")
                    .header(AUTHORIZATION, "Bearer desktop-session")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
    }

    assert!(observations.recv().await.is_some());
    assert!(observations.recv().await.is_some());
    assert!(observations.try_recv().is_err());
}

#[tokio::test]
async fn workspace_proxy_forwards_topology_routes_when_core_authority_is_installed() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_workspace_proxy_server().await;
    install(&state, &core_url);
    let app = local_router(state);

    for resource in ["nodes", "edges"] {
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/workspaces/core-only-workspace/topology/{resource}"
                    ))
                    .header("x-agistack-launch", "launch-token")
                    .header(AUTHORIZATION, "Bearer desktop-session")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
    }

    assert!(observations.recv().await.is_some());
    assert!(observations.recv().await.is_some());
    assert!(observations.try_recv().is_err());
}

#[tokio::test]
async fn workspace_proxy_forwards_routing_policy_queries_and_mutations_to_core() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_routing_policy_proxy_server().await;
    install(&state, &core_url);
    let app = local_router(state);
    let path = "/api/v1/llm-providers/routing-policy?project_id=local-project&workspace_id=core-only-workspace";

    let get_response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(path)
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    let policy = json!({
        "revision": 4,
        "roles": { "planner": "provider:model" },
        "fallbacks": ["provider:fallback"]
    });
    let put_response = app
        .oneshot(
            Request::builder()
                .method("PUT")
                .uri(path)
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .header("x-expected-revision", "4")
                .body(Body::from(policy.to_string()))
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(get_response.status(), StatusCode::OK);
    assert_eq!(put_response.status(), StatusCode::OK);
    let (get_method, get_uri, get_headers, get_body) =
        observations.recv().await.expect("Core GET request");
    assert_eq!(get_method, "GET");
    assert_eq!(get_uri, path);
    assert!(get_body.is_empty());
    assert_eq!(
        get_headers
            .get("x-memstack-user-id")
            .and_then(|value| value.to_str().ok()),
        Some("local-user")
    );
    let (put_method, put_uri, put_headers, put_body) =
        observations.recv().await.expect("Core PUT request");
    assert_eq!(put_method, "PUT");
    assert_eq!(put_uri, path);
    assert_eq!(put_body, policy.to_string().as_bytes());
    assert_eq!(
        put_headers
            .get("x-expected-revision")
            .and_then(|value| value.to_str().ok()),
        Some("4")
    );
    assert_eq!(
        put_headers
            .get("x-memstack-project-membership-role")
            .and_then(|value| value.to_str().ok()),
        Some("owner")
    );
}

#[tokio::test]
async fn runtime_policy_reads_the_core_authority_without_legacy_sqlite_state() {
    let state = state();
    let (core_url, mut observations) = create_policy_read_server().await;
    install(&state, &core_url);

    let policy = workspace_policy(&state, "local", "local-project", "core-only-workspace")
        .await
        .expect("Core policy");

    assert_eq!(policy["revision"], 7);
    assert_eq!(policy["reasoning_effort"], "high");
    let (path, headers) = observations.recv().await.expect("Core policy request");
    assert_eq!(
        path,
        "/api/v1/tenants/local/projects/local-project/workspaces/core-only-workspace/agent-policy"
    );
    assert_eq!(
        headers
            .get(AUTHORIZATION)
            .and_then(|value| value.to_str().ok()),
        Some("Bearer service-token")
    );
    assert_eq!(
        headers
            .get("x-memstack-user-id")
            .and_then(|value| value.to_str().ok()),
        Some("local-user")
    );
}

#[tokio::test]
async fn workspace_routes_fail_closed_before_core_is_installed() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let app = local_router(state);

    let plan = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/v1/workspaces/local-workspace/plan")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    let topology = app
        .oneshot(
            Request::builder()
                .uri("/api/v1/workspaces/local-workspace/topology/nodes")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(plan.status(), StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(topology.status(), StatusCode::SERVICE_UNAVAILABLE);
}

fn agent_lookup(extra: Option<(&str, Value)>) -> Value {
    let mut body = json!({
        "tenant_id": "local",
        "project_id": "local-project",
        "agent_id": "builtin:all-access"
    });
    if let Some((name, value)) = extra {
        body[name] = value;
    }
    body
}

fn provider_request(id: &str, conversation_id: &str, method: &str) -> Value {
    json!({
        "type": "req",
        "id": id,
        "method": method,
        "session_id": "session-1",
        "bcn_group_id": "group-1",
        "to_bot": {
            "provider_id": "memstack-workspace-agent-runtime",
            "provider_bot_ref": "builtin:all-access"
        },
        "message": {
            "content": [{ "type": "text", "text": "hello from Workspace Core" }]
        },
        "timeout_ms": 30_000,
        "extensions": {
            "tenant_id": "local",
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "user_id": "local-user",
            "conversation_id": conversation_id,
            "task_id": "task-1",
            "plan_id": "plan-1",
            "plan_node_id": "node-1"
        }
    })
}

fn plan_dispatch_request(outbox_id: &str, conversation_id: &str) -> Value {
    json!({
        "tenant_id": "local",
        "project_id": "local-project",
        "workspace_id": "local-workspace",
        "plan_id": "plan-1",
        "plan_node_id": "node-1",
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "agent_id": "builtin:all-access",
        "action": "run_pipeline",
        "outbox_id": outbox_id,
        "correlation_id": "correlation-1",
        "conversation_id": conversation_id,
        "payload": { "objective": "verify plan dispatch" }
    })
}

fn insert_conversation(state: &LocalRuntimeState, conversation_id: &str) {
    let timestamp = now_iso();
    state
        .session_store
        .insert_conversation(&LocalConversation {
            id: conversation_id.to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Workspace Core bridge test".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: timestamp.clone(),
            updated_at: timestamp,
        })
        .expect("insert conversation");
}

#[tokio::test]
async fn registry_resolves_the_project_scoped_builtin_agent() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");

    let (status, body) = post_json(
        router(state),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(None),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["available"], true);
    assert_eq!(body["agent_id"], "builtin:all-access");
}

#[tokio::test]
async fn registry_resolves_active_provider_without_generic_resource_status() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "provider-1",
            "active",
            None,
            json!({
                "id": "provider-1",
                "tenant_id": "local",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example.test/v1",
                "auth_method": "none",
                "is_active": true,
                "llm_model": "model-1",
                "allowed_models": ["model-1"]
            }),
            chrono::Utc::now().timestamp_millis(),
        )
        .expect("seed provider");

    let (status, body) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider-registry/resolve",
        "registry-token",
        json!({
            "tenant_id": "local",
            "provider_id": "provider-1",
            "model_id": "model-1"
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["available"], true);
    assert_eq!(body["provider_id"], "provider-1");
    assert_eq!(body["model_id"], "model-1");

    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "provider-1",
            "disabled",
            Some(0),
            json!({
                "id": "provider-1",
                "tenant_id": "local",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example.test/v1",
                "auth_method": "none",
                "is_active": false,
                "llm_model": "model-1",
                "allowed_models": ["model-1"]
            }),
            chrono::Utc::now().timestamp_millis(),
        )
        .expect("disable provider");
    let (disabled_status, disabled_body) = post_json(
        router(state),
        "/internal/v1/workspace-core/provider-registry/resolve",
        "registry-token",
        json!({
            "tenant_id": "local",
            "provider_id": "provider-1",
            "model_id": "model-1"
        }),
    )
    .await;
    assert_eq!(disabled_status, StatusCode::OK);
    assert_eq!(disabled_body["available"], false);
}

#[tokio::test]
async fn internal_authority_is_separate_from_launch_and_provider_tokens() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    let app = local_router(state);

    let (registry_status, _) = post_json(
        app.clone(),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(None),
    )
    .await;
    let (launch_status, _) = post_json(
        app.clone(),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "launch-token",
        agent_lookup(None),
    )
    .await;
    let (provider_status, _) = post_json(
        app,
        "/internal/v1/workspace-core/agent-registry/resolve",
        "provider-token",
        agent_lookup(None),
    )
    .await;

    assert_eq!(registry_status, StatusCode::OK);
    assert_eq!(launch_status, StatusCode::UNAUTHORIZED);
    assert_eq!(provider_status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn missing_authority_unknown_fields_and_cross_scope_fail_closed() {
    let state = state();
    let (missing_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(None),
    )
    .await;
    install(&state, "http://127.0.0.1:21000");
    let (unknown_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(Some(("unexpected", json!(true)))),
    )
    .await;
    let (scope_status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        json!({
            "tenant_id": "another-tenant",
            "project_id": "local-project",
            "agent_id": "builtin:all-access"
        }),
    )
    .await;

    assert_eq!(missing_status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(unknown_status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(scope_status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn duplicate_provider_request_does_not_execute_a_second_side_effect() {
    let state = state();
    let (core_url, mut callbacks) = callback_server().await;
    install(&state, &core_url);
    let request = provider_request("provider-run-1", "provider-conversation-1", "chat.send");

    let (first_status, first) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        request.clone(),
    )
    .await;
    let callback = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let callback = callbacks.recv().await.expect("callback");
            if matches!(
                callback["payload"]["state"].as_str(),
                Some("final" | "error" | "aborted")
            ) {
                return callback;
            }
        }
    })
    .await
    .expect("terminal callback deadline");
    let (duplicate_status, duplicate) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        request,
    )
    .await;

    assert_eq!(first_status, StatusCode::OK);
    assert_eq!(duplicate_status, StatusCode::OK);
    assert_eq!(first, duplicate);
    assert_eq!(callback["run_id"], "provider-run-1");
    assert_eq!(callback["payload"]["state"], "final");
    let timeline = state
        .session_store
        .timeline("provider-conversation-1", 100)
        .expect("timeline");
    assert_eq!(
        timeline
            .iter()
            .filter(|item| item["type"] == "user_message")
            .count(),
        1
    );
    assert!(timeline
        .iter()
        .any(|item| item["type"] == "assistant_message"));
}

#[tokio::test]
async fn request_id_payload_conflict_is_rejected() {
    let state = state();
    let (core_url, _callbacks) = callback_server().await;
    install(&state, &core_url);
    let first = provider_request(
        "provider-run-conflict",
        "provider-conversation-2",
        "chat.send",
    );
    let mut conflicting = first.clone();
    conflicting["message"]["content"][0]["text"] = json!("different payload");

    let (first_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        first,
    )
    .await;
    let (conflict_status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        conflicting,
    )
    .await;

    assert_eq!(first_status, StatusCode::OK);
    assert_eq!(conflict_status, StatusCode::CONFLICT);
}

#[tokio::test]
async fn injected_context_is_returned_by_provider_history() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    insert_conversation(&state, "provider-conversation-history");
    let mut inject = provider_request(
        "provider-inject-1",
        "provider-conversation-history",
        "chat.inject",
    );
    inject["message"]["content"][0]["text"] = json!("durable injected context");

    let (inject_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        inject,
    )
    .await;
    let history = provider_request(
        "provider-history-1",
        "provider-conversation-history",
        "chat.history",
    );
    let (history_status, body) = post_json(
        router(state),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        history,
    )
    .await;

    assert_eq!(inject_status, StatusCode::OK);
    assert_eq!(history_status, StatusCode::OK);
    let messages = body["messages"].as_array().expect("history messages");
    assert!(messages.iter().any(|message| {
        message["type"] == "avernet_context_injection"
            && message["content"] == "durable injected context"
    }));
}

#[tokio::test]
async fn provider_abort_sets_the_active_run_cancel_directive() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    let conversation_id = "provider-conversation-abort";
    insert_conversation(&state, conversation_id);
    let control = state
        .claim_agent_run(conversation_id, None)
        .expect("claim active Agent run");

    let (status, body) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        provider_request("provider-abort-1", conversation_id, "chat.abort"),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["local_worker_cancelled"], true);
    assert!(matches!(
        control.directive(conversation_id, 0).await,
        Ok(RunDirective::Cancel)
    ));
    state.release_agent_run(conversation_id);
}

#[tokio::test]
async fn duplicate_plan_dispatch_does_not_start_a_second_agent_run() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    state.agent_run_claim_attempts.store(0, Ordering::SeqCst);
    let request = plan_dispatch_request("plan-outbox-1", "plan-conversation-1");

    let (first_status, first) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/plan-dispatch",
        "provider-token",
        request.clone(),
    )
    .await;
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while state.agent_run_claim_attempts.load(Ordering::SeqCst) == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("plan Agent start deadline");
    let (duplicate_status, duplicate) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/plan-dispatch",
        "provider-token",
        request,
    )
    .await;
    tokio::time::sleep(std::time::Duration::from_millis(25)).await;

    assert_eq!(first_status, StatusCode::OK);
    assert_eq!(duplicate_status, StatusCode::OK);
    assert_eq!(first, duplicate);
    assert_eq!(first["provider_id"], "memstack-agent-runtime");
    assert_eq!(first["provider_bot_ref"], "builtin:all-access");
    assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn judge_fails_closed_when_agent_returns_finish_without_a_tool_call() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");

    let (status, body) = post_json(
        router(state),
        "/internal/v1/workspace-core/plan-judge",
        "registry-token",
        json!({
            "tenant_id": "local",
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "actor_id": "supervisor-1",
            "plan_id": "plan-1",
            "plan_revision": 1,
            "kind": "select_pipeline_target",
            "candidate_node_ids": ["node-1"],
            "evidence": { "ready": true }
        }),
    )
    .await;

    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert!(body.to_string().contains("structured tool call"));
}

#[tokio::test]
async fn stale_authority_generation_cannot_clear_the_rotated_authority() {
    let state = state();
    let first_generation = install(&state, "http://127.0.0.1:21000");
    let second_generation = install_authority(
        &state,
        "http://127.0.0.1:22000".to_string(),
        "service-token-2".to_string(),
        "registry-token-2".to_string(),
        "provider-token-2".to_string(),
        "event-token-2".to_string(),
    )
    .expect("rotate authority");
    clear_authority(&state, first_generation);

    let (rotated_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token-2",
        agent_lookup(None),
    )
    .await;
    let (stale_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(None),
    )
    .await;
    clear_authority(&state, second_generation);
    let (cleared_status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token-2",
        agent_lookup(None),
    )
    .await;

    assert_eq!(rotated_status, StatusCode::OK);
    assert_eq!(stale_status, StatusCode::UNAUTHORIZED);
    assert_eq!(cleared_status, StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn cleared_authority_never_restores_legacy_workspace_routes_after_cutover() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let generation = install(&state, "http://127.0.0.1:21000");
    clear_authority(&state, generation);

    let response = local_router(state)
        .oneshot(
            Request::builder()
                .uri("/api/v1/tenants/local/projects/local-project/workspaces/legacy-workspace")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn task_sessions_are_core_owned_and_fail_closed_when_authority_is_lost() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_task_session_proxy_server().await;
    let generation = install(&state, &core_url);
    let app = local_router(Arc::clone(&state));
    let path = "/api/v1/tenants/local/projects/local-project/task-sessions";

    let proxied = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "idempotency_key": "desktop-task-session-cutover",
                        "workspace": {
                            "kind": "existing",
                            "workspace_id": "local-workspace"
                        },
                        "conversation": {
                            "title": "Cutover thread",
                            "capability_mode": "work"
                        },
                        "initial_message": { "content": "Verify fail-closed cutover" }
                    })
                    .to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(proxied.status(), StatusCode::CREATED);
    observations
        .recv()
        .await
        .expect("Core received task session");

    clear_authority(&state, generation);
    let unavailable = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "idempotency_key": "desktop-task-session-after-cutover",
                        "workspace": {
                            "kind": "existing",
                            "workspace_id": "local-workspace"
                        },
                        "conversation": {
                            "title": "Unavailable thread",
                            "capability_mode": "work"
                        },
                        "initial_message": { "content": "Must fail without authority" }
                    })
                    .to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(unavailable.status(), StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn task_sessions_use_the_private_core_atomic_command_contract() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_task_session_proxy_server().await;
    install(&state, &core_url);

    let response = local_router(Arc::clone(&state))
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/tenants/local/projects/local-project/task-sessions")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "idempotency_key": "desktop-task-session-1",
                        "workspace": {
                            "kind": "existing",
                            "workspace_id": "local-workspace"
                        },
                        "conversation": {
                            "title": "Local thread",
                            "capability_mode": "work"
                        },
                        "initial_message": {
                            "content": "Create a reviewable plan",
                            "context_items": []
                        }
                    })
                    .to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(response.status(), StatusCode::CREATED);
    let response_body = to_bytes(response.into_body(), 1024 * 1024)
        .await
        .expect("task-session response body");
    let response_value: Value =
        serde_json::from_slice(&response_body).expect("task-session response JSON");
    assert_eq!(response_value["conversation"]["title"], "Local thread");
    assert_eq!(response_value["conversation"]["message_count"], 1);
    assert_eq!(
        response_value["conversation"]["workspace_id"],
        "local-workspace"
    );
    assert_eq!(
        response_value["initial_message"]["metadata"]["conversation_id"],
        response_value["conversation"]["id"]
    );
    assert!(state
        .session_store
        .conversation(
            response_value["conversation"]["id"]
                .as_str()
                .expect("conversation id")
        )
        .expect("conversation projection")
        .is_some());

    let (path, headers, body) = observations.recv().await.expect("Core request");
    assert_eq!(
        path,
        "/internal/v1/tenants/local/projects/local-project/task-sessions"
    );
    assert_eq!(
        headers
            .get("x-idempotency-key")
            .and_then(|value| value.to_str().ok()),
        Some("desktop-task-session-1")
    );
    let core_request: Value = serde_json::from_slice(&body).expect("Core request JSON");
    assert_eq!(core_request["workspace"]["kind"], "existing");
    assert_eq!(core_request["workspace"]["workspace_id"], "local-workspace");
    assert_eq!(core_request["capability_mode"], "work");
    assert_eq!(
        core_request["initial_message"]["content"],
        "Create a reviewable plan"
    );
    assert!(core_request["conversation_id"].as_str().is_some());
    assert!(core_request["initial_message"]["message_id"]
        .as_str()
        .is_some());
    assert!(core_request.get("idempotency_key").is_none());
    assert!(core_request.get("conversation").is_none());
}

#[tokio::test]
async fn task_session_core_failure_does_not_create_a_local_conversation_projection() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_task_session_proxy_server_with(
        TaskSessionProxyBehavior::Failure(StatusCode::SERVICE_UNAVAILABLE),
    )
    .await;
    install(&state, &core_url);

    let response = local_router(Arc::clone(&state))
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/tenants/local/projects/local-project/task-sessions")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "idempotency_key": "desktop-task-session-core-failure",
                        "workspace": {
                            "kind": "existing",
                            "workspace_id": "local-workspace"
                        },
                        "conversation": {
                            "title": "Must not persist",
                            "capability_mode": "work"
                        },
                        "initial_message": { "content": "Do not persist this request" }
                    })
                    .to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    observations.recv().await.expect("Core request");
    assert!(state
        .session_store
        .list_conversations("local-project", Some("local-workspace"))
        .expect("conversation projections")
        .is_empty());
}

#[tokio::test]
async fn task_session_replay_reuses_the_local_conversation_projection() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_task_session_proxy_server().await;
    let generation = install(&state, &core_url);
    let app = local_router(Arc::clone(&state));
    let body = json!({
        "idempotency_key": "desktop-task-session-replay",
        "workspace": {
            "kind": "existing",
            "workspace_id": "local-workspace"
        },
        "conversation": {
            "title": "Replay local thread",
            "capability_mode": "work"
        },
        "initial_message": { "content": "Create one local projection" }
    })
    .to_string();

    let request = || {
        Request::builder()
            .method("POST")
            .uri("/api/v1/tenants/local/projects/local-project/task-sessions")
            .header("x-agistack-launch", "launch-token")
            .header(AUTHORIZATION, "Bearer desktop-session")
            .header("content-type", "application/json")
            .body(Body::from(body.clone()))
            .expect("request")
    };
    let first = app
        .clone()
        .oneshot(request())
        .await
        .expect("first response");
    assert_eq!(first.status(), StatusCode::CREATED);
    let first_body = to_bytes(first.into_body(), 1024 * 1024)
        .await
        .expect("first body");
    let first_value: Value = serde_json::from_slice(&first_body).expect("first response JSON");
    observations.recv().await.expect("first Core request");
    clear_authority(&state, generation);

    let second = app.oneshot(request()).await.expect("second response");
    assert_eq!(second.status(), StatusCode::OK);
    let second_body = to_bytes(second.into_body(), 1024 * 1024)
        .await
        .expect("second body");
    let second_value: Value = serde_json::from_slice(&second_body).expect("second response JSON");

    assert_eq!(second_value["replayed"], true);
    assert_eq!(
        second_value["capability_version"],
        "avernet-task-session-v1"
    );
    assert_eq!(
        second_value["conversation"]["id"],
        first_value["conversation"]["id"]
    );
    assert_eq!(
        state
            .session_store
            .list_conversations("local-project", Some("local-workspace"))
            .expect("conversation projections")
            .len(),
        1
    );
    assert!(observations.try_recv().is_err());
}

#[tokio::test]
async fn task_session_core_conflict_maps_to_the_desktop_idempotency_contract() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) =
        create_task_session_proxy_server_with(TaskSessionProxyBehavior::IdempotencyConflict).await;
    install(&state, &core_url);

    let response = local_router(state)
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/tenants/local/projects/local-project/task-sessions")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "idempotency_key": "desktop-task-session-conflict",
                        "workspace": { "kind": "existing", "workspace_id": "local-workspace" },
                        "conversation": { "title": "Conflict thread", "capability_mode": "work" },
                        "initial_message": { "content": "Conflicting objective" }
                    })
                    .to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");
    let status = response.status();
    let body = to_bytes(response.into_body(), 1024 * 1024)
        .await
        .expect("response body");
    let body: Value = serde_json::from_slice(&body).expect("response JSON");

    observations.recv().await.expect("Core request");
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(body["code"], "TASK_SESSION_IDEMPOTENCY_CONFLICT");
    assert_eq!(body["detail"], "Core failure");
}

#[tokio::test]
async fn task_session_non_idempotency_conflict_remains_distinct() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_task_session_proxy_server_with(
        TaskSessionProxyBehavior::Failure(StatusCode::CONFLICT),
    )
    .await;
    install(&state, &core_url);

    let response = local_router(state)
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/tenants/local/projects/local-project/task-sessions")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "idempotency_key": "desktop-task-session-policy-conflict",
                        "workspace": { "kind": "existing", "workspace_id": "local-workspace" },
                        "conversation": { "title": "Policy conflict", "capability_mode": "work" },
                        "initial_message": { "content": "Preserve conflict semantics" }
                    })
                    .to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");
    let status = response.status();
    let body = to_bytes(response.into_body(), 1024 * 1024)
        .await
        .expect("response body");
    let body: Value = serde_json::from_slice(&body).expect("response JSON");

    observations.recv().await.expect("Core request");
    assert_eq!(status, StatusCode::CONFLICT);
    assert!(body.get("code").is_none());
    assert_eq!(body["detail"], "Core failure");
}

#[tokio::test]
async fn malformed_core_task_session_does_not_poison_the_local_receipt() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) =
        create_task_session_proxy_server_with(TaskSessionProxyBehavior::MalformedSuccess).await;
    install(&state, &core_url);

    let response = local_router(Arc::clone(&state))
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/tenants/local/projects/local-project/task-sessions")
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({
                        "idempotency_key": "desktop-task-session-malformed-core",
                        "workspace": { "kind": "existing", "workspace_id": "local-workspace" },
                        "conversation": { "title": "Reject malformed", "capability_mode": "work" },
                        "initial_message": { "content": "Expected objective" }
                    })
                    .to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");

    observations.recv().await.expect("Core request");
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    assert!(state
        .session_store
        .list_conversations("local-project", Some("local-workspace"))
        .expect("conversation projections")
        .is_empty());
}

#[tokio::test]
async fn unavailable_core_task_session_contract_maps_to_stable_service_unavailable() {
    for upstream_status in [StatusCode::NOT_FOUND, StatusCode::METHOD_NOT_ALLOWED] {
        let state = state();
        state
            .session_store
            .seed_test_session("desktop-session")
            .expect("desktop session");
        let core_url = create_status_proxy_server(upstream_status).await;
        install(&state, &core_url);
        let response = local_router(state)
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/tenants/local/projects/local-project/task-sessions")
                    .header("x-agistack-launch", "launch-token")
                    .header(AUTHORIZATION, "Bearer desktop-session")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        json!({
                            "idempotency_key": "desktop-task-session-missing-contract",
                            "workspace": {
                                "kind": "existing",
                                "workspace_id": "local-workspace"
                            },
                            "conversation": {
                                "title": "Unavailable contract",
                                "capability_mode": "work"
                            },
                            "initial_message": { "content": "Verify unavailable contract" }
                        })
                        .to_string(),
                    ))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    }
}

#[tokio::test]
async fn provider_callbacks_preserve_tool_start_end_and_final_order() {
    let state = state();
    let (core_url, mut callbacks) = callback_server().await;
    install(&state, &core_url);

    let (status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        provider_request(
            "provider-run-order",
            "provider-conversation-order",
            "chat.send",
        ),
    )
    .await;
    let states = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let mut states = Vec::new();
        loop {
            let callback = callbacks.recv().await.expect("callback");
            let callback_state = callback["payload"]["state"]
                .as_str()
                .expect("callback state")
                .to_string();
            let terminal = matches!(callback_state.as_str(), "final" | "error" | "aborted");
            states.push(callback_state);
            if terminal {
                return states;
            }
        }
    })
    .await
    .expect("ordered callback deadline");

    assert_eq!(status, StatusCode::OK);
    let start = states
        .iter()
        .position(|state| state == "tool_call_start")
        .expect("tool start callback");
    let end = states
        .iter()
        .position(|state| state == "tool_call_end")
        .expect("tool end callback");
    let final_event = states
        .iter()
        .position(|state| state == "final")
        .expect("final callback");
    assert!(
        start < end && end < final_event,
        "callback states: {states:?}"
    );
}

#[tokio::test]
async fn terminal_callback_outbox_replays_after_core_recovers() {
    let state = state();
    let (failing_core_url, mut failed_callbacks) =
        callback_server_with_status(StatusCode::SERVICE_UNAVAILABLE).await;
    install(&state, &failing_core_url);

    let (status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        provider_request(
            "provider-run-replay",
            "provider-conversation-replay",
            "chat.send",
        ),
    )
    .await;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let callback = failed_callbacks.recv().await.expect("failed callback");
            if callback["payload"]["state"] == "final" {
                break;
            }
        }
    })
    .await
    .expect("failed terminal callback deadline");
    let pending = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let pending = state
                .session_store
                .pending_workspace_core_terminal_callbacks(10)
                .expect("pending terminal callbacks");
            if pending
                .first()
                .is_some_and(|callback| callback.attempt_count >= 3)
            {
                return pending;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("terminal outbox persistence deadline");

    assert_eq!(status, StatusCode::OK);
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].run_id, "provider-run-replay");
    assert_eq!(pending[0].payload["payload"]["state"], "final");
    let timeline = state
        .session_store
        .timeline("provider-conversation-replay", 100)
        .expect("terminal timeline");
    assert!(timeline
        .iter()
        .any(|item| item["type"] == "assistant_message"));

    let (recovered_core_url, mut recovered_callbacks) = callback_server().await;
    install_authority(
        &state,
        recovered_core_url,
        "service-token-recovered".to_string(),
        "registry-token".to_string(),
        "provider-token".to_string(),
        "event-token".to_string(),
    )
    .expect("install recovered authority");
    let delivered = replay_pending_terminal_callbacks(Arc::clone(&state))
        .await
        .expect("replay terminal callbacks");
    let recovered = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        recovered_callbacks.recv(),
    )
    .await
    .expect("recovered callback deadline")
    .expect("recovered callback");

    assert_eq!(delivered, 1);
    assert_eq!(recovered["run_id"], "provider-run-replay");
    assert_eq!(recovered["payload"]["state"], "final");
    assert!(state
        .session_store
        .pending_workspace_core_terminal_callbacks(10)
        .expect("drained terminal callbacks")
        .is_empty());
}

#[tokio::test]
async fn terminal_callback_gone_response_is_marked_delivered() {
    let state = state();
    let (core_url, mut callbacks) = callback_server_with_status(StatusCode::GONE).await;
    install(&state, &core_url);

    let (status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        provider_request(
            "provider-run-gone",
            "provider-conversation-gone",
            "chat.send",
        ),
    )
    .await;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let callback = callbacks.recv().await.expect("gone callback");
            if callback["payload"]["state"] == "final" {
                break;
            }
        }
    })
    .await
    .expect("gone terminal callback deadline");
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            if state
                .session_store
                .pending_workspace_core_terminal_callbacks(10)
                .expect("pending terminal callbacks")
                .is_empty()
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("gone delivery marker deadline");

    assert_eq!(status, StatusCode::OK);
}

async fn callback_server() -> (String, mpsc::Receiver<Value>) {
    callback_server_with_status(StatusCode::OK).await
}

type CallbackState = Arc<Mutex<(mpsc::Sender<Value>, StatusCode)>>;

async fn callback_server_with_status(status: StatusCode) -> (String, mpsc::Receiver<Value>) {
    let (sender, receiver) = mpsc::channel(32);
    let sender = Arc::new(Mutex::new((sender, status)));

    async fn callback(
        State(state): State<CallbackState>,
        headers: HeaderMap,
        Json(body): Json<Value>,
    ) -> StatusCode {
        assert_eq!(headers["authorization"], "Bearer event-token");
        assert_eq!(
            headers["bcn-provider-id"],
            "memstack-workspace-agent-runtime"
        );
        let (sender, status) = &*state.lock().await;
        sender.send(body).await.expect("record callback");
        *status
    }

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind callback server");
    let address = listener.local_addr().expect("callback address");
    tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new()
                .route("/bot/events", post(callback))
                .with_state(sender),
        )
        .await
        .expect("callback server");
    });
    (format!("http://{address}"), receiver)
}
