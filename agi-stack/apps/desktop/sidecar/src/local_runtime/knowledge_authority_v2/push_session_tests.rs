use super::push_http_tests::{install_broker, push, setup};
use super::*;
use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use std::sync::Mutex;
use tokio::sync::Notify;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Auth,
    Project,
    Mutation,
    Conflict,
}
struct Cloud {
    phase: Phase,
    entered: Notify,
    release: Notify,
    calls: Mutex<Vec<Phase>>,
    request: Mutex<Option<Value>>,
    conflict_id: String,
}
impl Cloud {
    async fn barrier(&self, phase: Phase) {
        self.calls.lock().unwrap().push(phase);
        if phase == self.phase {
            self.entered.notify_one();
            self.release.notified().await;
        }
    }
}
async fn auth(State(cloud): State<Arc<Cloud>>) -> Json<Value> {
    cloud.barrier(Phase::Auth).await;
    Json(super::sync_auth_tests::auth_me_fixture())
}
async fn project(State(cloud): State<Arc<Cloud>>) -> Json<Value> {
    cloud.barrier(Phase::Project).await;
    Json(json!({"id":"remote-project","tenant_id":"remote-tenant"}))
}
async fn mutation(
    State(cloud): State<Arc<Cloud>>,
    Json(request): Json<Value>,
) -> (StatusCode, Json<Value>) {
    *cloud.request.lock().unwrap() = Some(request.clone());
    cloud.barrier(Phase::Mutation).await;
    if cloud.phase == Phase::Conflict {
        return (
            StatusCode::CONFLICT,
            Json(
                json!({"receipt":{"status":"conflict","change_id":request["change_id"],"conflict_id":cloud.conflict_id},"replayed":false}),
            ),
        );
    }
    (
        StatusCode::OK,
        Json(
            json!({"receipt":{"status":"applied","change_id":request["change_id"],"sequence":1,"version":{"memory_id":request["memory_id"],"revision":1,"deleted":false,"author_id":"remote-actor","created_at_ms":100,"content":request["content"]}},"replayed":false}),
        ),
    )
}
async fn conflict(State(cloud): State<Arc<Cloud>>) -> Json<Value> {
    cloud.barrier(Phase::Conflict).await;
    let mut proposed = cloud.request.lock().unwrap().clone().unwrap();
    proposed.as_object_mut().unwrap().remove("change_id");
    Json(
        json!({"id":cloud.conflict_id,"memory_id":proposed["memory_id"],"proposed":proposed,"current":null,"resolved_change_id":null}),
    )
}
async fn cloud(phase: Phase) -> (Arc<Cloud>, String, tokio::task::JoinHandle<()>) {
    let cloud = Arc::new(Cloud {
        phase,
        entered: Notify::new(),
        release: Notify::new(),
        calls: Mutex::new(vec![]),
        request: Mutex::new(None),
        conflict_id: Uuid::new_v4().to_string(),
    });
    let app = Router::new()
        .route("/api/v1/projects/remote-project/knowledge-sync/enrollment", get(crate::local_runtime::knowledge_authority_v2::tests::sync_cloud_fixture::enrollment))
        .route("/api/v1/auth/me", get(auth))
        .route("/api/v1/projects/remote-project", get(project))
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/mutations",
            post(mutation),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/conflicts/:id",
            get(conflict),
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

#[tokio::test]
async fn clear_rotation_and_same_token_restore_fence_every_http_phase() {
    for phase in [
        Phase::Auth,
        Phase::Project,
        Phase::Mutation,
        Phase::Conflict,
    ] {
        for transition in ["clear", "rotate", "same_token_restore"] {
            let directory = TestDirectory::new();
            let state = test_state(TOKEN);
            publish(&state, &directory, 1, true).await;
            let (operation, scope) = setup(&state).await;
            let (cloud, base, server) = cloud(phase).await;
            let broker = install_broker(&state, &directory, base);
            let request_state = Arc::clone(&state);
            let task =
                tokio::spawn(async move { push(request_state, json!({"scope":scope})).await });
            tokio::time::timeout(std::time::Duration::from_secs(5), cloud.entered.notified())
                .await
                .unwrap();
            let mut record = broker.load().unwrap().unwrap();
            match transition {
                "clear" => broker.clear().unwrap(),
                "rotate" => {
                    record.credential = "rotated-test-credential".into();
                    broker.save(record).unwrap();
                }
                "same_token_restore" => {
                    broker.clear().unwrap();
                    broker.save(record).unwrap();
                }
                _ => unreachable!(),
            }
            cloud.release.notify_one();
            let result = task.await.unwrap();
            assert_eq!(
                result.0,
                StatusCode::SERVICE_UNAVAILABLE,
                "{phase:?} {transition}"
            );
            let expected = match phase {
                Phase::Auth => vec![Phase::Auth],
                Phase::Project => vec![Phase::Auth, Phase::Project],
                Phase::Mutation => vec![Phase::Auth, Phase::Project, Phase::Mutation],
                Phase::Conflict => vec![
                    Phase::Auth,
                    Phase::Project,
                    Phase::Mutation,
                    Phase::Conflict,
                ],
            };
            assert_eq!(*cloud.calls.lock().unwrap(), expected);
            assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
            assert!(operation
                .remote_baseline("knowledge-test-memory")
                .await
                .unwrap()
                .is_none());
            assert!(operation.push_conflicts(20).await.unwrap().is_empty());
            let database =
                rusqlite::Connection::open(directory.0.join("knowledge/memories.db")).unwrap();
            let (prepared, acked): (i64, i64) = database
                .query_row(
                    "SELECT count(*),count(receipt_json) FROM knowledge_sync_pushes",
                    [],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .unwrap();
            assert_eq!(
                prepared,
                if matches!(phase, Phase::Mutation | Phase::Conflict) {
                    1
                } else {
                    0
                }
            );
            assert_eq!(acked, 0);
            drop(operation);
            state.platform_plugin_authority_v2.deactivate().await;
            server.abort();
        }
    }
}

#[tokio::test]
async fn expired_or_invalid_expiry_never_starts_http() {
    for expiry in ["2000-01-01T00:00:00Z", "invalid-expiry"] {
        let directory = TestDirectory::new();
        let state = test_state(TOKEN);
        publish(&state, &directory, 1, true).await;
        let (operation, scope) = setup(&state).await;
        let (cloud, base, server) = cloud(Phase::Mutation).await;
        let broker = install_broker(&state, &directory, base);
        let mut record = broker.load().unwrap().unwrap();
        record.expires_at = Some(expiry.into());
        broker.save(record).unwrap();
        assert_eq!(
            push(Arc::clone(&state), json!({"scope":scope})).await.0,
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert!(cloud.calls.lock().unwrap().is_empty());
        drop(operation);
        state.platform_plugin_authority_v2.deactivate().await;
        server.abort();
    }
}

#[tokio::test]
async fn expiry_during_response_wait_rejects_late_receipt_without_epoch_change() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud(Phase::Mutation).await;
    let broker = install_broker(&state, &directory, base);
    let expiry = chrono::Utc::now() + chrono::Duration::seconds(5);
    let mut record = broker.load().unwrap().unwrap();
    record.expires_at = Some(expiry.to_rfc3339());
    broker.save(record).unwrap();
    let epoch = broker.snapshot().unwrap().epoch;
    let request_state = Arc::clone(&state);
    let task = tokio::spawn(async move { push(request_state, json!({"scope":scope})).await });
    tokio::time::timeout(std::time::Duration::from_secs(5), cloud.entered.notified())
        .await
        .unwrap();
    tokio::time::sleep(
        (expiry - chrono::Utc::now()).to_std().unwrap_or_default()
            + std::time::Duration::from_millis(10),
    )
    .await;
    cloud.release.notify_one();
    assert_eq!(task.await.unwrap().0, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(broker.snapshot().unwrap().epoch, epoch);
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
    assert!(operation
        .remote_baseline("knowledge-test-memory")
        .await
        .unwrap()
        .is_none());
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}
