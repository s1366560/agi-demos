//! End-to-end graph record sync over the native RPCs against a strict mock cloud.
use std::sync::Mutex;

use super::*;
use crate::local_runtime::local_router_with_generation_required;
use agistack_core::knowledge::processing::ProcessingRepository;
use agistack_core::knowledge::sync::graph::{
    KnowledgeGraphPushRepository, KnowledgeGraphSyncReadRepository,
};
use agistack_core::Entity;
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
    mutations: Mutex<Vec<String>>,
    conflicts: Mutex<std::collections::BTreeMap<String, Value>>,
    resolutions: Mutex<Vec<String>>,
    conflict_next: std::sync::atomic::AtomicBool,
    events: Mutex<Vec<Value>>,
}

fn check_auth(headers: &HeaderMap) {
    assert_eq!(headers["authorization"], "Bearer cloud-test-credential");
}
async fn user(headers: HeaderMap) -> Json<Value> {
    check_auth(&headers);
    Json(super::sync_auth_tests::auth_me_fixture())
}
async fn project(headers: HeaderMap) -> Json<Value> {
    check_auth(&headers);
    Json(json!({"id":"remote-project","tenant_id":"remote-tenant"}))
}
async fn memory_mutate(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    body: String,
) -> (StatusCode, Json<Value>) {
    check_auth(&headers);
    cloud.mutations.lock().unwrap().push(body.clone());
    let request: Value = serde_json::from_str(&body).unwrap();
    let id = request["change_id"].as_str().unwrap().to_string();
    (
        StatusCode::OK,
        Json(json!({
            "receipt": {
                "change_id": id,
                "status": "applied",
                "sequence": 1,
                "version": {
                    "memory_id": request["memory_id"],
                    "revision": request["expected_revision"].as_u64().unwrap() + 1,
                    "deleted": false,
                    "author_id": "remote-actor",
                    "created_at_ms": 100,
                    "content": request["content"]
                }
            },
            "replayed": false
        })),
    )
}
async fn graph_mutate(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    body: String,
) -> (StatusCode, Json<Value>) {
    check_auth(&headers);
    cloud.mutations.lock().unwrap().push(body.clone());
    let request: Value = serde_json::from_str(&body).unwrap();
    let id = request["change_id"].as_str().unwrap().to_string();
    let receipt = if cloud.conflict_next.swap(false, std::sync::atomic::Ordering::SeqCst) {
        let conflict_id = Uuid::new_v4().to_string();
        let mut proposed = request.clone();
        proposed.as_object_mut().unwrap().remove("change_id");
        let current = json!({
            "object_id": request["object_id"],
            "revision": 3,
            "deleted": false,
            "author_id": "remote-actor",
            "created_at_ms": 100,
            "content": {
                "source_revision": 1,
                "change_sequence": 9,
                "audit_attempt": 1,
                "entities": [{"name": "Cloud", "kind": "Person"}],
                "relationships": []
            }
        });
        cloud.conflicts.lock().unwrap().insert(
            conflict_id.clone(),
            json!({"id":conflict_id,"object_id":request["object_id"],"proposed":proposed,"current":current,"resolved_change_id":null}),
        );
        json!({"change_id":id,"status":"conflict","conflict_id":conflict_id})
    } else {
        json!({
            "change_id": id,
            "status": "applied",
            "sequence": 11,
            "version": {
                "object_id": request["object_id"],
                "revision": request["expected_revision"].as_u64().unwrap() + 1,
                "deleted": false,
                "author_id": "remote-actor",
                "created_at_ms": 100,
                "content": request["content"]
            }
        })
    };
    (
        if receipt["status"] == "conflict" {
            StatusCode::CONFLICT
        } else {
            StatusCode::OK
        },
        Json(json!({"receipt":receipt,"replayed":false})),
    )
}
async fn graph_conflict(
    State(cloud): State<Arc<Cloud>>,
    Path(id): Path<String>,
    headers: HeaderMap,
) -> Json<Value> {
    check_auth(&headers);
    Json(cloud.conflicts.lock().unwrap()[&id].clone())
}
async fn graph_resolve(
    State(cloud): State<Arc<Cloud>>,
    Path(id): Path<String>,
    headers: HeaderMap,
    body: String,
) -> Json<Value> {
    check_auth(&headers);
    cloud.resolutions.lock().unwrap().push(body.clone());
    let request: Value = serde_json::from_str(&body).unwrap();
    let mut conflicts = cloud.conflicts.lock().unwrap();
    let conflict = conflicts.get_mut(&id).unwrap();
    conflict["resolved_change_id"] = request["change_id"].clone();
    let current = conflict["current"].clone();
    Json(json!({
        "receipt": {
            "status": "resolved",
            "change_id": request["change_id"],
            "version": current,
            "conflict_id": id,
        },
        "replayed": false
    }))
}
async fn changes(headers: HeaderMap) -> Json<Value> {
    check_auth(&headers);
    Json(json!({"changes":[],"next_cursor":0,"has_more":false}))
}
async fn graph_changes(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
) -> Json<Value> {
    check_auth(&headers);
    let events = std::mem::take(&mut *cloud.events.lock().unwrap());
    let next = events.last().map_or(0, |event| event["sequence"].as_u64().unwrap());
    Json(json!({"changes":events,"next_cursor":next,"has_more":false}))
}

