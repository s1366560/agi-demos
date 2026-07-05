use super::*;

#[tokio::test]
async fn supervisor_tick_handler_reconciles_retry_same_node_supervisor_decision() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-retry".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    node.metadata_json = json!({
        "last_supervisor_decision_action": "retry_same_node",
        "last_supervisor_decision_rationale": "retry after tightening the implementation",
        "last_supervisor_decision_confidence": 0.72,
        "last_supervisor_decision_feedback_items": [{
            "target_layer": "implementation",
            "recommended_action": "fix_regression",
            "summary": "missing regression coverage"
        }],
        "retry_not_before": "2999-01-02T03:04:05Z"
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-retry",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("worker produced a candidate with a gap".to_string());
    store.insert_attempt(attempt);
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
    let attempt = store.attempt("attempt-retry");
    assert_eq!(attempt.status, REJECTED_ATTEMPT_STATUS);
    assert_eq!(
        attempt.leader_feedback.as_deref(),
        Some("retry after tightening the implementation")
    );
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some(SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON)
    );
    assert!(attempt.completed_at.is_some());

    let node = store.node("node-test");
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id, None);
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_reason"],
        SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
    );
    assert_eq!(
        node.metadata_json["supervisor_decision_retry_attempt_id"],
        "attempt-retry"
    );
    assert_eq!(
        node.metadata_json["supervisor_decision_retry_attempt_status"],
        REJECTED_ATTEMPT_STATUS
    );
    assert!(node
        .metadata_json
        .get("reported_attempt_reconciled_at")
        .is_none());
    assert!(node.metadata_json.get("retry_not_before").is_none());

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].event_type,
        "supervisor_decision_retry_same_node_reconciled"
    );
    assert_eq!(
        events[0].payload_json["reason"],
        SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
    );
    assert_eq!(events[0].payload_json["action"], "retry_same_node");
    assert_eq!(
        events[0].payload_json["rationale"],
        "retry after tightening the implementation"
    );
    assert_eq!(events[0].payload_json["retry_exhausted"], false);

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(queued[0].payload_json["task_id"], "task-test");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-retry"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
    );
    assert_eq!(
        queued[0].payload_json["retry_not_before"],
        "2999-01-02T03:04:05+00:00"
    );
    assert_eq!(
        queued[0].next_attempt_at,
        Some(
            DateTime::parse_from_rfc3339("2999-01-02T03:04:05Z")
                .unwrap()
                .with_timezone(&Utc)
        )
    );
}
