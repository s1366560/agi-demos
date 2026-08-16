use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

use agistack_adapters_device::SqliteCheckpointStore;
use agistack_adapters_local_tools::LocalToolHost;
use agistack_core::agent::react::{ReActControl, RunDirective};
use axum::{
    body::{to_bytes, Body},
    extract::State,
    http::{HeaderMap, Request, StatusCode},
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::sync::{mpsc, Mutex};
use tower::ServiceExt;
use uuid::Uuid;

use super::*;
use crate::local_runtime::{
    authority_store::{recover_interrupted_runs, DesktopPlanStatus, DesktopRunStatus},
    local_router, now_iso,
    resource_registry::ManagedResourceKind,
    session_store::{DesktopSessionStore, DesktopWorkspaceCoreTerminalCallback},
    workspace_task_run::ProjectWorkspaceTaskRunInput,
    ConversationCapabilityMode, ConversationRunMode, LlmRouteTarget, LocalConversation,
    LocalRuntimeState,
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
        if let Some(selection) = command["workspace_policy"].as_object() {
            let route = selection
                .get("route")
                .cloned()
                .expect("task-session policy route");
            let capability_role = if command["capability_mode"] == "code" {
                "coding"
            } else {
                "default"
            };
            response["policy"] = json!({
                "tenant_id": "local",
                "project_id": "local-project",
                "workspace_id": "local-workspace",
                "revision": selection
                    .get("expected_revision")
                    .and_then(Value::as_u64)
                    .map(|revision| revision + 1)
                    .unwrap_or(1),
                "roles": {
                    "default": if capability_role == "default" { route.clone() } else { Value::Null },
                    "fast": null,
                    "coding": if capability_role == "coding" { route.clone() } else { Value::Null },
                    "vision": null
                },
                "fallbacks": [],
                "reasoning_effort": selection
                    .get("reasoning_effort")
                    .cloned()
                    .unwrap_or_else(|| json!("medium")),
                "permission_mode": selection
                    .get("permission_mode")
                    .cloned()
                    .unwrap_or_else(|| json!("ask")),
                "capability_version": "workspace-agent-policy-v1",
                "updated_at": "2026-08-13T00:00:00Z"
            });
        }
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

    let response = local_router(Arc::clone(&state))
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
async fn workspace_proxy_forwards_attention_list_and_retry_with_trusted_identity_headers() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, mut observations) = create_routing_policy_proxy_server().await;
    install(&state, &core_url);
    let app = local_router(state);
    let list_path = "/api/v1/workspaces/core-only-workspace/autonomy/attentions";
    let retry_path = "/api/v1/workspaces/core-only-workspace/autonomy/attentions/attention-1/retry";

    let unauthenticated = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(list_path)
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(unauthenticated.status(), StatusCode::UNAUTHORIZED);

    let list_response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(list_path)
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("accept", "application/json")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    let retry_response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(retry_path)
                .header("x-agistack-launch", "launch-token")
                .header(AUTHORIZATION, "Bearer desktop-session")
                .header("content-type", "application/json")
                .header("idempotency-key", "attention-retry-1")
                .header("if-match", "5")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");

    assert_eq!(list_response.status(), StatusCode::OK);
    assert_eq!(retry_response.status(), StatusCode::OK);
    let (list_method, list_uri, list_headers, list_body) =
        observations.recv().await.expect("Core attention list");
    assert_eq!(list_method, "GET");
    assert_eq!(list_uri, list_path);
    assert!(list_body.is_empty());
    assert_eq!(
        list_headers
            .get(AUTHORIZATION)
            .and_then(|value| value.to_str().ok()),
        Some("Bearer service-token")
    );
    assert_eq!(
        list_headers
            .get("x-memstack-user-id")
            .and_then(|value| value.to_str().ok()),
        Some("local-user")
    );
    assert_eq!(
        list_headers
            .get("x-memstack-project-membership-role")
            .and_then(|value| value.to_str().ok()),
        Some("owner")
    );
    let (retry_method, retry_uri, retry_headers, retry_body) =
        observations.recv().await.expect("Core attention retry");
    assert_eq!(retry_method, "POST");
    assert_eq!(retry_uri, retry_path);
    assert!(retry_body.is_empty());
    assert_eq!(
        retry_headers
            .get(AUTHORIZATION)
            .and_then(|value| value.to_str().ok()),
        Some("Bearer service-token")
    );
    assert_eq!(
        retry_headers
            .get("idempotency-key")
            .and_then(|value| value.to_str().ok()),
        Some("attention-retry-1")
    );
    assert_eq!(
        retry_headers
            .get("if-match")
            .and_then(|value| value.to_str().ok()),
        Some("5")
    );
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
            "conversation_id": conversation_id
        }
    })
}

