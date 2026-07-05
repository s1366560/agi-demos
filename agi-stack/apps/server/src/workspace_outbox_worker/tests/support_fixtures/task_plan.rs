use super::super::*;

pub(in crate::workspace_outbox_worker::tests) fn task_with_plan_metadata() -> WorkspaceTaskRecord {
    WorkspaceTaskRecord {
        id: "task-test".to_string(),
        workspace_id: "workspace-test".to_string(),
        title: "Build feature".to_string(),
        description: None,
        created_by: "actor-test".to_string(),
        assignee_user_id: None,
        assignee_agent_id: Some("agent-worker".to_string()),
        status: "todo".to_string(),
        priority: 1,
        estimated_effort: None,
        blocker_reason: None,
        metadata_json: json!({
            ROOT_GOAL_TASK_ID: "root-task",
            WORKSPACE_PLAN_ID: "plan-test",
            WORKSPACE_PLAN_NODE_ID: "node-test"
        }),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
        completed_at: None,
        archived_at: None,
    }
}

pub(in crate::workspace_outbox_worker::tests) fn root_goal_task() -> WorkspaceTaskRecord {
    WorkspaceTaskRecord {
        id: "root-task".to_string(),
        workspace_id: "workspace-test".to_string(),
        title: "Finish root goal".to_string(),
        description: None,
        created_by: "actor-test".to_string(),
        assignee_user_id: None,
        assignee_agent_id: None,
        status: "todo".to_string(),
        priority: 1,
        estimated_effort: None,
        blocker_reason: None,
        metadata_json: json!({
            TASK_ROLE: GOAL_ROOT_TASK_ROLE,
            "goal_health": "healthy"
        }),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
        completed_at: None,
        archived_at: None,
    }
}

pub(in crate::workspace_outbox_worker::tests) fn workspace_with_metadata(
    metadata_json: Value,
) -> WorkspaceRecord {
    WorkspaceRecord {
        id: "workspace-test".to_string(),
        tenant_id: "tenant-test".to_string(),
        project_id: "project-test".to_string(),
        name: "Workspace".to_string(),
        description: None,
        created_by: "actor-test".to_string(),
        is_archived: false,
        metadata_json,
        office_status: "active".to_string(),
        hex_layout_config_json: json!({}),
        default_blocking_categories_json: Vec::new(),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
    }
}

pub(in crate::workspace_outbox_worker::tests) fn workspace_with_code_root(
    root: &str,
) -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "code_context": {
            "sandbox_code_root": root
        }
    }))
}

pub(in crate::workspace_outbox_worker::tests) fn workspace_with_pipeline_contract(
) -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "delivery_cicd": {
            "provider": "sandbox_native",
            "code_root": "/workspace/project",
            "auto_deploy": false,
            "timeout_seconds": 120,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "contract_confidence": 0.82,
            "env": {"CI": "true"},
            "stages": [
                {
                    "stage": "test",
                    "command": "cargo test --workspace",
                    "required": true,
                    "timeout_seconds": 120
                }
            ]
        }
    }))
}

pub(in crate::workspace_outbox_worker::tests) fn plan() -> WorkspacePlanRecord {
    WorkspacePlanRecord {
        id: "plan-test".to_string(),
        workspace_id: "workspace-test".to_string(),
        goal_id: "root-task".to_string(),
        status: "active".to_string(),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
    }
}

pub(in crate::workspace_outbox_worker::tests) fn plan_node() -> WorkspacePlanNodeRecord {
    WorkspacePlanNodeRecord {
        id: "node-test".to_string(),
        plan_id: "plan-test".to_string(),
        parent_id: None,
        kind: "task".to_string(),
        title: "Build feature".to_string(),
        description: String::new(),
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
        execution: "idle".to_string(),
        progress_json: json!({}),
        assignee_agent_id: Some("agent-worker".to_string()),
        current_attempt_id: None,
        workspace_task_id: Some("task-test".to_string()),
        metadata_json: json!({"terminal_attempt_retry_reason": "worker_crashed"}),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
        completed_at: None,
    }
}

pub(in crate::workspace_outbox_worker::tests) fn task_session_attempt(
    id: &str,
    status: &str,
    conversation_id: Option<&str>,
) -> WorkspaceTaskSessionAttemptRecord {
    WorkspaceTaskSessionAttemptRecord {
        id: id.to_string(),
        workspace_task_id: "task-test".to_string(),
        root_goal_task_id: "root-task".to_string(),
        workspace_id: "workspace-test".to_string(),
        attempt_number: 1,
        status: status.to_string(),
        conversation_id: conversation_id.map(ToOwned::to_owned),
        worker_agent_id: Some("agent-worker".to_string()),
        leader_agent_id: None,
        candidate_summary: None,
        candidate_artifacts_json: Vec::new(),
        candidate_verifications_json: Vec::new(),
        leader_feedback: None,
        adjudication_reason: None,
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: Some(Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap()),
        completed_at: None,
    }
}
