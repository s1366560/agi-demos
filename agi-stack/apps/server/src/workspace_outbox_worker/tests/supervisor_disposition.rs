use super::*;

#[tokio::test]
async fn supervisor_tick_handler_reconciles_mark_blocked_human_supervisor_decision() {
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
        CURRENT_ATTEMPT_ID: "attempt-human-block",
        PENDING_LEADER_ADJUDICATION: true,
        "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS
    });
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-human-block".to_string());
    node.metadata_json = json!({
        "last_supervisor_decision_action": "mark_blocked_human",
        "last_supervisor_decision_rationale": "production deploy approval is required",
        "last_supervisor_decision_confidence": 0.93,
        "last_supervisor_decision_feedback_items": [{
            "target_layer": "human",
            "recommended_action": "escalate_human",
            "summary": "approval gate is outside the worker authority"
        }],
        "last_supervisor_decision_event_payload": {
            "human_required": true,
            "approval_scope": "production_deploy"
        },
        "verification_evidence_refs": ["approval:production_deploy"]
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-human-block",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("candidate needs production approval".to_string());
    attempt.candidate_artifacts_json = vec!["artifact:release-plan".to_string()];
    attempt.candidate_verifications_json = vec!["approval:production_deploy".to_string()];
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
    let attempt = store.attempt("attempt-human-block");
    assert_eq!(attempt.status, "blocked");
    assert_eq!(
        attempt.leader_feedback.as_deref(),
        Some("production deploy approval is required")
    );
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some(SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_REASON)
    );
    assert!(attempt.completed_at.is_some());

    let node = store.node("node-test");
    assert_eq!(node.intent, "blocked");
    assert_eq!(node.execution, "idle");
    assert_eq!(
        node.current_attempt_id.as_deref(),
        Some("attempt-human-block")
    );
    assert_eq!(
        node.metadata_json["last_verification_judge_verdict"],
        SUPERVISOR_BLOCKED_HUMAN_VERDICT
    );
    assert_eq!(
        node.metadata_json["last_supervisor_decision_action"],
        "mark_blocked_human"
    );
    assert_eq!(
        node.metadata_json["last_verification_summary"],
        "production deploy approval is required"
    );
    assert_eq!(node.metadata_json["terminal_attempt_status"], "blocked");
    assert_eq!(
        node.metadata_json["workspace_task_projection_status"],
        "blocked"
    );
    assert_eq!(
        node.metadata_json["verification_evidence_refs"],
        json!(["artifact:release-plan", "approval:production_deploy"])
    );

    let task = store.task("task-test");
    assert_eq!(task.status, "blocked");
    assert_eq!(
        task.blocker_reason.as_deref(),
        Some("production deploy approval is required")
    );
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
    assert_eq!(task.metadata_json["durable_plan_verdict"], "blocked");
    assert_eq!(
        task.metadata_json["durable_plan_verification_summary"],
        "production deploy approval is required"
    );
    assert_eq!(task.metadata_json["last_attempt_status"], "blocked");
    assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
    assert_eq!(
        task.metadata_json["last_leader_adjudication_status"],
        "blocked"
    );
    assert_eq!(task.metadata_json["last_attempt_id"], "attempt-human-block");
    assert_eq!(
        task.metadata_json[CURRENT_ATTEMPT_ID],
        "attempt-human-block"
    );
    assert_eq!(
        task.metadata_json["evidence_refs"],
        json!(["artifact:release-plan", "approval:production_deploy"])
    );

    let root = store.task("root-task");
    assert_eq!(root.metadata_json["goal_health"], "blocked");
    assert_eq!(root.metadata_json[REMEDIATION_STATUS], "replan_required");
    assert_eq!(
        root.metadata_json["blocked_child_task_ids"],
        json!(["task-test"])
    );

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "supervisor_blocked_human_reconciled");
    assert_eq!(events[0].payload_json["action"], "mark_blocked_human");
    assert_eq!(events[0].payload_json["attempt_projected"], true);
    assert_eq!(events[0].payload_json["task_projected"], true);
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_projects_dispose_node_supervisor_decision() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut task = task_with_plan_metadata();
    task.status = "in_progress".to_string();
    task.metadata_json = json!({
        WORKSPACE_PLAN_ID: "plan-test",
        WORKSPACE_PLAN_NODE_ID: "node-test",
        ROOT_GOAL_TASK_ID: "root-task",
        CURRENT_ATTEMPT_ID: "attempt-dispose",
        PENDING_LEADER_ADJUDICATION: true,
        "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS
    });
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-dispose".to_string());
    node.metadata_json = json!({
        "last_supervisor_decision_action": "dispose_node",
        "last_supervisor_decision_rationale": "repair node superseded this obsolete node",
        "last_supervisor_decision_confidence": 0.81,
        "last_supervisor_decision_feedback_items": [{
            "target_layer": "planner",
            "recommended_action": "obsolete_node",
            "summary": "repair alternative already covers the requirement"
        }],
        "last_supervisor_decision_event_payload": {
            "disposed_node_id": "node-test",
            "superseded_by_node_id": "repair-node",
            "superseded_by_task_id": "repair-task"
        },
        "last_verification_summary": "obsolete after repair alternative"
    });
    store.insert_node(node);
    store.insert_supervisor_dispose_decision("workspace-test", "plan-test", "node-test");
    let mut attempt = task_session_attempt(
        "attempt-dispose",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("obsolete candidate".to_string());
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
    let attempt = store.attempt("attempt-dispose");
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert_eq!(attempt.completed_at, None);

    let node = store.node("node-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-dispose"));
    assert!(node.completed_at.is_some());
    assert_eq!(
        node.metadata_json["verification_feedback_disposition"],
        SUPERVISOR_DISPOSED_NODE_DISPOSITION
    );
    assert_eq!(
        node.metadata_json["last_supervisor_decision_action"],
        "dispose_node"
    );
    assert_eq!(
        node.metadata_json["last_supervisor_decision_rationale"],
        "repair node superseded this obsolete node"
    );
    assert_eq!(
        node.metadata_json["workspace_task_projection_status"],
        "done"
    );
    assert!(node.metadata_json["workspace_task_projected_at"].is_string());
    assert!(node
        .metadata_json
        .get("reported_attempt_reconciled_at")
        .is_none());

    let task = store.task("task-test");
    assert_eq!(task.status, "done");
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
    assert_eq!(task.metadata_json["durable_plan_verdict"], "disposed");
    assert_eq!(
        task.metadata_json["durable_plan_disposition"],
        SUPERVISOR_DISPOSED_NODE_DISPOSITION
    );
    assert_eq!(
        task.metadata_json["durable_plan_verification_summary"],
        "repair node superseded this obsolete node"
    );
    assert_eq!(task.metadata_json["last_attempt_status"], "disposed");
    assert_eq!(task.metadata_json["last_worker_report_type"], "disposed");
    assert_eq!(
        task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
        "repair node superseded this obsolete node"
    );
    assert_eq!(
        task.metadata_json["last_leader_adjudication_status"],
        "disposed"
    );
    assert_eq!(task.metadata_json["last_attempt_id"], "attempt-dispose");
    assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-dispose");
    assert_eq!(task.metadata_json["disposed_node_id"], "node-test");
    assert_eq!(task.metadata_json["superseded_by_node_id"], "repair-node");
    assert_eq!(task.metadata_json["superseded_by_task_id"], "repair-task");

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "supervisor_disposition_reconciled");
    assert_eq!(events[0].payload_json["action"], "dispose_node");
    assert_eq!(events[0].payload_json["had_dispose_event"], true);
    assert_eq!(events[0].payload_json["task_projected"], true);
    assert!(store.outbox().is_empty());
}