fn task_provider_request(id: &str, conversation_id: &str) -> Value {
    let mut request = provider_request(id, conversation_id, "chat.send");
    request["extensions"]["task_id"] = json!("task-1");
    request["extensions"]["attempt_id"] = json!("attempt-1");
    request["extensions"]["plan_id"] = json!("plan-1");
    request["extensions"]["plan_node_id"] = json!("node-1");
    request["extensions"]["workspace_agent_binding_id"] = json!("binding-1");
    request["extensions"]["delivery_request_id"] = json!(id);
    request
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
async fn workspace_task_send_projects_one_authoritative_run_and_preserves_callback_scope() {
    let state = state();
    let (core_url, mut callbacks) = task_core_server().await;
    install(&state, &core_url);
    let request = task_provider_request("task-provider-run-1", "task-provider-conversation-1");

    let (first_status, first) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        request.clone(),
    )
    .await;
    let callback = receive_terminal_callback(&mut callbacks).await;
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
    assert_eq!(first["provider_run_id"], "task-provider-run-1");
    assert_eq!(callback["run_id"], "task-provider-run-1");
    let sequence = callback["payload"]["seq"]
        .as_u64()
        .expect("terminal sequence");
    let expected_terminal_event_id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("memstack-workspace-terminal:task-provider-run-1:{sequence}").as_bytes(),
    )
    .to_string();
    let expected_terminal_message_id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("memstack-workspace-terminal-message:task-provider-run-1:{sequence}").as_bytes(),
    )
    .to_string();
    assert_eq!(
        callback["payload"]["terminal_event_id"],
        expected_terminal_event_id
    );
    assert_eq!(
        callback["payload"]["terminal_message_id"],
        expected_terminal_message_id
    );
    let report = &callback["payload"]["terminal_report"];
    assert_eq!(report["provider_state"], "final");
    assert_eq!(report["sequence"], sequence);
    assert_eq!(
        report["message_text"], callback["message"]["text"],
        "the persisted report and Provider command must share exact text"
    );
    let mut sanitized = callback["payload"].clone();
    let sanitized = sanitized.as_object_mut().expect("Provider event object");
    sanitized.remove("terminal_message_id");
    sanitized.remove("terminal_event_id");
    sanitized.remove("terminal_report");
    assert_eq!(report["provider_event"], Value::Object(sanitized.clone()));
    assert_eq!(callback["payload"]["extensions"]["task_id"], "task-1");
    assert_eq!(callback["payload"]["extensions"]["attempt_id"], "attempt-1");
    assert_eq!(
        callback["payload"]["extensions"]["workspace_agent_binding_id"],
        "binding-1"
    );
    assert_eq!(
        callback["payload"]["extensions"]["delivery_request_id"],
        "task-provider-run-1"
    );

    let conversation = state
        .session_store
        .conversation("task-provider-conversation-1")
        .expect("conversation")
        .expect("projected conversation");
    assert_eq!(conversation.current_mode, ConversationRunMode::Build);
    assert_eq!(
        conversation.capability_mode,
        ConversationCapabilityMode::Code
    );
    let selection = state
        .session_store
        .execution_selection(&conversation.id)
        .expect("execution selection")
        .expect("selected Agent");
    assert_eq!(selection.agent_id.as_deref(), Some("builtin:all-access"));
    assert!(selection.forced_skill_id.is_none());
    assert!(selection.subagent_id.is_none());
    assert_eq!(
        state
            .session_store
            .conversation_llm_route(&conversation.id)
            .expect("LLM route"),
        Some(LlmRouteTarget {
            provider_id: "provider-1".to_string(),
            model_id: "model-1".to_string(),
        })
    );
    let snapshot = state
        .session_store
        .conversation_session_snapshot(&conversation.id)
        .expect("session snapshot")
        .expect("authoritative session");
    assert_eq!(snapshot.run_history.len(), 1);
    assert_eq!(snapshot.run_history[0].id, "task-provider-run-1");
    assert_eq!(
        snapshot.run_history[0].permission_profile,
        crate::local_runtime::authority_store::DesktopPermissionProfile::WorkspaceWrite
    );
    assert_eq!(
        snapshot.run_history[0].authorization_snapshot["llm_provider_id"],
        "provider-1"
    );
    assert_eq!(
        snapshot.run_history[0].authorization_snapshot["llm_model_id"],
        "model-1"
    );
    assert_eq!(snapshot.plan_history.len(), 1);
    assert_eq!(snapshot.plan_history[0].status, DesktopPlanStatus::Approved);
    assert_eq!(snapshot.plan_history[0].tasks.len(), 1);
    let timeline = state
        .session_store
        .timeline(&conversation.id, 100)
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
    assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn workspace_task_send_conflict_and_incomplete_receipt_fail_closed() {
    let state = state();
    let (core_url, mut callbacks) = task_core_server().await;
    install(&state, &core_url);
    let request = task_provider_request(
        "task-provider-run-conflict",
        "task-provider-conversation-conflict",
    );
    let mut conflicting = request.clone();
    conflicting["message"]["content"][0]["text"] = json!("different task payload");

    let (first_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        request.clone(),
    )
    .await;
    receive_terminal_callback(&mut callbacks).await;
    let (conflict_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        conflicting,
    )
    .await;
    state
        .session_store
        .with_local_mcp_connection(|connection| {
            connection
                .execute(
                    "DELETE FROM desktop_runs WHERE id = 'task-provider-run-conflict'",
                    [],
                )
                .map(|_| ())
                .map_err(|error| error.to_string())
        })
        .expect("remove authority projection");
    let (incomplete_status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        request,
    )
    .await;

    assert_eq!(first_status, StatusCode::OK);
    assert_eq!(conflict_status, StatusCode::CONFLICT);
    assert_eq!(incomplete_status, StatusCode::INTERNAL_SERVER_ERROR);
}

