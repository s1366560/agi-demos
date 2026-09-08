use super::*;
use std::time::Duration;

#[tokio::test]
async fn cloud_clear_rotation_aba_and_expiry_fence_every_binding_http_phase() {
    for phase in [Phase::Auth, Phase::Project, Phase::Enrollment] {
        for change in ["clear", "rotate", "aba", "expiry"] {
            let f = Fixture::new().await;
            f.cloud.enabled.store(true, Ordering::SeqCst);
            let revision = f.observation().await;
            let operation = f.operation();
            f.cloud.pause.store(phase as u8, Ordering::SeqCst);
            let body = f.target(&revision);
            let state = f.state.clone();
            let pending = tokio::spawn(async move { rpc(state, "sync-bind", body).await });
            tokio::time::timeout(Duration::from_secs(3), f.cloud.entered.notified())
                .await
                .unwrap();
            let record = f.broker.load().unwrap().unwrap();
            match change {
                "clear" => f.broker.clear().unwrap(),
                "aba" => {
                    f.broker.clear().unwrap();
                    f.broker.save(record).unwrap();
                }
                "expiry" => {
                    let mut record = record;
                    record.expires_at =
                        Some((chrono::Utc::now() - chrono::Duration::seconds(1)).to_rfc3339());
                    f.broker.save(record).unwrap();
                }
                _ => {
                    let mut record = record;
                    record.credential = "rotated-test-credential".into();
                    f.broker.save(record).unwrap();
                }
            }
            f.cloud.release.notify_one();
            assert_ne!(pending.await.unwrap().0, StatusCode::OK);
            assert!(operation.sync_status().await.unwrap().link.is_none());
            assert_eq!(f.cloud.posts.load(Ordering::SeqCst), 0);
        }
    }
}

#[tokio::test]
async fn local_context_role_and_session_changes_during_cloud_read_cannot_commit_binding() {
    for sql in [
        "UPDATE desktop_workspace_contexts SET revision=revision+1",
        "UPDATE desktop_tenant_memberships SET role='viewer'",
        "UPDATE desktop_user_sessions SET status='revoked'",
    ] {
        let f = Fixture::new().await;
        f.cloud.enabled.store(true, Ordering::SeqCst);
        let revision = f.observation().await;
        let operation = f.operation();
        f.cloud
            .pause
            .store(Phase::Enrollment as u8, Ordering::SeqCst);
        let body = f.target(&revision);
        let state = f.state.clone();
        let pending = tokio::spawn(async move { rpc(state, "sync-bind", body).await });
        tokio::time::timeout(Duration::from_secs(3), f.cloud.entered.notified())
            .await
            .unwrap();
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute_batch(sql)
            .unwrap();
        f.cloud.release.notify_one();
        assert_ne!(pending.await.unwrap().0, StatusCode::OK);
        assert!(operation.sync_status().await.unwrap().link.is_none());
    }
}

#[tokio::test]
async fn replaced_native_generation_discards_binding_and_rotates_connection_observation() {
    let f = Fixture::new().await;
    f.cloud.enabled.store(true, Ordering::SeqCst);
    let revision = f.observation().await;
    let operation = f.operation();
    f.cloud
        .pause
        .store(Phase::Enrollment as u8, Ordering::SeqCst);
    let body = f.target(&revision);
    let state = f.state.clone();
    let pending = tokio::spawn(async move { rpc(state, "sync-bind", body).await });
    tokio::time::timeout(Duration::from_secs(3), f.cloud.entered.notified())
        .await
        .unwrap();
    let (snapshot, generation) = stage(&f.directory, 2, true).await;
    let retired = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    f.cloud.release.notify_one();
    assert_eq!(pending.await.unwrap().0, StatusCode::CONFLICT);
    assert!(operation.sync_status().await.unwrap().link.is_none());
    drop(operation);
    retired.dispose().await;
    f.cloud.pause.store(Phase::None as u8, Ordering::SeqCst);
    let auth = authenticated(&f.state);
    let lease = f
        .state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    let scope = operation_scope(&auth, &lease);
    let (status, result) = f.request("sync-connection", json!({"scope":scope})).await;
    assert_eq!(status, StatusCode::OK, "{result}");
    assert_ne!(
        result["result"]["connection"]["connection_revision"],
        revision
    );
    assert_eq!(
        f.request(
            "sync-tenants",
            json!({"scope":scope,"expected_connection_revision":revision})
        )
        .await
        .0,
        StatusCode::CONFLICT
    );
}

