use super::*;

#[tokio::test]
async fn supervisor_tick_handler_releases_missing_attempt_node_and_queues_retry() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("missing-attempt".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    node.metadata_json = json!({"retry_not_before": "2026-01-02T03:04:05Z"});
    store.insert_node(node);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id, None);
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_reason"],
        "missing_attempt"
    );
    assert_eq!(node.metadata_json["terminal_attempt_retry_count"], 1);
    assert!(node.metadata_json["terminal_attempt_reconciled_at"].is_string());
    assert!(node.metadata_json.get("retry_not_before").is_none());

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(queued[0].payload_json["task_id"], "task-test");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "missing-attempt"
    );
    assert_eq!(queued[0].payload_json["retry_reason"], "missing_attempt");
    assert_eq!(queued[0].metadata_json["retry_node_id"], "node-test");
    assert_eq!(
        queued[0].metadata_json["retry_attempt_id"],
        "missing-attempt"
    );
}

#[tokio::test]
async fn supervisor_tick_handler_releases_terminal_rejected_attempt_and_queues_retry() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-rejected".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
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
        "plan_id": "plan-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id, None);
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_reason"],
        "terminal_attempt_rejected"
    );
    assert_eq!(node.metadata_json["terminal_attempt_retry_count"], 1);
    assert!(node.metadata_json["terminal_attempt_reconciled_at"].is_string());

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-rejected"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "terminal_attempt_rejected"
    );
}
