use super::*;

#[tokio::test]
async fn worker_launch_handler_binds_conversation_and_marks_node_running() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task_metadata.insert("preferred_language".to_string(), json!("zh-CN"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut item = worker_launch_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.insert("previous_attempt_id".to_string(), json!("attempt-old"));
        payload.insert(
            "retry_reason".to_string(),
            json!("worker_stream_agent_not_running_stream_idle"),
        );
        payload.insert(
            "retry_origin".to_string(),
            json!("worker_stream_orphan_report"),
        );
        payload.insert(
            "worker_stream_orphan_retry_reason".to_string(),
            json!("worker_stream_agent_not_running_stream_idle"),
        );
        payload.insert(
                "worker_stream_orphan_summary".to_string(),
                json!(
                    "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
                ),
            );
    }

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
    );
    assert_eq!(task.metadata_json["current_attempt_number"], 1);
    assert_eq!(
        task.metadata_json["current_attempt_worker_agent_id"],
        "agent-worker"
    );
    assert_eq!(
        task.metadata_json["worker_runtime_admission"]["status"],
        "admit"
    );
    assert_eq!(
        task.metadata_json["worker_runtime_admission"]["conversation_id"],
        "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
    );
    assert_eq!(
        task.metadata_json["worker_runtime_admission"]["control_plane"],
        "worker_launch"
    );
    assert_eq!(
        task.metadata_json["worker_runtime_admission"]["cooldown_claimed"],
        true
    );
    assert!(task.metadata_json["worker_launch_admitted_at"].is_string());
    assert!(task.metadata_json["worker_launch_bound_at"].is_string());
    assert_eq!(
        task.metadata_json["last_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        task.metadata_json["last_retry_previous_attempt_id"],
        "attempt-old"
    );
    assert_eq!(
        task.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "running");
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("d267a78e-eefc-5d33-bfb3-ac4fa7ece855")
    );
    let conversation = store.conversation("d267a78e-eefc-5d33-bfb3-ac4fa7ece855");
    assert_eq!(conversation.project_id, "project-test");
    assert_eq!(conversation.tenant_id, "tenant-test");
    assert_eq!(conversation.user_id, "actor-test");
    assert_eq!(conversation.title, "Workspace Worker - Build feature");
    assert_eq!(
        conversation.agent_config_json["selected_agent_id"],
        "agent-worker"
    );
    assert_eq!(
        conversation.metadata_json["source"],
        "workspace_worker_launch"
    );
    assert_eq!(
        conversation.metadata_json["conversation_scope"],
        "task:task-test:attempt:attempt-test"
    );
    assert_eq!(conversation.metadata_json["preferred_language"], "zh-CN");
    assert_eq!(
        conversation.metadata_json["last_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        conversation.metadata_json["last_retry_previous_attempt_id"],
        "attempt-old"
    );
    assert_eq!(
        conversation.metadata_json["retry_origin"],
        "worker_stream_orphan_report"
    );
    assert_eq!(
        conversation.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(conversation.participant_agents_json, vec!["agent-worker"]);
    assert_eq!(conversation.focused_agent_id, "agent-worker");
    assert_eq!(
        conversation.linked_workspace_task_id.as_deref(),
        Some("task-test")
    );
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
    assert_eq!(node.metadata_json["launch_state"], "bound");
    assert_eq!(
        node.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
    );
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn worker_launch_handler_defers_when_active_capacity_reached() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    store.set_active_worker_conversations(1);
    let handler = worker_launch_handler(Arc::clone(&store), 1);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(queued[0].status, "pending");
    assert!(queued[0].next_attempt_at.is_some());
    assert_eq!(
        queued[0].metadata_json["source"],
        "workspace_plan.worker_launch.deferred_capacity"
    );
    assert_eq!(
        queued[0].metadata_json["deferred_from_outbox_id"],
        "job-worker-launch"
    );
    assert_eq!(queued[0].metadata_json["active_worker_conversations"], 1);
    assert_eq!(
        queued[0].metadata_json["max_active_worker_conversations"],
        1
    );
    let task = store.task("task-test");
    assert_ne!(task.metadata_json["launch_state"], "runtime_admitted");
}

#[tokio::test]
async fn worker_launch_handler_skips_stale_attempt_without_projection() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-new"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-new".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert!(store.outbox().is_empty());
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert_ne!(task.metadata_json["launch_state"], "runtime_admitted");
    let node = store.node("node-test");
    assert_eq!(node.execution, "dispatched");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-new"));
}
