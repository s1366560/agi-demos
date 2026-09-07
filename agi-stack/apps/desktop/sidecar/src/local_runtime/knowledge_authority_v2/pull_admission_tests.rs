use super::pull_http_tests::{cloud, pull, request, Phase};
use super::push_http_tests::{install_broker, setup};
use super::*;
use axum::http::StatusCode;
use std::sync::atomic::Ordering;

#[tokio::test]
async fn pull_rejects_renderer_remote_inputs_and_mismatched_scope_before_cloud_calls() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    assert_eq!(
        pull(Arc::clone(&state), scope.clone()).await.0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    let (cloud, base, server) = cloud(Phase::None).await;
    let broker = install_broker(&state, &directory, base);
    for key in [
        "page",
        "response",
        "after",
        "cursor",
        "url",
        "credential",
        "limit",
        "target",
    ] {
        let mut body = json!({"scope":scope});
        body[key] = json!({"forged":true});
        assert_eq!(
            request(Arc::clone(&state), "/api/v1/knowledge/sync-pull", body)
                .await
                .0,
            StatusCode::UNPROCESSABLE_ENTITY,
            "{key}"
        );
    }
    for (field, value, expected) in [
        ("tenant_id", json!("other"), StatusCode::FORBIDDEN),
        ("project_id", json!("other"), StatusCode::FORBIDDEN),
        ("context_revision", json!(99), StatusCode::FORBIDDEN),
        ("profile_id", json!("other"), StatusCode::CONFLICT),
        ("generation", json!(99), StatusCode::CONFLICT),
        ("digest", json!("other"), StatusCode::CONFLICT),
    ] {
        let mut body = json!({"scope":scope});
        body["scope"][field] = value;
        assert_eq!(
            request(Arc::clone(&state), "/api/v1/knowledge/sync-pull", body)
                .await
                .0,
            expected,
            "{field}"
        );
    }
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
        viewer.pull_once(&broker).await,
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    assert!(cloud.calls.lock().unwrap().is_empty());
    assert!(viewer.pull_conflicts(10).await.unwrap().is_empty());
    let query = json!({"scope":scope,"query":{"operation":"pull_conflicts","limit":10}});
    assert_eq!(
        request(Arc::clone(&state), "/api/v1/knowledge/query", query)
            .await
            .1["result"]["items"],
        json!([])
    );
    let invalid = json!({"scope":scope,"query":{"operation":"pull_conflicts","limit":0}});
    assert_eq!(
        request(Arc::clone(&state), "/api/v1/knowledge/query", invalid)
            .await
            .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert_eq!(operation.changes(0, 20).await.unwrap().len(), 1);
    drop(viewer);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}

#[tokio::test]
async fn pull_verifies_cloud_actor_and_project_before_reading_remote_changes() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud(Phase::None).await;
    install_broker(&state, &directory, base);
    cloud.wrong_actor.store(true, Ordering::SeqCst);
    assert_eq!(
        pull(Arc::clone(&state), scope.clone()).await.0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(*cloud.calls.lock().unwrap(), [Phase::Auth]);
    cloud.wrong_actor.store(false, Ordering::SeqCst);
    cloud.wrong_project.store(true, Ordering::SeqCst);
    assert_eq!(
        pull(Arc::clone(&state), scope).await.0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        *cloud.calls.lock().unwrap(),
        [Phase::Auth, Phase::Auth, Phase::Project]
    );
    assert!(cloud.cursors.lock().unwrap().is_empty());
    assert!(operation.get("remote-memory").await.unwrap().is_none());
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}

#[test]
fn v4_pull_upgrade_backs_up_before_adding_cursor_journal_and_conflict_tables() {
    let directory = TestDirectory::new();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let knowledge = directory.0.join("knowledge");
    let connection = rusqlite::Connection::open(knowledge.join("memories.db")).unwrap();
    let replica: String = connection
        .query_row("SELECT replica_id FROM knowledge_replica", [], |row| {
            row.get(0)
        })
        .unwrap();
    connection.execute_batch(super::storage_tests::DROP_CLOUD_SCHEMA).unwrap();
    connection.execute_batch("DROP TABLE knowledge_sync_outbox_metadata; DROP TABLE knowledge_sync_superseded_outbox; DROP TABLE knowledge_sync_resolved_pull_conflicts; DROP TABLE knowledge_sync_resolutions; DROP TABLE knowledge_sync_pull_cursors; DROP TABLE knowledge_sync_pull_events; DROP TABLE knowledge_sync_pull_conflicts; UPDATE knowledge_schema SET version=4;").unwrap();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .contains("pre-v4-")
        })
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = rusqlite::Connection::open(&backups[0]).unwrap();
    let original:(i64,String,i64)=backup.query_row("SELECT (SELECT version FROM knowledge_schema),(SELECT replica_id FROM knowledge_replica),(SELECT count(*) FROM sqlite_master WHERE name='knowledge_sync_pull_cursors')",[],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).unwrap();
    assert_eq!(original, (4, replica, 0));
    let upgraded: i64 = connection
        .query_row("SELECT version FROM knowledge_schema", [], |row| row.get(0))
        .unwrap();
    assert_eq!(upgraded, 7);
}
