use super::*;

#[tokio::test]
async fn pipeline_run_handler_reflects_existing_success_run_to_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.metadata_json = json!({
        "iteration_phase": "test",
        "pipeline_evidence_refs": ["existing:evidence"]
    });
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-success",
        "success",
        Some("attempt-test"),
        Some("abcdef1234567890"),
        json!({
            "source_publish_source_commit_ref": "abcdef1234567890",
            "source_publish_status": "published",
            "external_url": "https://ci.example/runs/pipeline-run-success",
            "external_provider": "sandbox_native",
            "pipeline_last_summary": "existing run already passed"
        }),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(
        node.metadata_json["pipeline_run_id"],
        "pipeline-run-success"
    );
    assert_eq!(node.metadata_json["pipeline_status"], "success");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "success");
    assert_eq!(
        node.metadata_json["source_publish_source_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(node.metadata_json["source_publish_status"], "published");
    assert_eq!(
        node.metadata_json["external_url"],
        "https://ci.example/runs/pipeline-run-success"
    );
    assert_eq!(
        node.metadata_json["pipeline_last_summary"],
        "existing run already passed"
    );
    assert_eq!(
        node.metadata_json["last_verification_summary"],
        "harness-native CI/CD pipeline passed"
    );
    assert_eq!(node.metadata_json["last_verification_passed"], true);
    assert_eq!(node.metadata_json["last_verification_hard_fail"], false);
    assert!(node.metadata_json["last_verification_ran_at"].is_string());
    assert_eq!(
        node.metadata_json["pipeline_evidence_refs"],
        json!([
            "existing:evidence",
            "ci_pipeline:passed",
            "pipeline_run:success:pipeline-run-success"
        ])
    );
    assert!(node.metadata_json.get("pipeline_requested_at").is_none());
}
