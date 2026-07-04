use super::*;

#[test]
fn workspace_response_matches_golden() {
    assert_golden(
        &WorkspaceView::from(canonical_workspace()),
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_response.json"
        ))
        .unwrap(),
    );
}

#[test]
fn workspace_task_response_matches_golden() {
    let task = WorkspaceTaskRecord {
        id: "task-1".to_string(),
        workspace_id: "ws-1".to_string(),
        title: "Port P6".to_string(),
        description: Some("Move core workspace ledger".to_string()),
        created_by: "user-1".to_string(),
        assignee_user_id: Some("user-2".to_string()),
        assignee_agent_id: None,
        status: "todo".to_string(),
        priority: 2,
        estimated_effort: Some("M".to_string()),
        blocker_reason: None,
        metadata_json: json!({
            "workspace_agent_binding_id": "wa-1",
            "pending_leader_adjudication": true,
            "last_worker_report_artifacts": ["artifact-1"]
        }),
        created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
        updated_at: None,
        completed_at: None,
        archived_at: None,
    };
    assert_golden(
        &WorkspaceTaskView::from(task),
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_task_response.json"
        ))
        .unwrap(),
    );
}

#[test]
fn workspace_message_responses_match_goldens() {
    let message = WorkspaceMessageRecord {
        id: "msg-1".to_string(),
        workspace_id: "ws-1".to_string(),
        sender_id: "user-1".to_string(),
        sender_type: "human".to_string(),
        content: "Ship P6 chat".to_string(),
        mentions_json: vec!["user-2".to_string(), "agent-1".to_string()],
        parent_message_id: None,
        metadata_json: json!({"sender_name": "Alice"}),
        created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
    };
    let view = MessageView::from(message);
    assert_golden(
        &view,
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_message_response.json"
        ))
        .unwrap(),
    );
    assert_golden(
        &MessageListView { items: vec![view] },
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_message_list.json"
        ))
        .unwrap(),
    );
}

#[test]
fn workspace_agent_mention_outbox_matches_golden() {
    let message = MessageView {
        id: "msg-1".to_string(),
        workspace_id: "ws-mention".to_string(),
        sender_id: "user-1".to_string(),
        sender_type: "human".to_string(),
        content: "Ship the workspace runtime bridge".to_string(),
        mentions: vec!["user-1".to_string(), "agent-1".to_string()],
        parent_message_id: Some("msg-parent".to_string()),
        metadata: json!({
            "sender_name": "Alice",
            "conversation_scope": "objective:root-1"
        }),
        created_at: "2026-01-02T03:04:05.000Z".to_string(),
    };
    let agents = vec![WorkspaceAgentRecord {
        id: "wa-1".to_string(),
        workspace_id: "ws-mention".to_string(),
        agent_id: "agent-1".to_string(),
        display_name: Some("Builder".to_string()),
    }];
    let records = workspace_agent_mention_outbox_records(WorkspaceAgentMentionOutboxInput {
        tenant_id: "tenant-1",
        project_id: "project-1",
        workspace_id: "ws-mention",
        sender_user_id: "user-1",
        sender_name: "Alice",
        message: &message,
        agents: &agents,
        now: "2026-01-02T03:04:06Z".parse().unwrap(),
    });
    assert_eq!(records.len(), 1);
    let record = &records[0];
    assert_golden(
        &json!({
            "event_type": &record.event_type,
            "status": &record.status,
            "payload": &record.payload_json,
            "metadata": &record.metadata_json,
        }),
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_agent_mention_outbox.json"
        ))
        .unwrap(),
    );
}

#[test]
fn topology_responses_match_goldens() {
    let node = TopologyNodeRecord {
        id: "node-1".to_string(),
        workspace_id: "ws-1".to_string(),
        node_type: "task".to_string(),
        ref_id: Some("task-1".to_string()),
        title: "Port P6".to_string(),
        position_x: 1.5,
        position_y: -2.0,
        hex_q: Some(1),
        hex_r: Some(-1),
        status: "active".to_string(),
        tags_json: vec!["p6".to_string()],
        data_json: json!({"lane": "foundation"}),
        created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
        updated_at: None,
    };
    let edge = TopologyEdgeRecord {
        id: "edge-1".to_string(),
        workspace_id: "ws-1".to_string(),
        source_node_id: "node-1".to_string(),
        target_node_id: "node-2".to_string(),
        label: Some("depends_on".to_string()),
        source_hex_q: Some(1),
        source_hex_r: Some(-1),
        target_hex_q: Some(2),
        target_hex_r: Some(-1),
        direction: Some("forward".to_string()),
        auto_created: false,
        data_json: json!({}),
        created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
        updated_at: None,
    };
    assert_golden(
        &TopologyNodeView::from(node),
        serde_json::from_str(include_str!(
            "../../../tests/golden/topology_node_response.json"
        ))
        .unwrap(),
    );
    assert_golden(
        &TopologyEdgeView::from(edge),
        serde_json::from_str(include_str!(
            "../../../tests/golden/topology_edge_response.json"
        ))
        .unwrap(),
    );
}

