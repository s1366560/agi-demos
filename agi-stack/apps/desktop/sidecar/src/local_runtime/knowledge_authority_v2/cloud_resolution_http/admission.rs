use super::*;

#[tokio::test]
async fn resolution_routes_reject_untrusted_fields_wrong_scope_generation_and_missing_key() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let (operation, scope) = setup(&state).await;
    let (cloud, base, server) = cloud().await;
    let broker = install_broker(&state, &directory, base);
    push(Arc::clone(&state), json!({"scope":scope})).await;
    cloud.data.lock().unwrap().calls.clear();
    let body = json!({"scope":scope,"resolution":command(&cloud)});
    assert_eq!(
        call(Arc::clone(&state), "sync-resolve-push", body.clone(), None)
            .await
            .0,
        StatusCode::BAD_REQUEST
    );
    for field in ["actor_id", "remote", "receipt", "url"] {
        let mut forged = body.clone();
        forged[field] = json!("injected");
        assert_eq!(
            call(Arc::clone(&state), "sync-resolve-push", forged, Some("key"))
                .await
                .0,
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }
    let mut wrong = body.clone();
    wrong["scope"]["tenant_id"] = json!("other");
    assert_eq!(
        call(Arc::clone(&state), "sync-resolve-push", wrong, Some("key"))
            .await
            .0,
        StatusCode::FORBIDDEN
    );
    let mut wrong = body;
    wrong["scope"]["generation"] = json!(99);
    assert_eq!(
        call(Arc::clone(&state), "sync-resolve-push", wrong, Some("key"))
            .await
            .0,
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
            .resolve_cloud_conflict(
                &broker,
                "key",
                serde_json::from_value::<KnowledgeCloudResolutionCommand>(command(&cloud)).unwrap()
            )
            .await,
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    assert!(cloud.data.lock().unwrap().calls.is_empty());
    drop(viewer);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
    server.abort();
}

#[tokio::test]
async fn all_cloud_routes_stay_closed_without_opening_storage() {
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
    let id = Uuid::new_v4().to_string();
    let resolution = json!({
        "local_sequence":1,
        "memory_id":"memory",
        "conflict_id":id,
        "guard":{
            "expected_local_revision":1,
            "expected_remote_revision":1,
            "expected_baseline_revision":0,
            "conflict_sequences":[]
        },
        "choice":{
            "decision":"keep_current"
        }
    });
    for (path, body) in [
        (
            "sync-resolve-push",
            json!({"scope":scope,"resolution":resolution}),
        ),
        (
            "sync-resume-resolution",
            json!({"scope":scope,"resolution_id":id}),
        ),
        (
            "sync-reconcile-resolution",
            json!({
                "scope":scope,
                "resolution_id":id,
                "reconciliation":{
                    "guard":{
                        "expected_local_revision":1,
                        "expected_remote_revision":1,
                        "expected_baseline_revision":0,
                        "conflict_sequences":[]
                    },
                    "choice":{
                        "decision":"use_remote"
                    }
                }
            }),
        ),
        (
            "sync-cloud-query",
            json!({"scope":scope,"query":{"operation":"resolutions","limit":10}}),
        ),
    ] {
        let result = call(Arc::clone(&state), path, body, Some("key")).await;
        assert_eq!(result.0, StatusCode::SERVICE_UNAVAILABLE, "{path}");
        assert_eq!(result.1["error"]["code"], "knowledge_release_closed");
    }
    assert!(!directory.0.exists());
    state.platform_plugin_authority_v2.deactivate().await;
}
