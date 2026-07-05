use super::*;

#[tokio::test]
async fn supervisor_tick_handler_waits_for_pipeline_from_supervisor_decision() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let mut task = task_with_plan_metadata();
    task.status = "in_progress".to_string();
    task.metadata_json = json!({
        WORKSPACE_PLAN_ID: "plan-test",
        WORKSPACE_PLAN_NODE_ID: "node-test",
        CURRENT_ATTEMPT_ID: "attempt-wait-pipeline",
        PENDING_LEADER_ADJUDICATION: true,
        "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS
    });
    store.insert_task(task);
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-wait-pipeline".to_string());
    node.metadata_json = json!({
        "last_supervisor_decision_action": "wait_pipeline",
        "last_supervisor_decision_rationale": "Pipeline is already running; wait for the result.",
        "last_supervisor_decision_confidence": 0.88,
        "last_supervisor_decision_feedback_items": [{
            "target_layer": "runtime",
            "recommended_action": "wait_pipeline",
            "summary": "The requested CI run has not completed."
        }],
        "last_supervisor_decision_event_payload": {
            "source_commit_ref": "f00dbabe12345678"
        },
        "pipeline_provider": "drone",
        "pipeline_status": "running",
        "pipeline_gate_status": "running",
        "pipeline_request_count": 1,
        "verification_evidence_refs": ["pipeline_run:run-1"]
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-wait-pipeline",
        AWAITING_LEADER_ADJUDICATION_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_summary = Some("candidate is waiting for CI".to_string());
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
    let attempt = store.attempt("attempt-wait-pipeline");
    assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
    assert!(attempt.completed_at.is_none());
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(
        node.current_attempt_id.as_deref(),
        Some("attempt-wait-pipeline")
    );
    assert_eq!(
        node.metadata_json["last_supervisor_decision_action"],
        "wait_pipeline"
    );
    assert_eq!(node.metadata_json["pipeline_required"], true);
    assert_eq!(node.metadata_json["pipeline_provider"], "drone");
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
    assert_eq!(node.metadata_json["pipeline_request_count"], 1);
    assert_eq!(
        node.metadata_json["pipeline_wait_reason"],
        SUPERVISOR_DECISION_WAIT_PIPELINE_REASON
    );
    assert_eq!(
        node.metadata_json["last_verification_summary"],
        "Pipeline is already running; wait for the result."
    );
    assert_eq!(
        node.metadata_json["last_verification_attempt_id"],
        "attempt-wait-pipeline"
    );
    assert_eq!(
        node.metadata_json["verified_commit_ref"],
        "f00dbabe12345678"
    );
    assert_eq!(
        node.metadata_json["source_publish_source_commit_ref"],
        "f00dbabe12345678"
    );
    assert_eq!(
        node.metadata_json["candidate_artifacts"],
        json!(["artifact:diff-summary"])
    );
    assert_eq!(
        node.metadata_json["candidate_verifications"],
        json!(["worker_report:completed"])
    );
    assert_eq!(
        node.metadata_json["verification_evidence_refs"],
        json!([
            "artifact:diff-summary",
            "worker_report:completed",
            "pipeline_run:run-1",
            "commit_ref:f00dbabe12345678"
        ])
    );
    assert!(store.outbox().is_empty());
    assert!(node
        .metadata_json
        .get("supervisor_pipeline_outbox_id")
        .is_none());

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "supervisor_wait_pipeline_reconciled");
    assert_eq!(events[0].payload_json["action"], "wait_pipeline");
    assert_eq!(
        events[0].payload_json["reason"],
        SUPERVISOR_DECISION_WAIT_PIPELINE_REASON
    );

    let task = store.task("task-test");
    assert_eq!(task.status, "in_progress");
    assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], true);
}
