use super::*;

#[tokio::test]
async fn clear_rotate_aba_and_expiry_fence_prepare_and_ack_at_every_resolution_http_phase() {
    for phase in 1..=4 {
        for transition in ["clear", "rotate", "aba", "expiry"] {
            let directory = TestDirectory::new();
            let state = test_state(TOKEN);
            publish(&state, &directory, 1, true).await;
            let (operation, scope) = setup(&state).await;
            let (cloud, base, server) = cloud().await;
            let broker = install_broker(&state, &directory, base);
            push(Arc::clone(&state), json!({"scope":scope})).await;
            cloud.data.lock().unwrap().calls.clear();
            cloud.phase.store(phase, Ordering::SeqCst);
            let mut session = broker.load().unwrap().unwrap();
            let expiry = chrono::Utc::now() + chrono::Duration::seconds(2);
            if transition == "expiry" {
                session.expires_at = Some(expiry.to_rfc3339());
                broker.save(session.clone()).unwrap();
            }
            let body = json!({"scope":scope,"resolution":command(&cloud)});
            let request = tokio::spawn(call(
                Arc::clone(&state),
                "sync-resolve-push",
                body,
                Some("fenced"),
            ));
            tokio::time::timeout(Duration::from_secs(5), cloud.entered.notified())
                .await
                .unwrap();
            match transition {
                "clear" => broker.clear().unwrap(),
                "rotate" => {
                    session.credential = "rotated".into();
                    broker.save(session).unwrap();
                }
                "aba" => {
                    broker.clear().unwrap();
                    broker.save(session).unwrap();
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
            let result = request.await.unwrap();
            assert_eq!(
                result.0,
                StatusCode::SERVICE_UNAVAILABLE,
                "phase {phase} {transition}: {}",
                result.1
            );
            assert_eq!(
                cloud.data.lock().unwrap().calls,
                (1..=phase).collect::<Vec<_>>()
            );
            let db = rusqlite::Connection::open(directory.0.join("knowledge/memories.db")).unwrap();
            let counts: (i64, i64, i64) = db
                .query_row(
                    "SELECT count(*),count(receipt_json),count(rejection_json) \
                     FROM knowledge_cloud_resolutions",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                )
                .unwrap();
            assert_eq!(counts, (if phase == 4 { 1 } else { 0 }, 0, 0));
            assert_eq!(
                cloud.data.lock().unwrap().receipts.len(),
                if phase == 4 { 1 } else { 0 }
            );
            assert!(operation
                .remote_baseline("knowledge-test-memory")
                .await
                .unwrap()
                .is_none());
            assert_eq!(operation.sync_status().await.unwrap().pending_changes, 1);
            drop(operation);
            state.platform_plugin_authority_v2.deactivate().await;
            server.abort();
        }
    }
}
