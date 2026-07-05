use super::*;

#[tokio::test]
async fn worker_launch_handler_replays_bound_stream_complete_to_terminal_report() {
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
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "1-0",
        json!({"type": "message", "data": {"id": "msg-1"}}),
    );
    stream_events.push(
        conversation_id,
        "2-0",
        json!({"type": "text_delta", "data": {"text": "finished "}}),
    );
    stream_events.push(
        conversation_id,
        "3-0",
        json!({
            "type": "complete",
            "data": {
                "content": "{\"summary\":\"done via event stream\",\"test_commands\":[\"cargo test -p app\"]}"
            }
        }),
    );
    let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        conversation_id
    );
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "terminal"
    );
    assert_eq!(
        task.metadata_json["worker_stream_last_event_type"],
        "complete"
    );
    assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-1");
    assert_eq!(
        task.metadata_json["worker_stream_terminal_outcome"],
        "completed"
    );
    assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
        "done via event stream"
    );
    assert_eq!(
        task.metadata_json["last_worker_report_verifications"],
        json!(["test_run:cargo test -p app"])
    );

    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("done via event stream")
    );
    assert_eq!(attempt.conversation_id.as_deref(), Some(conversation_id));
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.progress_json["note"], "done via event stream");
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "worker_report_terminal");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
}

#[tokio::test]
async fn worker_launch_handler_ignores_previous_attempt_stream_cursor() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("99-0"));
    task_metadata.insert(
        "worker_stream_replay_attempt_id".to_string(),
        json!("attempt-old"),
    );
    task_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
    task_metadata.insert(
        "worker_stream_last_event_type".to_string(),
        json!("text_delta"),
    );
    task_metadata.insert(
        LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
        json!("attempt-old"),
    );
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "1-0",
        json!({"type": "message", "data": {"id": "msg-new"}}),
    );
    stream_events.push(
        conversation_id,
        "2-0",
        json!({
            "type": "complete",
            "data": {
                "content": "{\"summary\":\"done after retry\",\"test_commands\":[\"cargo test -p retry\"]}"
            }
        }),
    );
    let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
    assert_eq!(
        task.metadata_json["worker_stream_replay_attempt_id"],
        "attempt-test"
    );
    assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-new");
    assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
        "done after retry"
    );
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_ATTEMPT_ID],
        "attempt-test"
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("done after retry")
    );
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
}

#[tokio::test]
async fn worker_launch_handler_replays_nonterminal_stream_without_reporting() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "1-0",
        json!({"type": "message", "data": {"id": "msg-1"}}),
    );
    stream_events.push(
        conversation_id,
        "2-0",
        json!({"type": "text_delta", "data": {"text": "still running"}}),
    );
    let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "observed"
    );
    assert_eq!(
        task.metadata_json["worker_stream_last_event_type"],
        "text_delta"
    );
    assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-1");
    assert!(task.metadata_json.get("last_worker_report_type").is_none());
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "running");
    assert!(attempt.candidate_summary.is_none());
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert!(store.plan_events().is_empty());
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
    assert_eq!(outbox[0].payload_json["stream_after_id"], "2-0");
    assert!(outbox[0]
        .payload_json
        .get("reuse_conversation_id")
        .is_none());
    assert!(outbox[0].next_attempt_at.is_some());
    assert_eq!(
        outbox[0].metadata_json["source"],
        "workspace_plan.worker_launch.stream_poll"
    );
    assert_eq!(outbox[0].metadata_json["stream_poll_after_id"], "2-0");
}
