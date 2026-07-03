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

#[tokio::test]
async fn supervisor_tick_handler_retries_worker_stream_orphan_report() {
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
        "last_worker_report_summary": "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-test",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some(
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
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
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id, None);
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        node.metadata_json["worker_report_supervisor_tick_status"],
        "orphan_retry_admitted"
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "blocked");
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some("worker_stream_agent_not_running_stream_idle")
    );
    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-test"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        queued[0].payload_json["retry_origin"],
        "worker_stream_orphan_report"
    );
    assert_eq!(
        queued[0].payload_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
            queued[0].payload_json["worker_stream_orphan_summary"],
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        );
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "worker_stream_orphan_retry_admitted");
    assert_eq!(
        events[0].payload_json["retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(events[0].payload_json["retry_exhausted"], false);
    assert_eq!(events[0].payload_json["retry_count"], 1);
    assert_eq!(
        events[0].payload_json["max_retries"],
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES
    );
}

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
