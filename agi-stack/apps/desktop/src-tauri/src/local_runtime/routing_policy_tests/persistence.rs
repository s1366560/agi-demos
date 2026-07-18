use super::*;

#[tokio::test]
async fn get_routing_policy_returns_empty_then_migrates_legacy_selection() {
    let credential = "routing-get-secret";
    let state = test_state(credential);
    let app = local_router(Arc::clone(&state));

    let empty = app
        .clone()
        .oneshot(authenticated_json_request(
            "GET",
            "/api/v1/llm-providers/routing-policy",
            credential,
            json!({}),
        ))
        .await
        .expect("empty routing policy response");
    assert_eq!(empty.status(), StatusCode::OK);
    let empty = response_json(empty).await;
    assert_eq!(empty["tenant_id"], "local");
    assert_eq!(empty["revision"], 0);
    assert_eq!(
        empty["roles"],
        json!({"default": null, "fast": null, "coding": null, "vision": null})
    );
    assert_eq!(empty["fallbacks"], json!([]));

    seed_active_provider(
        &state,
        "local",
        "local-runtime",
        "primary-model",
        &["primary-model", "coding-model"],
    );
    state
        .session_store
        .connection()
        .expect("session connection")
        .execute(
            "INSERT INTO desktop_llm_provider_selections(tenant_id, provider_id, selected_at_ms)
             VALUES ('local', 'local-runtime', ?1)",
            [Utc::now().timestamp_millis()],
        )
        .expect("legacy provider selection");

    let migrated = app
        .oneshot(authenticated_json_request(
            "GET",
            "/api/v1/llm-providers/routing-policy",
            credential,
            json!({}),
        ))
        .await
        .expect("migrated routing policy response");
    assert_eq!(migrated.status(), StatusCode::OK);
    let migrated = response_json(migrated).await;
    assert_eq!(migrated["revision"], 0);
    assert_eq!(migrated["roles"]["default"]["provider_id"], "local-runtime");
    assert_eq!(migrated["roles"]["default"]["model_id"], "primary-model");
    assert_eq!(
        state
            .session_store
            .list_llm_routing_policies()
            .expect("persisted migrated policy")
            .len(),
        1
    );
}

#[tokio::test]
async fn put_routing_policy_persists_order_and_restores_selected_model_after_restart() {
    let root = test_root();
    std::fs::create_dir_all(&root).expect("create test root");
    let store_path = root.join("sessions.db");
    let workspace_root = root.join("workspace");
    std::fs::create_dir_all(&workspace_root).expect("create workspace root");
    let credential = "routing-restart-secret";

    {
        let state = file_state(&store_path, &workspace_root, credential);
        state
            .session_store
            .seed_test_session(credential)
            .expect("authenticated test session");
        seed_active_provider(
            &state,
            "local",
            "local-runtime",
            "primary-model",
            &["primary-model", "coding-model"],
        );
        seed_active_provider(
            &state,
            "local",
            "fallback-provider",
            "fallback-a",
            &["fallback-a", "fallback-b"],
        );
        let app = local_router(Arc::clone(&state));
        let saved = app
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/routing-policy",
                credential,
                policy_body(
                    0,
                    "local-runtime",
                    "coding-model",
                    json!([
                        {"provider_id": "fallback-provider", "model_id": "fallback-b"},
                        {"provider_id": "local-runtime", "model_id": "primary-model"}
                    ]),
                ),
            ))
            .await
            .expect("save routing policy");
        assert_eq!(saved.status(), StatusCode::OK);
        let saved = response_json(saved).await;
        assert_eq!(saved["revision"], 1);
        assert_eq!(saved["fallbacks"][0]["provider_id"], "fallback-provider");
        assert_eq!(saved["fallbacks"][1]["provider_id"], "local-runtime");
        assert_eq!(
            state
                .session_store
                .list_selected_llm_providers()
                .expect("legacy selection"),
            vec![("local".to_string(), "local-runtime".to_string())]
        );
        let runtime = state.provider_runtime.lock().expect("provider runtime");
        let key = ProviderRuntimeKey {
            tenant_id: "local".to_string(),
            provider_id: "local-runtime".to_string(),
        };
        assert_eq!(runtime.bindings[&key].model, "coding-model");
    }

    let state = file_state(&store_path, &workspace_root, credential);
    let key = ProviderRuntimeKey {
        tenant_id: "local".to_string(),
        provider_id: "local-runtime".to_string(),
    };
    {
        let runtime = state
            .provider_runtime
            .lock()
            .expect("restored provider runtime");
        assert_eq!(
            runtime.selections.get("local"),
            Some(&"local-runtime".to_string())
        );
        assert_eq!(runtime.bindings[&key].model, "coding-model");
    }
    let restored = local_router(state)
        .oneshot(authenticated_json_request(
            "GET",
            "/api/v1/llm-providers/routing-policy",
            credential,
            json!({}),
        ))
        .await
        .expect("restored routing policy response");
    assert_eq!(restored.status(), StatusCode::OK);
    let restored = response_json(restored).await;
    assert_eq!(restored["revision"], 1);
    assert_eq!(restored["roles"]["default"]["model_id"], "coding-model");

    std::fs::remove_dir_all(root).expect("remove test root");
}