#[tokio::test]
async fn workspace_task_send_requires_attempt_before_projecting_authority() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    let mut missing = task_provider_request(
        "task-provider-run-missing-attempt",
        "task-provider-conversation-missing-attempt",
    );
    missing["extensions"]
        .as_object_mut()
        .expect("extensions")
        .remove("attempt_id");
    let mut blank = task_provider_request(
        "task-provider-run-blank-attempt",
        "task-provider-conversation-blank-attempt",
    );
    blank["extensions"]["attempt_id"] = json!("");

    let (missing_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        missing,
    )
    .await;
    let (blank_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        blank,
    )
    .await;

    assert_eq!(missing_status, StatusCode::BAD_REQUEST);
    assert_eq!(blank_status, StatusCode::BAD_REQUEST);
    assert!(state
        .session_store
        .run("task-provider-run-missing-attempt")
        .expect("run lookup")
        .is_none());
    assert!(state
        .session_store
        .run("task-provider-run-blank-attempt")
        .expect("run lookup")
        .is_none());
    let receipt_count = state
        .session_store
        .with_local_mcp_connection(|connection| {
            connection
                .query_row(
                    "SELECT COUNT(*) FROM desktop_workspace_core_requests WHERE request_id IN (\
                     'task-provider-run-missing-attempt', 'task-provider-run-blank-attempt')",
                    [],
                    |row| row.get::<_, i64>(0),
                )
                .map_err(|error| error.to_string())
        })
        .expect("receipt count");
    assert_eq!(receipt_count, 0);
}

