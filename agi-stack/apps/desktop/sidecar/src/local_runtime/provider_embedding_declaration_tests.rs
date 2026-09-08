#[tokio::test]
async fn explicit_embedding_declaration_is_revision_bound_and_visible_in_saved_catalog() {
    let (base, shutdown) = spawn_provider_model_server(&["opaque-a", "opaque-b"]).await;
    let state = test_state("embedding-declaration-test");
    let app = local_router(Arc::clone(&state));
    let update = app.clone().oneshot(authenticated_json_request("PUT", "/api/v1/llm-providers/local-runtime", "embedding-declaration-test", json!({
        "provider_type":"openai_compatible", "base_url":base, "auth_method":"none", "is_active":true,
        "llm_model":"opaque-a", "allowed_models":["opaque-a", "opaque-b"], "embedding_model":"opaque-b", "expected_revision":0
    }))).await.expect("save declared provider");
    assert_eq!(update.status(), axum::http::StatusCode::OK);
    let provider = response_json(update).await;
    assert_eq!(provider["embedding_model"], "opaque-b");
    assert_eq!(provider["revision"], 1);
    assert!(provider_supports_route_model(&provider, "opaque-b"));
    let stored = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "local-runtime",
        )
        .expect("stored provider")
        .expect("provider exists");
    assert_eq!(stored["embedding_model"], "opaque-b");
    for suffix in ["models/discover", "health-check"] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                &format!("/api/v1/llm-providers/local-runtime/{suffix}"),
                "embedding-declaration-test",
                json!({"expected_revision":1}),
            ))
            .await
            .expect("read provider catalog");
        assert_eq!(response.status(), axum::http::StatusCode::OK);
        let result = response_json(response).await;
        let catalog = if suffix == "health-check" {
            &result["catalog"]
        } else {
            &result
        };
        assert_eq!(catalog["models"]["embedding"], json!(["opaque-b"]));
        assert_eq!(catalog["models"]["chat"], json!(["opaque-a", "opaque-b"]));
        assert_eq!(catalog["source"], "provider-api+explicit-configuration");
    }
    let _ = shutdown.send(());
}

#[tokio::test]
async fn embedding_declaration_rejects_nonmembers_and_stale_revision_and_can_be_cleared() {
    let state = test_state("embedding-membership-test");
    let app = local_router(state);
    let invalid = app.clone().oneshot(authenticated_json_request("PUT", "/api/v1/llm-providers/local-runtime", "embedding-membership-test", json!({"llm_model":"opaque-a", "allowed_models":["opaque-a"], "embedding_model":"not-allowed", "expected_revision":0}))).await.expect("invalid declaration");
    assert_eq!(
        invalid.status(),
        axum::http::StatusCode::UNPROCESSABLE_ENTITY
    );
    let update = app.clone().oneshot(authenticated_json_request("PUT", "/api/v1/llm-providers/local-runtime", "embedding-membership-test", json!({"llm_model":"opaque-a", "allowed_models":["opaque-a", "opaque-b"], "embedding_model":"opaque-b", "expected_revision":0}))).await.expect("valid declaration");
    assert_eq!(update.status(), axum::http::StatusCode::OK);
    for (payload, status) in [
        (
            json!({"embedding_model":"opaque-a", "expected_revision":0}),
            axum::http::StatusCode::CONFLICT,
        ),
        (
            json!({"allowed_models":["opaque-a"], "expected_revision":1}),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY,
        ),
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "embedding-membership-test",
                payload,
            ))
            .await
            .expect("reject invalid update");
        assert_eq!(response.status(), status);
    }
    let clear = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "embedding-membership-test",
            json!({"embedding_model":"", "allowed_models":["opaque-a"], "expected_revision":1}),
        ))
        .await
        .expect("clear declaration");
    assert_eq!(clear.status(), axum::http::StatusCode::OK);
    let provider = response_json(clear).await;
    assert!(provider["embedding_model"].is_null());
    assert_eq!(provider["revision"], 2);
}

#[test]
fn saved_embedding_role_comes_only_from_explicit_allowed_configuration() {
    let outcome = ProviderProbeOutcome {
        status: "healthy",
        detail: "fixture",
        error_code: None,
        response_time_ms: 0,
        models: vec![provider_probe::DiscoveredModel {
            id: "text-embedding-name-is-not-authority".into(),
        }],
    };
    let undeclared = provider_probe_catalog(
        "openai_compatible",
        Some("provider"),
        &outcome,
        "fixture",
        None,
    );
    assert_eq!(undeclared["models"]["embedding"], json!([]));
    let declared = json!({"llm_model":"opaque-primary", "allowed_models":["opaque-other"], "embedding_model":"opaque-other"});
    let catalog = provider_probe_catalog(
        "openai_compatible",
        Some("provider"),
        &outcome,
        "fixture",
        Some(&declared),
    );
    assert_eq!(catalog["models"]["embedding"], json!(["opaque-other"]));
    let invalid = json!({"allowed_models":[], "embedding_model":"not-allowed"});
    let catalog = provider_probe_catalog(
        "openai_compatible",
        Some("provider"),
        &outcome,
        "fixture",
        Some(&invalid),
    );
    assert_eq!(catalog["models"]["embedding"], json!([]));
    let failed = ProviderProbeOutcome {
        status: "failed",
        models: Vec::new(),
        ..outcome
    };
    let catalog = provider_probe_catalog(
        "openai_compatible",
        Some("provider"),
        &failed,
        "fixture",
        Some(&declared),
    );
    assert_eq!(catalog["availability"], "unavailable");
    assert_eq!(catalog["models"]["embedding"], json!([]));
}

#[test]
fn omitted_embedding_declaration_preserves_legacy_mutation_serialization() {
    let request: LlmProviderMutation =
        serde_json::from_value(json!({"name":"Provider"})).expect("legacy mutation");
    let serialized = serde_json::to_value(request).expect("serialized mutation");
    assert!(serialized.get("embedding_model").is_none());
}
