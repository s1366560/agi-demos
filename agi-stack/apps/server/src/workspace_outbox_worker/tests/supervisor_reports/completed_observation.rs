use super::*;

#[tokio::test]
async fn supervisor_tick_handler_observes_worker_report_without_retrying_completed_candidate() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    node.metadata_json = json!({
        "launch_state": "completed_via_stream",
        "last_worker_report_type": "completed",
        "last_worker_report_summary": "finished from stream"
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-test",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("finished from stream".to_string());
    attempt.candidate_verifications_json = vec!["worker_report:completed".to_string()];
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let item = worker_report_supervisor_tick(
        "workspace-test",
        "plan-test",
        "node-test",
        "attempt-test",
        "root-task",
        "actor-test",
        Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
        Utc.with_ymd_and_hms(2026, 1, 2, 5, 0, 0).unwrap(),
    );

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
    assert_eq!(
        node.metadata_json["worker_report_supervisor_tick_status"],
        "reported_candidate_observed"
    );
    assert_eq!(
        node.metadata_json["reported_attempt_status"],
        AWAITING_LEADER_ADJUDICATION_STATUS
    );
    assert!(store.outbox().is_empty());
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "auto_reported_attempt_reconciled");
    assert_eq!(
        events[0].payload_json["reason"],
        "worker_report_supervisor_tick"
    );
}
