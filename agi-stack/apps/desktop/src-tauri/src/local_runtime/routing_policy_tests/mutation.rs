use super::*;

#[tokio::test]
async fn routing_policy_rejects_stale_revision_without_changing_selection() {
    let credential = "routing-revision-secret";
    let state = test_state(credential);
    seed_active_provider(
        &state,
        "local",
        "local-runtime",
        "primary-model",
        &["primary-model"],
    );
    let app = local_router(Arc::clone(&state));

    let initial = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(0, "local-runtime", "primary-model", json!([])),
        ))
        .await
        .expect("initial routing policy save");
    assert_eq!(initial.status(), StatusCode::OK);

    let stale = app
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(0, "provider-removed", "model-removed", json!([])),
        ))
        .await
        .expect("stale routing policy save");
    assert_eq!(stale.status(), StatusCode::CONFLICT);
    assert!(response_json(stale).await["detail"]
        .as_str()
        .is_some_and(|detail| detail.contains("expected 0, found 1")));
    let persisted = state
        .session_store
        .llm_routing_policy("local", Utc::now().timestamp_millis())
        .expect("persisted routing policy");
    assert_eq!(persisted["revision"], 1);
}

#[tokio::test]
async fn legacy_runtime_selection_atomically_updates_existing_policy_default() {
    let credential = "routing-legacy-selection-secret";
    let state = test_state(credential);
    seed_active_provider(
        &state,
        "local",
        "local-runtime",
        "primary-model",
        &["primary-model", "coding-model"],
    );
    let fallback_revision = seed_active_provider(
        &state,
        "local",
        "fallback-provider",
        "fallback-model",
        &["fallback-model"],
    );
    let app = local_router(Arc::clone(&state));
    let saved = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(
                0,
                "local-runtime",
                "coding-model",
                json!([{"provider_id": "local-runtime", "model_id": "primary-model"}]),
            ),
        ))
        .await
        .expect("initial routing policy save");
    assert_eq!(saved.status(), StatusCode::OK);

    let stale_selection = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/fallback-provider/runtime-selection",
            credential,
            json!({
                "expected_revision": fallback_revision,
                "expected_policy_revision": 0
            }),
        ))
        .await
        .expect("stale legacy runtime selection");
    assert_eq!(stale_selection.status(), StatusCode::CONFLICT);

    let selected = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/fallback-provider/runtime-selection",
            credential,
            json!({
                "expected_revision": fallback_revision,
                "expected_policy_revision": 1
            }),
        ))
        .await
        .expect("legacy runtime selection");
    assert_eq!(selected.status(), StatusCode::OK);

    let policy = app
        .oneshot(authenticated_json_request(
            "GET",
            "/api/v1/llm-providers/routing-policy",
            credential,
            json!({}),
        ))
        .await
        .expect("routing policy after legacy selection");
    assert_eq!(policy.status(), StatusCode::OK);
    let policy = response_json(policy).await;
    assert_eq!(policy["revision"], 2);
    assert_eq!(
        policy["roles"]["default"],
        json!({"provider_id": "fallback-provider", "model_id": "fallback-model"})
    );
    assert_eq!(
        policy["fallbacks"],
        json!([{"provider_id": "local-runtime", "model_id": "primary-model"}])
    );
    assert_eq!(
        state
            .session_store
            .list_selected_llm_providers()
            .expect("legacy selection"),
        vec![("local".to_string(), "fallback-provider".to_string())]
    );
    let runtime = state.provider_runtime.lock().expect("provider runtime");
    let key = ProviderRuntimeKey {
        tenant_id: "local".to_string(),
        provider_id: "fallback-provider".to_string(),
    };
    assert_eq!(runtime.bindings[&key].model, "fallback-model");
}

#[tokio::test]
async fn provider_update_cannot_invalidate_selected_default_route() {
    let credential = "routing-provider-invalidation-secret";
    let state = test_state(credential);
    let provider_revision = seed_active_provider(
        &state,
        "local",
        "local-runtime",
        "primary-model",
        &["primary-model", "coding-model"],
    );
    let app = local_router(Arc::clone(&state));
    let saved = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(0, "local-runtime", "coding-model", json!([])),
        ))
        .await
        .expect("routing policy save");
    assert_eq!(saved.status(), StatusCode::OK);

    for mutation in [
        json!({
            "allowed_models": ["primary-model"],
            "expected_revision": provider_revision
        }),
        json!({
            "is_active": false,
            "expected_revision": provider_revision
        }),
    ] {
        let rejected = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                credential,
                mutation,
            ))
            .await
            .expect("provider invalidation response");
        assert_eq!(rejected.status(), StatusCode::UNPROCESSABLE_ENTITY);
        assert!(response_json(rejected).await["detail"]
            .as_str()
            .is_some_and(|detail| detail.contains("invalidate")));
    }

    let provider = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "local-runtime",
        )
        .expect("load provider")
        .expect("provider");
    assert_eq!(provider["revision"], provider_revision);
    assert_eq!(provider["is_active"], true);
    assert_eq!(
        state
            .session_store
            .llm_routing_policy("local", Utc::now().timestamp_millis())
            .expect("routing policy")["roles"]["default"]["model_id"],
        "coding-model"
    );
    let runtime = state.provider_runtime.lock().expect("provider runtime");
    let key = ProviderRuntimeKey {
        tenant_id: "local".to_string(),
        provider_id: "local-runtime".to_string(),
    };
    assert_eq!(runtime.bindings[&key].model, "coding-model");
}

