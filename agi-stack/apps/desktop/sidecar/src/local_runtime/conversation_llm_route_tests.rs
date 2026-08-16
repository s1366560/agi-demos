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

async fn spawn_empty_workspace_policy_server() -> (String, tokio::sync::oneshot::Sender<()>) {
    let app = Router::new().route(
        "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/agent-policy",
        get(
            |Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>| async move {
                Json(json!({
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "roles": {},
                    "fallbacks": [],
                }))
            },
        ),
    );
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .await
        .expect("workspace policy listener");
    let address = listener.local_addr().expect("workspace policy address");
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();
    tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                shutdown_rx.await.ok();
            })
            .await
            .ok();
    });
    (format!("http://{address}/"), shutdown_tx)
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
async fn conversation_config_updates_provider_specific_model_routes() {
    let state = test_state("conversation-config-secret");
    let app = local_router(Arc::clone(&state));
    let configured = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "conversation-config-secret",
            json!({
                "provider_type": "openai_compatible",
                "base_url": "http://127.0.0.1:11434/v1",
                "auth_method": "none",
                "llm_model": "default-model",
                "allowed_models": ["default-model", "switched-model"],
                "is_active": true,
                "expected_revision": 0
            }),
        ))
        .await
        .expect("configure provider for switch");
    assert_eq!(configured.status(), StatusCode::OK);

    let created = app
        .clone()
        .oneshot(authenticated_json_request(
            "POST",
            "/api/v1/agent/conversations",
            "conversation-config-secret",
            json!({
                "project_id": "local-project",
                "title": "Switch model session"
            }),
        ))
        .await
        .expect("create switchable conversation");
    assert_eq!(created.status(), StatusCode::OK);
    let conversation_id = response_json(created).await["id"]
        .as_str()
        .expect("conversation id")
        .to_string();

    let updated = app
        .oneshot(authenticated_json_request(
            "PATCH",
            &format!(
                "/api/v1/agent/conversations/{conversation_id}/config?project_id=local-project"
            ),
            "conversation-config-secret",
            json!({
                "llm_model_override": "switched-model",
                "llm_route_override": {
                    "provider_id": "local-runtime",
                    "model_id": "switched-model"
                }
            }),
        ))
        .await
        .expect("update conversation model config");
    assert_eq!(updated.status(), StatusCode::OK);
    let updated = response_json(updated).await;
    assert_eq!(
        updated["agent_config"]["llm_model_override"],
        "switched-model"
    );
    assert_eq!(
        state
            .session_store
            .conversation_llm_route(&conversation_id)
            .expect("switched conversation route"),
        Some(LlmRouteTarget {
            provider_id: "local-runtime".to_string(),
            model_id: "switched-model".to_string(),
        })
    );
}

#[tokio::test]
async fn workspace_bound_agent_engine_uses_persisted_conversation_route_over_empty_policy() {
    let state = test_state("workspace-conversation-route-secret");
    state
        .mock_llm_enabled
        .store(0, std::sync::atomic::Ordering::Release);
    let app = local_router(Arc::clone(&state));
    let (provider_base_url, requests, provider_shutdown) = spawn_provider_chat_server().await;
    let configured = app
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "workspace-conversation-route-secret",
            json!({
                "provider_type": "openai_compatible",
                "base_url": provider_base_url,
                "auth_method": "none",
                "llm_model": "default-model",
                "allowed_models": ["default-model", "workspace-model"],
                "is_active": true,
                "expected_revision": 0
            }),
        ))
        .await
        .expect("configure workspace conversation provider");
    assert_eq!(configured.status(), StatusCode::OK);

    let conversation = LocalConversation {
        id: format!("workspace-routed-{}", Uuid::new_v4()),
        project_id: "local-project".to_string(),
        tenant_id: "local".to_string(),
        title: "Workspace-routed session".to_string(),
        workspace_id: Some("local-workspace".to_string()),
        capability_mode: ConversationCapabilityMode::Work,
        current_mode: ConversationRunMode::Plan,
        created_at: now_iso(),
        updated_at: now_iso(),
    };
    state
        .session_store
        .insert_conversation(&conversation)
        .expect("insert workspace conversation");
    let route = LlmRouteTarget {
        provider_id: "local-runtime".to_string(),
        model_id: "workspace-model".to_string(),
    };
    state
        .session_store
        .update_conversation_llm_route(&conversation.id, Some(&route), &now_iso())
        .expect("persist workspace conversation route");

    let (workspace_base_url, workspace_shutdown) = spawn_empty_workspace_policy_server().await;
    workspace_core_bridge::install_authority(
        &state,
        workspace_base_url,
        "workspace-policy-service-token".to_string(),
        "workspace-agent-registry-token".to_string(),
        "workspace-provider-webhook-token".to_string(),
        "workspace-provider-event-token".to_string(),
    )
    .expect("install workspace policy authority");

    let engine = state
        .agent_engine_for_role(&conversation, None, None)
        .await
        .expect("build workspace-bound agent engine");
    let result = engine
        .run(
            &format!("checkpoint-{}", conversation.id),
            "route this workspace request",
            Some("local-project"),
        )
        .await
        .expect("run workspace-bound routed agent");
    assert_eq!(result.status, SessionStatus::Finished);
    assert_eq!(result.answer.as_deref(), Some("routed answer"));

    let captured = requests.lock().await;
    assert_eq!(captured.len(), 1);
    assert_eq!(captured[0]["model"], "workspace-model");
    drop(captured);
    provider_shutdown.send(()).ok();
    workspace_shutdown.send(()).ok();
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
