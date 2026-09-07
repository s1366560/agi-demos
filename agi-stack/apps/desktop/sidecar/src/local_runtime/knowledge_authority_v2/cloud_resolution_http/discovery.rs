use super::*;

#[tokio::test]
async fn recovery_queries_read_saved_keys_and_pending_without_resending_or_refreshing_conflicts() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (_, scope) = setup(&state).await;
    let (cloud, base, server) = cloud().await;
    install_broker(&state, &directory, base);
    assert_eq!(
        push(Arc::clone(&state), json!({"scope": scope})).await.0,
        StatusCode::OK
    );
    cloud.fail_after_commit.store(true, Ordering::SeqCst);
    let initial = call(
        Arc::clone(&state),
        "sync-resolve-push",
        json!({"scope": scope, "resolution": command(&cloud)}),
        Some("saved-choice"),
    )
    .await;
    assert_eq!(initial.0, StatusCode::BAD_GATEWAY);
    let reads = cloud.data.lock().unwrap().conflict_reads;
    cloud.forbid_conflict_get.store(true, Ordering::SeqCst);
    let found = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope": scope, "query": {
            "operation": "resolution_by_key", "idempotency_key": "saved-choice",
        }}),
        None,
    )
    .await;
    assert_eq!(found.0, StatusCode::OK, "{}", found.1);
    let record = &found.1["result"]["record"];
    assert!(record["receipt"].is_null());
    let id = record["resolution_id"].as_str().unwrap();
    let page = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope": scope, "query": {"operation": "pending_resolutions", "limit": 1}}),
        None,
    )
    .await;
    assert_eq!(page.0, StatusCode::OK, "{}", page.1);
    assert_eq!(page.1["result"]["items"], json!([record]));
    assert!(page.1["result"]["next_before_resolution_id"].is_null());
    let missing = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope": scope, "query": {
            "operation": "resolution_by_key", "idempotency_key": "missing",
        }}),
        None,
    )
    .await;
    assert_eq!(missing.0, StatusCode::OK);
    assert!(missing.1["result"]["record"].is_null());
    {
        let data = cloud.data.lock().unwrap();
        assert_eq!(data.requests.len(), 1);
        assert_eq!(data.conflict_reads, reads);
    }
    let resumed = call(
        Arc::clone(&state),
        "sync-resume-resolution",
        json!({"scope": scope, "resolution_id": id}),
        None,
    )
    .await;
    assert_eq!(resumed.0, StatusCode::OK);
    let empty = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope": scope, "query": {"operation": "pending_resolutions", "limit": 200}}),
        None,
    )
    .await;
    assert_eq!(empty.0, StatusCode::OK);
    assert_eq!(empty.1["result"]["items"], json!([]));
    let cursor = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope": scope, "query": {
            "operation": "pending_resolutions", "before_resolution_id": id, "limit": 1,
        }}),
        None,
    )
    .await;
    assert_eq!(cursor.0, StatusCode::OK);
    assert_eq!(cursor.1["result"]["items"], json!([]));
    server.abort();
}

#[tokio::test]
async fn recovery_queries_reject_forged_authority_invalid_bounds_and_expired_cloud_auth() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (_, scope) = setup(&state).await;
    let (cloud, base, server) = cloud().await;
    install_broker(&state, &directory, base);
    for query in [
        json!({"operation": "resolution_by_key", "idempotency_key": " ",}),
        json!({"operation": "resolution_by_key", "idempotency_key": "k", "actor": "other"}),
        json!({"operation": "pending_resolutions", "limit": 0}),
        json!({"operation": "pending_resolutions", "limit": 201}),
        json!({"operation": "pending_resolutions", "limit": 1, "before_resolution_id": "bad"}),
    ] {
        let result = call(
            Arc::clone(&state),
            "sync-cloud-query",
            json!({"scope": scope, "query": query}),
            None,
        )
        .await;
        assert_eq!(result.0, StatusCode::UNPROCESSABLE_ENTITY, "{}", result.1);
    }
    let mut wrong_scope = serde_json::to_value(&scope).unwrap();
    wrong_scope["tenant_id"] = json!("other");
    let result = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope": wrong_scope, "query": {"operation": "pending_resolutions", "limit": 1}}),
        None,
    )
    .await;
    assert_eq!(result.0, StatusCode::FORBIDDEN);
    cloud.data.lock().unwrap().calls.clear();
    cloud.auth_status.store(403, Ordering::SeqCst);
    let result = call(
        Arc::clone(&state),
        "sync-cloud-query",
        json!({"scope": scope, "query": {"operation": "pending_resolutions", "limit": 1}}),
        None,
    )
    .await;
    assert_eq!(result.0, StatusCode::FORBIDDEN);
    assert_eq!(cloud.data.lock().unwrap().calls, vec![1]);
    assert!(cloud.data.lock().unwrap().requests.is_empty());
    server.abort();
}

#[tokio::test]
async fn recovery_queries_keep_release_closed_without_creating_storage() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, false).await;
    let auth = authenticated(&state);
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    let scope = operation_scope(&auth, &lease);
    drop(lease);
    for query in [
        json!({"operation": "resolution_by_key", "idempotency_key": "saved-choice"}),
        json!({"operation": "pending_resolutions", "limit": 200}),
    ] {
        let result = call(
            Arc::clone(&state),
            "sync-cloud-query",
            json!({"scope": scope, "query": query}),
            None,
        )
        .await;
        assert_eq!(result.0, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(result.1["error"]["code"], "knowledge_release_closed");
        assert!(!directory.0.join("knowledge").exists());
    }
}
