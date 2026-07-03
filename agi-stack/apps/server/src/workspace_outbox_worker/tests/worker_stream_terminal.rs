use super::*;

#[tokio::test]
async fn worker_stream_terminal_outcome_persists_completed_report_like_python() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    task.status = "in_progress".to_string();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt(
        "attempt-test",
        "running",
        Some("conversation-test"),
    ));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut stream = worker_stream_watchdog::StreamState::default();
    stream.observe_event(&json!({
            "type": "complete",
            "data": {
                "content": "{\"summary\":\"finished from stream\",\"commit_ref\":\"abcdef1234567890\",\"test_commands\":[\"cargo test -p app\"]}"
            }
        }));
    let outcome = stream.terminal_outcome(false);

    let reported = handler
        .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: "workspace-test",
            task_id: "task-test",
            root_goal_task_id: Some("root-task"),
            attempt_id: Some("attempt-test"),
            conversation_id: Some("conversation-test"),
            actor_user_id: "actor-test",
            worker_agent_id: "agent-worker",
            leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            plan_id: Some("plan-test"),
            node_id: Some("node-test"),
            outcome: &outcome,
            now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 0, 0).unwrap(),
        })
        .await
        .unwrap();

    assert!(reported);
    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
    assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
        "finished from stream"
    );
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_ATTEMPT_ID],
        "attempt-test"
    );
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
    assert_eq!(
        task.metadata_json["last_attempt_status"],
        "awaiting_plan_verification"
    );
    assert_eq!(
        task.metadata_json["last_worker_report_artifacts"],
        json!(["commit_ref:abcdef1234567890"])
    );
    assert_eq!(
        task.metadata_json["last_worker_report_verifications"],
        json!(["test_run:cargo test -p app"])
    );
    assert_eq!(
        task.metadata_json["execution_state"]["last_agent_action"],
        "await_plan_verification"
    );
    assert_eq!(
        task.metadata_json["last_worker_report_fingerprint"]
            .as_str()
            .unwrap()
            .len(),
        64
    );
    let attempt = store.attempts().remove(0);
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("finished from stream")
    );
    assert_eq!(
        attempt.candidate_artifacts_json,
        vec!["commit_ref:abcdef1234567890".to_string()]
    );
    assert_eq!(
        attempt.candidate_verifications_json,
        vec!["test_run:cargo test -p app".to_string()]
    );
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("conversation-test")
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.progress_json["note"], "finished from stream");
    assert_eq!(
        node.metadata_json["latest_worker_progress"]["attempt_id"],
        "attempt-test"
    );
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "worker_report_terminal");
    assert_eq!(events[0].payload_json["report_type"], "completed");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
    assert_eq!(outbox[0].metadata_json["source"], "worker_report");
}

#[tokio::test]
async fn worker_stream_terminal_outcome_persists_no_terminal_blocked_report() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut stream = worker_stream_watchdog::StreamState::default();
    stream.mark_stream_ended_without_terminal();
    let outcome = stream.terminal_outcome(false);

    let reported = handler
        .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: "workspace-test",
            task_id: "task-test",
            root_goal_task_id: Some("root-task"),
            attempt_id: Some("attempt-test"),
            conversation_id: Some("conversation-test"),
            actor_user_id: "actor-test",
            worker_agent_id: "agent-worker",
            leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            plan_id: Some("plan-test"),
            node_id: Some("node-test"),
            outcome: &outcome,
            now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 1, 0).unwrap(),
        })
        .await
        .unwrap();

    assert!(reported);
    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
    assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
    assert_eq!(
        task.blocker_reason.as_deref(),
        Some("Worker stream ended without a terminal complete/error event.")
    );
    let attempt = store.attempts().remove(0);
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("Worker stream ended without a terminal complete/error event.")
    );
    assert!(attempt.candidate_verifications_json.is_empty());
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    assert_eq!(
        store.plan_events()[0].payload_json["report_type"],
        "blocked"
    );
}

#[tokio::test]
async fn worker_stream_terminal_outcome_does_not_duplicate_applied_terminal_tool_report() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut stream = worker_stream_watchdog::StreamState::default();
    stream.observe_event(&json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_complete",
            "result": "{\"applied_report\":{\"applied\":true}}"
        }
    }));
    stream.observe_event(&json!({"type": "complete", "data": {"content": "done"}}));
    let outcome = stream.terminal_outcome(true);

    let reported = handler
        .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: "workspace-test",
            task_id: "task-test",
            root_goal_task_id: Some("root-task"),
            attempt_id: Some("attempt-test"),
            conversation_id: None,
            actor_user_id: "actor-test",
            worker_agent_id: "agent-worker",
            leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            plan_id: Some("plan-test"),
            node_id: Some("node-test"),
            outcome: &outcome,
            now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 2, 0).unwrap(),
        })
        .await
        .unwrap();

    assert!(!reported);
    let task = store.task("task-test");
    assert_eq!(
        task.metadata_json["launch_state"],
        "terminal_report_tool_applied"
    );
    assert!(task.metadata_json.get("last_worker_report_type").is_none());
    let attempt = store.attempts().remove(0);
    assert_eq!(attempt.status, "running");
    assert!(attempt.candidate_summary.is_none());
    assert!(store.plan_events().is_empty());
    assert!(store.outbox().is_empty());
}
