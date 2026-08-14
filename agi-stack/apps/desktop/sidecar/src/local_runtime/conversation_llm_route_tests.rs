async fn spawn_provider_chat_server() -> (
    String,
    Arc<tokio::sync::Mutex<Vec<Value>>>,
    tokio::sync::oneshot::Sender<()>,
) {
    let requests = Arc::new(tokio::sync::Mutex::new(Vec::new()));
    let app = Router::new().route(
        "/v1/chat/completions",
        post({
            let requests = Arc::clone(&requests);
            move |Json(body): Json<Value>| {
                let requests = Arc::clone(&requests);
                async move {
                    requests.lock().await.push(body);
                    Json(json!({
                        "choices": [{
                            "message": {
                                "content": r#"{"kind":"finish","answer":"routed answer"}"#
                            }
                        }]
                    }))
                }
            }
        }),
    );
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .await
        .expect("provider chat listener");
    let address = listener.local_addr().expect("provider chat address");
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();
    tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                shutdown_rx.await.ok();
            })
            .await
            .ok();
    });
    (format!("http://{address}/v1"), requests, shutdown_tx)
}

#[tokio::test]
async fn unbound_conversation_creation_persists_and_projects_provider_specific_model_route() {
    let state = test_state("conversation-route-secret");
    let app = local_router(Arc::clone(&state));
    let configured = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "conversation-route-secret",
            json!({
                "provider_type": "openai_compatible",
                "base_url": "http://127.0.0.1:11434/v1",
                "auth_method": "none",
                "llm_model": "default-model",
                "allowed_models": ["default-model", "routed-model"],
                "is_active": true,
                "expected_revision": 0
            }),
        ))
        .await
        .expect("configure provider response");
    assert_eq!(configured.status(), StatusCode::OK);

    let created = app
        .oneshot(authenticated_json_request(
            "POST",
            "/api/v1/agent/conversations",
            "conversation-route-secret",
            json!({
                "project_id": "local-project",
                "title": "Provider-routed session",
                "agent_config": {
                    "selected_agent_id": "builtin:all-access",
                    "capability_mode": "code",
                    "llm_model_override": "routed-model",
                    "llm_route_override": {
                        "provider_id": "local-runtime",
                        "model_id": "routed-model"
                    }
                }
            }),
        ))
        .await
        .expect("create routed conversation response");

    assert_eq!(created.status(), StatusCode::OK);
    let created = response_json(created).await;
    assert_eq!(
        created["agent_config"]["llm_model_override"],
        "routed-model"
    );
    assert_eq!(
        created["agent_config"]["llm_route_override"],
        json!({ "provider_id": "local-runtime", "model_id": "routed-model" })
    );
    let conversation_id = created["id"].as_str().expect("conversation id");
    assert_eq!(
        state
            .session_store
            .conversation_llm_route(conversation_id)
            .expect("stored conversation route"),
        Some(LlmRouteTarget {
            provider_id: "local-runtime".to_string(),
            model_id: "routed-model".to_string(),
        })
    );
}

#[tokio::test]
async fn unbound_conversation_creation_rejects_ambiguous_or_unavailable_model_routes() {
    let state = test_state("conversation-route-rejection-secret");
    let app = local_router(Arc::clone(&state));
    let configured = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "conversation-route-rejection-secret",
            json!({
                "provider_type": "openai_compatible",
                "base_url": "http://127.0.0.1:11434/v1",
                "auth_method": "none",
                "llm_model": "available-model",
                "allowed_models": ["available-model"],
                "is_active": true,
                "expected_revision": 0
            }),
        ))
        .await
        .expect("configure provider response");
    assert_eq!(configured.status(), StatusCode::OK);
    let count_before = state
        .session_store
        .list_conversations("local-project", None)
        .expect("conversations before invalid requests")
        .len();

    for agent_config in [
        json!({ "llm_model_override": "available-model" }),
        json!({
            "llm_model_override": "different-model",
            "llm_route_override": {
                "provider_id": "local-runtime",
                "model_id": "available-model"
            }
        }),
        json!({
            "llm_model_override": "unavailable-model",
            "llm_route_override": {
                "provider_id": "local-runtime",
                "model_id": "unavailable-model"
            }
        }),
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/agent/conversations",
                "conversation-route-rejection-secret",
                json!({
                    "project_id": "local-project",
                    "title": "Rejected routed session",
                    "agent_config": agent_config,
                }),
            ))
            .await
            .expect("invalid routed conversation response");
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    assert_eq!(
        state
            .session_store
            .list_conversations("local-project", None)
            .expect("conversations after invalid requests")
            .len(),
        count_before
    );
}

