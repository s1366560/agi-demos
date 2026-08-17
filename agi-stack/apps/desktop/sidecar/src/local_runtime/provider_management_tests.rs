struct ConflictThenFailClearProviderCredentialStore {
    values: Mutex<HashMap<String, String>>,
    session_store: DesktopSessionStore,
    conflict_armed: std::sync::atomic::AtomicBool,
    injected_conflict: std::sync::atomic::AtomicBool,
    fail_next_generation_clear: std::sync::atomic::AtomicBool,
}

impl ConflictThenFailClearProviderCredentialStore {
    fn new(session_store: DesktopSessionStore) -> Self {
        Self {
            values: Mutex::new(HashMap::new()),
            session_store,
            conflict_armed: std::sync::atomic::AtomicBool::new(false),
            injected_conflict: std::sync::atomic::AtomicBool::new(false),
            fail_next_generation_clear: std::sync::atomic::AtomicBool::new(false),
        }
    }

    fn arm_conflict(&self) {
        self.conflict_armed.store(true, Ordering::SeqCst);
    }
}

impl ProviderCredentialStore for ConflictThenFailClearProviderCredentialStore {
    fn save(&self, account: &str, value: &str) -> Result<(), ProviderCredentialStoreError> {
        self.values
            .lock()
            .expect("conflict credential store")
            .insert(account.to_string(), value.to_string());
        if self.conflict_armed.load(Ordering::SeqCst)
            && account.starts_with("llm-provider-credential.v2.")
            && !self.injected_conflict.swap(true, Ordering::SeqCst)
        {
            self.session_store
                .put_managed_resource(
                    ManagedResourceKind::Provider,
                    "tenant",
                    "local",
                    "local-runtime",
                    "active",
                    Some(0),
                    json!({
                        "id": "local-runtime",
                        "name": "External provider winner",
                        "provider_type": "openai_compatible",
                        "tenant_id": "local",
                        "is_active": true,
                        "base_url": "http://127.0.0.1:11434/v1",
                        "auth_method": "none",
                        "credential_source": "none",
                        "credential_configured": true,
                        "llm_model": "external-model",
                        "allowed_models": ["external-model"],
                        "secondary_models": [],
                        "health_status": "not_checked",
                        "revision": 0
                    }),
                    Utc::now().timestamp_millis(),
                )
                .expect("inject provider revision conflict");
            self.fail_next_generation_clear
                .store(true, Ordering::SeqCst);
        }
        Ok(())
    }

    fn load(&self, account: &str) -> Result<Option<String>, ProviderCredentialStoreError> {
        Ok(self
            .values
            .lock()
            .expect("conflict credential store")
            .get(account)
            .cloned())
    }

    fn clear(&self, account: &str) -> Result<(), ProviderCredentialStoreError> {
        if account.starts_with("llm-provider-credential.v2.")
            && self
                .fail_next_generation_clear
                .swap(false, Ordering::SeqCst)
        {
            return Err(ProviderCredentialStoreError::Unavailable);
        }
        self.values
            .lock()
            .expect("conflict credential store")
            .remove(account);
        Ok(())
    }
}