#[tokio::test]
async fn disabling_unreferenced_provider_clears_only_its_runtime_material() {
    let credential = "routing-spare-provider-secret";
    let state = test_state(credential);
    seed_active_provider(
        &state,
        "local",
        "primary-provider",
        "primary-model",
        &["primary-model"],
    );
    let app = local_router(Arc::clone(&state));
    let saved = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(0, "primary-provider", "primary-model", json!([])),
        ))
        .await
        .expect("primary routing policy save");
    assert_eq!(saved.status(), StatusCode::OK);

    let created = app
        .clone()
        .oneshot(authenticated_json_request(
            "POST",
            "/api/v1/llm-providers/",
            credential,
            json!({
                "name": "Spare provider",
                "provider_type": "openai",
                "base_url": "https://spare.example.test/v1",
                "auth_method": "api_key",
                "api_key": "spare-provider-key",
                "llm_model": "spare-model",
                "allowed_models": ["spare-model"],
                "is_active": true
            }),
        ))
        .await
        .expect("create spare provider");
    assert_eq!(created.status(), StatusCode::OK);
    let created = response_json(created).await;
    let spare_id = created["id"].as_str().expect("spare provider id");
    let spare_revision = created["revision"].as_u64().expect("spare revision");
    let spare_key = ProviderRuntimeKey {
        tenant_id: "local".to_string(),
        provider_id: spare_id.to_string(),
    };
    {
        let runtime = state.provider_runtime.lock().expect("provider runtime");
        assert!(runtime.bindings.contains_key(&spare_key));
        assert!(runtime.credentials.contains_key(&spare_key));
    }

    let disabled = app
        .oneshot(authenticated_json_request(
            "PUT",
            &format!("/api/v1/llm-providers/{spare_id}"),
            credential,
            json!({"is_active": false, "expected_revision": spare_revision}),
        ))
        .await
        .expect("disable spare provider");
    assert_eq!(disabled.status(), StatusCode::OK);
    let runtime = state.provider_runtime.lock().expect("provider runtime");
    assert!(!runtime.bindings.contains_key(&spare_key));
    assert!(!runtime.credentials.contains_key(&spare_key));
    assert_eq!(
        runtime.selections.get("local").map(String::as_str),
        Some("primary-provider")
    );
    drop(runtime);
    let policy = state
        .session_store
        .llm_routing_policy("local", Utc::now().timestamp_millis())
        .expect("unchanged policy");
    assert_eq!(policy["revision"], 1);
    assert_eq!(
        policy["roles"]["default"]["provider_id"],
        "primary-provider"
    );
}

#[tokio::test]
async fn routing_policy_is_tenant_isolated_and_rejects_cross_tenant_targets() {
    let credential = "routing-tenant-secret";
    let state = test_state(credential);
    seed_active_provider(
        &state,
        "local",
        "local-runtime",
        "local-model",
        &["local-model"],
    );
    seed_active_provider(
        &state,
        "northstar",
        "northstar-only",
        "northstar-model",
        &["northstar-model"],
    );
    let app = local_router(Arc::clone(&state));

    let cross_tenant = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(0, "northstar-only", "northstar-model", json!([])),
        ))
        .await
        .expect("cross-tenant routing policy response");
    assert_eq!(cross_tenant.status(), StatusCode::NOT_FOUND);

    let local = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(0, "local-runtime", "local-model", json!([])),
        ))
        .await
        .expect("local routing policy save");
    assert_eq!(local.status(), StatusCode::OK);
    switch_context(
        &state,
        credential,
        "northstar",
        "desktop-client",
        0,
        "switch-routing-policy-tenant",
    );
    let northstar = app
        .oneshot(authenticated_json_request(
            "GET",
            "/api/v1/llm-providers/routing-policy",
            credential,
            json!({}),
        ))
        .await
        .expect("northstar routing policy response");
    assert_eq!(northstar.status(), StatusCode::OK);
    let northstar = response_json(northstar).await;
    assert_eq!(northstar["tenant_id"], "northstar");
    assert_eq!(northstar["roles"]["default"], Value::Null);
    assert_eq!(
        state
            .session_store
            .llm_routing_policy("local", Utc::now().timestamp_millis())
            .expect("local routing policy")["revision"],
        1
    );
}

