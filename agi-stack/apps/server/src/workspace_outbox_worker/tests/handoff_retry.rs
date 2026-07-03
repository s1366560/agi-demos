use super::*;

#[tokio::test]
async fn handoff_retry_handler_projects_attempt_and_queues_worker_launch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler =
        DurableHandoffResumeHandler::new(Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>);
    let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "task_id": "task-test",
        "node_id": "node-test",
        "worker_agent_id": "agent-worker",
        "actor_user_id": "actor-test",
        "previous_attempt_id": "attempt-old",
        "extra_instructions": "retry with context"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let attempts = store.attempts();
    assert_eq!(attempts.len(), 1);
    let attempt = &attempts[0];
    assert_eq!(attempt.workspace_task_id, "task-test");
    assert_eq!(attempt.root_goal_task_id, "root-task");
    assert_eq!(attempt.status, "running");
    assert_eq!(attempt.attempt_number, 1);
    assert_eq!(attempt.worker_agent_id.as_deref(), Some("agent-worker"));
    assert_eq!(attempt.leader_agent_id, None);

    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_ID].as_str(),
        Some(attempt.id.as_str())
    );
    assert_eq!(task.metadata_json["launch_state"], "scheduled");
    assert_eq!(task.metadata_json["last_attempt_status"], "running");

    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "dispatched");
    assert_eq!(
        node.current_attempt_id.as_deref(),
        Some(attempt.id.as_str())
    );
    assert_eq!(
        node.handoff_package_json
            .as_ref()
            .and_then(|value| value["previous_attempt_id"].as_str()),
        Some("attempt-old")
    );

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(
        queued[0].payload_json["attempt_id"].as_str(),
        Some(attempt.id.as_str())
    );
    assert_eq!(
        queued[0].payload_json["extra_instructions"].as_str(),
        Some("retry with context")
    );
    assert_eq!(
        queued[0].metadata_json["source"].as_str(),
        Some("workspace_plan.attempt_retry")
    );
}

#[tokio::test]
async fn handoff_retry_handler_preserves_worker_stream_orphan_retry_context() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut task = task_with_plan_metadata();
    task.blocker_reason =
        Some("Worker stream stopped without a terminal complete/error event".to_string());
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("42-0"));
    task_metadata.insert(
        "worker_stream_replay_attempt_id".to_string(),
        json!("attempt-old"),
    );
    task_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
    task_metadata.insert(
        "worker_stream_terminal_outcome".to_string(),
        json!("no_terminal_event"),
    );
    task_metadata.insert("last_worker_report_type".to_string(), json!("blocked"));
    task_metadata.insert(
        LAST_WORKER_REPORT_SUMMARY.to_string(),
        json!("old orphan report"),
    );
    task_metadata.insert(
        LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
        json!("attempt-old"),
    );
    task_metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(true));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    let mut node_metadata = object_or_empty(node.metadata_json.clone());
    node_metadata.insert("worker_stream_last_entry_id".to_string(), json!("42-0"));
    node_metadata.insert(
        "worker_stream_replay_attempt_id".to_string(),
        json!("attempt-old"),
    );
    node_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
    node_metadata.insert("last_worker_report_type".to_string(), json!("blocked"));
    node_metadata.insert(
        LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
        json!("attempt-old"),
    );
    node.metadata_json = Value::Object(node_metadata);
    store.insert_node(node);
    let handler =
        DurableHandoffResumeHandler::new(Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>);
    let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "task_id": "task-test",
        "node_id": "node-test",
        "worker_agent_id": "agent-worker",
        "actor_user_id": "actor-test",
        "previous_attempt_id": "attempt-old",
        "retry_reason": "worker_stream_agent_not_running_stream_idle",
        "retry_origin": "worker_stream_orphan_report",
        "worker_stream_orphan_retry_reason": "worker_stream_agent_not_running_stream_idle",
        "worker_stream_orphan_summary": "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert!(task.blocker_reason.is_none());
    assert_eq!(
        task.metadata_json["last_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
        task.metadata_json["last_retry_previous_attempt_id"],
        "attempt-old"
    );
    assert_eq!(
        task.metadata_json["retry_origin"],
        "worker_stream_orphan_report"
    );
    assert_eq!(
        task.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert!(task
        .metadata_json
        .get("last_retry_context_at")
        .and_then(Value::as_str)
        .is_some());
    for key in [
        "worker_stream_last_entry_id",
        "worker_stream_replay_attempt_id",
        "worker_stream_message_id",
        "worker_stream_terminal_outcome",
        "last_worker_report_type",
        LAST_WORKER_REPORT_SUMMARY,
        LAST_WORKER_REPORT_ATTEMPT_ID,
        PENDING_LEADER_ADJUDICATION,
    ] {
        assert!(
            task.metadata_json.get(key).is_none(),
            "task metadata key {key} should be cleared for retry"
        );
    }

    let node = store.node("node-test");
    let handoff = node.handoff_package_json.as_ref().unwrap();
    assert_eq!(
        handoff["retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    assert_eq!(
            handoff["worker_stream_orphan_summary"],
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        );
    assert_eq!(
        node.metadata_json["worker_stream_orphan_retry_reason"],
        "worker_stream_agent_not_running_stream_idle"
    );
    for key in [
        "worker_stream_last_entry_id",
        "worker_stream_replay_attempt_id",
        "worker_stream_message_id",
        "last_worker_report_type",
        LAST_WORKER_REPORT_ATTEMPT_ID,
    ] {
        assert!(
            node.metadata_json.get(key).is_none(),
            "node metadata key {key} should be cleared for retry"
        );
    }

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
    assert_eq!(queued[0].payload_json["previous_attempt_id"], "attempt-old");
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
}

#[tokio::test]
async fn handoff_retry_handler_applies_attempt_worktree_checkpoint_to_feature_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.feature_checkpoint_json = Some(json!({
        "commit_ref": "abcdef1234567890",
        "base_ref": "main",
        "expected_artifacts": ["src/lib.rs"]
    }));
    store.insert_node(node);
    let handler =
        DurableHandoffResumeHandler::new(Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>);
    let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "task_id": "task-test",
        "node_id": "node-test",
        "worker_agent_id": "agent-worker",
        "actor_user_id": "actor-test",
        "previous_attempt_id": "attempt-old",
        "extra_instructions": "retry with context"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    let attempt_id = node.current_attempt_id.as_deref().unwrap();
    let checkpoint = node.feature_checkpoint_json.as_ref().unwrap();
    assert_eq!(
        checkpoint["worktree_path"],
        format!("${{sandbox_code_root}}/../.memstack/worktrees/{attempt_id}")
    );
    assert_eq!(
        checkpoint["branch_name"],
        worktree_branch_name("node-test", attempt_id)
    );
    assert_eq!(checkpoint["base_ref"], "abcdef1234567890");
}
