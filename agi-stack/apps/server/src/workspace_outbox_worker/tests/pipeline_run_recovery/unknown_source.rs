use super::*;

#[tokio::test]
async fn pipeline_run_handler_marks_running_run_without_source_ref_stale() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_pipeline_contract());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-running-unknown",
        "running",
        Some("attempt-test"),
        None,
        json!({"pipeline_last_summary": "still running without source ref"}),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    let new_run_id = node.metadata_json["pipeline_run_id"].as_str().unwrap();
    assert_ne!(new_run_id, "pipeline-run-running-unknown");
    let run = store.pipeline_run("pipeline-run-running-unknown");
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("stale pipeline run source commit unknown superseded by abcdef1234567890")
    );
    assert_eq!(
        run.metadata_json["pipeline_last_summary"],
        "still running without source ref"
    );
    assert_eq!(run.metadata_json["stale_pipeline_run"], true);
    assert!(run.metadata_json["stale_source_commit_ref"].is_null());
    assert_eq!(
        run.metadata_json["superseded_by_source_commit_ref"],
        "abcdef1234567890"
    );
    let new_run = store.pipeline_run(new_run_id);
    assert_eq!(new_run.status, "running");
    assert_eq!(new_run.commit_ref.as_deref(), Some("abcdef1234567890"));
}
