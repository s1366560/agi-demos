use super::*;
use crate::local_runtime::{ManagedResourceKind, ProviderRuntimeKey};

#[tokio::test]
async fn viewer_queries_and_coverage_work_but_all_index_writes_require_current_writer_role() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "build")
        .await
        .unwrap();
    let config = f
        .operation
        .select_index_build(&f.state, &f.auth, &build, None)
        .unwrap();
    let receipt = f
        .operation
        .index_one(&f.state, &f.auth, &config, IndexRunOptions::default())
        .await
        .unwrap()
        .unwrap();
    f.operation
        .promote_index_build(&f.state, &f.auth, &config, None)
        .unwrap();
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_tenant_memberships SET role='viewer'")
        .unwrap();
    let auth = authenticated(&f.state);
    let lease = Arc::new(
        f.state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let viewer =
        KnowledgeOperationV2::admit(lease.clone(), &auth, &operation_scope(&auth, &lease)).unwrap();
    assert_eq!(
        viewer
            .semantic_query(&f.state, &auth, &config, "query", 10)
            .await
            .unwrap()
            .hits
            .len(),
        1
    );
    assert!(viewer
        .index_coverage(&f.state, &auth, &config)
        .unwrap()
        .1
        .complete());
    assert!(viewer
        .select_index_build(&f.state, &auth, &build, Some(config.revision))
        .is_err());
    assert!(f
        .operation
        .select_index_build(&f.state, &f.auth, &build, Some(config.revision))
        .is_err());
    assert!(viewer
        .prepare_index_build(&f.state, &auth, &route, "denied")
        .await
        .is_err());
    assert!(viewer
        .index_one(&f.state, &auth, &config, IndexRunOptions::default())
        .await
        .is_err());
    assert!(viewer
        .promote_index_build(&f.state, &auth, &config, Some("build"))
        .is_err());
    assert!(viewer
        .retry_index(&f.state, &auth, &config, &receipt.input, 1)
        .is_err());
    // The original operation captured writable=true, but live role downgrade
    // must also reject writes made through that old admission.
    assert!(f
        .operation
        .index_one(&f.state, &f.auth, &config, IndexRunOptions::default())
        .await
        .is_err());
}

#[tokio::test]
async fn durable_provider_delete_before_runtime_cleanup_revision_and_binding_changes_fence_inflight_results(
) {
    for change in 0..3 {
        let f = Fixture::new().await;
        let endpoint = Endpoint::new().await;
        let route = f.provider(&endpoint).await;
        let build = f
            .operation
            .prepare_index_build(&f.state, &f.auth, &route, "build")
            .await
            .unwrap();
        let config = f
            .operation
            .select_index_build(&f.state, &f.auth, &build, None)
            .unwrap();
        endpoint.pause();
        let task = f.run(
            config.clone(),
            IndexRunOptions {
                lease_ms: 1000,
                renew_every_ms: 500,
            },
        );
        endpoint.entered().await;
        let key = ProviderRuntimeKey {
            tenant_id: f.operation.scope.tenant_id.clone(),
            provider_id: route.provider_id.clone(),
        };
        if change == 0 {
            // Execute the real durable deletion operation, intentionally delaying
            // the later runtime cleanup phase of delete_llm_provider.
            f.state
                .session_store
                .mutate_managed_resource(crate::local_runtime::ManagedResourceMutationCommand {
                    actor_id: f.auth.user.user_id.clone(),
                    kind: ManagedResourceKind::Provider,
                    scope_kind: "tenant".into(),
                    scope_id: f.operation.scope.tenant_id.clone(),
                    resource_id: route.provider_id.clone(),
                    operation: crate::local_runtime::ManagedResourceMutationOperation::Delete,
                    expected_revision: route.provider_revision,
                    idempotency_key: "embedding-delete-fixture-key".into(),
                    payload_hash: "cd".repeat(32),
                    status: "deleted".into(),
                    value: None,
                    target_revision: None,
                    vault_refs: vec![],
                    now_ms: chrono::Utc::now().timestamp_millis(),
                })
                .unwrap();
            assert!(f
                .state
                .provider_runtime
                .lock()
                .unwrap()
                .bindings
                .contains_key(&key));
        } else if change == 2 {
            // Exercise the normal Provider mutation/vault binding path while the
            // request retains its old private runtime snapshot.
            let response = crate::local_runtime::provider_management::update_llm_provider(
                State(f.state.clone()),
                Extension(f.auth.clone()),
                axum::extract::Path(route.provider_id.clone()),
                Json(
                    serde_json::from_value(json!({
                        "expected_revision":route.provider_revision,
                        "base_url":"http://127.0.0.1:1", "api_key":"replacement-fixture-key"
                    }))
                    .unwrap(),
                ),
            )
            .await
            .unwrap()
            .0;
            assert_eq!(
                response["revision"].as_u64(),
                Some(route.provider_revision + 1)
            );
        } else {
            let value = f
                .state
                .session_store
                .managed_resource(
                    ManagedResourceKind::Provider,
                    "tenant",
                    &f.operation.scope.tenant_id,
                    &route.provider_id,
                )
                .unwrap()
                .unwrap();
            f.state
                .session_store
                .put_managed_resource(
                    ManagedResourceKind::Provider,
                    "tenant",
                    &f.operation.scope.tenant_id,
                    &route.provider_id,
                    "active",
                    Some(route.provider_revision),
                    value,
                    chrono::Utc::now().timestamp_millis(),
                )
                .unwrap();
        }
        endpoint.release();
        assert!(task.await.unwrap().is_err());
        assert_eq!(
            f.repo()
                .reconcile_index_durable(&config, &|| Ok(chrono::Utc::now().timestamp_millis()))
                .unwrap()
                .completed_sources,
            0
        );
        assert!(f
            .operation
            .prepare_index_build(&f.state, &f.auth, &route, "stale-route")
            .await
            .is_err());
    }
}

