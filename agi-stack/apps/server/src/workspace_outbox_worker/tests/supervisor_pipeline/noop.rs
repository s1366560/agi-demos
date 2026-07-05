use super::*;

#[tokio::test]
async fn supervisor_tick_handler_preserves_noop_supervisor_decision() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut task = task_with_plan_metadata();
    task.status = "in_progress".to_string();
    task.metadata_json = json!({
        WORKSPACE_PLAN_ID: "plan-test",
        WORKSPACE_PLAN_NODE_ID: "node-test",
        CURRENT_ATTEMPT_ID: "attempt-noop",
        PENDING_LEADER_ADJUDICATION: true,
        "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS
    });
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-noop".to_string());
    node.metadata_json = json!({
        "last_supervisor_decision_action": "noop",
        "last_supervisor_decision_rationale": "No durable state transition is needed yet.",
        "last_supervisor_decision_confidence": 0.76,
        "last_supervisor_decision_feedback_items": [{
            "target_layer": "runtime",
            "recommended_action": "continue_observing",
            "summary": "The supervisor intentionally left the plan unchanged."
        }],
        "last_verification_summary": "old verifier summary should not override noop rationale",
        "verification_evidence_refs": ["worker_report:completed"]
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-noop",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("candidate remains under observation".to_string());
    attempt.candidate_artifacts_json = vec!["artifact:diff-summary".to_string()];
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
    let attempt = store.attempt("attempt-noop");
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert!(attempt.completed_at.is_none());
    assert_eq!(
        attempt.candidate_summary.as_deref(),
        Some("candidate remains under observation")
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-noop"));
    assert_eq!(
        node.metadata_json["last_supervisor_decision_action"],
        SUPERVISOR_DECISION_NOOP_ACTION
    );
    assert_eq!(
        node.metadata_json["last_supervisor_decision_rationale"],
        "No durable state transition is needed yet."
    );
    assert_eq!(
        node.metadata_json["supervisor_noop_reason"],
        SUPERVISOR_DECISION_NOOP_REASON
    );
    assert_eq!(
        node.metadata_json["supervisor_noop_attempt_id"],
        "attempt-noop"
    );
    assert!(node
        .metadata_json
        .get("supervisor_noop_reconciled_at")
        .is_some());
    assert_eq!(
        node.metadata_json["last_verification_summary"],
        "old verifier summary should not override noop rationale"
    );
    assert!(node.metadata_json.get("pipeline_required").is_none());
    assert!(node
        .metadata_json
        .get("supervisor_pipeline_outbox_id")
        .is_none());
    assert!(store.outbox().is_empty());

    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], true);
    assert_eq!(
        task.metadata_json["last_attempt_status"],
        AWAITING_LEADER_ADJUDICATION_STATUS
    );

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "supervisor_noop_reconciled");
    assert_eq!(events[0].payload_json["action"], "noop");
    assert_eq!(
        events[0].payload_json["reason"],
        SUPERVISOR_DECISION_NOOP_REASON
    );
    assert_eq!(events[0].payload_json["attempt_id"], "attempt-noop");

    let mut item = outbox("job-supervisor-tick-again", SUPERVISOR_TICK_EVENT);
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
    assert_eq!(store.plan_events().len(), 1);
    assert!(store.outbox().is_empty());
}
