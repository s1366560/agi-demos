use super::*;

#[tokio::test]
async fn supervisor_tick_handler_queues_attempt_retry_for_retry_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.current_attempt_id = Some("attempt-stale".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    store.insert_node(node);
    let handler = supervisor_tick_handler(Arc::clone(&store));

    let outcome = handler.handle(supervisor_tick_retry_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].plan_id.as_deref(), Some("plan-test"));
    assert_eq!(queued[0].payload_json["workspace_id"], "workspace-test");
    assert_eq!(queued[0].payload_json["task_id"], "task-test");
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(queued[0].payload_json["worker_agent_id"], "agent-worker");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-stale"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "stale_plan_node_no_terminal_worker_report"
    );
    assert_eq!(
        queued[0].payload_json["extra_instructions"],
        "recover stale node"
    );
    assert_eq!(
        queued[0].metadata_json["source"],
        "workspace_plan.supervisor_tick.retry_admission"
    );
    let node = store.node("node-test");
    assert_eq!(
        node.metadata_json["supervisor_tick_status"],
        "retry_admitted"
    );
    assert_eq!(
        node.metadata_json["supervisor_tick_retry_attempt_id"],
        "attempt-stale"
    );
    assert!(node.metadata_json["supervisor_tick_admitted_at"].is_string());
}

#[tokio::test]
async fn supervisor_tick_handler_releases_missing_attempt_node_and_queues_retry() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("missing-attempt".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    node.metadata_json = json!({"retry_not_before": "2026-01-02T03:04:05Z"});
    store.insert_node(node);
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
        "missing_attempt"
    );
    assert_eq!(node.metadata_json["terminal_attempt_retry_count"], 1);
    assert!(node.metadata_json["terminal_attempt_reconciled_at"].is_string());
    assert!(node.metadata_json.get("retry_not_before").is_none());

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(queued[0].payload_json["task_id"], "task-test");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "missing-attempt"
    );
    assert_eq!(queued[0].payload_json["retry_reason"], "missing_attempt");
    assert_eq!(queued[0].metadata_json["retry_node_id"], "node-test");
    assert_eq!(
        queued[0].metadata_json["retry_attempt_id"],
        "missing-attempt"
    );
}

#[tokio::test]
async fn supervisor_tick_handler_releases_terminal_rejected_attempt_and_queues_retry() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-rejected".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    store.insert_node(node);
    store.insert_attempt(task_session_attempt(
        "attempt-rejected",
        "rejected",
        Some("conversation-test"),
    ));
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
        "terminal_attempt_rejected"
    );
    assert_eq!(node.metadata_json["terminal_attempt_retry_count"], 1);
    assert!(node.metadata_json["terminal_attempt_reconciled_at"].is_string());

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-rejected"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "terminal_attempt_rejected"
    );
}

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

#[tokio::test]
async fn supervisor_tick_handler_skips_terminal_attempt_with_pipeline_result_pending() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-rejected".to_string());
    node.metadata_json = json!({
        "pipeline_status": "success",
        "pipeline_run_id": "pipeline-run-test"
    });
    store.insert_node(node);
    store.insert_attempt(task_session_attempt(
        "attempt-rejected",
        "rejected",
        Some("conversation-test"),
    ));
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
    assert_eq!(node.execution, "reported");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-rejected"));
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_reconciles_retry_same_node_supervisor_decision() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-retry".to_string());
    node.assignee_agent_id = Some("agent-worker".to_string());
    node.metadata_json = json!({
        "last_supervisor_decision_action": "retry_same_node",
        "last_supervisor_decision_rationale": "retry after tightening the implementation",
        "last_supervisor_decision_confidence": 0.72,
        "last_supervisor_decision_feedback_items": [{
            "target_layer": "implementation",
            "recommended_action": "fix_regression",
            "summary": "missing regression coverage"
        }],
        "retry_not_before": "2999-01-02T03:04:05Z"
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-retry",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("worker produced a candidate with a gap".to_string());
    store.insert_attempt(attempt);
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
    let attempt = store.attempt("attempt-retry");
    assert_eq!(attempt.status, REJECTED_ATTEMPT_STATUS);
    assert_eq!(
        attempt.leader_feedback.as_deref(),
        Some("retry after tightening the implementation")
    );
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some(SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON)
    );
    assert!(attempt.completed_at.is_some());

    let node = store.node("node-test");
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id, None);
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_reason"],
        SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
    );
    assert_eq!(
        node.metadata_json["supervisor_decision_retry_attempt_id"],
        "attempt-retry"
    );
    assert_eq!(
        node.metadata_json["supervisor_decision_retry_attempt_status"],
        REJECTED_ATTEMPT_STATUS
    );
    assert!(node
        .metadata_json
        .get("reported_attempt_reconciled_at")
        .is_none());
    assert!(node.metadata_json.get("retry_not_before").is_none());

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].event_type,
        "supervisor_decision_retry_same_node_reconciled"
    );
    assert_eq!(
        events[0].payload_json["reason"],
        SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
    );
    assert_eq!(events[0].payload_json["action"], "retry_same_node");
    assert_eq!(
        events[0].payload_json["rationale"],
        "retry after tightening the implementation"
    );
    assert_eq!(events[0].payload_json["retry_exhausted"], false);

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(queued[0].payload_json["task_id"], "task-test");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-retry"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
    );
    assert_eq!(
        queued[0].payload_json["retry_not_before"],
        "2999-01-02T03:04:05+00:00"
    );
    assert_eq!(
        queued[0].next_attempt_at,
        Some(
            DateTime::parse_from_rfc3339("2999-01-02T03:04:05Z")
                .unwrap()
                .with_timezone(&Utc)
        )
    );
}

#[tokio::test]
async fn supervisor_tick_handler_releases_generic_tick_until_full_runtime() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "controller_reason": "delivery_contract_regeneration_requested"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Release {
            reason: Some("supervisor_tick_requires_full_runtime".to_string())
        }
    );
    assert!(store.outbox().is_empty());
}
