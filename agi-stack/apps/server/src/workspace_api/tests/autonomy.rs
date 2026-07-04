use super::*;

#[tokio::test]
async fn dev_service_autonomy_tick_queues_existing_root_plan_once() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = canonical_workspace();
    let now = "2026-01-02T03:04:05Z".parse().unwrap();
    {
        let mut state = service.state.lock().expect("workspace dev state");
        state
            .workspaces
            .insert(workspace.id.clone(), workspace.clone());
        state.tasks.insert(
            "root-autonomy".to_string(),
            WorkspaceTaskRecord {
                id: "root-autonomy".to_string(),
                workspace_id: workspace.id.clone(),
                title: "Deliver autonomy root".to_string(),
                description: Some("Drive the durable plan forward".to_string()),
                created_by: "user-1".to_string(),
                assignee_user_id: None,
                assignee_agent_id: None,
                status: "todo".to_string(),
                priority: 1,
                estimated_effort: None,
                blocker_reason: None,
                metadata_json: json!({"task_role": "goal_root"}),
                created_at: now,
                updated_at: None,
                completed_at: None,
                archived_at: None,
            },
        );
        state.tasks.insert(
            "child-autonomy".to_string(),
            WorkspaceTaskRecord {
                id: "child-autonomy".to_string(),
                workspace_id: workspace.id.clone(),
                title: "Implement child".to_string(),
                description: None,
                created_by: "user-1".to_string(),
                assignee_user_id: None,
                assignee_agent_id: Some("agent-1".to_string()),
                status: "todo".to_string(),
                priority: 1,
                estimated_effort: None,
                blocker_reason: None,
                metadata_json: json!({
                    "task_role": "execution_task",
                    "root_goal_task_id": "root-autonomy",
                    "workspace_plan_id": "plan-autonomy",
                    "workspace_plan_node_id": "node-autonomy"
                }),
                created_at: now,
                updated_at: None,
                completed_at: None,
                archived_at: None,
            },
        );
        state.plans.insert(
            "plan-autonomy".to_string(),
            WorkspacePlanRecord {
                id: "plan-autonomy".to_string(),
                workspace_id: workspace.id.clone(),
                goal_id: "goal-autonomy".to_string(),
                status: "active".to_string(),
                created_at: now,
                updated_at: None,
            },
        );
        state.plan_nodes.insert(
            "goal-autonomy".to_string(),
            WorkspacePlanNodeRecord {
                id: "goal-autonomy".to_string(),
                plan_id: "plan-autonomy".to_string(),
                parent_id: None,
                kind: "goal".to_string(),
                title: "Deliver autonomy root".to_string(),
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
                priority: 0,
                intent: "todo".to_string(),
                execution: "idle".to_string(),
                progress_json: json!({}),
                assignee_agent_id: None,
                current_attempt_id: None,
                workspace_task_id: Some("root-autonomy".to_string()),
                metadata_json: json!({"root_goal_task_id": "root-autonomy"}),
                created_at: now,
                updated_at: None,
                completed_at: None,
            },
        );
    }

    let first = service
        .trigger_autonomy_tick(
            "user-1",
            &workspace.id,
            AutonomyTickRequest { force: false },
        )
        .await
        .unwrap();
    assert_eq!(
        first,
        AutonomyTickView::new(
            false,
            Some("root-autonomy".to_string()),
            "durable_plan_started"
        )
    );

    {
        let state = service.state.lock().expect("workspace dev state");
        let queued = state
            .plan_outbox
            .iter()
            .filter(|item| item.plan_id.as_deref() == Some("plan-autonomy"))
            .collect::<Vec<_>>();
        assert_eq!(queued.len(), 1);
        let outbox = queued[0];
        assert_eq!(outbox.event_type, SUPERVISOR_TICK_EVENT);
        assert_eq!(outbox.status, "pending");
        assert_eq!(outbox.payload_json["workspace_id"], workspace.id);
        assert_eq!(outbox.payload_json["root_task_id"], "root-autonomy");
        assert_eq!(outbox.payload_json["actor_user_id"], "user-1");
        assert_eq!(
            outbox.payload_json["leader_agent_id"],
            WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        );
        assert_eq!(outbox.metadata_json["source"], "workspace.autonomy_tick");
        assert_eq!(outbox.metadata_json["resume_existing_root_plan"], true);
    }

    let second = service
        .trigger_autonomy_tick(
            "user-1",
            &workspace.id,
            AutonomyTickRequest { force: false },
        )
        .await
        .unwrap();
    assert_eq!(
        second,
        AutonomyTickView::new(
            false,
            Some("root-autonomy".to_string()),
            "durable_plan_active"
        )
    );
    let state = service.state.lock().expect("workspace dev state");
    assert_eq!(
        state
            .plan_outbox
            .iter()
            .filter(|item| item.plan_id.as_deref() == Some("plan-autonomy"))
            .count(),
        1
    );
}

#[tokio::test]
async fn dev_service_autonomy_tick_reports_open_root_without_pending_progress() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = canonical_workspace();
    let now = "2026-01-02T03:04:05Z".parse().unwrap();
    {
        let mut state = service.state.lock().expect("workspace dev state");
        state
            .workspaces
            .insert(workspace.id.clone(), workspace.clone());
        state.tasks.insert(
            "root-autonomy".to_string(),
            WorkspaceTaskRecord {
                id: "root-autonomy".to_string(),
                workspace_id: workspace.id.clone(),
                title: "Deliver autonomy root".to_string(),
                description: None,
                created_by: "user-1".to_string(),
                assignee_user_id: None,
                assignee_agent_id: None,
                status: "todo".to_string(),
                priority: 1,
                estimated_effort: None,
                blocker_reason: None,
                metadata_json: json!({"task_role": "goal_root"}),
                created_at: now,
                updated_at: None,
                completed_at: None,
                archived_at: None,
            },
        );
        state.tasks.insert(
            "child-in-progress".to_string(),
            WorkspaceTaskRecord {
                id: "child-in-progress".to_string(),
                workspace_id: workspace.id.clone(),
                title: "Already running child".to_string(),
                description: None,
                created_by: "user-1".to_string(),
                assignee_user_id: None,
                assignee_agent_id: Some("agent-1".to_string()),
                status: "in_progress".to_string(),
                priority: 1,
                estimated_effort: None,
                blocker_reason: None,
                metadata_json: json!({
                    "task_role": "execution_task",
                    "root_goal_task_id": "root-autonomy"
                }),
                created_at: now,
                updated_at: None,
                completed_at: None,
                archived_at: None,
            },
        );
    }

    let result = service
        .trigger_autonomy_tick(
            "user-1",
            &workspace.id,
            AutonomyTickRequest { force: false },
        )
        .await
        .unwrap();

    assert_eq!(
        result,
        AutonomyTickView::new(false, None, "no_root_needs_progress")
    );
    let state = service.state.lock().expect("workspace dev state");
    assert!(state.plan_outbox.is_empty());
}

#[tokio::test]
async fn dev_service_autonomy_tick_reports_missing_workspace_as_404() {
    let service = DevWorkspaceService::new("user-1");
    let err = service
        .trigger_autonomy_tick("user-1", "missing", AutonomyTickRequest::default())
        .await
        .unwrap_err();

    assert_eq!(err.status, StatusCode::NOT_FOUND);
    assert_eq!(err.detail, "Workspace not found");
}
