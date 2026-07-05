use super::*;

#[tokio::test]
async fn supervisor_tick_handler_skips_terminal_attempt_with_pipeline_result_pending() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-rejected".to_string());
    node.metadata_json = json!({
        "pipeline_status": "success",
        "pipeline_run_id": "pipeline-run-test"
    });
    store.insert_node(node);
    store.insert_attempt(task_session_attempt(
        "attempt-rejected",
        "rejected",
        Some("conversation-test"),
    ));
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Release {
            reason: Some("supervisor_tick_requires_full_runtime".to_string())
        }
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-rejected"));
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_releases_generic_tick_until_full_runtime() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "controller_reason": "delivery_contract_regeneration_requested"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Release {
            reason: Some("supervisor_tick_requires_full_runtime".to_string())
        }
    );
    assert!(store.outbox().is_empty());
}
