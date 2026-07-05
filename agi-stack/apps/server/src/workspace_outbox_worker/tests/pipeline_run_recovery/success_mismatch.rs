use super::*;

#[tokio::test]
async fn pipeline_run_handler_keeps_requested_on_success_commit_mismatch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_pipeline_contract());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-stale",
        "success",
        Some("attempt-test"),
        Some("bbbbbb1234567890"),
        json!({
            "source_publish_source_commit_ref": "bbbbbb1234567890",
            "pipeline_last_summary": "stale run passed"
        }),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
    let new_run_id = node.metadata_json["pipeline_run_id"].as_str().unwrap();
    assert_ne!(new_run_id, "pipeline-run-stale");
    let new_run = store.pipeline_run(new_run_id);
    assert_eq!(new_run.status, "running");
    assert_eq!(new_run.commit_ref.as_deref(), Some("abcdef1234567890"));
    assert!(node.metadata_json.get("last_verification_passed").is_none());
    assert!(node.metadata_json.get("pipeline_evidence_refs").is_none());
}
