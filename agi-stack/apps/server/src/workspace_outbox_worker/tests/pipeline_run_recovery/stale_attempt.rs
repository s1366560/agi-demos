use super::*;

#[tokio::test]
async fn pipeline_run_handler_skips_stale_attempt_without_projection() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-new".to_string());
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    assert_ne!(node.metadata_json["pipeline_status"], "requested");
}
