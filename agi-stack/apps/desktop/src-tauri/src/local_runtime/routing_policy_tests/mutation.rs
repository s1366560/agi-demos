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
            LOCAL_ROUTING_POLICY_URI,
            credential,
            policy_body(0, "local-runtime", "primary-model", json!([])),
        ))
        .await
        .expect("initial routing policy save");
    assert_eq!(initial.status(), StatusCode::OK);

    let stale = app
        .oneshot(authenticated_json_request(
            "PUT",
            LOCAL_ROUTING_POLICY_URI,
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
        .workspace_llm_routing_policy(
            "local",
            "local-project",
            "local-workspace",
            Utc::now().timestamp_millis(),
        )
        .expect("persisted routing policy");
    assert_eq!(persisted["revision"], 1);
}

#[tokio::test]
async fn routing_policy_rejects_workspace_scope_outside_the_active_hierarchy_without_writes() {
    let credential = "routing-scope-secret";
    let state = test_state(credential);
    let app = local_router(Arc::clone(&state));

    let read = app
        .clone()
        .oneshot(authenticated_json_request(
            "GET",
            "/api/v1/llm-providers/routing-policy?project_id=local-project&workspace_id=local-demo-desktop-client-main",
            credential,
            json!({}),
        ))
        .await
        .expect("cross-scope read");
    assert_eq!(read.status(), StatusCode::FORBIDDEN);

    let mut mutation = policy_body(0, "local-runtime", "local-model", json!([]));
    mutation["workspace_id"] = json!("local-demo-desktop-client-main");
    let write = app
        .oneshot(authenticated_json_request(
            "PUT",
            LOCAL_ROUTING_POLICY_URI,
            credential,
            mutation,
        ))
        .await
        .expect("cross-scope write");
    assert_eq!(write.status(), StatusCode::FORBIDDEN);

    let policy_count: i64 = state
        .session_store
        .connection()
        .expect("session connection")
        .query_row(
            "SELECT COUNT(*) FROM desktop_llm_workspace_routing_policies",
            [],
            |row| row.get(0),
        )
        .expect("workspace routing policy count");
    assert_eq!(policy_count, 0);
}

#[tokio::test]
async fn legacy_runtime_selection_does_not_overwrite_workspace_policy() {
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
            LOCAL_ROUTING_POLICY_URI,
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

    let selected = app
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
        .expect("legacy runtime selection");
    assert_eq!(selected.status(), StatusCode::OK);

    let policy = app
        .oneshot(authenticated_json_request(
            "GET",
            LOCAL_ROUTING_POLICY_URI,
            credential,
            json!({}),
        ))
        .await
        .expect("routing policy after legacy selection");
    assert_eq!(policy.status(), StatusCode::OK);
    let policy = response_json(policy).await;
    assert_eq!(policy["revision"], 1);
    assert_eq!(
        policy["roles"]["default"],
        json!({"provider_id": "local-runtime", "model_id": "coding-model"})
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
            LOCAL_ROUTING_POLICY_URI,
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
            .workspace_llm_routing_policy(
                "local",
                "local-project",
                "local-workspace",
                Utc::now().timestamp_millis(),
            )
            .expect("routing policy")["roles"]["default"]["model_id"],
        "coding-model"
    );
    let runtime = state.provider_runtime.lock().expect("provider runtime");
    let key = ProviderRuntimeKey {
        tenant_id: "local".to_string(),
        provider_id: "local-runtime".to_string(),
    };
    assert_eq!(runtime.bindings[&key].model, "primary-model");
}

#[tokio::test]
async fn provider_update_cannot_invalidate_the_unmaterialized_legacy_workspace_baseline() {
    let credential = "routing-legacy-baseline-protection-secret";
    let state = test_state(credential);
    let provider_revision = seed_active_provider(
        &state,
        "local",
        "legacy-provider",
        "legacy-model",
        &["legacy-model"],
    );
    state
        .session_store
        .connection()
        .expect("session connection")
        .execute(
            "INSERT INTO desktop_llm_provider_selections(tenant_id, provider_id, selected_at_ms)
             VALUES ('local', 'legacy-provider', ?1)",
            [Utc::now().timestamp_millis()],
        )
        .expect("legacy provider selection");
    let policy_count: i64 = state
        .session_store
        .connection()
        .expect("session connection")
        .query_row(
            "SELECT COUNT(*) FROM desktop_llm_workspace_routing_policies",
            [],
            |row| row.get(0),
        )
        .expect("workspace routing policy count");
    assert_eq!(policy_count, 0);
    let app = local_router(Arc::clone(&state));

    let rejected = app
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/legacy-provider",
            credential,
            json!({
                "is_active": false,
                "expected_revision": provider_revision,
            }),
        ))
        .await
        .expect("legacy baseline invalidation response");
    assert_eq!(rejected.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert!(response_json(rejected).await["detail"]
        .as_str()
        .is_some_and(|detail| detail.contains("invalidate routing policy")));
    assert!(state
        .session_store
        .workspace_llm_routing_policy(
            "local",
            "local-project",
            "local-workspace",
            Utc::now().timestamp_millis(),
        )
        .expect("protected workspace baseline")["roles"]["default"]
        .is_object());
}