#[tokio::test]
async fn credential_cleanup_failure_preserves_conflict_and_other_authoritative_provider() {
    let credential = "provider-conflict-cleanup-session";
    let root = test_root();
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let credential_store = Arc::new(ConflictThenFailClearProviderCredentialStore::new(
        session_store.clone(),
    ));
    let provider_credentials =
        ProviderCredentialBroker::new(credential_store.clone(), session_store.installation_id())
            .expect("conflict credential broker");
    let state = Arc::new(
        LocalRuntimeState::new_with_provider_credentials(
            root,
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
            provider_credentials,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "provider-a",
            "active",
            Some(0),
            json!({
                "id": "provider-a",
                "name": "Provider A",
                "provider_type": "openai",
                "tenant_id": "local",
                "is_active": true,
                "base_url": "https://provider-a.example.test/v1",
                "auth_method": "api_key",
                "credential_source": "application_vault",
                "credential_configured": true,
                "llm_model": "provider-a-model",
                "allowed_models": ["provider-a-model"],
                "secondary_models": [],
                "health_status": "not_checked",
                "revision": 0
            }),
            Utc::now().timestamp_millis(),
        )
        .expect("persist authoritative provider A");
    let provider_a_binding_digest = provider_credential_binding_digest(
        "openai",
        "https://provider-a.example.test/v1",
        "api_key",
    );
    state
        .provider_credentials
        .save(
            "local",
            "provider-a",
            0,
            &provider_a_binding_digest,
            "provider-a-authoritative-secret",
        )
        .expect("stage provider A authoritative credential journal entry");
    credential_store.arm_conflict();

    let response = local_router(Arc::clone(&state))
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            credential,
            json!({
                "provider_type": "openai",
                "base_url": "https://api.example.test/v1",
                "auth_method": "api_key",
                "api_key": "rejected-candidate-secret",
                "llm_model": "candidate-model",
                "is_active": true,
                "expected_revision": 0
            }),
        ))
        .await
        .expect("provider conflict response");

    assert_eq!(response.status(), StatusCode::CONFLICT);
    let error = response_json(response).await;
    assert!(error["detail"]
        .as_str()
        .is_some_and(|detail| detail.contains("revision conflict")));
    assert!(!error.to_string().contains("rejected-candidate-secret"));
    let persisted = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "local-runtime",
        )
        .expect("persisted provider")
        .expect("external provider winner");
    assert_eq!(persisted["revision"], 1);
    assert_eq!(persisted["name"], "External provider winner");
    assert_eq!(
        state
            .provider_credentials
            .load("local", "provider-a", 0, &provider_a_binding_digest)
            .expect("load provider A after provider B cleanup")
            .as_deref(),
        Some("provider-a-authoritative-secret")
    );

    let binding_digest =
        provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
    assert_eq!(
        state
            .provider_credentials
            .load("local", "local-runtime", 1, &binding_digest)
            .expect("load rejected candidate after failed cleanup")
            .as_deref(),
        Some("rejected-candidate-secret")
    );
    state
        .provider_credentials
        .recover_pending([("local", "provider-a", 0, provider_a_binding_digest.as_str())])
        .expect("replay rejected candidate cleanup");
    assert_eq!(
        state
            .provider_credentials
            .load("local", "local-runtime", 1, &binding_digest)
            .expect("load rejected candidate after replay"),
        None
    );
    assert_eq!(
        state
            .provider_credentials
            .load("local", "provider-a", 0, &provider_a_binding_digest)
            .expect("load provider A after cleanup replay")
            .as_deref(),
        Some("provider-a-authoritative-secret")
    );
}

