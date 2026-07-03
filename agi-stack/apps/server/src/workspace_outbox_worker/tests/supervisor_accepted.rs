use super::*;

#[tokio::test]
async fn supervisor_tick_handler_projects_accepted_attempt_to_node_and_task() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": "/workspace/.worktrees/attempt-accepted",
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
    attempt.leader_feedback = Some("accepted after verification".to_string());
    attempt.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
    attempt.candidate_verifications_json = vec![
        "test_run:cargo test -p agistack-server workspace_outbox_worker".to_string(),
        "git_diff_summary:updated supervisor projection".to_string(),
    ];
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
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
    assert_eq!(
        node.metadata_json["terminal_attempt_status"],
        ACCEPTED_ATTEMPT_STATUS
    );
    assert_eq!(
        node.metadata_json["last_verification_summary"],
        "accepted after verification"
    );
    assert_eq!(node.metadata_json["last_verification_passed"], true);
    assert_eq!(
        node.metadata_json["last_verification_attempt_id"],
        "attempt-accepted"
    );
    assert_eq!(
        node.metadata_json["candidate_artifacts"],
        json!(["commit_ref:abcdef1234567890"])
    );

    let task = store.task("task-test");
    assert_eq!(task.status, "done");
    assert!(task.completed_at.is_some());
    assert_eq!(task.metadata_json["durable_plan_verdict"], "accepted");
    assert_eq!(
        task.metadata_json["last_attempt_status"],
        ACCEPTED_ATTEMPT_STATUS
    );
    assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-accepted");
    assert_eq!(
        task.metadata_json["last_worker_report_summary"],
        "accepted after verification"
    );
    assert_eq!(
        task.metadata_json["handoff_package"]["git_head"],
        "abcdef1234567890"
    );
    assert_eq!(
        task.metadata_json["handoff_package"]["git_diff_summary"],
        "updated supervisor projection"
    );
    assert_eq!(
        task.metadata_json["handoff_package"]["test_commands"],
        json!(["cargo test -p agistack-server workspace_outbox_worker"])
    );
    assert_eq!(task.metadata_json["worktree_integration_status"], "skipped");
    assert_eq!(
        task.metadata_json["worktree_integration_summary"],
        "sandbox_code_root is not available for accepted worktree integration"
    );
    assert_eq!(
        node.metadata_json["worktree_integration_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(node.metadata_json["worktree_integration_status"], "skipped");
    assert!(store.plan_events().is_empty());
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_reconciles_accepted_supervisor_judge_attempt() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    let mut task = task_with_plan_metadata();
    task.status = "in_progress".to_string();
    task.metadata_json = json!({
        WORKSPACE_PLAN_ID: "plan-test",
        WORKSPACE_PLAN_NODE_ID: "node-test",
        ROOT_GOAL_TASK_ID: "root-task",
        CURRENT_ATTEMPT_ID: "attempt-judge",
        PENDING_LEADER_ADJUDICATION: true,
        "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS,
        "last_worker_report_summary": "candidate satisfies the acceptance criteria"
    });
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "done".to_string();
    node.execution = "idle".to_string();
    node.current_attempt_id = Some("attempt-judge".to_string());
    node.metadata_json = json!({
        "last_verification_judge_verdict": "accepted",
        "last_verification_summary": "supervisor accepted current evidence",
        "last_verification_passed": true,
        "verification_evidence_refs": ["worker_report:completed"]
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-judge",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("candidate satisfies the acceptance criteria".to_string());
    attempt.candidate_artifacts_json = vec!["artifact:review-report".to_string()];
    attempt.candidate_verifications_json = vec!["worker_report:completed".to_string()];
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
    let attempt = store.attempt("attempt-judge");
    assert_eq!(attempt.status, ACCEPTED_ATTEMPT_STATUS);
    assert_eq!(
        attempt.leader_feedback.as_deref(),
        Some("supervisor accepted current evidence")
    );
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some("supervisor_decision_accept_node_reconciled")
    );
    assert!(attempt.completed_at.is_some());
    let node = store.node("node-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-judge"));
    assert_eq!(
        node.metadata_json["terminal_attempt_status"],
        ACCEPTED_ATTEMPT_STATUS
    );
    assert_eq!(
        node.metadata_json["last_verification_summary"],
        "supervisor accepted current evidence"
    );
    assert_eq!(
        node.metadata_json["last_verification_attempt_id"],
        "attempt-judge"
    );
    assert_eq!(
        node.metadata_json["candidate_artifacts"],
        json!(["artifact:review-report"])
    );
    let task = store.task("task-test");
    assert_eq!(task.status, "done");
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
    assert_eq!(task.metadata_json["durable_plan_verdict"], "accepted");
    assert_eq!(
        task.metadata_json["durable_plan_verification_summary"],
        "supervisor accepted current evidence"
    );
    assert_eq!(
        task.metadata_json["last_attempt_status"],
        ACCEPTED_ATTEMPT_STATUS
    );
    assert_eq!(task.metadata_json["last_attempt_id"], "attempt-judge");
    assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-judge");
    assert_eq!(
        task.metadata_json["last_leader_adjudication_status"],
        ACCEPTED_ATTEMPT_STATUS
    );
    assert_eq!(
        task.metadata_json["evidence_refs"],
        json!(["artifact:review-report", "worker_report:completed"])
    );
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_reconciles_root_goal_progress_for_accepted_child() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_metadata(json!({})));
    store.insert_task(root_goal_task());
    store.insert_task(task_with_plan_metadata());
    let mut stale_child = task_with_plan_metadata();
    stale_child.id = "stale-helper-task".to_string();
    stale_child.title = "Old helper task".to_string();
    stale_child.status = "blocked".to_string();
    stale_child.blocker_reason = Some("stale helper blocked".to_string());
    stale_child.assignee_agent_id = None;
    stale_child.metadata_json = json!({
        ROOT_GOAL_TASK_ID: "root-task",
        WORKSPACE_PLAN_ID: "old-plan",
        WORKSPACE_PLAN_NODE_ID: "missing-node"
    });
    store.insert_task(stale_child);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.leader_feedback = Some("accepted after verification".to_string());
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
    let task = store.task("task-test");
    assert_eq!(task.status, "done");
    let root = store.task("root-task");
    assert_eq!(root.status, "todo");
    assert_eq!(
        root.metadata_json["goal_progress_summary"],
        "1/1 child tasks done; 0 in progress; 0 blocked; 1/1 assigned"
    );
    assert_eq!(root.metadata_json["goal_health"], "achieved");
    assert_eq!(
        root.metadata_json[REMEDIATION_STATUS],
        "ready_for_completion"
    );
    assert_eq!(
        root.metadata_json[REMEDIATION_SUMMARY],
        "All child tasks are done; root goal should now validate completion evidence"
    );
    assert_eq!(root.metadata_json["active_child_task_ids"], json!([]));
    assert_eq!(root.metadata_json["blocked_child_task_ids"], json!([]));
    assert_eq!(root.metadata_json["blocked_reason"], Value::Null);
    assert!(root.metadata_json["last_progress_at"].is_string());
}
