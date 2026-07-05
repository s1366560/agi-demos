use super::*;

#[tokio::test]
async fn worker_launch_handler_publishes_idle_progress_for_stale_nonterminal_stream() {
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
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_running(conversation_id);
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "1-0",
        json!({
            "type": "message",
            "event_time_us": 0,
            "data": {"id": "msg-1"}
        }),
    );
    stream_events.push(
        conversation_id,
        "2-0",
        json!({
            "type": "text_delta",
            "event_time_us": 0,
            "data": {"text": "still running"}
        }),
    );
    let handler = worker_launch_handler_with_state_and_event_stream(
        Arc::clone(&store),
        runtime_state,
        stream_events,
        4,
    );

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "stream_idle"
    );
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
    assert_eq!(task.metadata_json["worker_stream_last_event_time_us"], 0);
    assert_eq!(
        task.metadata_json["worker_stream_idle_running_exists"],
        true
    );
    assert!(
        task.metadata_json["worker_stream_idle_seconds"]
            .as_i64()
            .unwrap()
            > DEFAULT_WORKER_STREAM_IDLE_PROGRESS_INTERVAL_SECONDS
    );
    let summary = task.metadata_json["worker_stream_idle_progress_summary"]
        .as_str()
        .unwrap();
    assert!(summary.contains("Worker stream still active"));
    assert!(summary.contains("agent:running present"));
    assert!(summary.contains("last_event=text_delta"));
    assert_eq!(
        task.metadata_json["execution_state"]["last_agent_action"],
        "observe_stream_idle"
    );
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
    assert_eq!(node.metadata_json["launch_state"], "stream_idle");
    assert_eq!(
        node.metadata_json["latest_worker_progress"]["event_type"],
        "worker_stream_idle"
    );
    assert_eq!(
        node.metadata_json["latest_worker_progress"]["attempt_id"],
        "attempt-test"
    );
    assert!(node.progress_json["note"]
        .as_str()
        .unwrap()
        .contains("Worker stream still active"));
    assert!(store.plan_events().is_empty());
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
    assert_eq!(outbox[0].payload_json["stream_after_id"], "2-0");
    assert_eq!(
        outbox[0].metadata_json["source"],
        "workspace_plan.worker_launch.stream_poll"
    );
}

#[tokio::test]
async fn worker_launch_stream_poll_bypasses_launch_gates_and_continues_from_cursor() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.set_active_worker_conversations(99);
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
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
    runtime_state.insert_cooldown(conversation_id);
    runtime_state.insert_running(conversation_id);
    let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
    stream_events.push(
        conversation_id,
        "2-0",
        json!({"type": "text_delta", "data": {"text": "already seen"}}),
    );
    stream_events.push(
        conversation_id,
        "3-0",
        json!({"type": "text_delta", "data": {"text": "next chunk"}}),
    );
    let handler = worker_launch_handler_with_state_and_event_stream(
        Arc::clone(&store),
        Arc::clone(&runtime_state),
        stream_events,
        1,
    );
    let mut item = worker_launch_item();
    let payload = item.payload_json.as_object_mut().unwrap();
    payload.insert("worker_stream_poll".to_string(), json!(true));
    payload.insert("stream_after_id".to_string(), json!("2-0"));

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert!(runtime_state.claims().is_empty());
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "stream_polling");
    assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
    assert_eq!(
        task.metadata_json["worker_stream_replay_status"],
        "observed"
    );
    assert_eq!(
        task.metadata_json["worker_stream_last_event_type"],
        "text_delta"
    );
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert_eq!(node.metadata_json["launch_state"], "stream_polling");
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
    assert_eq!(outbox[0].payload_json["stream_after_id"], "3-0");
    assert_eq!(
        outbox[0].metadata_json["source"],
        "workspace_plan.worker_launch.stream_poll"
    );
    assert_eq!(outbox[0].metadata_json["stream_poll_entries_read"], 1);
    assert!(outbox[0].next_attempt_at.is_some());
}
