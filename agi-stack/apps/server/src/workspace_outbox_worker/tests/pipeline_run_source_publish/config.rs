use super::*;

#[tokio::test]
async fn pipeline_run_handler_fails_drone_source_publish_without_host_code_root() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_pipeline_contract_missing_host_root());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let runs = store.pipeline_runs();
    assert_eq!(runs.len(), 1);
    let run = &runs[0];
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("host_code_root is not available for Drone source publish")
    );
    assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(run.metadata_json["pipeline_failed_stage"], "source_publish");
    assert_eq!(run.metadata_json["source_publish_status"], "failed");
    assert_eq!(run.metadata_json["source_publish_provider"], "git");
    assert_eq!(
        run.metadata_json["source_publish_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(
        run.metadata_json["source_publish_source_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(
        run.metadata_json["source_publish_reason"],
        "host_code_root is not available for Drone source publish"
    );

    let stages = store.pipeline_stage_runs();
    assert_eq!(stages.len(), 1);
    let stage = &stages[0];
    assert_eq!(stage.run_id, run.id);
    assert_eq!(stage.stage, "source_publish");
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.command.as_deref(), Some("git:publish"));
    assert_eq!(stage.exit_code, Some(1));
    assert_eq!(
        stage.stderr_preview.as_deref(),
        Some("host_code_root is not available for Drone source publish")
    );
    assert_eq!(stage.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(stage.metadata_json["source_publish_status"], "failed");

    let contract = store.pipeline_contract("workspace-test", "plan-test");
    assert_eq!(contract.provider, DRONE_PROVIDER);
    assert_eq!(contract.metadata_json["source_publish_status"], "failed");
    assert_eq!(
        contract.metadata_json["provider_config"],
        json!({"branch": "main", "repo": "owner/repo"})
    );

    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "failed");
    assert_eq!(
        node.metadata_json["pipeline_failed_stage"],
        "source_publish"
    );
    assert_eq!(node.metadata_json["source_publish_status"], "failed");
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "source_publish:failed".to_string(),
            format!("pipeline_run:failed:{}", run.id)
        ]
    );

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, SUPERVISOR_TICK_EVENT);
    assert_eq!(
        queued[0].metadata_json["source"],
        "workspace_plan.drone_pipeline_run_completed"
    );
    assert_eq!(queued[0].payload_json["pipeline_status"], "failed");
}

#[tokio::test]
async fn pipeline_run_handler_fails_drone_source_publish_without_branch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_pipeline_contract_missing_branch());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("source_control.default_branch or delivery_cicd.drone.branch is required")
    );
    assert_eq!(run.metadata_json["pipeline_failed_stage"], "source_publish");
    assert_eq!(run.metadata_json["source_publish_status"], "failed");
    assert!(run.metadata_json.get("source_publish_branch").is_none());

    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(stage.stage, "source_publish");
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.exit_code, Some(1));
    assert_eq!(
        stage.stderr_preview.as_deref(),
        Some("source_control.default_branch or delivery_cicd.drone.branch is required")
    );

    let contract = store.pipeline_contract("workspace-test", "plan-test");
    assert_eq!(contract.provider, DRONE_PROVIDER);
    assert_eq!(
        contract.metadata_json["provider_config"],
        json!({"repo": "owner/repo"})
    );
    assert_eq!(contract.metadata_json["source_publish_status"], "failed");

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["source_publish_provider"], "git");
    assert_eq!(
        node.metadata_json["pipeline_failure_summary"],
        "source_control.default_branch or delivery_cicd.drone.branch is required"
    );
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "source_publish:failed".to_string(),
            format!("pipeline_run:failed:{}", run.id)
        ]
    );
    assert_eq!(
        store.outbox()[0].metadata_json["source"],
        "workspace_plan.drone_pipeline_run_completed"
    );
}
