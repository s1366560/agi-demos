use std::{
    collections::BTreeMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
};

use super::*;
use crate::application_vault::ApplicationCredentialVault;
use crate::local_runtime::local_router_with_generation_required;
use crate::trusted_session::{
    TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
    TrustedSessionRuntimeMode,
};
use agistack_core::knowledge::sync::KnowledgeSyncLink;
use axum::{
    body::{to_bytes, Body},
    extract::{Path, State},
    http::{HeaderMap, Request, StatusCode},
    routing::{get, post},
    Json, Router,
};
use tower::ServiceExt;

#[derive(Default)]
struct Cloud {
    requests: Mutex<Vec<String>>,
    receipts: Mutex<BTreeMap<String, Value>>,
    conflicts: Mutex<BTreeMap<String, Value>>,
    fail_next: AtomicBool,
    wrong_actor: AtomicBool,
    conflict_next: AtomicBool,
}

fn check_auth(headers: &HeaderMap) {
    assert_eq!(headers["authorization"], "Bearer cloud-test-credential");
}
async fn user(State(cloud): State<Arc<Cloud>>, headers: HeaderMap) -> Json<Value> {
    check_auth(&headers);
    let mut user = super::sync_auth_tests::auth_me_fixture();
    if cloud.wrong_actor.load(Ordering::SeqCst) {
        user["user_id"] = json!("wrong");
    }
    Json(user)
}
async fn project(headers: HeaderMap) -> Json<Value> {
    check_auth(&headers);
    Json(json!({"id":"remote-project","tenant_id":"remote-tenant"}))
}
async fn mutate(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    body: String,
) -> (StatusCode, Json<Value>) {
    check_auth(&headers);
    cloud.requests.lock().unwrap().push(body.clone());
    let request: Value = serde_json::from_str(&body).unwrap();
    let id = request["change_id"].as_str().unwrap().to_string();
    let mut receipts = cloud.receipts.lock().unwrap();
    let existing = receipts.contains_key(&id);
    let receipt = if let Some(existing) = receipts.get(&id) {
        existing.clone()
    } else if cloud.conflict_next.swap(false, Ordering::SeqCst) {
        let conflict_id = Uuid::new_v4().to_string();
        let mut proposed = request.clone();
        proposed.as_object_mut().unwrap().remove("change_id");
        let current = json!({"memory_id":request["memory_id"],"revision":7,"deleted":true,"author_id":"remote-actor","created_at_ms":100,"content":{"title":"remote deleted","content":"remote copy","content_type":"text","tags":[],"status":"ENABLED","metadata":{"remote":["preserved"]}}});
        cloud.conflicts.lock().unwrap().insert(conflict_id.clone(),json!({"id":conflict_id,"memory_id":request["memory_id"],"proposed":proposed,"current":current,"resolved_change_id":null}));
        json!({"change_id":id,"status":"conflict","conflict_id":conflict_id})
    } else {
        json!({"change_id":id,"status":"applied","sequence":receipts.len()+1,"version":{"memory_id":request["memory_id"],"revision":request["expected_revision"].as_u64().unwrap()+1,"deleted":false,"author_id":"remote-actor","created_at_ms":100,"content":request["content"],"remote_extra":{"retained":true}}})
    };
    receipts.insert(id, receipt.clone());
    if cloud.fail_next.swap(false, Ordering::SeqCst) {
        return (
            StatusCode::BAD_GATEWAY,
            Json(json!({"error":"response lost after commit"})),
        );
    }
    (
        if receipt["status"] == "conflict" {
            StatusCode::CONFLICT
        } else {
            StatusCode::OK
        },
        Json(json!({"receipt":receipt,"replayed":existing})),
    )
}
async fn conflict(
    State(cloud): State<Arc<Cloud>>,
    Path(id): Path<String>,
    headers: HeaderMap,
) -> Json<Value> {
    check_auth(&headers);
    Json(cloud.conflicts.lock().unwrap()[&id].clone())
}