#[tokio::test]
async fn saved_api_key_probe_uses_the_live_runtime_credential_when_vault_read_is_empty() {
    let credential = "write-only-provider-session";
    let root = test_root();
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let provider_credentials = ProviderCredentialBroker::new(
        Arc::new(WriteOnlyProviderCredentialStore),
        session_store.installation_id(),
    )
    .expect("write-only credential broker");
    let state = Arc::new(
        LocalRuntimeState::new_with_provider_credentials(
            root,
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
            provider_credentials,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    let app = local_router(state);

    let created = app
        .clone()
        .oneshot(authenticated_json_request(
            "POST",
            "/api/v1/llm-providers/",
            credential,
            json!({
                "name": "Custom provider",
                "provider_type": "openai_compatible",
                "base_url": "https://127.0.0.1:9/v1",
                "auth_method": "api_key",
                "api_key": "runtime-provider-key",
                "llm_model": "custom-model",
                "allowed_models": ["custom-model"],
                "is_active": true
            }),
        ))
        .await
        .expect("create provider response");
    assert_eq!(created.status(), axum::http::StatusCode::OK);
    let created = response_json(created).await;
    assert_eq!(created["credential_configured"], true);
    let provider_id = created["id"].as_str().expect("provider id");
    let revision = created["revision"].as_u64().expect("provider revision");

    let health = app
        .oneshot(authenticated_json_request(
            "POST",
            &format!("/api/v1/llm-providers/{provider_id}/health-check"),
            credential,
            json!({ "expected_revision": revision }),
        ))
        .await
        .expect("provider health response");
    assert_eq!(health.status(), axum::http::StatusCode::OK);
    let health = response_json(health).await;
    assert_eq!(health["probed"], true);
    assert_ne!(health["status"], "needs_credentials");
    assert_ne!(health["error_code"], "credential_unavailable");
    assert_eq!(health["provider"]["credential_configured"], true);
}

#[tokio::test]
async fn provider_create_idempotency_replays_one_resource_and_rejects_payload_rebinding() {
    let state = test_state("provider-create-idempotency-secret");
    let app = local_router(Arc::clone(&state));
    let request = |name: &str| {
        let mut request = authenticated_json_request(
            "POST",
            "/api/v1/llm-providers/",
            "provider-create-idempotency-secret",
            json!({
                "name": name,
                "provider_type": "openai_compatible",
                "base_url": "http://127.0.0.1:11434/v1",
                "auth_method": "none",
                "llm_model": "idempotent-model",
                "allowed_models": ["idempotent-model"],
                "is_active": true
            }),
        );
        request.headers_mut().insert(
            "idempotency-key",
            HeaderValue::from_static("provider-create-retry-1"),
        );
        request
    };

    let first = app
        .clone()
        .oneshot(request("Idempotent provider"))
        .await
        .expect("first provider create response");
    assert_eq!(first.status(), StatusCode::OK);
    let first = response_json(first).await;
    let replay = app
        .clone()
        .oneshot(request("Idempotent provider"))
        .await
        .expect("replayed provider create response");
    assert_eq!(replay.status(), StatusCode::OK);
    let replay = response_json(replay).await;
    assert_eq!(replay["id"], first["id"]);

    let conflict = app
        .clone()
        .oneshot(request("Rebound provider"))
        .await
        .expect("conflicting provider create response");
    assert_eq!(conflict.status(), StatusCode::CONFLICT);

    let providers = app
        .oneshot(authenticated_json_request(
            "GET",
            "/api/v1/llm-providers/",
            "provider-create-idempotency-secret",
            json!({}),
        ))
        .await
        .expect("provider list response");
    let providers = response_json(providers).await;
    assert_eq!(
        providers
            .as_array()
            .expect("provider list")
            .iter()
            .filter(|provider| provider["name"] == "Idempotent provider")
            .count(),
        1
    );
}

#[tokio::test]
async fn first_created_provider_becomes_runtime_default_without_overriding_later_choice() {
    let state = test_state("provider-auto-select-secret");
    let app = local_router(Arc::clone(&state));
    let create = |name: &str, model: &str| {
        authenticated_json_request(
            "POST",
            "/api/v1/llm-providers/",
            "provider-auto-select-secret",
            json!({
                "name": name,
                "provider_type": "openai_compatible",
                "base_url": "http://127.0.0.1:11434/v1",
                "auth_method": "none",
                "llm_model": model,
                "allowed_models": [model],
                "is_active": true
            }),
        )
    };

    let first = app
        .clone()
        .oneshot(create("First provider", "model-one"))
        .await
        .expect("first create response");
    assert_eq!(first.status(), StatusCode::OK);
    let first = response_json(first).await;
    assert_eq!(
        first["runtime_selected"], json!(true),
        "the first configured provider must become the runtime default"
    );

    let second = app
        .clone()
        .oneshot(create("Second provider", "model-two"))
        .await
        .expect("second create response");
    assert_eq!(second.status(), StatusCode::OK);
    let second = response_json(second).await;
    assert_eq!(
        second["runtime_selected"], json!(false),
        "an existing selection must never be overridden by a later create"
    );

    let runtime = state.provider_runtime.lock().expect("runtime");
    let selections: Vec<_> = runtime.selections.values().collect();
    assert_eq!(selections.len(), 1);
    assert_eq!(selections[0], &first["id"].as_str().expect("first id").to_string());
    drop(runtime);
}

#[tokio::test]
async fn concurrent_provider_updates_keep_the_winning_revision_and_credential_together() {
    let state = test_state("concurrent-provider-session");
    let app = local_router(Arc::clone(&state));
    let request = |model: &str, api_key: &str| {
        authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "concurrent-provider-session",
            json!({
                "provider_type": "openai",
                "base_url": "https://api.example.test/v1",
                "auth_method": "api_key",
                "api_key": api_key,
                "llm_model": model,
                "is_active": true,
                "expected_revision": 0
            }),
        )
    };

    let (first, second) = tokio::join!(
        app.clone()
            .oneshot(request("winner-a-model", "winner-a-secret")),
        app.oneshot(request("winner-b-model", "winner-b-secret")),
    );
    let first = first.expect("first provider response");
    let second = second.expect("second provider response");
    let (winner, conflict) = match (first.status(), second.status()) {
        (StatusCode::OK, StatusCode::CONFLICT) => (first, second),
        (StatusCode::CONFLICT, StatusCode::OK) => (second, first),
        statuses => panic!("expected one winner and one revision conflict, got {statuses:?}"),
    };
    let winner = response_json(winner).await;
    let conflict = response_json(conflict).await;
    assert_eq!(winner["revision"], 1);
    assert!(!winner.to_string().contains("winner-a-secret"));
    assert!(!winner.to_string().contains("winner-b-secret"));
    assert!(!conflict.to_string().contains("winner-a-secret"));
    assert!(!conflict.to_string().contains("winner-b-secret"));

    let expected_credential = match winner["llm_model"].as_str() {
        Some("winner-a-model") => "winner-a-secret",
        Some("winner-b-model") => "winner-b-secret",
        model => panic!("unexpected winning provider model {model:?}"),
    };
    let key = ProviderRuntimeKey {
        tenant_id: "local".to_string(),
        provider_id: "local-runtime".to_string(),
    };
    assert_eq!(
        state
            .provider_runtime
            .lock()
            .expect("provider runtime")
            .credentials
            .get(&key)
            .map(String::as_str),
        Some(expected_credential)
    );
    let binding_digest =
        provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
    assert_eq!(
        state
            .provider_credentials
            .load("local", "local-runtime", 1, &binding_digest)
            .expect("winning provider credential")
            .as_deref(),
        Some(expected_credential)
    );
}

#[tokio::test]
async fn provider_delete_replays_one_tombstone_and_cleans_runtime_selection_and_vault() {
    let state = test_state("provider-delete-session");
    let app = local_router(Arc::clone(&state));
    let updated = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "provider-delete-session",
            json!({
                "provider_type": "openai",
                "base_url": "https://api.example.test/v1",
                "auth_method": "api_key",
                "api_key": "provider-delete-secret",
                "llm_model": "delete-model",
                "is_active": true,
                "expected_revision": 0
            }),
        ))
        .await
        .expect("provider update response");
    assert_eq!(updated.status(), StatusCode::OK);
    let updated = response_json(updated).await;
    assert_eq!(updated["revision"], 1);
    let selected = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime/runtime-selection",
            "provider-delete-session",
            json!({ "expected_revision": 1 }),
        ))
        .await
        .expect("provider selection response");
    assert_eq!(selected.status(), StatusCode::OK);
    let binding_digest =
        provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
    assert_eq!(
        state
            .provider_credentials
            .load("local", "local-runtime", 1, &binding_digest)
            .expect("provider credential before delete")
            .as_deref(),
        Some("provider-delete-secret")
    );

    let delete_request = |expected_revision: u64| {
        authenticated_json_request(
            "DELETE",
            "/api/v1/llm-providers/local-runtime",
            "provider-delete-session",
            json!({
                "expected_revision": expected_revision,
                "idempotency_key": "provider-delete-retry-1"
            }),
        )
    };
    let deleted = app
        .clone()
        .oneshot(delete_request(1))
        .await
        .expect("provider delete response");
    assert_eq!(deleted.status(), StatusCode::OK);
    let deleted = response_json(deleted).await;
    assert_eq!(deleted["deleted"], true);
    assert_eq!(deleted["id"], "local-runtime");
    assert_eq!(deleted["replayed"], false);
    assert!(!deleted.to_string().contains("provider-delete-secret"));

    let replayed = app
        .clone()
        .oneshot(delete_request(1))
        .await
        .expect("provider delete replay response");
    assert_eq!(replayed.status(), StatusCode::OK);
    assert_eq!(response_json(replayed).await["replayed"], true);

    let conflict = app
        .oneshot(delete_request(9))
        .await
        .expect("provider delete idempotency conflict response");
    assert_eq!(conflict.status(), StatusCode::CONFLICT);

    assert!(state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "local-runtime",
        )
        .expect("deleted provider lookup")
        .is_none());
    assert!(state
        .session_store
        .list_selected_llm_providers()
        .expect("selected providers")
        .is_empty());
    assert_eq!(
        state
            .provider_credentials
            .load("local", "local-runtime", 1, &binding_digest)
            .expect("provider credential after delete"),
        None
    );
    let key = ProviderRuntimeKey {
        tenant_id: "local".to_string(),
        provider_id: "local-runtime".to_string(),
    };
    let runtime = state.provider_runtime.lock().expect("provider runtime");
    assert!(!runtime.credentials.contains_key(&key));
    assert!(!runtime.configured_credentials.contains(&key));
    assert!(!runtime.bindings.contains_key(&key));
    assert!(!runtime.probes.contains_key(&key));
    assert!(!runtime.selections.contains_key("local"));
}

#[tokio::test]
async fn provider_delete_preflight_allows_browser_delete_request() {
    let response = local_router(test_state("provider-delete-preflight-secret"))
        .oneshot(
            Request::builder()
                .method("OPTIONS")
                .uri("/api/v1/llm-providers/local-runtime")
                .header("origin", "agistack://app")
                .header("access-control-request-method", "DELETE")
                .header(
                    "access-control-request-headers",
                    "authorization,content-type,idempotency-key,x-agistack-launch",
                )
                .body(Body::empty())
                .expect("provider DELETE preflight request"),
        )
        .await
        .expect("provider DELETE preflight response");

    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("access-control-allow-origin")
            .and_then(|value| value.to_str().ok()),
        Some("agistack://app")
    );
    assert!(response
        .headers()
        .get("access-control-allow-methods")
        .and_then(|value| value.to_str().ok())
        .is_some_and(|methods| methods
            .split(',')
            .any(|method| method.trim() == "DELETE")));
}