#[test]
fn blackboard_responses_match_goldens() {
    let post = BlackboardPostRecord {
        id: "post-1".to_string(),
        workspace_id: "ws-1".to_string(),
        author_id: "user-1".to_string(),
        title: "Status".to_string(),
        content: "P6 started".to_string(),
        status: "open".to_string(),
        is_pinned: true,
        metadata_json: json!({"lane": "p6"}),
        created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
        updated_at: None,
    };
    let reply = BlackboardReplyRecord {
        id: "reply-1".to_string(),
        post_id: "post-1".to_string(),
        workspace_id: "ws-1".to_string(),
        author_id: "user-2".to_string(),
        content: "ack".to_string(),
        metadata_json: json!({}),
        created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
        updated_at: None,
    };
    let file = BlackboardFileRecord {
        id: "file-1".to_string(),
        workspace_id: "ws-1".to_string(),
        parent_path: "/docs/".to_string(),
        name: "status.txt".to_string(),
        is_directory: false,
        file_size: 11,
        content_type: "text/plain".to_string(),
        storage_key: "file-1/status.txt".to_string(),
        uploader_type: "user".to_string(),
        uploader_id: "user-1".to_string(),
        uploader_name: "Owner".to_string(),
        checksum_sha256: None,
        mime_type_detected: None,
        created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
    };
    assert_golden(
        &BlackboardPostListView {
            items: vec![BlackboardPostView::from(post)],
        },
        serde_json::from_str(include_str!(
            "../../../tests/golden/blackboard_post_list.json"
        ))
        .unwrap(),
    );
    assert_golden(
        &BlackboardReplyListView {
            items: vec![BlackboardReplyView::from(reply)],
        },
        serde_json::from_str(include_str!(
            "../../../tests/golden/blackboard_reply_list.json"
        ))
        .unwrap(),
    );
    assert_golden(
        &BlackboardFileListView {
            items: vec![BlackboardFileView::from(file)],
        },
        serde_json::from_str(include_str!(
            "../../../tests/golden/blackboard_file_list.json"
        ))
        .unwrap(),
    );
}

