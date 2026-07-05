use super::*;

#[tokio::test]
async fn worker_launch_stream_poll_persists_orphan_stop_when_running_marker_is_missing() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
    task_metadata.insert("worker_stream_message_id".to_string(), json!("msg-1"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    store.insert_attempt(task_session_attempt(
        "attempt-test",
        "running",
        Some(conversation_id),
    ));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "2-0",
        json!({
            "type": "text_delta",
            "event_time_us": 0,
            "data": {"text": "already seen"}
        }),
    );
    stream_events.push(
        conversation_id,
        "3-0",
        json!({
            "type": "text_delta",
            "event_time_us": 0,
            "data": {"text": "last visible output"}
        }),
    );
    let handler = worker_launch_handler_with_state_and_event_stream(
        Arc::clone(&store),
        runtime_state,
        stream_events,
        4,
    );
    let mut item = worker_launch_item();
    let payload = item.payload_json.as_object_mut().unwrap();
    payload.insert("worker_stream_poll".to_string(), json!(true));
    payload.insert("stream_after_id".to_string(), json!("2-0"));

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "terminal"
    );
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
    assert_eq!(
        task.metadata_json["worker_stream_terminal_outcome"],
        "no_terminal_event"
    );
    assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
    assert!(task
        .blocker_reason
        .as_deref()
        .unwrap()
        .contains("agent_not_running_stream_idle"));
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert!(attempt
        .candidate_summary
        .as_deref()
        .unwrap()
        .contains("agent_not_running_stream_idle"));
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.metadata_json["launch_state"], "no_terminal_event");
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "worker_report_terminal");
    assert_eq!(events[0].payload_json["report_type"], "blocked");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
}

#[tokio::test]
async fn worker_launch_stream_poll_persists_finished_marker_stop_without_new_entries() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
    task_metadata.insert("worker_stream_message_id".to_string(), json!("msg-1"));
    task_metadata.insert(
        "worker_stream_last_event_type".to_string(),
        json!("text_delta"),
    );
    task_metadata.insert("worker_stream_last_event_time_us".to_string(), json!(0));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    store.insert_attempt(task_session_attempt(
        "attempt-test",
        "running",
        Some(conversation_id),
    ));
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_finished(conversation_id);
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    let handler = worker_launch_handler_with_state_and_event_stream(
        Arc::clone(&store),
        runtime_state,
        stream_events,
        4,
    );
    let mut item = worker_launch_item();
    let payload = item.payload_json.as_object_mut().unwrap();
    payload.insert("worker_stream_poll".to_string(), json!(true));
    payload.insert("stream_after_id".to_string(), json!("2-0"));

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "terminal"
    );
    assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
    assert!(task.metadata_json[LAST_WORKER_REPORT_SUMMARY]
        .as_str()
        .unwrap()
        .contains("agent_finished_without_terminal_event"));
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(attempt.conversation_id.as_deref(), Some(conversation_id));
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].payload_json["report_type"], "blocked");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
}