#[tokio::test]
async fn same_revision_runtime_credential_rotation_is_not_exposed_and_discards_inflight_query() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "build")
        .await
        .unwrap();
    let config = f
        .operation
        .select_index_build(&f.state, &f.auth, &build, None)
        .unwrap();
    f.operation
        .index_one(&f.state, &f.auth, &config, IndexRunOptions::default())
        .await
        .unwrap();
    f.operation
        .promote_index_build(&f.state, &f.auth, &config, None)
        .unwrap();
    endpoint.pause();
    let operation = f.operation.clone();
    let state = f.state.clone();
    let auth = f.auth.clone();
    let querybuild = config.clone();
    let task = tokio::spawn(async move {
        operation
            .semantic_query(&state, &auth, &querybuild, "query", 10)
            .await
    });
    endpoint.entered().await;
    let key = ProviderRuntimeKey {
        tenant_id: f.operation.scope.tenant_id.clone(),
        provider_id: route.provider_id.clone(),
    };
    f.state
        .provider_runtime
        .lock()
        .unwrap()
        .credentials
        .insert(key, "rotated-fixture-credential".into());
    endpoint.release();
    assert!(task.await.unwrap().is_err());
}

#[tokio::test]
async fn explicit_no_auth_provider_uses_verified_embedding_without_a_credential_header() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let mut route = f.provider(&endpoint).await;
    let response = crate::local_runtime::provider_management::update_llm_provider(
        State(f.state.clone()),
        Extension(f.auth.clone()),
        axum::extract::Path(route.provider_id.clone()),
        Json(
            serde_json::from_value(
                json!({"expected_revision":route.provider_revision,"auth_method":"none"}),
            )
            .unwrap(),
        ),
    )
    .await
    .unwrap()
    .0;
    route.provider_revision = response["revision"].as_u64().unwrap();
    let build = f
        .operation
        .prepare_index_build(&f.state, &f.auth, &route, "no-auth")
        .await
        .unwrap();
    let config = f
        .operation
        .select_index_build(&f.state, &f.auth, &build, None)
        .unwrap();
    assert_eq!(build.profile.dimensions.get(), 2);
    assert_eq!(
        f.operation
            .index_one(&f.state, &f.auth, &config, IndexRunOptions::default())
            .await
            .unwrap()
            .unwrap()
            .outcome,
        IndexRunOutcome::Indexed
    );
    assert!(!endpoint.state.credential_seen.load(Ordering::SeqCst));
}
