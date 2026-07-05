use super::*;

#[tokio::test]
async fn supervisor_tick_handler_projects_superseding_accepted_attempt_before_retry() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-cancelled".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": "/workspace/.worktrees/attempt-accepted",
        "branch_name": "attempt-accepted",
        "base_ref": "main",
        "commit_ref": "abcdef1"
    }));
    store.insert_node(node);
    let mut cancelled =
        task_session_attempt("attempt-cancelled", "cancelled", Some("conversation-test"));
    cancelled.attempt_number = 2;
    cancelled.adjudication_reason = Some("recovery:parent_done".to_string());
    store.insert_attempt(cancelled);
    let mut accepted = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    accepted.attempt_number = 1;
    accepted.leader_feedback = Some("accepted after parent recovery".to_string());
    accepted.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
    accepted.candidate_verifications_json = vec![
        "test_run:cargo test -p agistack-server workspace_outbox_worker".to_string(),
        "git_diff_summary:accepted sibling won".to_string(),
    ];
    store.insert_attempt(accepted);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
    assert_eq!(
        node.metadata_json["terminal_attempt_status"],
        ACCEPTED_ATTEMPT_STATUS
    );
    assert_eq!(
        node.metadata_json["terminal_attempt_superseded_attempt_id"],
        "attempt-cancelled"
    );
    assert_eq!(
        node.metadata_json["terminal_attempt_superseded_status"],
        "cancelled"
    );
    assert_eq!(
        node.metadata_json["terminal_attempt_superseded_reason"],
        "recovery:parent_done"
    );
    assert_eq!(
        node.metadata_json["last_verification_attempt_id"],
        "attempt-accepted"
    );
    assert_eq!(node.metadata_json["last_verification_passed"], true);

    let task = store.task("task-test");
    assert_eq!(task.status, "done");
    assert_eq!(task.metadata_json["durable_plan_verdict"], "accepted");
    assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-accepted");
    assert_eq!(
        task.metadata_json["last_worker_report_summary"],
        "accepted after parent recovery"
    );
    assert_eq!(
        task.metadata_json["handoff_package"]["git_head"],
        "abcdef1234567890"
    );
    assert_eq!(
        task.metadata_json["handoff_package"]["git_diff_summary"],
        "accepted sibling won"
    );
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_retries_terminal_parent_done_with_output() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-cancelled".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1"}));
    store.insert_node(node);
    let mut cancelled =
        task_session_attempt("attempt-cancelled", "cancelled", Some("conversation-test"));
    cancelled.attempt_number = 2;
    cancelled.adjudication_reason = Some("recovery:parent_done".to_string());
    cancelled.candidate_summary = Some("cancelled attempt already produced output".to_string());
    store.insert_attempt(cancelled);
    let mut accepted = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    accepted.attempt_number = 1;
    accepted.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
    store.insert_attempt(accepted);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id, None);
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_reason"],
        "terminal_attempt_cancelled"
    );
    assert!(node
        .metadata_json
        .get("terminal_attempt_superseded_attempt_id")
        .is_none());
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert!(task.metadata_json.get("durable_plan_verdict").is_none());
    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-cancelled"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "terminal_attempt_cancelled"
    );
}
