use super::*;

#[tokio::test]
async fn supervisor_tick_handler_requests_pipeline_from_supervisor_decision() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut task = task_with_plan_metadata();
    task.status = "in_progress".to_string();
    task.metadata_json = json!({
        WORKSPACE_PLAN_ID: "plan-test",
        WORKSPACE_PLAN_NODE_ID: "node-test",
        CURRENT_ATTEMPT_ID: "attempt-pipeline",
        PENDING_LEADER_ADJUDICATION: true,
        "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS
    });
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-pipeline".to_string());
    node.metadata_json = json!({
        "last_supervisor_decision_action": "request_pipeline",
        "last_supervisor_decision_rationale": "Run harness-native CI for the accepted candidate.",
        "last_supervisor_decision_confidence": 0.91,
        "last_supervisor_decision_feedback_items": [{
            "target_layer": "runtime",
            "recommended_action": "request_pipeline",
            "summary": "CI evidence is required before accepting this node."
        }],
        "last_supervisor_decision_event_payload": {
            "source_commit_ref": "abcdef1234567890"
        },
        "pipeline_request_count": 2,
        "verification_evidence_refs": ["worker_report:completed"]
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-pipeline",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("candidate awaits platform CI".to_string());
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
    let attempt = store.attempt("attempt-pipeline");
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert!(attempt.completed_at.is_none());
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-pipeline"));
    assert_eq!(
        node.metadata_json["last_supervisor_decision_action"],
        "request_pipeline"
    );
    assert_eq!(node.metadata_json["pipeline_required"], true);
    assert_eq!(node.metadata_json["pipeline_provider"], "sandbox_native");
    assert_eq!(node.metadata_json["pipeline_status"], "requested");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "requested");
    assert_eq!(node.metadata_json["pipeline_request_count"], 3);
    assert_eq!(
        node.metadata_json["pipeline_request_reason"],
        SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON
    );
    assert_eq!(
        node.metadata_json["last_verification_summary"],
        "Run harness-native CI for the accepted candidate."
    );
    assert_eq!(
        node.metadata_json["last_verification_attempt_id"],
        "attempt-pipeline"
    );
    assert_eq!(
        node.metadata_json["verified_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(
        node.metadata_json["source_publish_source_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(
        node.metadata_json["verification_evidence_refs"],
        json!([
            "artifact:diff-summary",
            "worker_report:completed",
            "commit_ref:abcdef1234567890"
        ])
    );
    let outbox = store.outbox();
    assert_eq!(outbox.len(), 1);
    assert_eq!(outbox[0].event_type, PIPELINE_RUN_REQUESTED_EVENT);
    assert_eq!(
        outbox[0].metadata_json["source"],
        "workspace_plan.supervisor_decision_request_pipeline"
    );
    assert_eq!(outbox[0].payload_json["node_id"], "node-test");
    assert_eq!(outbox[0].payload_json["attempt_id"], "attempt-pipeline");
    assert_eq!(
        outbox[0].payload_json["reason"],
        SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON
    );
    assert_eq!(
        outbox[0].payload_json["summary"],
        "Run harness-native CI for the accepted candidate."
    );

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].event_type,
        "supervisor_request_pipeline_reconciled"
    );
    assert_eq!(events[0].payload_json["action"], "request_pipeline");
    assert_eq!(
        events[0].payload_json["reason"],
        SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON
    );

    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], true);
}
