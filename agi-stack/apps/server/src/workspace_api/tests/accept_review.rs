use super::*;

#[tokio::test]
async fn accept_review_marks_linked_attempt_accepted() {
    let service = DevWorkspaceService::new("user-1");
    let now = "2026-01-02T03:04:05Z".parse().unwrap();
    {
        let mut state = service.state.lock().expect("workspace dev state");
        state.tasks.insert(
            "task-review".to_string(),
            WorkspaceTaskRecord {
                id: "task-review".to_string(),
                workspace_id: "workspace-review".to_string(),
                title: "Review worker report".to_string(),
                description: None,
                created_by: "user-1".to_string(),
                assignee_user_id: None,
                assignee_agent_id: Some("agent-worker".to_string()),
                status: "blocked".to_string(),
                priority: 1,
                estimated_effort: None,
                blocker_reason: None,
                metadata_json: json!({
                    "pending_leader_adjudication": true,
                    "current_attempt_id": "attempt-review",
                    "current_attempt_number": 1,
                    "last_attempt_status": "awaiting_leader_adjudication",
                    "last_worker_report_summary": "candidate is acceptable after manual review"
                }),
                created_at: now,
                updated_at: None,
                completed_at: None,
                archived_at: None,
            },
        );
        state.plans.insert(
            "plan-review".to_string(),
            WorkspacePlanRecord {
                id: "plan-review".to_string(),
                workspace_id: "workspace-review".to_string(),
                goal_id: "node-review".to_string(),
                status: "active".to_string(),
                created_at: now,
                updated_at: None,
            },
        );
        state.plan_nodes.insert(
            "node-review".to_string(),
            WorkspacePlanNodeRecord {
                id: "node-review".to_string(),
                plan_id: "plan-review".to_string(),
                parent_id: None,
                kind: "task".to_string(),
                title: "Review worker report".to_string(),
                description: "Accept the candidate after human review".to_string(),
                depends_on_json: Vec::new(),
                inputs_schema_json: json!({}),
                outputs_schema_json: json!({}),
                acceptance_criteria_json: Vec::new(),
                feature_checkpoint_json: None,
                handoff_package_json: None,
                recommended_capabilities_json: Vec::new(),
                preferred_agent_id: None,
                estimated_effort_json: json!({}),
                priority: 1,
                intent: "blocked".to_string(),
                execution: "reported".to_string(),
                progress_json: json!({"percent": 60, "confidence": 0.8, "note": "review"}),
                assignee_agent_id: Some("agent-worker".to_string()),
                current_attempt_id: Some("attempt-review".to_string()),
                workspace_task_id: Some("task-review".to_string()),
                metadata_json: json!({
                    "last_verification_passed": false,
                    "verification_evidence_refs": ["ci:previous"]
                }),
                created_at: now,
                updated_at: None,
                completed_at: None,
            },
        );
        state.task_attempts.insert(
            "attempt-review".to_string(),
            WorkspaceTaskSessionAttemptRecord {
                id: "attempt-review".to_string(),
                workspace_task_id: "task-review".to_string(),
                root_goal_task_id: "root-review".to_string(),
                workspace_id: "workspace-review".to_string(),
                attempt_number: 1,
                status: "awaiting_leader_adjudication".to_string(),
                conversation_id: Some("conversation-review".to_string()),
                worker_agent_id: Some("agent-worker".to_string()),
                leader_agent_id: Some("agent-leader".to_string()),
                candidate_summary: Some("candidate is acceptable after manual review".to_string()),
                candidate_artifacts_json: vec!["artifact:report".to_string()],
                candidate_verifications_json: vec!["worker_report:completed".to_string()],
                leader_feedback: None,
                adjudication_reason: None,
                created_at: now,
                updated_at: None,
                completed_at: None,
            },
        );
    }

    let result = service
        .accept_plan_node_review(
            "user-1",
            "workspace-review",
            "node-review",
            WorkspacePlanActionRequest {
                reason: Some("operator accepts evidence".to_string()),
                evidence_refs: vec!["ci:new".to_string()],
            },
        )
        .await
        .unwrap();

    assert_eq!(result.message, "Plan node accepted after human review.");
    let state = service.state.lock().expect("workspace dev state");
    let attempt = state.task_attempts.get("attempt-review").unwrap();
    assert_eq!(attempt.status, "accepted");
    assert_eq!(
        attempt.leader_feedback.as_deref(),
        Some("operator accepts evidence")
    );
    assert_eq!(
        attempt.adjudication_reason.as_deref(),
        Some("operator_review_accepted")
    );
    assert!(attempt.completed_at.is_some());
    let node = state.plan_nodes.get("node-review").unwrap();
    assert_eq!(node.intent, "done");
    assert!(node.current_attempt_id.is_none());
    assert_eq!(node.metadata_json["last_attempt_status"], "accepted");
    assert_eq!(node.metadata_json["accepted_attempt_id"], "attempt-review");
    assert_eq!(
        node.metadata_json["verification_evidence_refs"],
        json!(["ci:previous", "ci:new"])
    );
    let task = state.tasks.get("task-review").unwrap();
    assert_eq!(task.status, "done");
    assert_eq!(task.metadata_json["pending_leader_adjudication"], false);
    assert_eq!(task.metadata_json["last_attempt_status"], "accepted");
    assert_eq!(task.metadata_json["last_attempt_id"], "attempt-review");
    assert_eq!(task.metadata_json["current_attempt_id"], "attempt-review");
    assert_eq!(task.metadata_json["current_attempt_number"], 1);
    assert!(state.plan_events.iter().any(|event| {
        event.event_type == "operator_review_accepted"
            && event.attempt_id.as_deref() == Some("attempt-review")
    }));
}
