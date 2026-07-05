use super::*;

#[tokio::test]
async fn supervisor_tick_handler_blocks_worker_stream_orphan_when_retry_budget_exhausted() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    node.metadata_json = json!({
        "launch_state": "no_terminal_event",
        "last_worker_report_type": "blocked",
        "last_worker_report_summary": "Worker stream stopped without a terminal complete/error event (agent_finished_without_terminal_event).",
        "terminal_attempt_retry_count": DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-test",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some(
        "Worker stream stopped without a terminal complete/error event (agent_finished_without_terminal_event)."
            .to_string(),
    );
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
        Utc.with_ymd_and_hms(2026, 1, 2, 5, 1, 0).unwrap(),
    );

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "blocked");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id, None);
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_reason"],
        "worker_stream_agent_finished_without_terminal_event"
    );
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_count"],
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES + 1
    );
    assert_eq!(
        node.metadata_json["worker_report_supervisor_tick_status"],
        "orphan_retry_exhausted"
    );
    assert_eq!(
        node.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_finished_without_terminal_event"
    );
    assert_eq!(
        node.metadata_json["worker_stream_orphan_retry_exhausted"],
        true
    );
    assert_eq!(
        node.metadata_json["worker_stream_orphan_retry_count"],
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES + 1
    );
    assert_eq!(
        node.metadata_json["worker_stream_orphan_retry_max_retries"],
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "blocked");
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some("worker_stream_agent_finished_without_terminal_event")
    );
    assert!(store.outbox().is_empty());
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "worker_stream_orphan_retry_exhausted");
    assert_eq!(
        events[0].payload_json["retry_reason"],
        "worker_stream_agent_finished_without_terminal_event"
    );
    assert_eq!(events[0].payload_json["retry_exhausted"], true);
    assert_eq!(
        events[0].payload_json["retry_count"],
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES + 1
    );
    assert_eq!(
        events[0].payload_json["max_retries"],
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES
    );
}
