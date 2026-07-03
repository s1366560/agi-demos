use super::*;

#[tokio::test]
async fn worker_launch_handler_refreshes_runtime_markers_after_binding() {
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
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
    runtime_state.insert_running(conversation_id);
    let handler =
        worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert_eq!(runtime_state.claims(), vec![conversation_id]);
    assert_eq!(runtime_state.refresh_cooldowns(), vec![conversation_id]);
    assert_eq!(runtime_state.refresh_running(), vec![conversation_id]);
    let task = store.task("task-test");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        conversation_id
    );
}

#[tokio::test]
async fn worker_launch_handler_reuses_repair_conversation_id_when_present() {
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
    let handler = worker_launch_handler(Arc::clone(&store), 4);
    let mut item = worker_launch_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.insert(
            "reuse_conversation_id".to_string(),
            json!("conv-existing-repair"),
        );
    }

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        "conv-existing-repair"
    );
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("conv-existing-repair")
    );
    let conversation = store.conversation("conv-existing-repair");
    assert_eq!(conversation.metadata_json["attempt_id"], "attempt-test");
    assert_eq!(
        conversation.metadata_json["conversation_scope"],
        "task:task-test:attempt:attempt-test"
    );
}

#[tokio::test]
async fn worker_launch_handler_skips_duplicate_launch_when_cooldown_exists() {
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
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_cooldown("d267a78e-eefc-5d33-bfb3-ac4fa7ece855");
    let handler =
        worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert_eq!(
        runtime_state.claims(),
        vec!["d267a78e-eefc-5d33-bfb3-ac4fa7ece855"]
    );
    assert!(runtime_state.has_cooldown("d267a78e-eefc-5d33-bfb3-ac4fa7ece855"));
    assert_eq!(store.conversation_count(), 0);
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert!(attempt.conversation_id.is_none());
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert!(task.metadata_json.get("launch_state").is_none());
    let node = store.node("node-test");
    assert_eq!(node.execution, "dispatched");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
}

#[tokio::test]
async fn worker_launch_handler_clears_reused_markers_before_repair_reuse() {
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
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_cooldown("conv-existing-repair");
    runtime_state.insert_finished("conv-existing-repair");
    let handler =
        worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);
    let mut item = worker_launch_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.insert(
            "reuse_conversation_id".to_string(),
            json!("conv-existing-repair"),
        );
    }

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert_eq!(runtime_state.clears(), vec!["conv-existing-repair"]);
    assert_eq!(runtime_state.claims(), vec!["conv-existing-repair"]);
    assert!(runtime_state.has_cooldown("conv-existing-repair"));
    assert!(!runtime_state.has_finished("conv-existing-repair"));
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(
        attempt.conversation_id.as_deref(),
        Some("conv-existing-repair")
    );
    assert_eq!(store.conversation_count(), 1);
    let task = store.task("task-test");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
        "conv-existing-repair"
    );
}

#[tokio::test]
async fn worker_launch_handler_skips_reuse_when_agent_running_marker_exists() {
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
    let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
    runtime_state.insert_running("conv-existing-repair");
    let handler =
        worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);
    let mut item = worker_launch_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.insert(
            "reuse_conversation_id".to_string(),
            json!("conv-existing-repair"),
        );
    }

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert!(runtime_state.clears().is_empty());
    assert!(runtime_state.claims().is_empty());
    assert_eq!(store.conversation_count(), 0);
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert!(attempt.conversation_id.is_none());
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert!(task.metadata_json.get("launch_state").is_none());
}
