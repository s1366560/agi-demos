use super::*;

#[tokio::test]
async fn supervisor_tick_handler_reconciles_reported_attempt_node_and_writes_event() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-test",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("worker produced a candidate".to_string());
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
    assert_eq!(
        node.metadata_json["reported_attempt_status"],
        AWAITING_LEADER_ADJUDICATION_STATUS
    );
    assert!(node.metadata_json["reported_attempt_reconciled_at"].is_string());
    assert!(store.outbox().is_empty());

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "auto_reported_attempt_reconciled");
    assert_eq!(events[0].source, "workspace_plan_supervisor_tick");
    assert_eq!(events[0].node_id.as_deref(), Some("node-test"));
    assert_eq!(events[0].attempt_id.as_deref(), Some("attempt-test"));
    assert_eq!(
        events[0].payload_json["reason"],
        "active_plan_node_points_to_reported_attempt"
    );
    assert_eq!(events[0].payload_json["node_ids"], json!(["node-test"]));
}
