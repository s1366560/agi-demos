use super::pull_http_tests::{cloud, pull, Phase};
use super::push_http_tests::{install_broker, setup};
use super::*;
use axum::http::StatusCode;
use std::time::Duration;

fn cursor(directory: &TestDirectory) -> u64 {
    rusqlite::Connection::open(directory.0.join("knowledge/memories.db"))
        .unwrap()
        .query_row(
            "SELECT COALESCE((SELECT cursor FROM knowledge_sync_pull_cursors LIMIT 1),0)",
            [],
            |row| row.get(0),
        )
        .unwrap()
}

#[tokio::test]
async fn clear_rotation_and_same_token_restore_fence_every_pull_http_phase() {
    for phase in [Phase::Auth, Phase::Project, Phase::Page, Phase::PageBody] {
        for transition in ["clear", "rotate", "same_token_restore"] {
            let directory = TestDirectory::new();
            let state = test_state(TOKEN);
            publish(&state, &directory, 1, true).await;
            let (operation, scope) = setup(&state).await;
            let (cloud, base, server) = cloud(phase).await;
            let broker = install_broker(&state, &directory, base);
            let task = tokio::spawn(pull(Arc::clone(&state), scope));
            tokio::time::timeout(Duration::from_secs(5), cloud.entered.notified())
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
            assert_eq!(
                task.await.unwrap().0,
                StatusCode::SERVICE_UNAVAILABLE,
                "{phase:?} {transition}"
            );
            assert_eq!(cursor(&directory), 0);
            assert!(operation.get("remote-memory").await.unwrap().is_none());
            assert_eq!(operation.changes(0, 20).await.unwrap().len(), 1);
            assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
            let expected = match phase {
                Phase::Auth => vec![Phase::Auth],
                Phase::Project => vec![Phase::Auth, Phase::Project],
                Phase::Page => vec![Phase::Auth, Phase::Project, Phase::Page],
                Phase::PageBody => vec![Phase::Auth, Phase::Project, Phase::Page, Phase::PageBody],
                Phase::None => unreachable!(),
            };
            assert_eq!(*cloud.calls.lock().unwrap(), expected);
            drop(operation);
            state.platform_plugin_authority_v2.deactivate().await;
            server.abort();
        }
    }
}

#[tokio::test]
async fn expiry_without_epoch_change_fences_auth_project_and_page_responses() {
    for phase in [Phase::Auth, Phase::Project, Phase::Page, Phase::PageBody] {
        let directory = TestDirectory::new();
        let state = test_state(TOKEN);
        publish(&state, &directory, 1, true).await;
        let (operation, scope) = setup(&state).await;
        let (cloud, base, server) = cloud(phase).await;
        let broker = install_broker(&state, &directory, base);
        let expiry = chrono::Utc::now() + chrono::Duration::seconds(2);
        let mut record = broker.load().unwrap().unwrap();
        record.expires_at = Some(expiry.to_rfc3339());
        broker.save(record).unwrap();
        let epoch = broker.snapshot().unwrap().epoch;
        let task = tokio::spawn(pull(Arc::clone(&state), scope));
        tokio::time::timeout(Duration::from_secs(5), cloud.entered.notified())
            .await
            .unwrap();
        tokio::time::sleep(
            (expiry - chrono::Utc::now()).to_std().unwrap_or_default() + Duration::from_millis(10),
        )
        .await;
        cloud.release.notify_one();
        assert_eq!(
            task.await.unwrap().0,
            StatusCode::SERVICE_UNAVAILABLE,
            "{phase:?}"
        );
        assert_eq!(broker.snapshot().unwrap().epoch, epoch);
        assert_eq!(cursor(&directory), 0);
        assert!(operation.get("remote-memory").await.unwrap().is_none());
        drop(operation);
        state.platform_plugin_authority_v2.deactivate().await;
        server.abort();
    }
}

#[tokio::test]
async fn native_pull_timeout_keeps_cursor_and_retry_imports_once() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud(Phase::Page).await;
    install_broker(&state, &directory, base);
    let task = tokio::spawn(pull(Arc::clone(&state), scope.clone()));
    tokio::time::timeout(Duration::from_secs(5), cloud.entered.notified())
        .await
        .unwrap();
    tokio::time::pause();
    tokio::time::advance(Duration::from_secs(31)).await;
    assert_eq!(task.await.unwrap().0, StatusCode::BAD_GATEWAY);
    tokio::time::resume();
    assert_eq!(cursor(&directory), 0);
    cloud.release.notify_one();
    let retry = tokio::spawn(pull(Arc::clone(&state), scope));
    tokio::time::timeout(Duration::from_secs(5), cloud.entered.notified())
        .await
        .unwrap();
    cloud.release.notify_one();
    assert_eq!(retry.await.unwrap().0, StatusCode::OK);
    assert_eq!(cursor(&directory), 4);
    assert_eq!(operation.changes(0, 20).await.unwrap().len(), 2);
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
    assert_eq!(*cloud.cursors.lock().unwrap(), [0, 0]);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}