#[tokio::test]
async fn workspace_task_prelaunch_recovery_reuses_the_same_run_once() {
    let state = state();
    let (core_url, mut callbacks) = task_core_server().await;
    install(&state, &core_url);
    let request_value = task_provider_request(
        "task-provider-run-recovery",
        "task-provider-conversation-recovery",
    );
    let request: contracts::ProviderWebhookRequest =
        serde_json::from_value(request_value.clone()).expect("typed Provider request");
    let request_hash =
        Sha256::digest(serde_json::to_vec(&request).expect("Provider request encoding"))
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
    let outcome = state
        .session_store
        .project_workspace_task_run(ProjectWorkspaceTaskRunInput {
            request_id: request.id.clone(),
            request_hash,
            request_payload: request_value,
            tenant_id: request.extensions.tenant_id.clone(),
            project_id: request.extensions.project_id.clone(),
            workspace_id: request.extensions.workspace_id.clone(),
            user_id: request.extensions.user_id.clone(),
            task_id: request.extensions.task_id.clone().expect("task id"),
            attempt_id: request.extensions.attempt_id.clone().expect("attempt id"),
            plan_id: request.extensions.plan_id.clone(),
            plan_node_id: request.extensions.plan_node_id.clone(),
            workspace_agent_binding_id: request
                .extensions
                .workspace_agent_binding_id
                .clone()
                .expect("binding id"),
            agent_id: request.to_bot.provider_bot_ref.clone(),
            conversation_id: request.extensions.conversation_id.clone(),
            message: "hello from Workspace Core".to_string(),
            llm_route: LlmRouteTarget {
                provider_id: "provider-1".to_string(),
                model_id: "model-1".to_string(),
            },
            now: now_iso(),
        })
        .expect("atomic task projection");
    assert_eq!(outcome.run.status, DesktopRunStatus::Queued);
    state
        .session_store
        .with_local_mcp_connection(|connection| recover_interrupted_runs(connection, &now_iso()))
        .expect("simulate startup recovery");

    let launched = resume_recovered_workspace_task_runs(Arc::clone(&state))
        .await
        .expect("resume pre-launch run");
    let callback = receive_terminal_callback(&mut callbacks).await;
    let duplicate_resume = resume_recovered_workspace_task_runs(Arc::clone(&state))
        .await
        .expect("idempotent recovery replay");

    assert_eq!(launched, 1);
    assert_eq!(duplicate_resume, 0);
    assert_eq!(callback["run_id"], "task-provider-run-recovery");
    let run = state
        .session_store
        .run("task-provider-run-recovery")
        .expect("run projection")
        .expect("same recovered run");
    assert_eq!(run.id, outcome.run.id);
    assert_eq!(state.agent_engine_attempts.load(Ordering::SeqCst), 1);
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

    let response = local_router(Arc::clone(&state))
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
async fn task_session_persists_and_replays_explicit_llm_route() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "local-runtime",
            "active",
            None,
            json!({
                "id": "local-runtime",
                "tenant_id": "local",
                "provider_type": "openai_compatible",
                "base_url": "http://127.0.0.1:19001/v1",
                "auth_method": "none",
                "is_active": true,
                "llm_model": "default-model",
                "allowed_models": ["default-model", "task-session-model"]
            }),
            chrono::Utc::now().timestamp_millis(),
        )
        .expect("seed active provider");
    {
        let mut runtime = state.provider_runtime.lock().expect("provider runtime");
        runtime.bindings.insert(
            crate::local_runtime::ProviderRuntimeKey {
                tenant_id: "local".to_string(),
                provider_id: "local-runtime".to_string(),
            },
            crate::local_runtime::ProviderRuntimeBinding {
                provider_type: "openai_compatible".to_string(),
                base_url: "http://127.0.0.1:19001/v1".to_string(),
                model: "default-model".to_string(),
                auth_method: "none".to_string(),
            },
        );
    }
    let (core_url, mut observations) = create_task_session_proxy_server().await;
    let generation = install(&state, &core_url);
    let app = local_router(Arc::clone(&state));
    let body = json!({
        "idempotency_key": "desktop-task-session-route",
        "workspace": {"kind": "existing", "workspace_id": "local-workspace"},
        "conversation": {
            "title": "Routed task session",
            "capability_mode": "code"
        },
        "initial_message": {"content": "Create a routed task session"},
        "workspace_policy": {
            "expected_revision": 0,
            "route": {
                "provider_id": "local-runtime",
                "model_id": "task-session-model"
            },
            "reasoning_effort": "medium",
            "permission_mode": "ask"
        }
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
            .expect("task-session route request")
    };

    let first = app
        .clone()
        .oneshot(request())
        .await
        .expect("first response");
    assert_eq!(first.status(), StatusCode::CREATED);
    let first_body = to_bytes(first.into_body(), 1024 * 1024)
        .await
        .expect("first response body");
    let first_value: Value = serde_json::from_slice(&first_body).expect("first response JSON");
    let conversation_id = first_value["conversation"]["id"]
        .as_str()
        .expect("conversation id")
        .to_string();
    assert_eq!(
        first_value["conversation"]["agent_config"]["llm_route_override"],
        json!({"provider_id": "local-runtime", "model_id": "task-session-model"})
    );
    assert_eq!(
        first_value["conversation"]["agent_config"]["llm_model_override"],
        "task-session-model"
    );
    assert_eq!(
        first_value["policy"]["roles"]["coding"]["model_id"],
        "task-session-model"
    );
    assert_eq!(
        state
            .session_store
            .conversation_llm_route(&conversation_id)
            .expect("persisted task-session route"),
        Some(LlmRouteTarget {
            provider_id: "local-runtime".to_string(),
            model_id: "task-session-model".to_string(),
        })
    );
    let (_, _, core_body) = observations.recv().await.expect("first Core request");
    let core_request: Value = serde_json::from_slice(&core_body).expect("Core request JSON");
    assert_eq!(
        core_request["workspace_policy"]["route"]["model_id"],
        "task-session-model"
    );

    clear_authority(&state, generation);
    let second = app.oneshot(request()).await.expect("replay response");
    assert_eq!(second.status(), StatusCode::OK);
    let second_body = to_bytes(second.into_body(), 1024 * 1024)
        .await
        .expect("replay response body");
    let second_value: Value = serde_json::from_slice(&second_body).expect("replay response JSON");
    assert_eq!(second_value["replayed"], true);
    assert_eq!(
        second_value["conversation"]["agent_config"]["llm_model_override"],
        "task-session-model"
    );
    assert_eq!(
        state
            .session_store
            .conversation_llm_route(&conversation_id)
            .expect("persisted task-session route after replay"),
        Some(LlmRouteTarget {
            provider_id: "local-runtime".to_string(),
            model_id: "task-session-model".to_string(),
        })
    );
    assert!(observations.try_recv().is_err());
}

