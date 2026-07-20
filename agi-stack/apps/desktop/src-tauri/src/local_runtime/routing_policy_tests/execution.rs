use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

async fn spawn_openai_decision_server() -> (String, Arc<tokio::sync::Mutex<Vec<String>>>) {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .await
        .expect("OpenAI-compatible test listener");
    let address = listener.local_addr().expect("test listener address");
    let captured = Arc::new(tokio::sync::Mutex::new(Vec::new()));
    let requests = Arc::clone(&captured);
    tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.expect("test provider request");
        let mut buffer = vec![0; 16 * 1024];
        let read = socket
            .read(&mut buffer)
            .await
            .expect("read provider request");
        requests
            .lock()
            .await
            .push(String::from_utf8_lossy(&buffer[..read]).to_string());
        let body = json!({
            "choices": [{
                "message": {
                    "content": r#"{"kind":"finish","answer":"glm-ready"}"#
                }
            }]
        })
        .to_string();
        let response = format!(
            "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            body.len()
        );
        socket
            .write_all(response.as_bytes())
            .await
            .expect("write provider response");
    });
    (format!("http://{address}/v1"), captured)
}

#[tokio::test]
async fn configured_api_key_provider_executes_the_selected_coding_model() {
    let credential = "coding-provider-routing-secret";
    let provider_api_key = "test-glm-provider-key";
    let (base_url, captured) = spawn_openai_decision_server().await;
    let state = test_state(credential);
    let app = local_router(Arc::clone(&state));

    let created = app
        .clone()
        .oneshot(authenticated_json_request(
            "POST",
            "/api/v1/llm-providers/",
            credential,
            json!({
                "name": "OpenAI-compatible",
                "provider_type": "openai_compatible",
                "base_url": base_url,
                "auth_method": "api_key",
                "api_key": provider_api_key,
                "llm_model": "glm-5.2",
                "allowed_models": ["glm-5.2"],
                "is_active": true
            }),
        ))
        .await
        .expect("create configured provider");
    assert_eq!(created.status(), StatusCode::OK);
    let created = response_json(created).await;
    let provider_id = created["id"].as_str().expect("created provider id");
    assert_eq!(created["credential_configured"], true);
    assert_eq!(created["health_status"], "configuration_valid");

    let saved = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            LOCAL_ROUTING_POLICY_URI,
            credential,
            json!({
                "project_id": "local-project",
                "workspace_id": "local-workspace",
                "expected_revision": 0,
                "roles": {
                    "default": {"provider_id": provider_id, "model_id": "glm-5.2"},
                    "fast": null,
                    "coding": {"provider_id": provider_id, "model_id": "glm-5.2"},
                    "vision": null
                },
                "fallbacks": []
            }),
        ))
        .await
        .expect("save coding route");
    assert_eq!(saved.status(), StatusCode::OK);

    let action = state
        .llm_for_scope(
            "local",
            "local-project",
            "local-workspace",
            LlmWorkloadRole::Coding,
        )
        .decide("verify selected model", 0, &[], &[])
        .await
        .expect("configured coding model response");
    assert_eq!(
        action,
        AgentAction::Finish {
            answer: "glm-ready".to_string()
        }
    );

    let requests = captured.lock().await;
    assert_eq!(requests.len(), 1);
    assert!(requests[0].contains("POST /v1/chat/completions"));
    assert!(requests[0].contains("authorization: Bearer test-glm-provider-key"));
    assert!(requests[0].contains(r#""model":"glm-5.2""#));
    drop(requests);

    let usage = app
        .oneshot(authenticated_json_request(
            "GET",
            &format!("/api/v1/llm-providers/{provider_id}/usage"),
            credential,
            json!({}),
        ))
        .await
        .expect("provider usage response");
    assert_eq!(usage.status(), StatusCode::OK);
    let usage = response_json(usage).await;
    assert_eq!(usage["provider_id"], provider_id);
    assert_eq!(usage["tenant_id"], "local");
    assert_eq!(usage["availability"], "available");
    assert_eq!(usage["statistics"].as_array().map(Vec::len), Some(1));
    let statistic = &usage["statistics"][0];
    assert_eq!(statistic["operation_type"], "llm");
    assert_eq!(statistic["total_requests"], 1);
    assert_eq!(statistic["total_prompt_tokens"], 0);
    assert_eq!(statistic["total_completion_tokens"], 0);
    assert_eq!(statistic["total_tokens"], 0);
    assert_eq!(statistic["total_cost_usd"], Value::Null);
    assert!(statistic["avg_response_time_ms"].is_number());
    assert!(statistic["first_request_at"].is_string());
    assert!(statistic["last_request_at"].is_string());
}

#[tokio::test]
async fn routing_policy_persists_published_role_targets_and_builds_ordered_workload_plans() {
    let credential = "routing-role-secret";
    let state = test_state(credential);
    seed_active_provider(
        &state,
        "local",
        "primary-provider",
        "default-model",
        &[
            "default-model",
            "fast-model",
            "coding-model",
            "vision-model",
        ],
    );
    seed_active_provider(
        &state,
        "local",
        "fallback-provider",
        "fallback-a",
        &["fallback-a", "fallback-b"],
    );
    let app = local_router(state);
    assert_eq!(
        workload_role_for_capability(ConversationCapabilityMode::Work),
        LlmWorkloadRole::Default
    );
    assert_eq!(
        workload_role_for_capability(ConversationCapabilityMode::Code),
        LlmWorkloadRole::Coding
    );
    let saved = app
        .oneshot(authenticated_json_request(
            "PUT",
            LOCAL_ROUTING_POLICY_URI,
            credential,
            json!({
                "project_id": "local-project",
                "workspace_id": "local-workspace",
                "expected_revision": 0,
                "roles": {
                    "default": {
                        "provider_id": "primary-provider",
                        "model_id": "default-model"
                    },
                    "fast": {
                        "provider_id": "primary-provider",
                        "model_id": "fast-model"
                    },
                    "coding": {
                        "provider_id": "primary-provider",
                        "model_id": "coding-model"
                    },
                    "vision": {
                        "provider_id": "primary-provider",
                        "model_id": "vision-model"
                    }
                },
                "fallbacks": [
                    {"provider_id": "fallback-provider", "model_id": "fallback-a"},
                    {"provider_id": "fallback-provider", "model_id": "fallback-b"}
                ]
            }),
        ))
        .await
        .expect("role routing policy save");
    assert_eq!(saved.status(), StatusCode::OK);
    let saved = response_json(saved).await;

    for (role, expected_primary) in [
        (LlmWorkloadRole::Default, "default-model"),
        (LlmWorkloadRole::Fast, "fast-model"),
        (LlmWorkloadRole::Coding, "coding-model"),
        (LlmWorkloadRole::Vision, "vision-model"),
    ] {
        let targets = routing_targets_for_role(&saved, role).expect("valid workload route plan");
        assert_eq!(targets.len(), 3);
        assert_eq!(targets[0].model_id, expected_primary);
        assert_eq!(targets[1].model_id, "fallback-a");
        assert_eq!(targets[2].model_id, "fallback-b");
    }

    let mut without_fast = saved;
    without_fast["roles"]["fast"] = Value::Null;
    assert_eq!(
        routing_targets_for_role(&without_fast, LlmWorkloadRole::Fast)
            .expect("default route fallback")[0]
            .model_id,
        "default-model"
    );
    without_fast["roles"]
        .as_object_mut()
        .expect("routing roles")
        .remove("vision");
    assert!(routing_targets_for_role(&without_fast, LlmWorkloadRole::Default).is_err());
}

#[tokio::test]
async fn failover_llm_attempts_candidates_in_order_and_stops_after_success() {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let llm = FailoverLlm::from_candidates(vec![
        Arc::new(RecordingLlm {
            label: "primary",
            succeeds: false,
            calls: Arc::clone(&calls),
        }),
        Arc::new(RecordingLlm {
            label: "fallback-a",
            succeeds: true,
            calls: Arc::clone(&calls),
        }),
        Arc::new(RecordingLlm {
            label: "fallback-b",
            succeeds: true,
            calls: Arc::clone(&calls),
        }),
    ]);

    let action = llm
        .decide("route the workload", 0, &[], &[])
        .await
        .expect("fallback succeeds");
    assert!(matches!(
        action,
        AgentAction::Finish { answer } if answer == "fallback-a"
    ));
    assert_eq!(
        *calls.lock().expect("recorded failover calls"),
        vec!["primary:decide", "fallback-a:decide"]
    );
}

#[tokio::test]
async fn failover_llm_times_out_pending_primary_then_uses_fallback() {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let llm = FailoverLlm::from_candidates_with_timeout(
        vec![
            Arc::new(PendingLlm {
                label: "primary",
                calls: Arc::clone(&calls),
            }),
            Arc::new(RecordingLlm {
                label: "fallback",
                succeeds: true,
                calls: Arc::clone(&calls),
            }),
        ],
        std::time::Duration::from_millis(10),
    );

    let action = tokio::time::timeout(
        std::time::Duration::from_secs(1),
        llm.decide("route the workload", 0, &[], &[]),
    )
    .await
    .expect("failover remains bounded")
    .expect("fallback succeeds after primary timeout");
    assert!(matches!(
        action,
        AgentAction::Finish { answer } if answer == "fallback"
    ));
    assert_eq!(
        *calls.lock().expect("recorded failover calls"),
        vec!["primary:decide", "fallback:decide"]
    );
}

#[tokio::test]
async fn failover_llm_times_out_single_pending_candidate_with_llm_error() {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let llm = FailoverLlm::from_candidates_with_timeout(
        vec![Arc::new(PendingLlm {
            label: "only",
            calls: Arc::clone(&calls),
        })],
        std::time::Duration::from_millis(10),
    );

    let result = tokio::time::timeout(
        std::time::Duration::from_secs(1),
        llm.decide("route the workload", 0, &[], &[]),
    )
    .await
    .expect("single candidate remains bounded");
    assert!(matches!(
        result,
        Err(CoreError::Llm(detail))
            if detail.contains("model_timeout") && detail.contains("10 ms")
    ));
    assert_eq!(
        *calls.lock().expect("recorded single candidate calls"),
        vec!["only:decide"]
    );
}
