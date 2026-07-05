use super::*;

#[tokio::test]
async fn supervisor_tick_handler_creates_repair_node_from_supervisor_decision() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut root_task = root_goal_task();
    root_task.status = "in_progress".to_string();
    store.insert_task(root_task);
    let mut task = task_with_plan_metadata();
    task.status = "in_progress".to_string();
    task.metadata_json = json!({
        WORKSPACE_PLAN_ID: "plan-test",
        WORKSPACE_PLAN_NODE_ID: "node-test",
        ROOT_GOAL_TASK_ID: "root-task",
        CURRENT_ATTEMPT_ID: "attempt-repair",
        PENDING_LEADER_ADJUDICATION: true,
        "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS
    });
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-repair".to_string());
    node.depends_on_json = vec!["setup-node".to_string()];
    node.metadata_json = json!({
        "last_supervisor_decision_action": "create_repair_node",
        "last_supervisor_decision_rationale": "Fix src/oauth/service.ts: MockUser is missing avatar.",
        "last_supervisor_decision_confidence": 0.88,
        "last_supervisor_decision_repair_brief": {
            "failed_items": ["MockUser.avatar"],
            "required_next_action": "Add avatar and rerun backend build."
        },
        "last_supervisor_decision_feedback_items": [{
            "target_layer": "worker",
            "feedback_kind": "product_code_failure",
            "recommended_action": "fix_code_and_rerun_drone",
            "summary": "Add avatar to MockUser, then rerun backend build.",
            "failure_signature": "mockuser-avatar-missing"
        }],
        "last_verification_summary": "old verifier summary should not override rationale",
        "retry_not_before": "2026-01-02T03:05:05Z",
        "terminal_attempt_retry_count": 4,
        "worker_stream_last_entry_id": "99-0",
        "verification_evidence_refs": ["supervisor_decision:create_repair_node"]
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-repair",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("candidate needs a separate repair".to_string());
    attempt.candidate_artifacts_json = vec!["artifact:failed-report".to_string()];
    attempt.candidate_verifications_json = vec!["worker_report:needs-repair".to_string()];
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
    let attempt = store.attempt("attempt-repair");
    assert_eq!(attempt.status, REJECTED_ATTEMPT_STATUS);
    assert_eq!(
        attempt.leader_feedback.as_deref(),
        Some("Fix src/oauth/service.ts: MockUser is missing avatar.")
    );
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON)
    );
    assert!(attempt.completed_at.is_some());

    let node = store.node("node-test");
    let repair_node_id = node.metadata_json["supervisor_repair_node_id"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id, None);
    assert_eq!(node.assignee_agent_id.as_deref(), Some("agent-worker"));
    assert!(node.depends_on_json.iter().any(|id| id == &repair_node_id));
    assert_eq!(
        node.metadata_json["last_supervisor_decision_action"],
        "create_repair_node"
    );
    assert_eq!(
        node.metadata_json["last_verification_judge_verdict"],
        "needs_rework"
    );
    assert_eq!(
        node.metadata_json["last_verification_judge_next_action_kind"],
        "create_repair_node"
    );
    assert_eq!(
        node.metadata_json["blocked_by_repair_node_id"],
        repair_node_id
    );
    assert_eq!(
        node.metadata_json["replan_source"],
        "verification_judge_create_repair_node"
    );
    assert_eq!(
        node.metadata_json["workspace_task_projection_status"],
        SUPERVISOR_REPLAN_REQUESTED_VERDICT
    );
    assert!(node.metadata_json.get("retry_not_before").is_none());
    assert!(node
        .metadata_json
        .get("terminal_attempt_retry_count")
        .is_none());
    assert!(node
        .metadata_json
        .get("worker_stream_last_entry_id")
        .is_none());
    assert_eq!(
        node.metadata_json["verification_evidence_refs"],
        json!([
            "artifact:failed-report",
            "worker_report:needs-repair",
            "supervisor_decision:create_repair_node"
        ])
    );

    let repair = store.node(&repair_node_id);
    assert_eq!(repair.intent, "todo");
    assert_eq!(repair.execution, "idle");
    assert_eq!(repair.workspace_task_id, None);
    assert_eq!(repair.assignee_agent_id, None);
    assert_eq!(repair.depends_on_json, vec!["setup-node".to_string()]);
    assert!(repair.title.starts_with("Repair Build feature"));
    assert!(repair.description.contains("active attempt worktree only"));
    assert_eq!(repair.metadata_json["repair_for_node_id"], "node-test");
    assert_eq!(
        repair.metadata_json["repair_source"],
        "verification_judge_create_repair_node"
    );
    assert_eq!(
        repair.metadata_json["source_verification_judge_next_action_kind"],
        "create_repair_node"
    );
    assert_eq!(
        repair.metadata_json["repair_failure_signature"],
        "mockuser-avatar-missing"
    );
    assert_eq!(
        repair.metadata_json["last_supervisor_decision_repair_brief"]["failed_items"],
        json!(["MockUser.avatar"])
    );
    assert_eq!(
        repair.metadata_json["verification_evidence_refs"],
        json!([
            "artifact:failed-report",
            "worker_report:needs-repair",
            "supervisor_decision:create_repair_node"
        ])
    );

    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.blocker_reason, None);
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
    assert_eq!(
        task.metadata_json["durable_plan_verdict"],
        SUPERVISOR_REPLAN_REQUESTED_VERDICT
    );
    assert_eq!(
        task.metadata_json["last_supervisor_decision_action"],
        "create_repair_node"
    );
    assert_eq!(
        task.metadata_json["last_attempt_status"],
        REJECTED_ATTEMPT_STATUS
    );
    assert_eq!(task.metadata_json["last_attempt_id"], "attempt-repair");
    assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-repair");

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].event_type,
        "supervisor_create_repair_node_reconciled"
    );
    assert_eq!(events[0].payload_json["action"], "create_repair_node");
    assert_eq!(events[0].payload_json["repair_node_id"], repair_node_id);
    assert_eq!(events[0].payload_json["repair_node_created"], true);
    assert_eq!(events[0].payload_json["task_projected"], true);
    assert_eq!(events[0].payload_json["attempt_projected"], true);
    assert!(store.outbox().is_empty());
}
