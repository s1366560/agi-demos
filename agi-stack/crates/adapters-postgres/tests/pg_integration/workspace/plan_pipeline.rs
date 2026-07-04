use super::*;

pub(super) async fn roundtrip_plan_pipeline(
    repo: &PgWorkspaceRepository,
    created_at: DateTime<Utc>,
) {
    let plan = repo
        .create_plan(WorkspacePlanRecord {
            id: "plan_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            goal_id: "plan_node_p6".to_string(),
            status: "active".to_string(),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    assert_eq!(plan.workspace_id, "ws_p6_repo");
    let node = repo
        .create_plan_node(WorkspacePlanNodeRecord {
            id: "plan_node_p6".to_string(),
            plan_id: "plan_p6_repo".to_string(),
            parent_id: None,
            kind: "task".to_string(),
            title: "Plan snapshot".to_string(),
            description: "Rust reads Python-shaped plan state".to_string(),
            depends_on_json: vec![],
            inputs_schema_json: json!({}),
            outputs_schema_json: json!({}),
            acceptance_criteria_json: vec![json!({
                "kind": "test",
                "spec": {"command": "cargo test"},
                "required": true,
                "description": "workspace tests pass"
            })],
            feature_checkpoint_json: None,
            handoff_package_json: None,
            recommended_capabilities_json: vec![json!({"name": "executor", "weight": 1.0})],
            preferred_agent_id: None,
            estimated_effort_json: json!({"minutes": 30, "confidence": 0.7}),
            priority: 1,
            intent: "todo".to_string(),
            execution: "idle".to_string(),
            progress_json: json!({"percent": 0.0, "confidence": 1.0, "note": ""}),
            assignee_agent_id: None,
            current_attempt_id: None,
            workspace_task_id: Some("task_p6_repo".to_string()),
            metadata_json: json!({"iteration_phase": "plan"}),
            created_at,
            updated_at: None,
            completed_at: None,
        })
        .await
        .unwrap();
    assert_eq!(node.workspace_task_id.as_deref(), Some("task_p6_repo"));
    let latest_plans = repo.list_plans("ws_p6_repo", 10).await.unwrap();
    assert_eq!(latest_plans[0].id, "plan_p6_repo");
    let nodes = repo.list_plan_nodes("plan_p6_repo").await.unwrap();
    assert_eq!(nodes.len(), 1);
    assert_eq!(nodes[0].acceptance_criteria_json[0]["kind"], "test");
    let mut updated_plan = plan.clone();
    updated_plan.status = "suspended".to_string();
    updated_plan.updated_at = Some(created_at);
    let updated_plan = repo.save_plan(updated_plan).await.unwrap();
    assert_eq!(updated_plan.status, "suspended");
    assert_eq!(updated_plan.updated_at, Some(created_at));
    let mut updated_node = node.clone();
    updated_node.intent = "blocked".to_string();
    updated_node.execution = "idle".to_string();
    updated_node.progress_json = json!({"percent": 50, "confidence": 0.6, "note": "waiting"});
    updated_node.current_attempt_id = Some("attempt_p6_repo".to_string());
    updated_node.metadata_json = json!({"operator_action": {"action": "test"}});
    updated_node.updated_at = Some(created_at);
    let updated_node = repo.save_plan_node(updated_node).await.unwrap();
    assert_eq!(updated_node.intent, "blocked");
    assert_eq!(
        updated_node.current_attempt_id.as_deref(),
        Some("attempt_p6_repo")
    );
    assert_eq!(
        updated_node.metadata_json["operator_action"]["action"],
        "test"
    );

    let contract_id = repo
        .ensure_pipeline_contract(
            "pipeline_contract_p6_repo",
            "ws_p6_repo",
            "plan_p6_repo",
            "sandbox_native",
            Some("/workspace/project"),
            &json!([{
                "stage": "test",
                "command": "cargo test --workspace",
                "required": true,
                "timeout_seconds": 120
            }]),
            &json!({"CI": "true"}),
            &json!({
                "trigger": "verification_gate",
                "node_id": "plan_node_p6",
                "attempt_id": "attempt_p6_repo_1"
            }),
            120,
            false,
            Some(3000),
            None,
            &json!({"source": "workspace_plan.pipeline_run_requested"}),
            created_at,
        )
        .await
        .unwrap();
    assert_eq!(contract_id, "pipeline_contract_p6_repo");
    let updated_contract_id = repo
        .ensure_pipeline_contract(
            "pipeline_contract_p6_repo_new",
            "ws_p6_repo",
            "plan_p6_repo",
            "sandbox_native",
            Some("/workspace/project"),
            &json!([{
                "stage": "build",
                "command": "cargo build",
                "required": true,
                "timeout_seconds": 90
            }]),
            &json!({}),
            &json!({"trigger": "verification_gate"}),
            90,
            false,
            Some(3000),
            None,
            &json!({"source": "workspace_plan.pipeline_run_requested", "updated": true}),
            created_at,
        )
        .await
        .unwrap();
    assert_eq!(updated_contract_id, "pipeline_contract_p6_repo");
    let pipeline_run = repo
        .create_pipeline_run(WorkspacePipelineRunRecord {
            id: "pipeline_run_p6_repo".to_string(),
            contract_id: contract_id.clone(),
            workspace_id: "ws_p6_repo".to_string(),
            plan_id: Some("plan_p6_repo".to_string()),
            node_id: Some("plan_node_p6".to_string()),
            attempt_id: Some("attempt_p6_repo_1".to_string()),
            commit_ref: Some("abcdef1234567890".to_string()),
            provider: "sandbox_native".to_string(),
            status: "running".to_string(),
            reason: None,
            started_at: Some(created_at),
            completed_at: None,
            metadata_json: json!({"reason": "pipeline_gate_required"}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    assert_eq!(pipeline_run.status, "running");
    let latest_run = repo
        .latest_pipeline_run_for_node("plan_p6_repo", "plan_node_p6", Some("attempt_p6_repo_1"))
        .await
        .unwrap()
        .expect("latest pipeline run");
    assert_eq!(latest_run.id, "pipeline_run_p6_repo");
    assert_eq!(latest_run.commit_ref.as_deref(), Some("abcdef1234567890"));
    assert_eq!(latest_run.metadata_json["reason"], "pipeline_gate_required");
    let stage_started_at = created_at;
    let pipeline_stage_run = repo
        .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
            id: "pipeline_stage_run_p6_repo".to_string(),
            run_id: pipeline_run.id.clone(),
            workspace_id: "ws_p6_repo".to_string(),
            stage: "test".to_string(),
            status: "running".to_string(),
            command: Some("cargo test --workspace".to_string()),
            exit_code: None,
            stdout_preview: None,
            stderr_preview: None,
            log_ref: None,
            artifact_refs_json: Vec::new(),
            started_at: Some(stage_started_at),
            completed_at: None,
            duration_ms: None,
            metadata_json: json!({"required": true}),
            created_at: stage_started_at,
            updated_at: None,
        })
        .await
        .unwrap();
    assert_eq!(pipeline_stage_run.status, "running");
    let stage_completed_at = ts(2026, 1, 2, 3, 4, 7);
    let artifact_refs = vec!["pipeline_log:test:sandbox://pipeline/test.log".to_string()];
    let finished_stage = repo
        .finish_pipeline_stage_run(
            &pipeline_stage_run.id,
            "success",
            Some(0),
            Some("ok"),
            Some(""),
            Some("sandbox://pipeline/test.log"),
            &artifact_refs,
            &json!({"duration_ms_observed": 1900}),
            stage_completed_at,
        )
        .await
        .unwrap()
        .expect("finished pipeline stage run");
    assert_eq!(finished_stage.status, "success");
    assert_eq!(finished_stage.exit_code, Some(0));
    assert_eq!(finished_stage.stdout_preview.as_deref(), Some("ok"));
    assert_eq!(finished_stage.stderr_preview.as_deref(), Some(""));
    assert_eq!(finished_stage.artifact_refs_json, artifact_refs);
    assert_eq!(finished_stage.duration_ms, Some(2_000));
    assert_eq!(finished_stage.metadata_json["required"], true);
    assert_eq!(finished_stage.metadata_json["duration_ms_observed"], 1900);

    repo.create_plan_blackboard_entry(WorkspacePlanBlackboardEntryRecord {
        id: "plan_bb_p6_v1".to_string(),
        plan_id: "plan_p6_repo".to_string(),
        key: "research.summary".to_string(),
        value_json: Some(json!({"summary": "old"})),
        published_by: "u_p6_owner".to_string(),
        version: 1,
        schema_ref: None,
        metadata_json: json!({}),
        created_at,
    })
    .await
    .unwrap();
    repo.create_plan_blackboard_entry(WorkspacePlanBlackboardEntryRecord {
        id: "plan_bb_p6_v2".to_string(),
        plan_id: "plan_p6_repo".to_string(),
        key: "research.summary".to_string(),
        value_json: Some(json!({"summary": "new"})),
        published_by: "u_p6_owner".to_string(),
        version: 2,
        schema_ref: Some("summary.v1".to_string()),
        metadata_json: json!({"source": "test"}),
        created_at,
    })
    .await
    .unwrap();
    let latest_blackboard = repo
        .list_plan_blackboard_latest("plan_p6_repo")
        .await
        .unwrap();
    assert_eq!(latest_blackboard.len(), 1);
    assert_eq!(
        latest_blackboard[0].value_json.as_ref().unwrap()["summary"],
        "new"
    );

    repo.create_plan_event(WorkspacePlanEventRecord {
        id: "plan_event_p6".to_string(),
        plan_id: "plan_p6_repo".to_string(),
        workspace_id: "ws_p6_repo".to_string(),
        node_id: Some("plan_node_p6".to_string()),
        attempt_id: None,
        event_type: "workspace_plan_updated".to_string(),
        source: "system".to_string(),
        actor_id: Some("u_p6_owner".to_string()),
        payload_json: json!({"status": "active"}),
        created_at,
    })
    .await
    .unwrap();
    let events = repo.list_plan_events("plan_p6_repo", 5).await.unwrap();
    assert_eq!(events[0].event_type, "workspace_plan_updated");
    repo.create_plan_event(WorkspacePlanEventRecord {
        id: "plan_event_p6_dispose".to_string(),
        plan_id: "plan_p6_repo".to_string(),
        workspace_id: "ws_p6_repo".to_string(),
        node_id: Some("plan_node_p6".to_string()),
        attempt_id: Some("attempt_p6_repo_1".to_string()),
        event_type: "supervisor_decision_completed".to_string(),
        source: "supervisor".to_string(),
        actor_id: Some("u_p6_owner".to_string()),
        payload_json: json!({"action": "dispose_node", "reason": "test"}),
        created_at,
    })
    .await
    .unwrap();
    assert!(repo
        .has_supervisor_dispose_decision_for_node("ws_p6_repo", "plan_p6_repo", "plan_node_p6")
        .await
        .unwrap());
    assert!(!repo
        .has_supervisor_dispose_decision_for_node("ws_p6_repo", "plan_p6_repo", "plan_node_other")
        .await
        .unwrap());

    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "supervisor_tick".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "test"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    let plan_outbox = repo.list_plan_outbox("plan_p6_repo", 5).await.unwrap();
    assert_eq!(plan_outbox[0].event_type, "supervisor_tick");
}