#[tokio::test]
async fn persisted_unbound_conversation_route_survives_restart_and_drives_the_llm_model() {
    let root = test_root();
    std::fs::create_dir_all(&root).expect("create conversation route restart root");
    let store_path = root.join("sessions.db");
    let workspace_root = root.join("workspace");
    std::fs::create_dir_all(&workspace_root).expect("create conversation route workspace");
    let credential = "conversation-route-restart-secret";
    let (base_url, requests, shutdown) = spawn_provider_chat_server().await;
    let conversation_id = {
        let store = DesktopSessionStore::open(&store_path).expect("open session store");
        let provider_credentials = ProviderCredentialBroker::in_memory(store.installation_id())
            .expect("provider credential broker");
        let state = Arc::new(
            LocalRuntimeState::new_with_provider_credentials(
                workspace_root.clone(),
                LocalToolHost::new(&workspace_root).expect("tool host"),
                Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints")),
                credential.to_string(),
                store,
                provider_credentials,
            )
            .expect("runtime state"),
        );
        state
            .session_store
            .seed_test_session(credential)
            .expect("test session");
        let app = local_router(state);
        let configured = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                credential,
                json!({
                    "provider_type": "openai_compatible",
                    "base_url": base_url,
                    "auth_method": "none",
                    "llm_model": "default-model",
                    "allowed_models": ["default-model", "restart-model"],
                    "is_active": true,
                    "expected_revision": 0
                }),
            ))
            .await
            .expect("configure restart provider");
        assert_eq!(configured.status(), StatusCode::OK);
        let created = app
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/agent/conversations",
                credential,
                json!({
                    "project_id": "local-project",
                    "title": "Restart routed session",
                    "agent_config": {
                        "llm_model_override": "restart-model",
                        "llm_route_override": {
                            "provider_id": "local-runtime",
                            "model_id": "restart-model"
                        }
                    }
                }),
            ))
            .await
            .expect("create restart routed conversation");
        assert_eq!(created.status(), StatusCode::OK);
        response_json(created).await["id"]
            .as_str()
            .expect("conversation id")
            .to_string()
    };

    let store = DesktopSessionStore::open(&store_path).expect("reopen session store");
    let provider_credentials = ProviderCredentialBroker::in_memory(store.installation_id())
        .expect("restored provider credential broker");
    let state = Arc::new(
        LocalRuntimeState::new_with_provider_credentials(
            workspace_root.clone(),
            LocalToolHost::new(&workspace_root).expect("restored tool host"),
            Arc::new(SqliteCheckpointStore::in_memory().expect("restored checkpoints")),
            credential.to_string(),
            store,
            provider_credentials,
        )
        .expect("restored runtime state"),
    );
    let conversation = state
        .session_store
        .conversation(&conversation_id)
        .expect("load restored conversation")
        .expect("restored conversation");
    let projected = state.conversation_value(&conversation);
    assert_eq!(
        projected["agent_config"]["llm_model_override"],
        "restart-model"
    );
    assert_eq!(
        projected["agent_config"]["llm_route_override"],
        json!({ "provider_id": "local-runtime", "model_id": "restart-model" })
    );

    let action = state
        .llm_for_role(&conversation, LlmWorkloadRole::Default)
        .await
        .expect("resolve restored conversation LLM")
        .decide("route this request", 0, &[], &[])
        .await
        .expect("routed LLM decision");
    assert_eq!(
        action,
        AgentAction::Finish {
            answer: "routed answer".to_string()
        }
    );
    let captured = requests.lock().await;
    assert_eq!(captured.len(), 1);
    assert_eq!(captured[0]["model"], "restart-model");
    drop(captured);
    shutdown.send(()).ok();
    drop(state);
    std::fs::remove_dir_all(root).expect("remove conversation route restart root");
}