#[tokio::test]
async fn routing_policy_validates_default_models_and_fallback_constraints() {
    let credential = "routing-validation-secret";
    let state = test_state(credential);
    seed_active_provider(
        &state,
        "local",
        "local-runtime",
        "primary-model",
        &["primary-model", "alternate-model"],
    );
    let missing_credential_revision = seed_active_provider(
        &state,
        "local",
        "missing-credential-provider",
        "credential-model",
        &["credential-model"],
    );
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "missing-credential-provider",
            "active",
            Some(missing_credential_revision),
            json!({
                "id": "missing-credential-provider",
                "name": "missing-credential-provider",
                "provider_type": "openai",
                "tenant_id": "local",
                "is_active": true,
                "base_url": "https://api.example.test/v1",
                "auth_method": "api_key",
                "credential_source": "runtime_memory",
                "credential_configured": true,
                "llm_model": "credential-model",
                "allowed_models": ["credential-model"],
                "secondary_models": [],
                "health_status": "configuration_valid",
            }),
            Utc::now().timestamp_millis(),
        )
        .expect("seed provider with unavailable runtime credential");
    let app = local_router(state);

    let missing_credential = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(
                0,
                "missing-credential-provider",
                "credential-model",
                json!([]),
            ),
        ))
        .await
        .expect("missing credential routing response");
    assert_eq!(
        missing_credential.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );

    for role in ["fast", "vision"] {
        let mut body = policy_body(0, "local-runtime", "primary-model", json!([]));
        body["roles"][role] = json!({
            "provider_id": "local-runtime",
            "model_id": "alternate-model",
        });
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/routing-policy",
                credential,
                body,
            ))
            .await
            .expect("unsupported workload routing response");
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        assert!(response_json(response).await["detail"]
            .as_str()
            .is_some_and(|detail| detail.contains(&format!("{role} routing target"))));
    }

    for body in [
        json!({
            "expected_revision": 0,
            "roles": {"default": null, "fast": null, "coding": null, "vision": null},
            "fallbacks": []
        }),
        json!({
            "expected_revision": 0,
            "roles": {
                "default": {"provider_id": "local-runtime", "model_id": "primary-model"},
                "fast": null,
                "coding": null
            },
            "fallbacks": []
        }),
        json!({
            "expected_revision": 0,
            "roles": {
                "default": {
                    "provider_id": "local-runtime",
                    "model_id": "primary-model",
                    "unexpected": true
                },
                "fast": null,
                "coding": null,
                "vision": null
            },
            "fallbacks": []
        }),
        policy_body(0, "local-runtime", "missing-model", json!([])),
        policy_body(
            0,
            "local-runtime",
            "primary-model",
            json!([
                {"provider_id": "local-runtime", "model_id": "alternate-model"},
                {"provider_id": "local-runtime", "model_id": "alternate-model"}
            ]),
        ),
        policy_body(
            0,
            "local-runtime",
            "primary-model",
            json!([
                {"provider_id": "local-runtime", "model_id": "primary-model"},
                {"provider_id": "local-runtime", "model_id": "alternate-model"},
                {"provider_id": "local-runtime", "model_id": "primary-model-2"},
                {"provider_id": "local-runtime", "model_id": "primary-model-3"},
                {"provider_id": "local-runtime", "model_id": "primary-model-4"},
                {"provider_id": "local-runtime", "model_id": "primary-model-5"},
                {"provider_id": "local-runtime", "model_id": "primary-model-6"},
                {"provider_id": "local-runtime", "model_id": "primary-model-7"},
                {"provider_id": "local-runtime", "model_id": "primary-model-8"}
            ]),
        ),
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/routing-policy",
                credential,
                body,
            ))
            .await
            .expect("invalid routing policy response");
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }
}

#[tokio::test]
async fn routing_policy_allows_member_reads_but_requires_manager_for_mutation() {
    let credential = "routing-member-secret";
    let state = test_state(credential);
    seed_active_provider(
        &state,
        "orbital",
        "local-runtime",
        "member-model",
        &["member-model"],
    );
    switch_context(
        &state,
        credential,
        "orbital",
        "agent-evals",
        0,
        "switch-routing-policy-member",
    );
    let app = local_router(state);

    let read = app
        .clone()
        .oneshot(authenticated_json_request(
            "GET",
            "/api/v1/llm-providers/routing-policy",
            credential,
            json!({}),
        ))
        .await
        .expect("member routing policy read");
    assert_eq!(read.status(), StatusCode::OK);

    let mutation = app
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy",
            credential,
            policy_body(0, "local-runtime", "member-model", json!([])),
        ))
        .await
        .expect("member routing policy mutation");
    assert_eq!(mutation.status(), StatusCode::FORBIDDEN);
}
