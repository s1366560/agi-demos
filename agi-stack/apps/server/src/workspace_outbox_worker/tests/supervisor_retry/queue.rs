use super::*;

#[tokio::test]
async fn supervisor_tick_handler_queues_attempt_retry_for_retry_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.current_attempt_id = Some("attempt-stale".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    store.insert_node(node);
    let handler = supervisor_tick_handler(Arc::clone(&store));

    let outcome = handler.handle(supervisor_tick_retry_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].plan_id.as_deref(), Some("plan-test"));
    assert_eq!(queued[0].payload_json["workspace_id"], "workspace-test");
    assert_eq!(queued[0].payload_json["task_id"], "task-test");
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(queued[0].payload_json["worker_agent_id"], "agent-worker");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-stale"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "stale_plan_node_no_terminal_worker_report"
    );
    assert_eq!(
        queued[0].payload_json["extra_instructions"],
        "recover stale node"
    );
    assert_eq!(
        queued[0].metadata_json["source"],
        "workspace_plan.supervisor_tick.retry_admission"
    );
    let node = store.node("node-test");
    assert_eq!(
        node.metadata_json["supervisor_tick_status"],
        "retry_admitted"
    );
    assert_eq!(
        node.metadata_json["supervisor_tick_retry_attempt_id"],
        "attempt-stale"
    );
    assert!(node.metadata_json["supervisor_tick_admitted_at"].is_string());
}