#[tokio::test]
async fn task_session_without_explicit_policy_does_not_infer_an_active_provider_route() {
    let state = state();
    state
        .session_store
        .seed_test_session("desktop-session")
        .expect("desktop session");
    let (core_url, _observations) = create_task_session_proxy_server().await;
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
                        "idempotency_key": "desktop-task-session-without-policy",
                        "workspace": {"kind": "existing", "workspace_id": "local-workspace"},
                        "conversation": {
                            "title": "Unrouted task session",
                            "capability_mode": "work"
                        },
                        "initial_message": {"content": "Do not infer a route"}
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
        .expect("response body");
    let response_value: Value = serde_json::from_slice(&response_body).expect("response JSON");
    let conversation_id = response_value["conversation"]["id"]
        .as_str()
        .expect("conversation id");
    assert_eq!(
        response_value["conversation"]["agent_config"]["llm_route_override"],
        Value::Null
    );
    assert_eq!(
        state
            .session_store
            .conversation_llm_route(conversation_id)
            .expect("task-session route"),
        None
    );
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
async fn workspace_task_terminal_404_stops_chain_and_remains_pending() {
    let state = state();
    let (core_url, _server, mut observations) =
        task_terminal_stage_server(StatusCode::NOT_FOUND, StatusCode::OK, StatusCode::OK).await;
    install(&state, &core_url);

    let (status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        task_provider_request(
            "task-provider-run-terminal-404",
            "task-provider-conversation-terminal-404",
        ),
    )
    .await;
    let pending =
        wait_for_pending_terminal_callback(&state, "task-provider-run-terminal-404", 3).await;
    let observed = receive_terminal_observations(&mut observations, 3).await;

    assert_eq!(status, StatusCode::OK);
    assert!(observed
        .iter()
        .all(|observation| observation.stage == TaskTerminalStage::Terminal));
    assert_eq!(pending.attempt_count, 3);
    assert!(pending
        .last_error
        .as_deref()
        .is_some_and(|error| error.contains("404")));
    assert!(observations.try_recv().is_err());
}

#[tokio::test]
async fn workspace_task_provider_callback_409_replays_exact_payload_before_ack() {
    let state = state();
    let (core_url, server, mut observations) =
        task_terminal_stage_server(StatusCode::OK, StatusCode::CONFLICT, StatusCode::OK).await;
    install(&state, &core_url);

    let (status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        task_provider_request(
            "task-provider-run-callback-409",
            "task-provider-conversation-callback-409",
        ),
    )
    .await;
    let pending =
        wait_for_pending_terminal_callback(&state, "task-provider-run-callback-409", 3).await;
    let failed = receive_terminal_observations(&mut observations, 6).await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        failed
            .iter()
            .map(|observation| observation.stage)
            .collect::<Vec<_>>(),
        vec![
            TaskTerminalStage::Terminal,
            TaskTerminalStage::Callback,
            TaskTerminalStage::Terminal,
            TaskTerminalStage::Callback,
            TaskTerminalStage::Terminal,
            TaskTerminalStage::Callback,
        ]
    );
    assert_eq!(failed[0].body, failed[2].body);
    assert_eq!(failed[2].body, failed[4].body);
    assert_eq!(failed[1].body, failed[3].body);
    assert_eq!(failed[3].body, failed[5].body);
    assert!(pending
        .last_error
        .as_deref()
        .is_some_and(|error| error.contains("409")));

    server
        .set_statuses(StatusCode::OK, StatusCode::OK, StatusCode::OK)
        .await;
    let delivered = replay_pending_terminal_callbacks(Arc::clone(&state))
        .await
        .expect("replay terminal callback after Provider recovery");
    let replayed = receive_terminal_observations(&mut observations, 3).await;

    assert_eq!(delivered, 1);
    assert_eq!(
        replayed
            .iter()
            .map(|observation| observation.stage)
            .collect::<Vec<_>>(),
        vec![
            TaskTerminalStage::Terminal,
            TaskTerminalStage::Callback,
            TaskTerminalStage::Acknowledgement,
        ]
    );
    assert_eq!(replayed[0].body, failed[0].body);
    assert_eq!(replayed[1].body, failed[1].body);
    assert!(state
        .session_store
        .pending_workspace_core_terminal_callbacks(10)
        .expect("drained terminal callbacks")
        .is_empty());
}

#[tokio::test]
async fn workspace_task_ack_410_replays_full_chain_until_success() {
    let state = state();
    let (core_url, server, mut observations) =
        task_terminal_stage_server(StatusCode::OK, StatusCode::OK, StatusCode::GONE).await;
    install(&state, &core_url);

    let (status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        task_provider_request(
            "task-provider-run-ack-410",
            "task-provider-conversation-ack-410",
        ),
    )
    .await;
    let pending = wait_for_pending_terminal_callback(&state, "task-provider-run-ack-410", 3).await;
    let failed = receive_terminal_observations(&mut observations, 9).await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        failed
            .iter()
            .map(|observation| observation.stage)
            .collect::<Vec<_>>(),
        vec![
            TaskTerminalStage::Terminal,
            TaskTerminalStage::Callback,
            TaskTerminalStage::Acknowledgement,
            TaskTerminalStage::Terminal,
            TaskTerminalStage::Callback,
            TaskTerminalStage::Acknowledgement,
            TaskTerminalStage::Terminal,
            TaskTerminalStage::Callback,
            TaskTerminalStage::Acknowledgement,
        ]
    );
    assert!(pending
        .last_error
        .as_deref()
        .is_some_and(|error| error.contains("410")));

    server
        .set_statuses(StatusCode::OK, StatusCode::OK, StatusCode::OK)
        .await;
    let delivered = replay_pending_terminal_callbacks(Arc::clone(&state))
        .await
        .expect("replay terminal callback after acknowledgement recovery");
    let replayed = receive_terminal_observations(&mut observations, 3).await;

    assert_eq!(delivered, 1);
    assert_eq!(replayed[0].body, failed[0].body);
    assert_eq!(replayed[1].body, failed[1].body);
    assert_eq!(replayed[2].body, failed[2].body);
    assert!(state
        .session_store
        .pending_workspace_core_terminal_callbacks(10)
        .expect("drained terminal callbacks")
        .is_empty());
}