async fn cloud(events: Vec<Value>) -> (Arc<Cloud>, String, tokio::task::JoinHandle<()>) {
    let cloud = Arc::new(Cloud {
        events: Mutex::new(events),
        ..Cloud::default()
    });
    let app = Router::new()
        .route("/api/v1/projects/remote-project/knowledge-sync/enrollment", get(crate::local_runtime::knowledge_authority_v2::tests::sync_cloud_fixture::enrollment))
        .route("/api/v1/auth/me", get(user))
        .route("/api/v1/projects/remote-project", get(project))
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/changes",
            get(changes),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/mutations",
            post(memory_mutate),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/graph/changes",
            get(graph_changes),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/graph/mutations",
            post(graph_mutate),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/graph/conflicts/:id",
            get(graph_conflict),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/graph/conflicts/:id/resolve",
            post(graph_resolve),
        )
        .layer(axum::middleware::from_fn(crate::local_runtime::knowledge_authority_v2::tests::sync_cloud_fixture::require_generation))
        .with_state(Arc::clone(&cloud));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (cloud, base, task)
}

async fn rpc(state: Arc<LocalRuntimeState>, path: &str, body: Value) -> (StatusCode, Value) {
    let response = local_router_with_generation_required(state)
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header("content-type", "application/json")
                .header("x-agistack-launch", TOKEN)
                .header("authorization", format!("Bearer {TOKEN}"))
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (status, serde_json::from_slice(&body).unwrap_or(Value::Null))
}

async fn extract(operation: &KnowledgeOperationV2) {
    let repository = operation.authority.repository().unwrap();
    let lease = repository
        .claim(&operation.scope, "worker", 0, 100)
        .await
        .unwrap()
        .unwrap();
    repository
        .complete(
            &operation.scope,
            &lease,
            agistack_core::knowledge::processing::ProcessingProjection {
                entities: vec![
                    Entity {
                        name: "Alice".into(),
                        kind: "Person".into(),
                    },
                    Entity {
                        name: "Acme".into(),
                        kind: "Organization".into(),
                    },
                ],
                relationships: vec![
                    agistack_core::knowledge::processing::ProcessingRelationship {
                        source_index: 0,
                        target_index: 1,
                        relation_type: "WORKS_AT".into(),
                        fact: "Alice works at Acme".into(),
                        score: 0.8,
                    },
                ],
            },
            1,
        )
        .await
        .unwrap();
}

#[tokio::test]
async fn graph_push_rides_sync_push_after_the_memory_outbox_drains() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = super::push_http_tests::setup(&state).await;
    extract(&operation).await;
    let (cloud, base, server) = cloud(vec![]).await;
    super::push_http_tests::install_broker(&state, &directory, base);
    let first = rpc(
        Arc::clone(&state),
        "/api/v1/knowledge/sync-push",
        json!({"scope":scope}),
    )
    .await;
    assert_eq!(first.0, StatusCode::OK);
    assert_eq!(first.1["result"]["receipt"]["status"], "applied");
    let second = rpc(
        Arc::clone(&state),
        "/api/v1/knowledge/sync-push",
        json!({"scope":scope}),
    )
    .await;
    assert_eq!(second.0, StatusCode::OK);
    assert_eq!(second.1["result"]["receipt"]["status"], "applied");
    let sent: Vec<Value> = cloud
        .mutations
        .lock()
        .unwrap()
        .iter()
        .map(|body| serde_json::from_str(body).unwrap())
        .collect();
    assert_eq!(sent.len(), 2);
    assert!(sent[0]["memory_id"].is_string());
    assert_eq!(sent[1]["operation"], "create");
    assert_eq!(sent[1]["content"]["entities"][0]["name"], "Alice");
    assert_eq!(sent[1]["content"]["relationships"][0]["score"], 0.8);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}