async fn cloud() -> (Arc<Cloud>, String, tokio::task::JoinHandle<()>) {
    let cloud = Arc::new(Cloud::default());
    let app = Router::new()
        .route("/api/v1/auth/me", get(user))
        .route("/api/v1/projects/remote-project", get(project))
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/mutations",
            post(mutate),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/conflicts/:id",
            get(conflict),
        )
        .with_state(Arc::clone(&cloud));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (cloud, base, task)
}
pub(super) fn install_broker(
    state: &LocalRuntimeState,
    directory: &TestDirectory,
    base: String,
) -> TrustedSessionBroker {
    let broker = TrustedSessionBroker::native(
        ApplicationCredentialVault::open(&directory.0.join("test-vault")).unwrap(),
    );
    broker
        .save(TrustedSessionRecord {
            version: 1,
            api_base_url: base,
            runtime_mode: TrustedSessionRuntimeMode::Cloud,
            credential_kind: TrustedSessionCredentialKind::CloudBearer,
            credential: "cloud-test-credential".into(),
            expires_at: None,
        })
        .unwrap();
    state
        .platform_plugin_authority_v2
        .install_trusted_sessions(broker.clone());
    broker
}
pub(super) async fn setup(
    state: &LocalRuntimeState,
) -> (KnowledgeOperationV2, KnowledgeOperationScopeV2) {
    let auth = authenticated(state);
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let scope = operation_scope(&auth, &lease);
    let operation = KnowledgeOperationV2::admit(lease, &auth, &scope).unwrap();
    operation
        .configure_sync_link(KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: "remote-actor".into(),
        })
        .await
        .unwrap();
    operation.mutate("create", mutation(&auth)).await.unwrap();
    (operation, scope)
}
pub(super) async fn push(state: Arc<LocalRuntimeState>, body: Value) -> (StatusCode, Value) {
    let response = local_router_with_generation_required(state)
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/knowledge/sync-push")
                .header("content-type", "application/json")
                .header("x-agistack-launch", TOKEN)
                .header("authorization", format!("Bearer {TOKEN}"))
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

#[tokio::test]
async fn trusted_http_replays_after_lost_response_without_overwriting_later_local_edit() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    assert_eq!(
        push(Arc::clone(&state), json!({"scope":scope})).await.0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    let (cloud, base, task) = cloud().await;
    install_broker(&state, &directory, base);
    assert_eq!(
        push(
            Arc::clone(&state),
            json!({"scope":scope,"receipt":{"status":"applied"}})
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    cloud.wrong_actor.store(true, Ordering::SeqCst);
    assert_eq!(
        push(Arc::clone(&state), json!({"scope":scope})).await.0,
        StatusCode::FORBIDDEN
    );
    assert!(cloud.requests.lock().unwrap().is_empty());
    cloud.wrong_actor.store(false, Ordering::SeqCst);
    cloud.fail_next.store(true, Ordering::SeqCst);
    assert_eq!(
        push(Arc::clone(&state), json!({"scope":scope})).await.0,
        StatusCode::BAD_GATEWAY
    );
    let mut memory = operation
        .get("knowledge-test-memory")
        .await
        .unwrap()
        .unwrap();
    memory.content = "later local edit".into();
    operation
        .mutate(
            "edit",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
    let success = push(Arc::clone(&state), json!({"scope":scope})).await;
    assert_eq!(success.0, StatusCode::OK);
    assert_eq!(success.1["result"]["receipt"]["version"]["revision"], 1);
    let requests = cloud.requests.lock().unwrap().clone();
    assert_eq!(requests.len(), 2);
    assert_eq!(requests[0], requests[1]);
    assert_eq!(
        operation
            .get("knowledge-test-memory")
            .await
            .unwrap()
            .unwrap()
            .content,
        "later local edit"
    );
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
    assert_eq!(
        operation
            .remote_baseline("knowledge-test-memory")
            .await
            .unwrap()
            .unwrap()["remote_extra"],
        json!({"retained":true})
    );
    assert_eq!(
        push(Arc::clone(&state), json!({"scope":scope})).await.0,
        StatusCode::OK
    );
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 0);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    task.abort();
}

#[tokio::test]
async fn cloud_conflict_snapshot_is_fetched_and_other_objects_can_continue() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, task) = cloud().await;
    install_broker(&state, &directory, base);
    cloud.conflict_next.store(true, Ordering::SeqCst);
    let result = push(Arc::clone(&state), json!({"scope":scope})).await;
    assert_eq!(result.0, StatusCode::OK);
    assert_eq!(result.1["result"]["receipt"]["status"], "conflict");
    let conflicts = operation.push_conflicts(20).await.unwrap();
    assert_eq!(conflicts.len(), 1);
    assert_eq!(
        conflicts[0]["current"]["content"]["metadata"],
        json!({"remote":["preserved"]})
    );
    assert_eq!(conflicts[0]["current"]["deleted"], true);
    let MemoryMutation::Create { mut memory } = mutation(&authenticated(&state)) else {
        panic!("create fixture")
    };
    memory.id = "another-memory".into();
    operation
        .mutate("another", MemoryMutation::Create { memory })
        .await
        .unwrap();
    assert_eq!(
        push(Arc::clone(&state), json!({"scope":scope})).await.0,
        StatusCode::OK
    );
    {
        let requests = cloud.requests.lock().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&requests[1]).unwrap()["memory_id"],
            "another-memory"
        );
    }
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
    assert!(operation
        .get("knowledge-test-memory")
        .await
        .unwrap()
        .is_some());
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    task.abort();
}
