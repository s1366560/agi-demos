use super::*;

#[tokio::test]
async fn routing_policy_persists_published_role_targets_and_builds_ordered_workload_plans() {
    let credential = "routing-role-secret";
    let state = test_state(credential);
    seed_active_provider(
        &state,
        "local",
        "primary-provider",
        "default-model",
        &["default-model", "coding-model"],
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
            "/api/v1/llm-providers/routing-policy",
            credential,
            json!({
                "expected_revision": 0,
                "roles": {
                    "default": {
                        "provider_id": "primary-provider",
                        "model_id": "default-model"
                    },
                    "fast": null,
                    "coding": {
                        "provider_id": "primary-provider",
                        "model_id": "coding-model"
                    },
                    "vision": null
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
        (LlmWorkloadRole::Fast, "default-model"),
        (LlmWorkloadRole::Coding, "coding-model"),
        (LlmWorkloadRole::Vision, "default-model"),
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