#[tokio::test]
async fn cloud_generation_drift_rejects_binding_and_data_without_automatic_write_retry() {
    let f = Fixture::new().await;
    f.cloud.enabled.store(true, Ordering::SeqCst);
    let revision = f.observation().await;
    let old = f.target(&revision);
    f.cloud.generation.store(2, Ordering::SeqCst);
    assert_eq!(
        f.request("sync-bind", old).await.0,
        StatusCode::PRECONDITION_FAILED
    );
    assert!(f.operation().sync_status().await.unwrap().link.is_none());
    assert_eq!(
        f.request("sync-bind", f.target(&revision)).await.0,
        StatusCode::OK
    );
    let operation = f.operation();
    operation
        .mutate("create", mutation(&authenticated(&f.state)))
        .await
        .unwrap();
    f.cloud.pause.store(Phase::Data as u8, Ordering::SeqCst);
    let state = f.state.clone();
    let scope = f.scope.clone();
    let pending =
        tokio::spawn(async move { rpc(state, "sync-push", json!({"scope":scope})).await });
    tokio::time::timeout(Duration::from_secs(3), f.cloud.entered.notified())
        .await
        .unwrap();
    f.cloud.generation.store(3, Ordering::SeqCst);
    f.cloud.release.notify_one();
    assert_eq!(pending.await.unwrap().0, StatusCode::PRECONDITION_FAILED);
    assert_eq!(f.cloud.posts.load(Ordering::SeqCst), 0);
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
    assert_eq!(
        f.cloud
            .calls
            .lock()
            .unwrap()
            .iter()
            .filter(|phase| **phase == Phase::Data)
            .count(),
        1
    );
    f.cloud.pause.store(Phase::None as u8, Ordering::SeqCst);
    assert_eq!(
        f.request("sync-push", json!({"scope":f.scope})).await.0,
        StatusCode::OK
    );
}

#[tokio::test]
async fn another_cloud_origin_cannot_claim_existing_binding_even_for_same_actor_and_ids() {
    let f = Fixture::new().await;
    let other = Fixture::new().await;
    f.cloud.enabled.store(true, Ordering::SeqCst);
    other.cloud.enabled.store(true, Ordering::SeqCst);
    let old = f.observation().await;
    assert_eq!(
        f.request("sync-bind", f.target(&old)).await.0,
        StatusCode::OK
    );
    let mut record = f.broker.load().unwrap().unwrap();
    record.api_base_url = other.base.clone();
    f.broker.save(record).unwrap();
    assert_eq!(
        f.request("sync-bind", f.target(&old)).await.0,
        StatusCode::CONFLICT
    );
    let fresh = f.observation().await;
    assert_ne!(fresh, old);
    assert_eq!(
        f.request("sync-bind", f.target(&fresh)).await.0,
        StatusCode::CONFLICT
    );
    let operation = f.operation();
    operation
        .mutate("create", mutation(&authenticated(&f.state)))
        .await
        .unwrap();
    assert_eq!(
        f.request("sync-push", json!({"scope":f.scope})).await.0,
        StatusCode::CONFLICT
    );
    assert_eq!(other.cloud.posts.load(Ordering::SeqCst), 0);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cloud_deadline_crossed_waiting_for_binding_storage_rolls_back_without_epoch_change() {
    let f = Fixture::new().await;
    f.cloud.enabled.store(true, Ordering::SeqCst);
    let mut record = f.broker.load().unwrap().unwrap();
    record.expires_at =
        Some((chrono::Utc::now() + chrono::Duration::milliseconds(2200)).to_rfc3339());
    f.broker.save(record).unwrap();
    let epoch = f.broker.snapshot().unwrap().epoch;
    let revision = f.observation().await;
    let operation = f.operation();
    f.cloud
        .pause
        .store(Phase::Enrollment as u8, Ordering::SeqCst);
    let state = f.state.clone();
    let body = f.target(&revision);
    let pending = tokio::spawn(async move { rpc(state, "sync-bind", body).await });
    tokio::time::timeout(Duration::from_secs(3), f.cloud.entered.notified())
        .await
        .unwrap();
    let connection =
        rusqlite::Connection::open(f.directory.0.join("knowledge/memories.db")).unwrap();
    connection.execute_batch("BEGIN EXCLUSIVE").unwrap();
    f.cloud.release.notify_one();
    tokio::time::sleep(Duration::from_millis(2400)).await;
    connection.execute_batch("COMMIT").unwrap();
    assert_ne!(pending.await.unwrap().0, StatusCode::OK);
    assert_eq!(f.broker.snapshot().unwrap().epoch, epoch);
    assert!(operation.sync_status().await.unwrap().link.is_none());
    let origins: i64 = connection
        .query_row("SELECT count(*) FROM knowledge_sync_targets", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(origins, 0);
}