#[tokio::test]
async fn workspace_task_crash_gap_rebuilds_terminal_callback_from_timeline_once() {
    let state = state();
    let (core_url, server, mut observations) = task_terminal_stage_server(
        StatusCode::SERVICE_UNAVAILABLE,
        StatusCode::OK,
        StatusCode::OK,
    )
    .await;
    install(&state, &core_url);

    let (status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        task_provider_request(
            "task-provider-run-crash-gap",
            "task-provider-conversation-crash-gap",
        ),
    )
    .await;
    let pending =
        wait_for_pending_terminal_callback(&state, "task-provider-run-crash-gap", 3).await;
    let failed = receive_terminal_observations(&mut observations, 3).await;
    let persisted_run = state
        .session_store
        .run(&pending.run_id)
        .expect("load persisted Workspace Task run")
        .expect("persisted Workspace Task run");
    assert_eq!(persisted_run.status, DesktopRunStatus::ReadyReview);
    assert_eq!(
        persisted_run.authorization_snapshot["source"],
        "workspace_task_dispatch"
    );
    assert_eq!(persisted_run.message_id, pending.run_id);
    let (boundary_position, terminal_position, terminal_type) = state
        .session_store
        .with_local_mcp_connection(|connection| {
            let boundary_position = connection
                .query_row(
                    "SELECT position FROM desktop_timeline
                     WHERE conversation_id = ?1
                       AND json_extract(value_json, '$.type') = 'user_message'
                       AND json_extract(value_json, '$.message_id') = ?2",
                    [&persisted_run.conversation_id, &persisted_run.message_id],
                    |row| row.get::<_, i64>(0),
                )
                .map_err(|error| error.to_string())?;
            let (terminal_position, terminal_type) = connection
                .query_row(
                    "SELECT position, json_extract(value_json, '$.type')
                     FROM desktop_timeline
                     WHERE conversation_id = ?1 AND position > ?2
                       AND json_extract(value_json, '$.type') IN (
                         'assistant_message', 'error', 'provider_aborted'
                       )
                     ORDER BY position ASC LIMIT 1",
                    rusqlite::params![persisted_run.conversation_id, boundary_position],
                    |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?)),
                )
                .map_err(|error| error.to_string())?;
            Ok((boundary_position, terminal_position, terminal_type))
        })
        .expect("load persisted Workspace Task timeline boundary");
    assert!(terminal_position > boundary_position);
    assert_eq!(terminal_type, "assistant_message");
    let expected_callback_body =
        serde_json::to_vec(&pending.payload).expect("encode persisted callback payload");
    state
        .session_store
        .with_local_mcp_connection(|connection| {
            connection
                .execute(
                    "DELETE FROM desktop_workspace_core_terminal_callbacks WHERE id = ?1",
                    [&pending.id],
                )
                .map(|_| ())
                .map_err(|error| error.to_string())
        })
        .expect("simulate callback outbox crash gap");
    let recoveries = state
        .session_store
        .workspace_task_terminals_missing_callbacks()
        .expect("find callback outbox crash gap");
    assert_eq!(recoveries.len(), 1);
    assert_eq!(recoveries[0].run_id, pending.run_id);
    server
        .set_statuses(StatusCode::OK, StatusCode::OK, StatusCode::OK)
        .await;

    let delivered = replay_pending_terminal_callbacks(Arc::clone(&state))
        .await
        .expect("rebuild and replay terminal callback");
    let replayed = receive_terminal_observations(&mut observations, 3).await;
    let terminal: Value = serde_json::from_slice(&replayed[0].body).expect("terminal proof JSON");

    assert_eq!(status, StatusCode::OK);
    assert!(failed
        .iter()
        .all(|observation| observation.stage == TaskTerminalStage::Terminal));
    assert_eq!(delivered, 1);
    assert_eq!(
        replayed
            .iter()
            .map(|observation| observation.stage)
            .collect::<Vec<_>>(),
        vec![
            TaskTerminalStage::Terminal,
            TaskTerminalStage::Callback,
            TaskTerminalStage::Acknowledgement,
        ]
    );
    assert_eq!(replayed[1].body, expected_callback_body);
    assert_eq!(terminal["terminal_event_id"], pending.id);
    assert_eq!(
        terminal["terminal_message_id"],
        pending.payload["payload"]["terminal_message_id"]
    );
    assert!(state
        .session_store
        .pending_workspace_core_terminal_callbacks(10)
        .expect("drained rebuilt terminal callback")
        .is_empty());
    assert_eq!(
        replay_pending_terminal_callbacks(Arc::clone(&state))
            .await
            .expect("idempotent completed replay"),
        0
    );
    assert!(observations.try_recv().is_err());
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
async fn terminal_callback_gone_response_remains_pending() {
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
    .expect("gone pending marker deadline");

    assert_eq!(status, StatusCode::OK);
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].attempt_count, 3);
    assert!(pending[0]
        .last_error
        .as_deref()
        .is_some_and(|error| error.contains("410")));
}