#[tokio::test]
async fn graph_pull_rides_sync_pull_and_serves_the_synced_projection() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = super::push_http_tests::setup(&state).await;
    let events = vec![json!({
        "sequence": 1,
        "change_id": Uuid::new_v4().to_string(),
        "version": {
            "object_id": "cloud-memory",
            "revision": 1,
            "deleted": false,
            "author_id": "remote-actor",
            "created_at_ms": 100,
            "content": {
                "source_revision": 1,
                "change_sequence": 42,
                "audit_attempt": 1,
                "entities": [{"name": "Cloud", "kind": "Person"}],
                "relationships": []
            }
        }
    })];
    let (_cloud, base, server) = cloud(events).await;
    super::push_http_tests::install_broker(&state, &directory, base);
    let result = rpc(
        Arc::clone(&state),
        "/api/v1/knowledge/sync-pull",
        json!({"scope":scope}),
    )
    .await;
    assert_eq!(result.0, StatusCode::OK);
    assert_eq!(result.1["result"]["applied"], 1);
    let repository = operation.authority.repository().unwrap();
    let synced = repository
        .synced_graph_projection(&operation.scope, "cloud-memory")
        .await
        .unwrap()
        .unwrap();
    assert!(!synced.source_available);
    assert_eq!(synced.content.entities[0].name, "Cloud");
    let listed = rpc(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        json!({"scope":scope,"query":{"operation":"synced_graph_projections","limit":10,"offset":0}}),
    )
    .await;
    assert_eq!(listed.0, StatusCode::OK);
    assert_eq!(
        listed.1["result"]["items"][0]["object_id"],
        "cloud-memory"
    );
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}

#[tokio::test]
async fn graph_push_conflict_resolves_through_the_cloud_and_settles_locally() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = super::push_http_tests::setup(&state).await;
    extract(&operation).await;
    let (cloud, base, server) = cloud(vec![]).await;
    super::push_http_tests::install_broker(&state, &directory, base);
    cloud.conflict_next
        .store(true, std::sync::atomic::Ordering::SeqCst);
    let pushed = rpc(
        Arc::clone(&state),
        "/api/v1/knowledge/sync-push",
        json!({"scope":scope}),
    )
    .await;
    assert_eq!(pushed.0, StatusCode::OK);
    assert_eq!(pushed.1["result"]["receipt"]["status"], "applied");
    let repository = operation.authority.repository().unwrap();
    let conflicted = rpc(
        Arc::clone(&state),
        "/api/v1/knowledge/sync-push",
        json!({"scope":scope}),
    )
    .await;
    assert_eq!(conflicted.0, StatusCode::OK);
    assert_eq!(conflicted.1["result"]["receipt"]["status"], "conflict");
    let conflict_id = conflicted.1["result"]["receipt"]["conflict_id"]
        .as_str()
        .unwrap()
        .to_string();
    let conflicts = rpc(
        Arc::clone(&state),
        "/api/v1/knowledge/query",
        json!({"scope":scope,"query":{"operation":"graph_push_conflicts","limit":10}}),
    )
    .await;
    assert_eq!(conflicts.1["result"]["items"].as_array().unwrap().len(), 1);
    let resolved = rpc(
        Arc::clone(&state),
        "/api/v1/knowledge/sync-resolve-graph-push",
        json!({
            "scope": scope,
            "conflict_id": conflict_id,
            "change_id": Uuid::new_v4().to_string(),
            "expected_current_revision": 3,
            "decision": "keep_current",
            "content": Value::Null,
        }),
    )
    .await;
    assert_eq!(resolved.0, StatusCode::OK);
    assert_eq!(resolved.1["result"]["receipt"]["status"], "resolved");
    // The cloud version wins locally; the paused push is settled.
    let synced = repository
        .synced_graph_projection(&operation.scope, "knowledge-test-memory")
        .await
        .unwrap()
        .unwrap();
    assert_eq!(synced.content.entities[0].name, "Cloud");
    let remaining = repository
        .graph_push_conflicts(&operation.scope, 10)
        .await
        .unwrap();
    assert!(remaining.is_empty());
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}
