use super::*;

#[tokio::test]
async fn pipeline_run_handler_marks_existing_running_run_on_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-running",
        "running",
        Some("attempt-test"),
        Some("abcdef1234567890"),
        json!({"source_publish_source_commit_ref": "abcdef1234567890"}),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "idle");
    assert_eq!(
        node.metadata_json["pipeline_run_id"],
        "pipeline-run-running"
    );
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
    assert!(node.metadata_json["pipeline_started_at"].is_string());
    assert!(node.metadata_json.get("pipeline_requested_at").is_none());
    assert!(node.metadata_json.get("last_verification_passed").is_none());
}