async fn callback_server() -> (String, mpsc::Receiver<Value>) {
    callback_server_with_status(StatusCode::OK).await
}

async fn task_core_server() -> (String, mpsc::Receiver<Value>) {
    let (sender, receiver) = mpsc::channel(32);
    let sender = Arc::new((sender, AtomicUsize::new(0)));

    async fn terminal(
        State(state): State<Arc<(mpsc::Sender<Value>, AtomicUsize)>>,
        headers: HeaderMap,
        Json(body): Json<Value>,
    ) -> Json<Value> {
        assert_eq!(headers["authorization"], "Bearer service-token");
        assert_eq!(headers["x-memstack-tenant-id"], "local");
        assert_eq!(state.1.fetch_add(1, Ordering::SeqCst), 0);
        assert_eq!(body["project_id"], "local-project");
        assert_eq!(body["workspace_id"], "local-workspace");
        assert_eq!(body["execution_status"], "complete");
        assert!(body["terminal_message_id"].as_str().is_some());
        assert!(body["terminal_event_id"].as_str().is_some());
        assert_eq!(body["report"]["provider_state"], "final");
        Json(json!({
            "correlation_id": "task-provider-run-1",
            "status": "completed",
            "outbox_id": "runtime-outbox-task-provider-run-1",
            "terminal_id": "runtime-terminal-task-provider-run-1",
            "report_hash": "0".repeat(64),
            "created": true,
        }))
    }

    async fn callback(
        State(state): State<Arc<(mpsc::Sender<Value>, AtomicUsize)>>,
        headers: HeaderMap,
        Json(body): Json<Value>,
    ) -> Json<Value> {
        assert_eq!(headers["authorization"], "Bearer event-token");
        assert_eq!(state.1.fetch_add(1, Ordering::SeqCst), 1);
        state.0.send(body).await.expect("record task callback");
        Json(json!({"delivered_count": 1, "failed_count": 0}))
    }

    async fn acknowledge(
        State(state): State<Arc<(mpsc::Sender<Value>, AtomicUsize)>>,
        headers: HeaderMap,
        Json(body): Json<Value>,
    ) -> Json<Value> {
        assert_eq!(headers["authorization"], "Bearer service-token");
        assert_eq!(headers["x-memstack-tenant-id"], "local");
        assert_eq!(state.1.fetch_add(1, Ordering::SeqCst), 2);
        assert_eq!(
            body,
            json!({
                "project_id": "local-project",
                "workspace_id": "local-workspace",
            })
        );
        Json(json!({
            "correlation_id": "task-provider-run-1",
            "status": "completed",
            "acknowledged": true,
        }))
    }

    async fn policy(headers: HeaderMap) -> Json<Value> {
        assert_eq!(headers["authorization"], "Bearer service-token");
        assert_eq!(headers["x-memstack-user-id"], "local-user");
        let route = json!({"provider_id": "provider-1", "model_id": "model-1"});
        Json(json!({
            "tenant_id": "local",
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "revision": 1,
            "roles": {
                "default": route,
                "fast": Value::Null,
                "coding": route,
                "vision": Value::Null
            },
            "fallbacks": [],
            "reasoning_effort": "medium",
            "permission_mode": "workspace_write",
            "capability_version": "workspace-agent-policy-v1",
            "updated_at": "2026-08-14T00:00:00Z"
        }))
    }

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind task Core server");
    let address = listener.local_addr().expect("task Core address");
    tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new()
                .route(
                    "/internal/v1/runtime-correlations/:correlation_id/terminal",
                    post(terminal),
                )
                .route("/bot/events", post(callback))
                .route(
                    "/internal/v1/runtime-correlations/:correlation_id/callback-ack",
                    post(acknowledge),
                )
                .route(
                    "/api/v1/tenants/local/projects/local-project/workspaces/local-workspace/agent-policy",
                    get(policy),
                )
                .with_state(sender),
        )
        .await
        .expect("task Core server");
    });
    (format!("http://{address}"), receiver)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TaskTerminalStage {
    Terminal,
    Callback,
    Acknowledgement,
}

#[derive(Debug)]
struct TaskTerminalObservation {
    stage: TaskTerminalStage,
    body: Vec<u8>,
}

#[derive(Clone, Copy)]
struct TaskTerminalStatuses {
    terminal: StatusCode,
    callback: StatusCode,
    acknowledgement: StatusCode,
}

struct TaskTerminalStageServer {
    statuses: Mutex<TaskTerminalStatuses>,
    observations: mpsc::Sender<TaskTerminalObservation>,
}

impl TaskTerminalStageServer {
    async fn set_statuses(
        &self,
        terminal: StatusCode,
        callback: StatusCode,
        acknowledgement: StatusCode,
    ) {
        *self.statuses.lock().await = TaskTerminalStatuses {
            terminal,
            callback,
            acknowledgement,
        };
    }
}

