use super::*;

#[tokio::test]
async fn supervisor_tick_handler_records_already_merged_accepted_worktree() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_code_root("/workspace/app"));
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": "/workspace/app",
        "branch_name": "attempt-accepted",
        "base_ref": "main",
        "commit_ref": "abcdef1"
    }));
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.leader_feedback = Some("accepted in main checkout".to_string());
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

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    let task = store.task("task-test");
    assert_eq!(node.intent, "done");
    assert_eq!(task.status, "done");
    assert_eq!(
        node.metadata_json["worktree_integration_status"],
        "already_merged"
    );
    assert_eq!(
        task.metadata_json["worktree_integration_worktree_path"],
        "/workspace/app"
    );
    assert_eq!(
        task.metadata_json["worktree_integration_summary"],
        "accepted attempt already ran in sandbox_code_root"
    );
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].event_type,
        "accepted_worktree_integration_skipped"
    );
    assert_eq!(
        events[0].source,
        "workspace_plan.accepted_worktree_integration"
    );
    assert_eq!(events[0].payload_json["status"], "already_merged");
    assert_eq!(events[0].payload_json["commit_ref"], "abcdef1234567890");
    assert_eq!(events[0].payload_json["worktree_path"], "/workspace/app");
    assert!(store.outbox().is_empty());
}
