use super::*;

#[tokio::test]
async fn pipeline_run_handler_marks_node_requested_without_running_provider() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.metadata_json["pipeline_status"], "requested");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "requested");
    assert_eq!(
        node.metadata_json["pipeline_request_outbox_id"],
        "job-pipeline-run"
    );
    assert_eq!(
        node.metadata_json["pipeline_request_reason"],
        "operator requested harness-native pipeline"
    );
    assert_eq!(
        node.metadata_json["pipeline_runtime_state"],
        "runtime_admitted"
    );
    assert_eq!(
        node.metadata_json["pipeline_requested_attempt_id"],
        "attempt-test"
    );
    assert!(node.metadata_json["pipeline_requested_at"].is_string());
}

#[tokio::test]
async fn pipeline_run_handler_creates_durable_running_run_for_planning_contract() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_pipeline_contract());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
    assert!(node.metadata_json["pipeline_run_id"].is_string());
    assert!(node.metadata_json["pipeline_started_at"].is_string());
    assert!(node.metadata_json.get("pipeline_requested_at").is_none());

    let runs = store.pipeline_runs();
    assert_eq!(runs.len(), 1);
    let run = &runs[0];
    assert_eq!(run.workspace_id, "workspace-test");
    assert_eq!(run.plan_id.as_deref(), Some("plan-test"));
    assert_eq!(run.node_id.as_deref(), Some("node-test"));
    assert_eq!(run.attempt_id.as_deref(), Some("attempt-test"));
    assert_eq!(run.commit_ref.as_deref(), Some("abcdef1234567890"));
    assert_eq!(run.provider, SANDBOX_NATIVE_PROVIDER);
    assert_eq!(run.status, "running");
    assert_eq!(
        run.metadata_json["reason"],
        "operator requested harness-native pipeline"
    );
    assert_eq!(
        node.metadata_json["pipeline_run_id"].as_str(),
        Some(run.id.as_str())
    );

    let contract = store.pipeline_contract("workspace-test", "plan-test");
    assert_eq!(contract.id, run.contract_id);
    assert_eq!(contract.provider, SANDBOX_NATIVE_PROVIDER);
    assert_eq!(contract.code_root.as_deref(), Some("/workspace/project"));
    assert_eq!(contract.timeout_seconds, 120);
    assert!(!contract.auto_deploy);
    assert_eq!(contract.env_json["CI"], "true");
    assert_eq!(
        contract.trigger_policy_json,
        json!({
            "trigger": "verification_gate",
            "node_id": "node-test",
            "attempt_id": "attempt-test"
        })
    );
    assert_eq!(contract.commands_json[0]["stage"], "test");
    assert_eq!(
        contract.commands_json[0]["command"],
        "cargo test --workspace"
    );
    assert_eq!(
        contract.metadata_json["source"],
        "workspace_plan.pipeline_run_requested"
    );
    assert_eq!(
        contract.metadata_json["contract_source"],
        PLANNING_CONTRACT_SOURCE
    );
}

#[tokio::test]
async fn pipeline_run_handler_executes_no_service_stage_and_finishes_success() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_pipeline_contract());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    let runner = Arc::new(StaticPipelineStageRunner::default());
    let stage_runner: Arc<dyn WorkspacePipelineStageRunner> = runner.clone();
    let handler = pipeline_run_handler_with_stage_runner(Arc::clone(&store), stage_runner);

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert_eq!(
        runner.seen(),
        vec![(
            "project-test".to_string(),
            "test".to_string(),
            "cargo test --workspace".to_string()
        )]
    );
    let runs = store.pipeline_runs();
    assert_eq!(runs.len(), 1);
    let run = &runs[0];
    assert_eq!(run.status, "success");
    assert_eq!(run.reason, None);
    assert!(run.completed_at.is_some());
    assert_eq!(run.metadata_json["stage_count"], 1);
    assert_eq!(run.metadata_json["service_count"], 0);

    let stages = store.pipeline_stage_runs();
    assert_eq!(stages.len(), 1);
    let stage = &stages[0];
    assert_eq!(stage.run_id, run.id);
    assert_eq!(stage.stage, "test");
    assert_eq!(stage.status, "success");
    assert_eq!(stage.exit_code, Some(0));
    assert_eq!(stage.stdout_preview.as_deref(), Some("ok"));
    assert_eq!(stage.metadata_json["required"], true);
    assert_eq!(stage.metadata_json["duration_ms_observed"], 25);

    let node = store.node("node-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.metadata_json["pipeline_status"], "success");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "success");
    assert_eq!(node.metadata_json["last_verification_passed"], true);
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:passed".to_string(),
            "pipeline_stage:test:passed".to_string(),
            format!("pipeline_run:success:{}", run.id)
        ]
    );
    assert_eq!(
        metadata_string_values(node.metadata_json.get("execution_verifications")),
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs"))
    );

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, SUPERVISOR_TICK_EVENT);
    assert_eq!(queued[0].payload_json["pipeline_run_id"], run.id);
    assert_eq!(queued[0].payload_json["pipeline_status"], "success");
    assert_eq!(
        queued[0].metadata_json["source"],
        "workspace_plan.pipeline_run_completed"
    );
}

#[tokio::test]
async fn pipeline_run_handler_executes_no_service_stage_and_finishes_failure() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_pipeline_contract());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    let runner = Arc::new(
        StaticPipelineStageRunner::default().with_result(PipelineStageResult {
            stage: "test".to_string(),
            status: "failed".to_string(),
            command: "cargo test --workspace".to_string(),
            exit_code: Some(2),
            stdout_preview: "tests failed".to_string(),
            stderr_preview: "failure details".to_string(),
            duration_ms: 31,
            log_ref: Some("sandbox://pipeline/test/test.log".to_string()),
            artifact_refs: vec!["pipeline_log:test:sandbox://pipeline/test/test.log".to_string()],
            service_id: None,
            required: true,
        }),
    );
    let stage_runner: Arc<dyn WorkspacePipelineStageRunner> = runner;
    let handler = pipeline_run_handler_with_stage_runner(Arc::clone(&store), stage_runner);

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.status, "failed");
    assert_eq!(run.reason.as_deref(), Some("stage test failed with exit 2"));
    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.exit_code, Some(2));
    assert_eq!(stage.stderr_preview.as_deref(), Some("failure details"));

    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "failed");
    assert!(node.metadata_json.get("last_verification_passed").is_none());
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "pipeline_stage:test:failed".to_string(),
            format!("pipeline_run:failed:{}", run.id)
        ]
    );
    assert_eq!(store.outbox().len(), 1);
}