async fn task_terminal_stage_server(
    terminal_status: StatusCode,
    callback_status: StatusCode,
    acknowledgement_status: StatusCode,
) -> (
    String,
    Arc<TaskTerminalStageServer>,
    mpsc::Receiver<TaskTerminalObservation>,
) {
    let (sender, receiver) = mpsc::channel(64);
    let state = Arc::new(TaskTerminalStageServer {
        statuses: Mutex::new(TaskTerminalStatuses {
            terminal: terminal_status,
            callback: callback_status,
            acknowledgement: acknowledgement_status,
        }),
        observations: sender,
    });

    async fn terminal(
        State(state): State<Arc<TaskTerminalStageServer>>,
        headers: HeaderMap,
        body: axum::body::Bytes,
    ) -> StatusCode {
        assert_eq!(headers["authorization"], "Bearer service-token");
        assert_eq!(headers["x-memstack-tenant-id"], "local");
        state
            .observations
            .send(TaskTerminalObservation {
                stage: TaskTerminalStage::Terminal,
                body: body.to_vec(),
            })
            .await
            .expect("record terminal proof");
        state.statuses.lock().await.terminal
    }

    async fn callback(
        State(state): State<Arc<TaskTerminalStageServer>>,
        headers: HeaderMap,
        body: axum::body::Bytes,
    ) -> StatusCode {
        assert_eq!(headers["authorization"], "Bearer event-token");
        assert_eq!(
            headers["bcn-provider-id"],
            "memstack-workspace-agent-runtime"
        );
        state
            .observations
            .send(TaskTerminalObservation {
                stage: TaskTerminalStage::Callback,
                body: body.to_vec(),
            })
            .await
            .expect("record Provider callback");
        state.statuses.lock().await.callback
    }

    async fn acknowledge(
        State(state): State<Arc<TaskTerminalStageServer>>,
        headers: HeaderMap,
        body: axum::body::Bytes,
    ) -> StatusCode {
        assert_eq!(headers["authorization"], "Bearer service-token");
        assert_eq!(headers["x-memstack-tenant-id"], "local");
        state
            .observations
            .send(TaskTerminalObservation {
                stage: TaskTerminalStage::Acknowledgement,
                body: body.to_vec(),
            })
            .await
            .expect("record callback acknowledgement");
        state.statuses.lock().await.acknowledgement
    }

    async fn policy(headers: HeaderMap) -> Json<Value> {
        assert_eq!(headers["authorization"], "Bearer service-token");
        assert_eq!(headers["x-memstack-user-id"], "local-user");
        let route = json!({"provider_id": "provider-1", "model_id": "model-1"});
        Json(json!({
            "tenant_id": "local",
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "revision": 1,
            "roles": {
                "default": route,
                "fast": Value::Null,
                "coding": route,
                "vision": Value::Null
            },
            "fallbacks": [],
            "reasoning_effort": "medium",
            "permission_mode": "workspace_write",
            "capability_version": "workspace-agent-policy-v1",
            "updated_at": "2026-08-14T00:00:00Z"
        }))
    }

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind staged task Core server");
    let address = listener.local_addr().expect("staged task Core address");
    let server_state = Arc::clone(&state);
    tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new()
                .route(
                    "/internal/v1/runtime-correlations/:correlation_id/terminal",
                    post(terminal),
                )
                .route("/bot/events", post(callback))
                .route(
                    "/internal/v1/runtime-correlations/:correlation_id/callback-ack",
                    post(acknowledge),
                )
                .route(
                    "/api/v1/tenants/local/projects/local-project/workspaces/local-workspace/agent-policy",
                    get(policy),
                )
                .with_state(server_state),
        )
        .await
        .expect("staged task Core server");
    });
    (format!("http://{address}"), state, receiver)
}

async fn wait_for_pending_terminal_callback(
    state: &LocalRuntimeState,
    run_id: &str,
    minimum_attempts: u64,
) -> DesktopWorkspaceCoreTerminalCallback {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let pending = state
                .session_store
                .pending_workspace_core_terminal_callbacks(10)
                .expect("pending terminal callbacks");
            if let Some(callback) = pending.into_iter().find(|callback| {
                callback.run_id == run_id && callback.attempt_count >= minimum_attempts
            }) {
                return callback;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("pending terminal callback deadline")
}

async fn receive_terminal_observations(
    observations: &mut mpsc::Receiver<TaskTerminalObservation>,
    count: usize,
) -> Vec<TaskTerminalObservation> {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let mut received = Vec::with_capacity(count);
        while received.len() < count {
            received.push(
                observations
                    .recv()
                    .await
                    .expect("terminal stage observation"),
            );
        }
        received
    })
    .await
    .expect("terminal stage observation deadline")
}

async fn receive_terminal_callback(callbacks: &mut mpsc::Receiver<Value>) -> Value {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let callback = callbacks.recv().await.expect("task callback");
            if matches!(
                callback["payload"]["state"].as_str(),
                Some("final" | "error" | "aborted")
            ) {
                return callback;
            }
        }
    })
    .await
    .expect("task terminal callback deadline")
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
