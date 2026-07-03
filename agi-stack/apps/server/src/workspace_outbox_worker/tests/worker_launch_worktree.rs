use super::*;

#[tokio::test]
async fn worker_launch_handler_records_skipped_worktree_context_without_sandbox_root() {
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

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(task.metadata_json["worktree_setup"]["status"], "skipped");
    assert_eq!(
        task.metadata_json["worktree_setup"]["reason"],
        "sandbox_code_root is not available for this workspace"
    );
    assert_eq!(
        task.metadata_json["attempt_worktree"]["attempt_id"],
        "attempt-test"
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
}

#[tokio::test]
async fn worker_launch_handler_blocks_attempt_for_rejected_worktree_path() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_code_root("/workspace/project"));
    let mut task = task_with_plan_metadata();
    let mut task_metadata = object_or_empty(task.metadata_json.clone());
    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
    task.metadata_json = Value::Object(task_metadata);
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "dispatched".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": "${sandbox_code_root}/src",
        "branch_name": "workspace/node-test-attempt",
        "base_ref": "HEAD"
    }));
    store.insert_node(node);
    store.insert_attempt(task_session_attempt("attempt-test", "running", None));
    let handler = worker_launch_handler(Arc::clone(&store), 4);

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.status, "blocked");
    assert_eq!(task.metadata_json["launch_state"], "worktree_setup_failed");
    assert_eq!(task.metadata_json["worktree_setup"]["status"], "failed");
    assert!(task
        .blocker_reason
        .as_deref()
        .unwrap()
        .contains("worktree_path must not be inside sandbox_code_root"));
    let attempt = store
        .attempts()
        .into_iter()
        .find(|attempt| attempt.id == "attempt-test")
        .unwrap();
    assert_eq!(attempt.status, "blocked");
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some("worktree_setup_failed")
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "blocked");
    assert_eq!(node.execution, "idle");
    assert!(node.current_attempt_id.is_none());
    assert_eq!(node.metadata_json["terminal_attempt_status"], "blocked");
    assert_eq!(node.metadata_json["worktree_setup"]["status"], "failed");
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn worker_launch_handler_prepares_local_git_attempt_worktree_when_available() {
    let Some(fixture) = git_publish_fixture() else {
        return;
    };
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_code_root(&fixture.repo.to_string_lossy()));
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

    let outcome = handler.handle(worker_launch_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json["launch_state"], "bound");
    assert_eq!(task.metadata_json["worktree_setup"]["status"], "prepared");
    let worktree_path = task.metadata_json["worktree_setup"]["worktree_path"]
        .as_str()
        .unwrap();
    assert!(Path::new(worktree_path).exists());
    assert_eq!(task.metadata_json["active_execution_root"], worktree_path);
    let inside = run_git_ok(
        Path::new(worktree_path),
        &["rev-parse", "--is-inside-work-tree"],
    );
    assert_eq!(inside.trim(), "true");
    let node = store.node("node-test");
    assert_eq!(node.execution, "running");
    assert_eq!(node.metadata_json["launch_state"], "bound");
}
