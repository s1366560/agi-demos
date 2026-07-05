use super::*;

#[tokio::test]
async fn supervisor_tick_handler_preserves_failed_worktree_when_commit_ref_was_missing() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "done".to_string();
    node.execution = "idle".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
        "branch_name": "workspace/node-attempt-accepted",
        "base_ref": "main",
        "commit_ref": "abcdef1"
    }));
    node.metadata_json = json!({
        "terminal_attempt_status": "accepted",
        "last_verification_passed": true,
        "last_verification_attempt_id": "attempt-accepted",
        "verified_commit_ref": "abcdef1234567890",
        "worktree_integration_attempt_id": "attempt-accepted",
        "worktree_integration_status": "failed",
        "worktree_integration_commit_ref": "abcdef1234567890",
        "worktree_integration_worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
        "worktree_integration_dirty_signature": Value::Null,
        "worktree_integration_summary": "status=failed\ncommit_ref not found in attempt worktree"
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Release {
            reason: Some("supervisor_tick_requires_full_runtime".to_string())
        }
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.metadata_json["worktree_integration_status"], "failed");
    assert!(store.plan_events().is_empty());
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_skips_accepted_attempt_with_commit_mismatch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1"}));
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_artifacts_json = vec!["commit_ref:1234567890abcdef".to_string()];
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Release {
            reason: Some("supervisor_tick_requires_full_runtime".to_string())
        }
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "running");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert!(store.outbox().is_empty());
}
