use super::push_http_tests::{install_broker, setup};
use super::*;
use crate::local_runtime::local_router_with_generation_required;
use axum::{
    body::{to_bytes, Body},
    extract::{Query, State},
    http::{HeaderMap, Request, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
};
use tokio::sync::Notify;
use tower::ServiceExt;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Phase {
    None,
    Auth,
    Project,
    Page,
    PageBody,
}
pub(super) struct Cloud {
    pub(super) phase: Phase,
    pub(super) entered: Notify,
    pub(super) release: Notify,
    pub(super) calls: Mutex<Vec<Phase>>,
    pub(super) cursors: Mutex<Vec<u64>>,
    pub(super) graph_cursors: Mutex<Vec<u64>>,
    pub(super) fail_next: AtomicBool,
    pub(super) malformed: AtomicBool,
    pub(super) wrong_actor: AtomicBool,
    pub(super) wrong_project: AtomicBool,
}
impl Cloud {
    async fn barrier(&self, phase: Phase, headers: &HeaderMap) {
        assert_eq!(headers["authorization"], "Bearer cloud-test-credential");
        self.calls.lock().unwrap().push(phase);
        if self.phase == phase {
            self.entered.notify_one();
            self.release.notified().await;
        }
    }
}
async fn auth(State(cloud): State<Arc<Cloud>>, headers: HeaderMap) -> Json<Value> {
    cloud.barrier(Phase::Auth, &headers).await;
    let mut user = super::sync_auth_tests::auth_me_fixture();
    if cloud.wrong_actor.load(Ordering::SeqCst) {
        user["user_id"] = json!("wrong");
    }
    Json(user)
}
async fn project(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
) -> Json<Value> {
    cloud.barrier(Phase::Project, &headers).await;
    assert_eq!(query.get("tenant_id").unwrap(), "remote-tenant");
    Json(
        json!({"id":"remote-project","tenant_id":if cloud.wrong_project.load(Ordering::SeqCst) {"wrong"} else {"remote-tenant"}}),
    )
}
async fn graph_changes(
    State(cloud): State<Arc<Cloud>>,
    Query(query): Query<HashMap<String, String>>,
) -> Response {
    assert_eq!(query.len(), 2);
    assert_eq!(query.get("limit").unwrap(), "1");
    let after: u64 = query.get("after").unwrap().parse().unwrap();
    cloud.graph_cursors.lock().unwrap().push(after);
    Json(json!({"changes":[],"next_cursor":0,"has_more":false})).into_response()
}
async fn changes(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
) -> Response {
    assert_eq!(query.len(), 2);
    assert_eq!(query.get("limit").unwrap(), "1");
    let after: u64 = query.get("after").unwrap().parse().unwrap();
    cloud.cursors.lock().unwrap().push(after);
    cloud.barrier(Phase::Page, &headers).await;
    if cloud.fail_next.swap(false, Ordering::SeqCst) {
        return (
            StatusCode::GATEWAY_TIMEOUT,
            Json(json!({"error":"temporary"})),
        )
            .into_response();
    }
    if cloud.malformed.load(Ordering::SeqCst) {
        return (
            StatusCode::OK,
            Json(json!({"changes":[],"next_cursor":99,"has_more":false})),
        )
            .into_response();
    }
    let items = if after == 0 {
        vec![
            json!({"sequence":4,"change_id":"00000000-0000-4000-8000-000000000004","version":{"memory_id":"remote-memory","revision":1,"deleted":false,"author_id":"remote-author","created_at_ms":100,"remote_extension":{"keep":true},"content":{"title":"remote title","content":"remote content","content_type":"text","tags":[],"metadata":{"retained":["remote"]},"status":"ENABLED"}}}),
        ]
    } else {
        vec![]
    };
    let page = json!({"changes":items,"next_cursor":4,"has_more":false});
    if cloud.phase == Phase::PageBody {
        // Response headers are sent while the JSON body is held in flight.
        let body = Body::from_stream(futures_util::stream::once(async move {
            cloud.calls.lock().unwrap().push(Phase::PageBody);
            cloud.entered.notify_one();
            cloud.release.notified().await;
            Ok::<_, std::convert::Infallible>(page.to_string())
        }));
        return Response::builder()
            .header("content-type", "application/json")
            .body(body)
            .unwrap();
    }
    Json(page).into_response()
}
pub(super) async fn cloud(phase: Phase) -> (Arc<Cloud>, String, tokio::task::JoinHandle<()>) {
    let cloud = Arc::new(Cloud {
        phase,
        entered: Notify::new(),
        release: Notify::new(),
        calls: Mutex::new(vec![]),
        cursors: Mutex::new(vec![]),
        graph_cursors: Mutex::new(vec![]),
        fail_next: AtomicBool::new(false),
        malformed: AtomicBool::new(false),
        wrong_actor: AtomicBool::new(false),
        wrong_project: AtomicBool::new(false),
    });
    let app = Router::new()
        .route("/api/v1/projects/remote-project/knowledge-sync/enrollment", get(crate::local_runtime::knowledge_authority_v2::tests::sync_cloud_fixture::enrollment))
        .route("/api/v1/auth/me", get(auth))
        .route("/api/v1/projects/remote-project", get(project))
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/changes",
            get(changes),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/graph/changes",
            get(graph_changes),
        )
        .layer(axum::middleware::from_fn(crate::local_runtime::knowledge_authority_v2::tests::sync_cloud_fixture::require_generation))
        .with_state(Arc::clone(&cloud));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (cloud, base, server)
}
pub(super) async fn request(
    state: Arc<LocalRuntimeState>,
    path: &str,
    body: Value,
) -> (StatusCode, Value) {
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
pub(super) async fn pull(
    state: Arc<LocalRuntimeState>,
    scope: KnowledgeOperationScopeV2,
) -> (StatusCode, Value) {
    request(state, "/api/v1/knowledge/sync-pull", json!({"scope":scope})).await
}
#[tokio::test]
async fn trusted_pull_retries_same_cursor_after_malformed_or_failed_page_without_echo() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud(Phase::None).await;
    install_broker(&state, &directory, base);
    cloud.fail_next.store(true, Ordering::SeqCst);
    assert_eq!(
        pull(Arc::clone(&state), scope.clone()).await.0,
        StatusCode::BAD_GATEWAY
    );
    cloud.malformed.store(true, Ordering::SeqCst);
    assert_eq!(
        pull(Arc::clone(&state), scope.clone()).await.0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert_eq!(operation.changes(0, 20).await.unwrap().len(), 1);
    cloud.malformed.store(false, Ordering::SeqCst);
    let result = pull(Arc::clone(&state), scope.clone()).await;
    assert_eq!(result.0, StatusCode::OK);
    assert_eq!(result.1["result"]["next_cursor"], 4);
    assert_eq!(result.1["result"]["applied"], 1);
    assert_eq!(
        operation
            .get("remote-memory")
            .await
            .unwrap()
            .unwrap()
            .content,
        "remote content"
    );
    assert_eq!(
        operation
            .remote_baseline("remote-memory")
            .await
            .unwrap()
            .unwrap()["remote_extension"],
        json!({"keep":true})
    );
    assert_eq!(
        pull(Arc::clone(&state), scope).await.1["result"]["applied"],
        0
    );
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
    assert_eq!(operation.changes(0, 20).await.unwrap().len(), 2);
    assert_eq!(*cloud.cursors.lock().unwrap(), [0, 0, 0, 4]);
    assert_eq!(*cloud.graph_cursors.lock().unwrap(), [0]);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}
