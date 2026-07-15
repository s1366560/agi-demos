use super::*;

#[tokio::test]
async fn dev_service_authorizes_workspace_event_subscription_by_workspace_scope() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = service
        .create_workspace(
            "user-1",
            "tenant-1",
            "project-1",
            WorkspaceCreatePayload {
                name: "Core Workspace".to_string(),
                description: None,
                metadata: json!({}),
                use_case: Some("programming".to_string()),
                collaboration_mode: Some("multi_agent_shared".to_string()),
                autonomy_profile: None,
                sandbox_code_root: None,
            },
        )
        .await
        .unwrap();

    let resolved_tenant = service
        .authorize_workspace_event_subscription("user-1", &workspace.id, "project-1", None)
        .await
        .unwrap();
    assert_eq!(resolved_tenant, "tenant-1");

    let resolved_tenant = service
        .authorize_workspace_event_subscription(
            "user-1",
            &workspace.id,
            "project-1",
            Some("tenant-1"),
        )
        .await
        .unwrap();
    assert_eq!(resolved_tenant, "tenant-1");

    let wrong_project = service
        .authorize_workspace_event_subscription("user-1", &workspace.id, "other-project", None)
        .await
        .unwrap_err();
    assert_eq!(wrong_project.status, StatusCode::NOT_FOUND);

    let wrong_tenant = service
        .authorize_workspace_event_subscription(
            "user-1",
            &workspace.id,
            "project-1",
            Some("other-tenant"),
        )
        .await
        .unwrap_err();
    assert_eq!(wrong_tenant.status, StatusCode::NOT_FOUND);

    let wrong_user = service
        .authorize_workspace_event_subscription("other-user", &workspace.id, "project-1", None)
        .await
        .unwrap_err();
    assert_eq!(wrong_user.status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn dev_service_lists_authoritative_workspace_roster_with_scope() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = service
        .create_workspace(
            "user-1",
            "tenant-1",
            "project-1",
            WorkspaceCreatePayload {
                name: "Roster Workspace".to_string(),
                description: None,
                metadata: json!({"member_count": 99, "active_agent_count": 99}),
                use_case: Some("programming".to_string()),
                collaboration_mode: Some("multi_agent_shared".to_string()),
                autonomy_profile: None,
                sandbox_code_root: None,
            },
        )
        .await
        .unwrap();

    let members = service
        .list_workspace_members(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            LimitOffset::default(),
        )
        .await
        .unwrap();
    assert_eq!(members.len(), 1);
    assert_eq!(members[0].user_id, "user-1");
    assert_eq!(members[0].role, "owner");
    assert_eq!(members[0].invited_by.as_deref(), Some("user-1"));

    let agents = service
        .list_workspace_agents(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            WorkspaceAgentListQuery::default(),
        )
        .await
        .unwrap();
    assert!(agents.is_empty());

    let wrong_scope = service
        .list_workspace_members(
            "user-1",
            "tenant-1",
            "other-project",
            &workspace.id,
            LimitOffset::default(),
        )
        .await
        .unwrap_err();
    assert_eq!(wrong_scope.status, StatusCode::NOT_FOUND);

    let wrong_user = service
        .list_workspace_members(
            "user-2",
            "tenant-1",
            "project-1",
            &workspace.id,
            LimitOffset::default(),
        )
        .await
        .unwrap_err();
    assert_eq!(wrong_user.status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn dev_service_filters_workspace_agents_before_pagination() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = service
        .create_workspace(
            "user-1",
            "tenant-1",
            "project-1",
            WorkspaceCreatePayload {
                name: "Agent Roster".to_string(),
                description: None,
                metadata: json!({}),
                use_case: None,
                collaboration_mode: None,
                autonomy_profile: None,
                sandbox_code_root: None,
            },
        )
        .await
        .unwrap();
    let created_at = "2026-01-02T03:04:05Z".parse().unwrap();
    let make_agent = |id: &str, is_active: bool| WorkspaceAgentDetailRecord {
        id: id.to_string(),
        workspace_id: workspace.id.clone(),
        agent_id: format!("agent-{id}"),
        display_name: Some(format!("Agent {id}")),
        description: None,
        config_json: json!({}),
        is_active,
        hex_q: None,
        hex_r: None,
        theme_color: None,
        label: None,
        status: Some("idle".to_string()),
        created_at,
        updated_at: None,
    };
    {
        let mut state = service.lock_state().unwrap();
        state.workspace_agent_details.push(make_agent("b", false));
        state.workspace_agent_details.push(make_agent("a", true));
        state.workspace_agent_details.push(make_agent("c", true));
    }

    let all = service
        .list_workspace_agents(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            WorkspaceAgentListQuery::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        all.iter()
            .map(|agent| agent.id.as_str())
            .collect::<Vec<_>>(),
        vec!["a", "b", "c"]
    );

    let active_page = service
        .list_workspace_agents(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            WorkspaceAgentListQuery {
                active_only: true,
                limit: Some(1),
                offset: Some(1),
            },
        )
        .await
        .unwrap();
    assert_eq!(active_page.len(), 1);
    assert_eq!(active_page[0].id, "c");
}

#[tokio::test]
async fn dev_service_rejects_invalid_workspace_roster_pagination() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = service
        .create_workspace(
            "user-1",
            "tenant-1",
            "project-1",
            WorkspaceCreatePayload {
                name: "Roster Pagination".to_string(),
                description: None,
                metadata: json!({}),
                use_case: None,
                collaboration_mode: None,
                autonomy_profile: None,
                sandbox_code_root: None,
            },
        )
        .await
        .unwrap();

    for query in [
        LimitOffset {
            limit: Some(0),
            offset: None,
        },
        LimitOffset {
            limit: Some(501),
            offset: None,
        },
        LimitOffset {
            limit: None,
            offset: Some(-1),
        },
    ] {
        let error = service
            .list_workspace_members("user-1", "tenant-1", "project-1", &workspace.id, query)
            .await
            .unwrap_err();
        assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    let error = service
        .list_workspace_agents(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            WorkspaceAgentListQuery {
                active_only: true,
                limit: Some(0),
                offset: None,
            },
        )
        .await
        .unwrap_err();
    assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn dev_service_roundtrips_workspace_task_topology_blackboard() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = service
        .create_workspace(
            "user-1",
            "tenant-1",
            "project-1",
            WorkspaceCreatePayload {
                name: "Core Workspace".to_string(),
                description: None,
                metadata: json!({}),
                use_case: Some("programming".to_string()),
                collaboration_mode: Some("multi_agent_shared".to_string()),
                autonomy_profile: None,
                sandbox_code_root: None,
            },
        )
        .await
        .unwrap();
    let task = service
        .create_task(
            "user-1",
            &workspace.id,
            WorkspaceTaskCreatePayload {
                title: "Implement P6".to_string(),
                description: None,
                assignee_user_id: None,
                metadata: json!({}),
                priority: Some("P1".to_string()),
                estimated_effort: None,
                blocker_reason: None,
                preferred_language: None,
            },
        )
        .await
        .unwrap();
    let node = service
        .create_node(
            "user-1",
            &workspace.id,
            TopologyNodeCreatePayload {
                node_type: "task".to_string(),
                ref_id: Some(task.id.clone()),
                title: Some(task.title.clone()),
                position_x: None,
                position_y: None,
                hex_q: Some(0),
                hex_r: Some(0),
                status: None,
                tags: vec![],
                data: json!({}),
            },
        )
        .await
        .unwrap();
    let node2 = service
        .create_node(
            "user-1",
            &workspace.id,
            TopologyNodeCreatePayload {
                node_type: "note".to_string(),
                ref_id: None,
                title: Some("Context".to_string()),
                position_x: None,
                position_y: None,
                hex_q: Some(1),
                hex_r: Some(0),
                status: None,
                tags: vec![],
                data: json!({}),
            },
        )
        .await
        .unwrap();
    let edge = service
        .create_edge(
            "user-1",
            &workspace.id,
            TopologyEdgeCreatePayload {
                source_node_id: node.id,
                target_node_id: node2.id,
                label: Some("relates".to_string()),
                direction: None,
                auto_created: false,
                data: json!({}),
            },
        )
        .await
        .unwrap();
    assert_eq!(edge.source_hex_q, Some(0));
    let post = service
        .create_post(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            BlackboardPostCreatePayload {
                title: "Status".to_string(),
                content: "P6 started".to_string(),
                status: "open".to_string(),
                is_pinned: true,
                metadata: json!({}),
            },
        )
        .await
        .unwrap();
    let reply = service
        .create_reply(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            &post.id,
            BlackboardReplyCreatePayload {
                content: "ack".to_string(),
                metadata: json!({}),
            },
        )
        .await
        .unwrap();
    assert_eq!(reply.post_id, post.id);
    let dir = service
        .create_directory(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            MkdirPayload {
                parent_path: "/".to_string(),
                name: "docs".to_string(),
            },
        )
        .await
        .unwrap();
    assert!(dir.is_directory);
    let file = service
        .upload_file(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            BlackboardUpload {
                parent_path: "/docs/".to_string(),
                filename: "status.txt".to_string(),
                content_type: Some("text/plain".to_string()),
                bytes: b"P6 file ok".to_vec(),
            },
        )
        .await
        .unwrap();
    assert_eq!(file.file_size, 10);
    let listed = service
        .list_files(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            BlackboardFileListQuery {
                parent_path: Some("/docs/".to_string()),
            },
        )
        .await
        .unwrap();
    assert_eq!(listed.items.len(), 1);
    let download = service
        .download_file("user-1", "tenant-1", "project-1", &workspace.id, &file.id)
        .await
        .unwrap();
    assert_eq!(download.bytes, b"P6 file ok");
    let renamed = service
        .patch_file(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            &file.id,
            RenameOrMoveFilePayload {
                name: Some("renamed.txt".to_string()),
                parent_path: None,
            },
        )
        .await
        .unwrap();
    assert_eq!(renamed.name, "renamed.txt");
    let copied = service
        .copy_file(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            &renamed.id,
            CopyFilePayload {
                target_parent_path: "/".to_string(),
                name: Some("copy.txt".to_string()),
            },
        )
        .await
        .unwrap();
    assert_eq!(copied.parent_path, "/");
    let deleted = service
        .delete_file(
            "user-1",
            "tenant-1",
            "project-1",
            &workspace.id,
            &renamed.id,
            DeleteFileQuery { recursive: false },
        )
        .await
        .unwrap();
    assert!(deleted.deleted);
    {
        let mut state = service.state.lock().expect("workspace dev state");
        let now = "2026-01-02T03:04:05Z".parse().unwrap();
        state.plans.insert(
            "plan-dev".to_string(),
            WorkspacePlanRecord {
                id: "plan-dev".to_string(),
                workspace_id: workspace.id.clone(),
                goal_id: "plan-node-dev".to_string(),
                status: "active".to_string(),
                created_at: now,
                updated_at: None,
            },
        );
        state.plan_nodes.insert(
            "plan-node-dev".to_string(),
            WorkspacePlanNodeRecord {
                id: "plan-node-dev".to_string(),
                plan_id: "plan-dev".to_string(),
                parent_id: None,
                kind: "task".to_string(),
                title: "Plan state".to_string(),
                description: "Durable P6 snapshot".to_string(),
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
                intent: "todo".to_string(),
                execution: "idle".to_string(),
                progress_json: json!({}),
                assignee_agent_id: None,
                current_attempt_id: None,
                workspace_task_id: Some(task.id.clone()),
                metadata_json: json!({"iteration_phase": "plan", "pipeline_required": true}),
                created_at: now,
                updated_at: None,
                completed_at: None,
            },
        );
        state
            .plan_blackboard
            .push(WorkspacePlanBlackboardEntryRecord {
                id: "plan-bb-dev".to_string(),
                plan_id: "plan-dev".to_string(),
                key: "plan.summary".to_string(),
                value_json: Some(json!({"ok": true})),
                published_by: "user-1".to_string(),
                version: 1,
                schema_ref: None,
                metadata_json: json!({}),
                created_at: now,
            });
        state.plan_outbox.push(WorkspacePlanOutboxRecord {
            id: "outbox-dev".to_string(),
            plan_id: Some("plan-dev".to_string()),
            workspace_id: workspace.id.clone(),
            event_type: "supervisor_tick".to_string(),
            payload_json: json!({"node_id": "plan-node-dev"}),
            status: "failed".to_string(),
            attempt_count: 1,
            max_attempts: 5,
            lease_owner: None,
            lease_expires_at: None,
            last_error: Some("provider unavailable".to_string()),
            next_attempt_at: None,
            processed_at: None,
            metadata_json: json!({"source": "workspace_plan_api"}),
            created_at: now,
            updated_at: None,
        });
    }
    let snapshot = service
        .get_plan_snapshot(
            "user-1",
            &workspace.id,
            WorkspacePlanSnapshotQuery::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        snapshot.plan.as_ref().map(|plan| plan.id.as_str()),
        Some("plan-dev")
    );
    assert_eq!(snapshot.blackboard.len(), 1);
    assert_eq!(snapshot.outbox.len(), 1);
    assert!(snapshot.outbox[0].actions["retry_outbox"].enabled);
    let retried = service
        .retry_plan_outbox(
            "user-1",
            &workspace.id,
            "outbox-dev",
            WorkspacePlanActionRequest {
                reason: Some("operator retry".to_string()),
                evidence_refs: Vec::new(),
            },
        )
        .await
        .unwrap();
    assert_eq!(retried.plan_id, "plan-dev");
    let retried_snapshot = service
        .get_plan_snapshot(
            "user-1",
            &workspace.id,
            WorkspacePlanSnapshotQuery::default(),
        )
        .await
        .unwrap();
    let retried_outbox = retried_snapshot
        .outbox
        .iter()
        .find(|item| item.id == "outbox-dev")
        .expect("retried outbox in snapshot");
    assert_eq!(retried_outbox.status, "pending");
    assert!(retried_outbox.last_error.is_none());
    assert_eq!(
        retried_outbox.metadata["operator_retry"]["previous_status"],
        "failed"
    );
    assert!(retried_snapshot
        .events
        .iter()
        .any(|event| event.event_type == "operator_retry_outbox"
            && event.payload["outbox_id"] == "outbox-dev"));
    let pipeline = service
        .request_delivery_pipeline_run(
            "user-1",
            &workspace.id,
            WorkspacePlanPipelineRunRequest {
                reason: Some("run CI".to_string()),
                evidence_refs: Vec::new(),
                node_id: None,
            },
        )
        .await
        .unwrap();
    assert_eq!(pipeline.message, "Harness-native pipeline run requested.");
    assert_eq!(pipeline.node_id.as_deref(), Some("plan-node-dev"));
    let regenerated = service
        .request_delivery_contract_regeneration(
            "user-1",
            &workspace.id,
            WorkspacePlanActionRequest {
                reason: Some("refresh contract".to_string()),
                evidence_refs: Vec::new(),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        regenerated.message,
        "Delivery contract regeneration requested."
    );
    let delivery_snapshot = service
        .get_plan_snapshot(
            "user-1",
            &workspace.id,
            WorkspacePlanSnapshotQuery::default(),
        )
        .await
        .unwrap();
    assert!(delivery_snapshot.outbox.iter().any(|item| {
        item.event_type == PIPELINE_RUN_REQUESTED_EVENT
            && item.payload["node_id"] == "plan-node-dev"
            && item.payload["reason"] == "run CI"
    }));
    assert!(delivery_snapshot
        .outbox
        .iter()
        .any(|item| item.event_type == SUPERVISOR_TICK_EVENT
            && item.metadata["source"] == "workspace_plan.operator_delivery_regenerate_contract"));
    assert!(delivery_snapshot.events.iter().any(|event| {
        event.event_type == "delivery_contract_regeneration_requested"
            && event.payload["requested_by"] == "user-1"
    }));
    {
        let state = service.state.lock().expect("workspace dev state");
        let delivery = &state.workspaces[&workspace.id].metadata_json["delivery_cicd"];
        assert_eq!(delivery["contract_source"], "agent_regeneration_requested");
        assert_eq!(delivery["regenerate_reason"], "refresh contract");
    }
    let replan = service
        .request_plan_node_replan(
            "user-1",
            &workspace.id,
            "plan-node-dev",
            WorkspacePlanActionRequest {
                reason: Some("needs another attempt".to_string()),
                evidence_refs: Vec::new(),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        replan.message,
        "Plan node sent back for supervisor recovery."
    );
    let replan_snapshot = service
        .get_plan_snapshot(
            "user-1",
            &workspace.id,
            WorkspacePlanSnapshotQuery::default(),
        )
        .await
        .unwrap();
    let replan_node = &replan_snapshot.plan.as_ref().unwrap().nodes[0];
    assert_eq!(
        replan_node.metadata["operator_action"]["action"],
        "operator_replan_requested"
    );
    assert!(replan_node.current_attempt_id.is_none());
    assert!(replan_snapshot.outbox.iter().any(|item| {
        item.event_type == SUPERVISOR_TICK_EVENT
            && item.payload["operator_action"] == "operator_replan_requested"
            && item.metadata["source"] == "operator_action"
    }));
    assert!(replan_snapshot.events.iter().any(|event| {
        event.event_type == "operator_replan_requested"
            && event.payload["reason"] == "needs another attempt"
    }));
    {
        let mut state = service.state.lock().expect("workspace dev state");
        state.plans.get_mut("plan-dev").unwrap().status = "suspended".to_string();
        let node = state.plan_nodes.get_mut("plan-node-dev").unwrap();
        node.intent = "blocked".to_string();
        node.execution = "running".to_string();
        node.assignee_agent_id = Some("agent-1".to_string());
        node.current_attempt_id = Some("attempt-blocked".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": "/tmp/work",
            "branch_name": "feature/p6",
            "base_ref": "main",
            "commit_ref": "abc123"
        }));
        node.metadata_json = json!({
            "retry_count": 2,
            "candidate_artifacts": ["old"],
            "last_verification_passed": false
        });
    }
    let reopened = service
        .reopen_plan_node(
            "user-1",
            &workspace.id,
            "plan-node-dev",
            WorkspacePlanActionRequest {
                reason: Some("human unblocked".to_string()),
                evidence_refs: Vec::new(),
            },
        )
        .await
        .unwrap();
    assert_eq!(reopened.message, "Blocked plan node reopened.");
    {
        let state = service.state.lock().expect("workspace dev state");
        let plan = state.plans.get("plan-dev").unwrap();
        let node = state.plan_nodes.get("plan-node-dev").unwrap();
        assert_eq!(plan.status, "active");
        assert_eq!(node.intent, "todo");
        assert_eq!(node.execution, "idle");
        assert!(node.assignee_agent_id.is_none());
        assert!(node.current_attempt_id.is_none());
        assert!(node.metadata_json.get("retry_count").is_none());
        assert!(node.metadata_json.get("candidate_artifacts").is_none());
        assert_eq!(
            node.metadata_json["operator_action"]["action"],
            "operator_node_reopened"
        );
        assert_eq!(
            node.feature_checkpoint_json.as_ref().unwrap()["base_ref"],
            "HEAD"
        );
        assert!(state.plan_events.iter().any(|event| {
            event.event_type == "operator_node_reopened"
                && event.attempt_id.as_deref() == Some("attempt-blocked")
        }));
    }
    {
        let mut state = service.state.lock().expect("workspace dev state");
        let node = state.plan_nodes.get_mut("plan-node-dev").unwrap();
        node.intent = "blocked".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-review".to_string());
        node.metadata_json = json!({
            "retry_count": 1,
            "last_verification_passed": false,
            "verification_evidence_refs": ["ci:previous"]
        });
        let task = state.tasks.get_mut(&task.id).unwrap();
        task.status = "blocked".to_string();
        task.completed_at = None;
    }
    let accepted = service
        .accept_plan_node_review(
            "user-1",
            &workspace.id,
            "plan-node-dev",
            WorkspacePlanActionRequest {
                reason: Some("operator accepts evidence".to_string()),
                evidence_refs: vec![
                    "ci:new".to_string(),
                    "ci:previous".to_string(),
                    " ".to_string(),
                ],
            },
        )
        .await
        .unwrap();
    assert_eq!(accepted.message, "Plan node accepted after human review.");
    {
        let state = service.state.lock().expect("workspace dev state");
        let node = state.plan_nodes.get("plan-node-dev").unwrap();
        let task = state.tasks.get(&task.id).unwrap();
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert!(node.current_attempt_id.is_none());
        assert!(node.completed_at.is_some());
        assert_eq!(
            node.metadata_json["human_review_acceptance"]["reason"],
            "operator accepts evidence"
        );
        assert_eq!(
            node.metadata_json["verification_evidence_refs"],
            json!(["ci:previous", "ci:new"])
        );
        assert!(node.metadata_json.get("retry_count").is_none());
        assert_eq!(task.status, "done");
        assert_eq!(task.metadata_json["durable_plan_verdict"], "accepted");
        assert_eq!(
            task.metadata_json["evidence_refs"],
            json!(["ci:previous", "ci:new"])
        );
        assert!(state.plan_events.iter().any(|event| {
            event.event_type == "operator_review_accepted"
                && event.attempt_id.as_deref() == Some("attempt-review")
                && event.payload_json["evidence_refs"] == json!(["ci:new", "ci:previous"])
        }));
    }
    {
        let mut state = service.state.lock().expect("workspace dev state");
        let now = "2026-01-02T03:05:05Z".parse().unwrap();
        state.plan_nodes.insert(
            "plan-node-stale".to_string(),
            WorkspacePlanNodeRecord {
                id: "plan-node-stale".to_string(),
                plan_id: "plan-dev".to_string(),
                parent_id: Some("plan-node-dev".to_string()),
                kind: "task".to_string(),
                title: "Recover stale node".to_string(),
                description: "Queue recovery without a linked attempt".to_string(),
                depends_on_json: Vec::new(),
                inputs_schema_json: json!({}),
                outputs_schema_json: json!({}),
                acceptance_criteria_json: Vec::new(),
                feature_checkpoint_json: None,
                handoff_package_json: None,
                recommended_capabilities_json: Vec::new(),
                preferred_agent_id: None,
                estimated_effort_json: json!({}),
                priority: 2,
                intent: "blocked".to_string(),
                execution: "idle".to_string(),
                progress_json: json!({}),
                assignee_agent_id: Some("agent-1".to_string()),
                current_attempt_id: None,
                workspace_task_id: Some(task.id.clone()),
                metadata_json: json!({
                    "terminal_attempt_retry_reason": "worker did not report terminal state",
                    "last_verification_passed": false
                }),
                created_at: now,
                updated_at: None,
                completed_at: None,
            },
        );
    }
    let recovered = service
        .recover_stale_attempts(
            "user-1",
            &workspace.id,
            WorkspacePlanActionRequest {
                reason: Some("recover stale node".to_string()),
                evidence_refs: Vec::new(),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        recovered.message,
        "Workspace plan stale attempt recovery queued."
    );
    let stale_snapshot = service
        .get_plan_snapshot(
            "user-1",
            &workspace.id,
            WorkspacePlanSnapshotQuery::default(),
        )
        .await
        .unwrap();
    assert!(stale_snapshot.outbox.iter().any(|item| {
        item.event_type == SUPERVISOR_TICK_EVENT
            && item.payload["retry_node_id"] == "plan-node-stale"
            && item.payload["retry_attempt_id"].is_null()
            && item.payload["retry_reason"] == "stale_plan_node_no_terminal_worker_report"
            && item.metadata["source"] == "workspace_plan.snapshot_stale_node_recovery"
    }));
    assert!(stale_snapshot.events.iter().any(|event| {
        event.event_type == "auto_stale_node_recovery_queued"
            && event.node_id.as_deref() == Some("plan-node-stale")
            && event.attempt_id.is_none()
            && event.payload["reason"] == "stale_plan_node_without_recoverable_attempt"
            && event.payload["execution"] == "idle"
    }));
    let duplicate = service
        .recover_stale_attempts(
            "user-1",
            &workspace.id,
            WorkspacePlanActionRequest {
                reason: Some("recover stale node again".to_string()),
                evidence_refs: Vec::new(),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        duplicate.message,
        "No stale workspace plan attempts needed recovery."
    );
    let done = service
        .transition_task(
            "user-1",
            &workspace.id,
            &task.id,
            TaskTransitionAction::Complete,
        )
        .await
        .unwrap();
    assert_eq!(done.status, "done");
    assert!(done.completed_at.is_some());
}