#[tokio::test]
async fn disabling_unreferenced_provider_clears_runtime_material_but_preserves_its_vault_secret() {
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
            LOCAL_ROUTING_POLICY_URI,
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
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            &format!("/api/v1/llm-providers/{spare_id}"),
            credential,
            json!({"is_active": false, "expected_revision": spare_revision}),
        ))
        .await
        .expect("disable spare provider");
    assert_eq!(disabled.status(), StatusCode::OK);
    let disabled = response_json(disabled).await;
    assert_eq!(disabled["credential_configured"], true);
    assert_eq!(disabled["health_status"], "disabled");
    let disabled_revision = disabled["revision"].as_u64().expect("disabled revision");
    {
        let runtime = state.provider_runtime.lock().expect("provider runtime");
        assert!(!runtime.bindings.contains_key(&spare_key));
        assert!(!runtime.credentials.contains_key(&spare_key));
        assert!(runtime.configured_credentials.contains(&spare_key));
        assert_eq!(runtime.selections.get("local"), None);
    }
    let policy = state
        .session_store
        .workspace_llm_routing_policy(
            "local",
            "local-project",
            "local-workspace",
            Utc::now().timestamp_millis(),
        )
        .expect("unchanged policy");
    assert_eq!(policy["revision"], 1);
    assert_eq!(
        policy["roles"]["default"]["provider_id"],
        "primary-provider"
    );

    let reactivated = app
        .oneshot(authenticated_json_request(
            "PUT",
            &format!("/api/v1/llm-providers/{spare_id}"),
            credential,
            json!({"is_active": true, "expected_revision": disabled_revision}),
        ))
        .await
        .expect("reactivate spare provider");
    assert_eq!(reactivated.status(), StatusCode::OK);
    let reactivated = response_json(reactivated).await;
    assert_eq!(reactivated["credential_configured"], true);
    assert_eq!(reactivated["health_status"], "configuration_valid");
    let runtime = state.provider_runtime.lock().expect("provider runtime");
    assert!(runtime.bindings.contains_key(&spare_key));
    assert!(runtime.credentials.contains_key(&spare_key));
    assert!(runtime.configured_credentials.contains(&spare_key));
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
            LOCAL_ROUTING_POLICY_URI,
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
            LOCAL_ROUTING_POLICY_URI,
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
            "/api/v1/llm-providers/routing-policy?project_id=desktop-client&workspace_id=local-demo-desktop-client-main",
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
            .workspace_llm_routing_policy(
                "local",
                "local-project",
                "local-workspace",
                Utc::now().timestamp_millis(),
            )
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
                "credential_source": "system_vault",
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
            LOCAL_ROUTING_POLICY_URI,
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

    for body in [
        json!({
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "expected_revision": 0,
            "roles": {"default": null, "fast": null, "coding": null, "vision": null},
            "fallbacks": []
        }),
        json!({
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "expected_revision": 0,
            "roles": {
                "default": {"provider_id": "local-runtime", "model_id": "primary-model"},
                "fast": null,
                "coding": null
            },
            "fallbacks": []
        }),
        json!({
            "project_id": "local-project",
            "workspace_id": "local-workspace",
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
                LOCAL_ROUTING_POLICY_URI,
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
    state
        .session_store
        .insert_workspace(&json!({
            "id": "orbital-evals-workspace",
            "tenant_id": "orbital",
            "project_id": "agent-evals",
            "name": "Agent evals",
        }))
        .expect("orbital workspace");
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
            "/api/v1/llm-providers/routing-policy?project_id=agent-evals&workspace_id=orbital-evals-workspace",
            credential,
            json!({}),
        ))
        .await
        .expect("member routing policy read");
    assert_eq!(read.status(), StatusCode::OK);

    let mut member_policy = policy_body(0, "local-runtime", "member-model", json!([]));
    member_policy["project_id"] = json!("agent-evals");
    member_policy["workspace_id"] = json!("orbital-evals-workspace");
    let mutation = app
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/routing-policy?project_id=agent-evals&workspace_id=orbital-evals-workspace",
            credential,
            member_policy,
        ))
        .await
        .expect("member routing policy mutation");
    assert_eq!(mutation.status(), StatusCode::FORBIDDEN);
}
