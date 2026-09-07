use super::*;

#[tokio::test]
async fn local_tombstone_restore_intent_obtains_real_cloud_conflict_then_explicit_restoration() {
    use agistack_core::knowledge::sync::{
        pull::KnowledgePullRepository,
        push::KnowledgeSyncTarget,
        resolution::{KnowledgeConflictChoice, KnowledgePullConflictResolution},
    };
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud().await;
    let broker = install_broker(&state, &directory, base.clone());
    let target = KnowledgeSyncTarget {
        authority: format!("{base}/api/v1"),
        link: operation.sync_status().await.unwrap().link.unwrap(),
    };
    let remote = cloud.data.lock().unwrap().current.clone();
    operation
        .authority
        .repository()
        .unwrap()
        .accept_pull_page(
            &operation.scope,
            &target,
            0,
            json!({
                "changes":[{
                        "sequence":2,
                        "change_id":"00000000-0000-4000-8000-000000000002",
                        "version":remote
                }],
                "next_cursor":2,
                "has_more":false
            }),
        )
        .await
        .unwrap();
    let resolved = operation
        .resolve_pull_conflicts(
            &broker,
            "retain local",
            KnowledgePullConflictResolution {
                memory_id: "knowledge-test-memory".into(),
                conflict_sequences: vec![2],
                expected_local_revision: 1,
                expected_remote_revision: 2,
                expected_baseline_revision: 0,
                choice: KnowledgeConflictChoice::UseLocal {},
            },
        )
        .await
        .unwrap();
    let sequence = resolved.receipt.pending_push_sequences[0];
    let pushed = push(Arc::clone(&state), json!({"scope":scope})).await;
    assert_eq!(pushed.0, StatusCode::OK, "{}", pushed.1);
    assert_eq!(pushed.1["result"]["receipt"]["status"], "conflict");
    let mut cmd = command(&cloud);
    cmd["local_sequence"] = json!(sequence);
    cmd["guard"]["expected_local_revision"] = json!(2);
    cmd["guard"]["expected_baseline_revision"] = json!(2);
    {
        let data = cloud.data.lock().unwrap();
        assert_eq!(data.conflict["proposed"]["operation"], "update");
        assert_eq!(data.conflict["proposed"]["expected_revision"], 2);
    }
    let done = call(
        Arc::clone(&state),
        "sync-resolve-push",
        json!({"scope":scope,"resolution":cmd}),
        Some("restore"),
    )
    .await;
    assert_eq!(done.0, StatusCode::OK, "{}", done.1);
    assert_eq!(done.1["result"]["receipt"]["version"]["deleted"], false);
    assert_eq!(operation.sync_status().await.unwrap().pending_changes, 0);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}

#[tokio::test]
async fn keep_current_lost_response_resumes_by_saved_id_without_get_or_journal_event() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud().await;
    install_broker(&state, &directory, base);
    push(Arc::clone(&state), json!({"scope":scope})).await;
    let mut cmd = command(&cloud);
    cmd["choice"] = json!({"decision":"keep_current"});
    cloud.fail_after_commit.store(true, Ordering::SeqCst);
    assert_eq!(
        call(
            Arc::clone(&state),
            "sync-resolve-push",
            json!({"scope":scope,"resolution":cmd}),
            Some("keep")
        )
        .await
        .0,
        StatusCode::BAD_GATEWAY
    );
    let records = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope":scope,"query":{"operation":"resolutions","limit":10}}),
        None,
    )
    .await;
    assert_eq!(records.0, StatusCode::OK);
    let id = records.1["result"]["items"][0]["resolution_id"]
        .as_str()
        .unwrap();
    assert_eq!(records.1["result"]["items"][0]["receipt"], Value::Null);
    cloud.forbid_conflict_get.store(true, Ordering::SeqCst);
    let done = call(
        Arc::clone(&state),
        "sync-resume-resolution",
        json!({"scope":scope,"resolution_id":id}),
        None,
    )
    .await;
    assert_eq!(done.0, StatusCode::OK, "{}", done.1);
    assert_eq!(done.1["result"]["receipt"]["status"], "resolved");
    assert_eq!(done.1["result"]["receipt"]["sequence"], Value::Null);
    let replay = call(
        Arc::clone(&state),
        "sync-resume-resolution",
        json!({"scope":scope,"resolution_id":id}),
        None,
    )
    .await;
    assert_eq!(replay.1["result"]["replayed"], true);
    assert!(operation
        .get("knowledge-test-memory")
        .await
        .unwrap()
        .is_none());
    {
        let data = cloud.data.lock().unwrap();
        assert_eq!(data.receipts.len(), 1);
        assert_eq!(data.requests.len(), 2);
        assert_eq!(data.requests[0], data.requests[1]);
    }
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}