#[test]
fn workspace_plan_snapshot_matches_golden() {
    let created_at = "2026-01-02T03:04:05Z".parse().unwrap();
    let plan = WorkspacePlanRecord {
        id: "plan-1".to_string(),
        workspace_id: "ws-1".to_string(),
        goal_id: "node-1".to_string(),
        status: "active".to_string(),
        created_at,
        updated_at: None,
    };
    let node = WorkspacePlanNodeRecord {
        id: "node-1".to_string(),
        plan_id: "plan-1".to_string(),
        parent_id: None,
        kind: "task".to_string(),
        title: "Implement P6 plans".to_string(),
        description: "Port snapshot ledger".to_string(),
        depends_on_json: Vec::new(),
        inputs_schema_json: json!({}),
        outputs_schema_json: json!({}),
        acceptance_criteria_json: Vec::new(),
        feature_checkpoint_json: None,
        handoff_package_json: None,
        recommended_capabilities_json: Vec::new(),
        preferred_agent_id: None,
        estimated_effort_json: json!({"minutes": 30, "confidence": 0.7}),
        priority: 1,
        intent: "todo".to_string(),
        execution: "idle".to_string(),
        progress_json: json!({"percent": 0.0, "confidence": 0.8, "note": "queued"}),
        assignee_agent_id: None,
        current_attempt_id: None,
        workspace_task_id: None,
        metadata_json: json!({
            "iteration_phase": "plan",
            "evidence_refs": ["ci_pipeline:passed"],
            "changed_files": ["agi-stack/apps/server/src/workspace_api.rs"],
            "last_verification_summary": "golden locked"
        }),
        created_at,
        updated_at: None,
        completed_at: None,
    };
    let snapshot = build_plan_snapshot(
        "ws-1",
        vec![(plan, vec![node])],
        "plan-1",
        true,
        vec![WorkspacePlanBlackboardEntryRecord {
            id: "bb-1".to_string(),
            plan_id: "plan-1".to_string(),
            key: "research.summary".to_string(),
            value_json: Some(json!({"summary": "ready"})),
            published_by: "agent-1".to_string(),
            version: 2,
            schema_ref: Some("workspace.plan.summary.v1".to_string()),
            metadata_json: json!({"source": "planner"}),
            created_at,
        }],
        vec![WorkspacePlanOutboxRecord {
            id: "outbox-1".to_string(),
            plan_id: Some("plan-1".to_string()),
            workspace_id: "ws-1".to_string(),
            event_type: "supervisor_tick".to_string(),
            payload_json: json!({"node_id": "node-1"}),
            status: "failed".to_string(),
            attempt_count: 1,
            max_attempts: 5,
            lease_owner: None,
            lease_expires_at: None,
            last_error: Some("provider unavailable".to_string()),
            next_attempt_at: None,
            processed_at: None,
            metadata_json: json!({"source": "workspace_plan_api"}),
            created_at,
            updated_at: None,
        }],
        vec![WorkspacePlanEventRecord {
            id: "event-1".to_string(),
            plan_id: "plan-1".to_string(),
            workspace_id: "ws-1".to_string(),
            node_id: Some("node-1".to_string()),
            attempt_id: None,
            event_type: "workspace_plan_updated".to_string(),
            source: "system".to_string(),
            actor_id: Some("agent-1".to_string()),
            payload_json: json!({"status": "active"}),
            created_at,
        }],
    );
    assert_golden(
        &snapshot,
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_plan_snapshot.json"
        ))
        .unwrap(),
    );
    assert_golden(
        &WorkspacePlanActionResultView {
            ok: true,
            message: "Outbox job queued for retry.".to_string(),
            plan_id: "plan-1".to_string(),
            node_id: None,
            outbox_id: Some("outbox-1".to_string()),
        },
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_plan_action_result.json"
        ))
        .unwrap(),
    );
    let delivery_results = json!({
        "pipeline": serde_json::to_value(WorkspacePlanActionResultView {
            ok: true,
            message: "Harness-native pipeline run requested.".to_string(),
            plan_id: "plan-1".to_string(),
            node_id: Some("node-1".to_string()),
            outbox_id: Some("outbox-pipeline".to_string()),
        }).unwrap(),
        "regenerate_contract": serde_json::to_value(WorkspacePlanActionResultView {
            ok: true,
            message: "Delivery contract regeneration requested.".to_string(),
            plan_id: "plan-1".to_string(),
            node_id: None,
            outbox_id: Some("outbox-contract".to_string()),
        }).unwrap()
    });
    assert_golden(
        &delivery_results,
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_plan_delivery_action_results.json"
        ))
        .unwrap(),
    );
    let node_action_results = json!({
        "request_replan": serde_json::to_value(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node sent back for supervisor recovery.".to_string(),
            plan_id: "plan-1".to_string(),
            node_id: Some("node-1".to_string()),
            outbox_id: None,
        }).unwrap(),
        "reopen": serde_json::to_value(WorkspacePlanActionResultView {
            ok: true,
            message: "Blocked plan node reopened.".to_string(),
            plan_id: "plan-1".to_string(),
            node_id: Some("node-1".to_string()),
            outbox_id: None,
        }).unwrap(),
        "accept_review": serde_json::to_value(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node accepted after human review.".to_string(),
            plan_id: "plan-1".to_string(),
            node_id: Some("node-1".to_string()),
            outbox_id: None,
        }).unwrap()
    });
    assert_golden(
        &node_action_results,
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_plan_node_action_results.json"
        ))
        .unwrap(),
    );
    let recover_stale_results = json!({
        "queued": serde_json::to_value(WorkspacePlanActionResultView {
            ok: true,
            message: "Workspace plan stale attempt recovery queued.".to_string(),
            plan_id: "plan-1".to_string(),
            node_id: None,
            outbox_id: None,
        }).unwrap(),
        "noop": serde_json::to_value(WorkspacePlanActionResultView {
            ok: true,
            message: "No stale workspace plan attempts needed recovery.".to_string(),
            plan_id: "plan-1".to_string(),
            node_id: None,
            outbox_id: None,
        }).unwrap()
    });
    assert_golden(
        &recover_stale_results,
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_plan_recover_stale_action_results.json"
        ))
        .unwrap(),
    );
    assert_golden(
        &AutonomyTickView::new(
            false,
            Some("root-autonomy".to_string()),
            "durable_plan_started",
        ),
        serde_json::from_str(include_str!(
            "../../../tests/golden/workspace_autonomy_tick.json"
        ))
        .unwrap(),
    );
}
