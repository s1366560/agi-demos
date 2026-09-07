use super::pull_http_tests::{cloud, Phase};
use super::push_http_tests::{install_broker, setup};
use super::*;
use crate::local_runtime::local_router_with_generation_required;
use agistack_core::knowledge::sync::resolution::KnowledgePullConflictResolution;
use agistack_core::knowledge::sync::{pull::KnowledgePullRepository, push::KnowledgeSyncTarget};
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use std::time::Duration;
use tower::ServiceExt;
fn decision() -> Value {
    json!({"memory_id":"knowledge-test-memory","conflict_sequences":[4],"expected_local_revision":1,"expected_remote_revision":1,"expected_baseline_revision":0,"choice":{"decision":"use_remote"}})
}
async fn seed(operation: &KnowledgeOperationV2, base: &str) {
    let repository = operation.authority.repository().unwrap();
    let link = operation.sync_status().await.unwrap().link.unwrap();
    let target = KnowledgeSyncTarget {
        authority: format!("{base}/api/v1"),
        link,
    };
    repository.accept_pull_page(&operation.scope,&target,0,json!({"changes":[{"sequence":4,"change_id":"00000000-0000-4000-8000-000000000004","version":{"memory_id":"knowledge-test-memory","revision":1,"deleted":true,"author_id":"remote-author","created_at_ms":100,"content":{"title":"remote","content":"preserved remote","content_type":"text","tags":[],"metadata":{"retain":true},"status":"ENABLED"}}}],"next_cursor":4,"has_more":false})).await.unwrap();
}
async fn resolve(
    state: Arc<LocalRuntimeState>,
    body: Value,
    key: Option<&str>,
) -> (StatusCode, Value) {
    let mut request = Request::builder()
        .method("POST")
        .uri("/api/v1/knowledge/sync-resolve-pull")
        .header("content-type", "application/json")
        .header("x-agistack-launch", TOKEN)
        .header("authorization", format!("Bearer {TOKEN}"));
    if let Some(key) = key {
        request = request.header("idempotency-key", key);
    }
    let response = local_router_with_generation_required(state)
        .oneshot(request.body(Body::from(body.to_string())).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (status, serde_json::from_slice(&body).unwrap_or(Value::Null))
}
#[tokio::test]
async fn native_resolution_uses_typed_choice_scope_and_trusted_session_without_cloud_write() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud(Phase::None).await;
    seed(&operation, &base).await;
    let broker = install_broker(&state, &directory, base);
    let body = json!({"scope":scope,"resolution":decision()});
    assert_eq!(
        resolve(Arc::clone(&state), body.clone(), None).await.0,
        StatusCode::BAD_REQUEST
    );
    let mut forged = body.clone();
    forged["remote_snapshot"] = json!({"revision":99});
    assert_eq!(
        resolve(Arc::clone(&state), forged, Some("choice")).await.0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let mut wrong = body.clone();
    wrong["scope"]["tenant_id"] = json!("foreign");
    assert_eq!(
        resolve(Arc::clone(&state), wrong, Some("choice")).await.0,
        StatusCode::FORBIDDEN
    );
    let mut wrong = body.clone();
    wrong["scope"]["generation"] = json!(99);
    assert_eq!(
        resolve(Arc::clone(&state), wrong, Some("choice")).await.0,
        StatusCode::CONFLICT
    );
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let mut auth = authenticated(&state);
    auth.membership_role = "viewer".into();
    let viewer = KnowledgeOperationV2::admit(lease, &auth, &scope).unwrap();
    assert!(matches!(
        viewer
            .resolve_pull_conflicts(
                &broker,
                "choice",
                serde_json::from_value::<KnowledgePullConflictResolution>(decision()).unwrap()
            )
            .await,
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    assert!(cloud.calls.lock().unwrap().is_empty());
    let first = resolve(Arc::clone(&state), body.clone(), Some("choice")).await;
    assert_eq!(first.0, StatusCode::OK);
    assert_eq!(first.1["result"]["replayed"], false);
    assert_eq!(
        first.1["result"]["receipt"]["pending_push_sequences"],
        json!([])
    );
    let second = resolve(Arc::clone(&state), body, Some("choice")).await;
    assert_eq!(second.0, StatusCode::OK);
    assert_eq!(second.1["result"]["replayed"], true);
    assert_eq!(first.1["result"]["receipt"], second.1["result"]["receipt"]);
    assert!(operation
        .get("knowledge-test-memory")
        .await
        .unwrap()
        .is_none());
    assert!(operation.pull_conflicts(20).await.unwrap().is_empty());
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 0);
    let history = operation
        .resolution_history("knowledge-test-memory", 10)
        .await
        .unwrap();
    assert_eq!(history.len(), 1);
    assert_eq!(
        history[0]["archive"]["remote"]["content"]["content"],
        "preserved remote"
    );
    assert_eq!(
        *cloud.calls.lock().unwrap(),
        [Phase::Auth, Phase::Project, Phase::Auth, Phase::Project]
    );
    assert!(cloud.cursors.lock().unwrap().is_empty());
    drop(viewer);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}
#[tokio::test]
async fn session_clear_rotate_aba_and_expiry_cannot_resolve_a_conflict_after_verification_started()
{
    for phase in [Phase::Auth, Phase::Project] {
        for transition in ["clear", "rotate", "aba", "expiry"] {
            let directory = TestDirectory::new();
            let state = test_state(TOKEN);
            publish(&state, &directory, 1, true).await;
            let (operation, scope) = setup(&state).await;
            let (cloud, base, server) = cloud(phase).await;
            seed(&operation, &base).await;
            let broker = install_broker(&state, &directory, base);
            let mut record = broker.load().unwrap().unwrap();
            let expiry = chrono::Utc::now() + chrono::Duration::seconds(2);
            if transition == "expiry" {
                record.expires_at = Some(expiry.to_rfc3339());
                broker.save(record.clone()).unwrap();
            }
            let body = json!({"scope":scope,"resolution":decision()});
            let task = tokio::spawn(resolve(Arc::clone(&state), body, Some("choice")));
            tokio::time::timeout(Duration::from_secs(5), cloud.entered.notified())
                .await
                .unwrap();
            match transition {
                "clear" => broker.clear().unwrap(),
                "rotate" => {
                    record.credential = "rotated".into();
                    broker.save(record).unwrap();
                }
                "aba" => {
                    broker.clear().unwrap();
                    broker.save(record).unwrap();
                }
                "expiry" => {
                    tokio::time::sleep(
                        (expiry - chrono::Utc::now()).to_std().unwrap_or_default()
                            + Duration::from_millis(10),
                    )
                    .await
                }
                _ => unreachable!(),
            }
            cloud.release.notify_one();
            assert_eq!(task.await.unwrap().0, StatusCode::SERVICE_UNAVAILABLE);
            assert_eq!(operation.pull_conflicts(20).await.unwrap().len(), 1);
            assert!(operation
                .resolution_history("knowledge-test-memory", 10)
                .await
                .unwrap()
                .is_empty());
            assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
            assert_eq!(operation.changes(0, 20).await.unwrap().len(), 1);
            drop(operation);
            state.platform_plugin_authority_v2.deactivate().await;
            server.abort();
        }
    }
}

#[test]
fn resolution_schema_upgrade_preserves_v5_backup_before_creating_resolution_tables() {
    let directory = TestDirectory::new();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let knowledge = directory.0.join("knowledge");
    let db = rusqlite::Connection::open(knowledge.join("memories.db")).unwrap();
    db.execute_batch(super::storage_tests::DROP_CLOUD_SCHEMA)
        .unwrap();
    db.execute_batch("DROP TABLE knowledge_sync_outbox_metadata; DROP TABLE knowledge_sync_superseded_outbox; DROP TABLE knowledge_sync_resolved_pull_conflicts; DROP TABLE knowledge_sync_resolutions; UPDATE knowledge_schema SET version=5;").unwrap();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let paths: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.file_name().unwrap().to_string_lossy().contains("pre-v5-"))
        .collect();
    assert_eq!(paths.len(), 1);
    let old = rusqlite::Connection::open(&paths[0]).unwrap();
    let old_state:(i64,i64)=old.query_row("SELECT (SELECT version FROM knowledge_schema),(SELECT count(*) FROM sqlite_master WHERE name='knowledge_sync_resolutions')",[],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();
    assert_eq!(old_state, (5, 0));
    let version: i64 = db
        .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
        .unwrap();
    assert_eq!(
        version,
        agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION
    );
}