#[tokio::test]
async fn verified_stale_is_terminal_for_old_key_and_new_choice_uses_refreshed_context() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud().await;
    install_broker(&state, &directory, base);
    push(Arc::clone(&state), json!({"scope":scope})).await;
    let body = json!({"scope":scope,"resolution":command(&cloud)});
    cloud.stale_next.store(true, Ordering::SeqCst);
    let first = call(
        Arc::clone(&state),
        "sync-resolve-push",
        body.clone(),
        Some("stale"),
    )
    .await;
    assert_eq!(first.0, StatusCode::CONFLICT);
    assert_eq!(first.1["error"]["code"], "knowledge_sync_resolution_stale");
    cloud.forbid_conflict_get.store(true, Ordering::SeqCst);
    let second = call(
        Arc::clone(&state),
        "sync-resolve-push",
        body.clone(),
        Some("stale"),
    )
    .await;
    assert_eq!(first, second);
    assert_eq!(cloud.data.lock().unwrap().requests.len(), 1);
    cloud.forbid_conflict_get.store(false, Ordering::SeqCst);
    let context = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope":scope,"query":{"operation":"conflict_context","local_sequence":1}}),
        None,
    )
    .await;
    assert_eq!(context.0, StatusCode::OK);
    assert_eq!(context.1["result"]["context"]["remote"]["revision"], 3);
    let mut fresh = body;
    fresh["resolution"]["guard"]["expected_remote_revision"] = json!(3);
    let done = call(
        Arc::clone(&state),
        "sync-resolve-push",
        fresh,
        Some("fresh"),
    )
    .await;
    assert_eq!(done.0, StatusCode::OK, "{}", done.1);
    assert_eq!(done.1["result"]["receipt"]["version"]["revision"], 4);
    {
        let data = cloud.data.lock().unwrap();
        assert_eq!(data.receipts.len(), 1);
        assert_eq!(data.requests.len(), 2);
        assert_ne!(data.requests[0], data.requests[1]);
    }
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}

#[tokio::test]
async fn real_auth_forbidden_stops_before_get_or_post_and_preserves_prepared_journal() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud().await;
    install_broker(&state, &directory, base);
    push(Arc::clone(&state), json!({"scope":scope})).await;
    cloud.fail_after_commit.store(true, Ordering::SeqCst);
    let body = json!({"scope":scope,"resolution":command(&cloud)});
    assert_eq!(
        call(
            Arc::clone(&state),
            "sync-resolve-push",
            body.clone(),
            Some("retry")
        )
        .await
        .0,
        StatusCode::BAD_GATEWAY
    );
    cloud.data.lock().unwrap().calls.clear();
    cloud.auth_status.store(403, Ordering::SeqCst);
    assert_eq!(
        call(
            Arc::clone(&state),
            "sync-resolve-push",
            body.clone(),
            Some("retry")
        )
        .await
        .0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(cloud.data.lock().unwrap().calls, vec![1]);
    assert_eq!(cloud.data.lock().unwrap().requests.len(), 1);
    let db = rusqlite::Connection::open(directory.0.join("knowledge/memories.db")).unwrap();
    let counts: (i64, i64, i64) = db
        .query_row(
            "SELECT count(*),count(receipt_json),count(rejection_json) \
                     FROM knowledge_cloud_resolutions",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    assert_eq!(counts, (1, 0, 0));
    cloud.auth_status.store(200, Ordering::SeqCst);
    assert_eq!(
        call(Arc::clone(&state), "sync-resolve-push", body, Some("retry"))
            .await
            .0,
        StatusCode::OK
    );
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}
