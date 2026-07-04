use super::support::*;

#[tokio::test]
async fn workspace_repository_roundtrips_against_shared_schema() {
    let Some(pool) = pool_or_skip("workspace_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    for sql in [
        "DELETE FROM workspace_pipeline_stage_runs WHERE run_id IN (SELECT id FROM workspace_pipeline_runs WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo') OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_pipeline_runs WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_pipeline_contracts WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_plan_outbox WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_plan_events WHERE plan_id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
        "DELETE FROM workspace_plan_blackboard_entries WHERE plan_id = 'plan_p6_repo'",
        "DELETE FROM workspace_plan_nodes WHERE plan_id = 'plan_p6_repo'",
        "DELETE FROM workspace_plans WHERE id = 'plan_p6_repo' OR workspace_id = 'ws_p6_repo'",
    ] {
        let _ = sqlx::query(sql).execute(&pool).await;
    }

    for table in [
        "workspace_blackboard_outbox",
        "blackboard_files",
        "blackboard_replies",
        "blackboard_posts",
        "topology_edges",
        "topology_nodes",
        "workspace_task_session_attempts",
        "workspace_tasks",
        "workspace_members",
    ] {
        let sql = format!("DELETE FROM {table} WHERE workspace_id = 'ws_p6_repo'");
        let _ = sqlx::query(&sql).execute(&pool).await;
    }
    sqlx::query("DELETE FROM workspaces WHERE id = 'ws_p6_repo'")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM projects WHERE id = 'p_p6_repo'")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM tenants WHERE id = 't_p6_repo'")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM users WHERE id IN ('u_p6_owner', 'u_p6_viewer')")
        .execute(&pool)
        .await
        .unwrap();

    sqlx::query(
        "INSERT INTO users (id, email) VALUES \
         ('u_p6_owner', 'owner-p6@example.com'), \
         ('u_p6_viewer', 'viewer-p6@example.com') \
         ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_p6_repo', 'P6') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_p6_repo', 't_p6_repo', 'P6 project', 'u_p6_owner')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) VALUES \
         ('u_p6_owner', 'p_p6_repo', 'owner'), \
         ('u_p6_viewer', 'p_p6_repo', 'viewer') \
         ON CONFLICT (user_id, project_id) DO UPDATE SET role = EXCLUDED.role",
    )
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgWorkspaceRepository::new(pool.clone());
    assert!(repo
        .user_can_access_project(
            "u_p6_owner",
            "t_p6_repo",
            "p_p6_repo",
            WorkspaceProjectAccess::Admin,
        )
        .await
        .unwrap());
    assert!(repo
        .user_can_access_project(
            "u_p6_viewer",
            "t_p6_repo",
            "p_p6_repo",
            WorkspaceProjectAccess::Read,
        )
        .await
        .unwrap());
    assert!(!repo
        .user_can_access_project(
            "u_p6_viewer",
            "t_p6_repo",
            "p_p6_repo",
            WorkspaceProjectAccess::Write,
        )
        .await
        .unwrap());

    let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
    let workspace = repo
        .create_workspace(
            WorkspaceRecord {
                id: "ws_p6_repo".to_string(),
                tenant_id: "t_p6_repo".to_string(),
                project_id: "p_p6_repo".to_string(),
                name: "P6 workspace".to_string(),
                description: Some("shared tables".to_string()),
                created_by: "u_p6_owner".to_string(),
                is_archived: false,
                metadata_json: json!({"workspace_use_case": "programming"}),
                office_status: "inactive".to_string(),
                hex_layout_config_json: json!({}),
                default_blocking_categories_json: vec!["blocked".to_string()],
                created_at,
                updated_at: None,
            },
            "wm_p6_owner".to_string(),
        )
        .await
        .unwrap();
    assert_eq!(workspace.id, "ws_p6_repo");
    assert!(repo
        .user_can_access_workspace("u_p6_owner", "ws_p6_repo", WorkspaceAccess::Write)
        .await
        .unwrap());
    let listed = repo
        .list_workspaces_for_user("t_p6_repo", "p_p6_repo", "u_p6_owner", 10, 0)
        .await
        .unwrap();
    assert!(listed.iter().any(|item| item.id == "ws_p6_repo"));

    let task = repo
        .create_task(WorkspaceTaskRecord {
            id: "task_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            title: "Implement P6".to_string(),
            description: None,
            created_by: "u_p6_owner".to_string(),
            assignee_user_id: Some("u_p6_viewer".to_string()),
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: 1,
            estimated_effort: Some("M".to_string()),
            blocker_reason: None,
            metadata_json: json!({"leader_only": true}),
            created_at,
            updated_at: None,
            completed_at: None,
            archived_at: None,
        })
        .await
        .unwrap();
    assert_eq!(task.priority, 1);
    let mut task = repo
        .get_task("ws_p6_repo", "task_p6_repo")
        .await
        .unwrap()
        .expect("task");
    task.status = "done".to_string();
    task.completed_at = Some(created_at);
    let saved_task = repo.save_task(task).await.unwrap();
    assert_eq!(saved_task.status, "done");

    let attempt = repo
        .create_task_session_attempt(WorkspaceTaskSessionAttemptRecord {
            id: "attempt_p6_repo_1".to_string(),
            workspace_task_id: "task_p6_repo".to_string(),
            root_goal_task_id: "task_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            attempt_number: 1,
            status: "pending".to_string(),
            conversation_id: None,
            worker_agent_id: Some("agent_p6_worker".to_string()),
            leader_agent_id: None,
            candidate_summary: None,
            candidate_artifacts_json: Vec::new(),
            candidate_verifications_json: Vec::new(),
            leader_feedback: None,
            adjudication_reason: None,
            created_at,
            updated_at: Some(created_at),
            completed_at: None,
        })
        .await
        .unwrap();
    assert_eq!(attempt.status, "pending");
    assert_eq!(
        repo.latest_task_session_attempt_number("task_p6_repo")
            .await
            .unwrap(),
        1
    );
    let running = repo
        .mark_task_session_attempt_running("attempt_p6_repo_1", created_at)
        .await
        .unwrap()
        .expect("attempt should update");
    assert_eq!(running.status, "running");
    let active = repo
        .find_active_task_session_attempt("task_p6_repo")
        .await
        .unwrap()
        .expect("active attempt");
    assert_eq!(active.id, "attempt_p6_repo_1");
    let loaded_attempt = repo
        .get_task_session_attempt("attempt_p6_repo_1")
        .await
        .unwrap()
        .expect("loaded attempt by id");
    assert_eq!(loaded_attempt.workspace_task_id, "task_p6_repo");
    let reported_attempt = repo
        .record_task_session_attempt_candidate_output(
            "attempt_p6_repo_1",
            Some("worker stream completed"),
            &["commit_ref:abcdef1234567890".to_string()],
            &["worker_report:completed".to_string()],
            Some("conv_p6_worker_reported"),
            created_at,
        )
        .await
        .unwrap()
        .expect("reported attempt should update");
    assert_eq!(reported_attempt.status, "awaiting_leader_adjudication");
    assert_eq!(
        reported_attempt.conversation_id.as_deref(),
        Some("conv_p6_worker_reported")
    );
    assert_eq!(
        reported_attempt.candidate_summary.as_deref(),
        Some("worker stream completed")
    );
    assert_eq!(
        reported_attempt.candidate_artifacts_json,
        vec!["commit_ref:abcdef1234567890".to_string()]
    );
    assert_eq!(
        reported_attempt.candidate_verifications_json,
        vec!["worker_report:completed".to_string()]
    );
    repo.create_task_session_attempt(WorkspaceTaskSessionAttemptRecord {
        id: "attempt_p6_repo_2".to_string(),
        workspace_task_id: "task_p6_repo".to_string(),
        root_goal_task_id: "task_p6_repo".to_string(),
        workspace_id: "ws_p6_repo".to_string(),
        attempt_number: 2,
        status: "running".to_string(),
        conversation_id: Some("conv_p6_worker_active".to_string()),
        worker_agent_id: Some("agent_p6_worker".to_string()),
        leader_agent_id: Some("agent_p6_leader".to_string()),
        candidate_summary: None,
        candidate_artifacts_json: Vec::new(),
        candidate_verifications_json: Vec::new(),
        leader_feedback: None,
        adjudication_reason: None,
        created_at,
        updated_at: Some(created_at),
        completed_at: None,
    })
    .await
    .unwrap();
    let active_worker_count = repo
        .count_recent_running_task_session_attempts_with_conversation(
            "ws_p6_repo",
            ts(2026, 1, 2, 3, 4, 4),
        )
        .await
        .unwrap();
    assert_eq!(active_worker_count, 1);
    let expired_worker_count = repo
        .count_recent_running_task_session_attempts_with_conversation(
            "ws_p6_repo",
            ts(2026, 1, 2, 3, 4, 6),
        )
        .await
        .unwrap();
    assert_eq!(expired_worker_count, 0);

    let node = repo
        .create_node(TopologyNodeRecord {
            id: "node_p6_task".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            node_type: "task".to_string(),
            ref_id: Some("task_p6_repo".to_string()),
            title: "Task".to_string(),
            position_x: 0.0,
            position_y: 0.0,
            hex_q: Some(0),
            hex_r: Some(0),
            status: "active".to_string(),
            tags_json: vec!["p6".to_string()],
            data_json: json!({}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    let node2 = repo
        .create_node(TopologyNodeRecord {
            id: "node_p6_note".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            node_type: "note".to_string(),
            ref_id: None,
            title: "Note".to_string(),
            position_x: 1.0,
            position_y: 0.0,
            hex_q: Some(1),
            hex_r: Some(0),
            status: "active".to_string(),
            tags_json: vec![],
            data_json: json!({}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    let coords = repo
        .edge_endpoints_in_workspace("ws_p6_repo", &node.id, &node2.id)
        .await
        .unwrap()
        .expect("edge endpoints");
    assert_eq!(coords, (Some(0), Some(0), Some(1), Some(0)));
    let edge = repo
        .create_edge(TopologyEdgeRecord {
            id: "edge_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            source_node_id: node.id,
            target_node_id: node2.id,
            label: Some("relates".to_string()),
            source_hex_q: coords.0,
            source_hex_r: coords.1,
            target_hex_q: coords.2,
            target_hex_r: coords.3,
            direction: None,
            auto_created: false,
            data_json: json!({}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    assert_eq!(edge.source_hex_q, Some(0));

    let post = repo
        .create_post(BlackboardPostRecord {
            id: "post_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            author_id: "u_p6_owner".to_string(),
            title: "Status".to_string(),
            content: "Foundation ready".to_string(),
            status: "open".to_string(),
            is_pinned: true,
            metadata_json: json!({"lane": "p6"}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    let reply = repo
        .create_reply(BlackboardReplyRecord {
            id: "reply_p6_repo".to_string(),
            post_id: post.id.clone(),
            workspace_id: "ws_p6_repo".to_string(),
            author_id: "u_p6_viewer".to_string(),
            content: "ack".to_string(),
            metadata_json: json!({}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    assert_eq!(reply.post_id, post.id);
    let dir = repo
        .create_file(BlackboardFileRecord {
            id: "file_p6_dir".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            parent_path: "/".to_string(),
            name: "docs".to_string(),
            is_directory: true,
            file_size: 0,
            content_type: String::new(),
            storage_key: String::new(),
            uploader_type: "user".to_string(),
            uploader_id: "u_p6_owner".to_string(),
            uploader_name: "Owner".to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at,
        })
        .await
        .unwrap();
    assert!(dir.is_directory);
    let file = repo
        .create_file(BlackboardFileRecord {
            id: "file_p6_doc".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            parent_path: "/docs/".to_string(),
            name: "status.txt".to_string(),
            is_directory: false,
            file_size: 11,
            content_type: "text/plain".to_string(),
            storage_key: "file_p6_doc/status.txt".to_string(),
            uploader_type: "user".to_string(),
            uploader_id: "u_p6_owner".to_string(),
            uploader_name: "Owner".to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at,
        })
        .await
        .unwrap();
    assert_eq!(file.parent_path, "/docs/");
    let files = repo.list_files("ws_p6_repo", "/docs/").await.unwrap();
    assert_eq!(
        files.iter().map(|f| f.name.as_str()).collect::<Vec<_>>(),
        vec!["status.txt"]
    );
    repo.bulk_update_file_parent_path("ws_p6_repo", "/docs/", "/notes/")
        .await
        .unwrap();
    let moved = repo
        .get_file("ws_p6_repo", "file_p6_doc")
        .await
        .unwrap()
        .expect("file");
    assert_eq!(moved.parent_path, "/notes/");
    repo.enqueue_blackboard_outbox(BlackboardOutboxRecord {
        id: "outbox_p6_repo".to_string(),
        workspace_id: "ws_p6_repo".to_string(),
        tenant_id: "t_p6_repo".to_string(),
        project_id: "p_p6_repo".to_string(),
        event_type: "blackboard_post_created".to_string(),
        payload_json: json!({"post_id": "post_p6_repo"}),
        metadata_json: json!({"tenant_id": "t_p6_repo"}),
        correlation_id: None,
    })
    .await
    .unwrap();
    let outbox_count = sqlx::query_as::<_, (i64,)>(
        "SELECT count(*) FROM workspace_blackboard_outbox WHERE id = 'outbox_p6_repo' \
         AND status = 'pending'",
    )
    .fetch_one(&pool)
    .await
    .unwrap()
    .0;
    assert_eq!(outbox_count, 1);

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

    let outbox_now = Utc.with_ymd_and_hms(2026, 1, 2, 4, 0, 0).unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_delayed".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "attempt_retry".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "pending".to_string(),
        attempt_count: 2,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: Some("retry later".to_string()),
        next_attempt_at: Some(ts(2026, 1, 2, 4, 1, 0)),
        processed_at: None,
        metadata_json: json!({"source": "delayed"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_expired".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "worker_launch".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "processing".to_string(),
        attempt_count: 1,
        max_attempts: 5,
        lease_owner: Some("old-worker".to_string()),
        lease_expires_at: Some(ts(2026, 1, 2, 3, 59, 59)),
        last_error: Some("stale lease".to_string()),
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "expired"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_release".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "worker_launch".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "release"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_dead".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "worker_launch".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "processing".to_string(),
        attempt_count: 5,
        max_attempts: 5,
        lease_owner: Some("worker-a".to_string()),
        lease_expires_at: Some(ts(2026, 1, 2, 4, 1, 0)),
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "dead-letter"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_mention_runtime".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "workspace_agent_mention".to_string(),
        payload_json: json!({"conversation_id": "conv_p6_mention"}),
        status: "pending_runtime".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "mention-runtime"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_mention_response".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "workspace_agent_mention".to_string(),
        payload_json: json!({"final_content": "done"}),
        status: "runtime_response_ready".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "mention-response"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_mention_writer".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "workspace_agent_mention".to_string(),
        payload_json: json!({"conversation_id": "conv_p6_writer"}),
        status: "pending_runtime".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "mention-writer"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_mention_error".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "workspace_agent_mention".to_string(),
        payload_json: json!({"runtime_error_detail": "model unavailable"}),
        status: "runtime_error_ready".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "mention-error"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_future_runtime".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "future_runtime_event".to_string(),
        payload_json: json!({}),
        status: "pending_runtime".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "future-runtime"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();

    let claimed = repo
        .claim_due_plan_outbox(10, "worker-a", 30, outbox_now)
        .await
        .unwrap();
    let claimed_ids = claimed
        .iter()
        .map(|item| item.id.as_str())
        .collect::<Vec<_>>();
    assert!(claimed_ids.contains(&"plan_outbox_p6"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_expired"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_release"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_mention_runtime"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_mention_response"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_mention_writer"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_mention_error"));
    assert!(!claimed_ids.contains(&"plan_outbox_p6_delayed"));
    assert!(!claimed_ids.contains(&"plan_outbox_p6_dead"));
    assert!(!claimed_ids.contains(&"plan_outbox_p6_future_runtime"));

    let claimed_due = repo
        .get_plan_outbox("plan_outbox_p6")
        .await
        .unwrap()
        .expect("claimed due outbox");
    assert_eq!(claimed_due.status, "processing");
    assert_eq!(claimed_due.attempt_count, 1);
    assert_eq!(claimed_due.lease_owner.as_deref(), Some("worker-a"));
    assert_eq!(claimed_due.lease_expires_at, Some(ts(2026, 1, 2, 4, 0, 30)));

    assert!(repo
        .renew_plan_outbox_lease("plan_outbox_p6", "worker-a", 45, outbox_now)
        .await
        .unwrap());
    assert!(!repo
        .renew_plan_outbox_lease("plan_outbox_p6", "wrong-worker", 45, outbox_now)
        .await
        .unwrap());
    let renewed = repo
        .get_plan_outbox("plan_outbox_p6")
        .await
        .unwrap()
        .expect("renewed outbox");
    assert_eq!(renewed.lease_expires_at, Some(ts(2026, 1, 2, 4, 0, 45)));

    assert!(repo
        .mark_plan_outbox_failed("plan_outbox_p6", "boom", Some("worker-a"), outbox_now)
        .await
        .unwrap());
    let failed = repo
        .get_plan_outbox("plan_outbox_p6")
        .await
        .unwrap()
        .expect("failed outbox");
    assert_eq!(failed.status, "failed");
    assert_eq!(failed.last_error.as_deref(), Some("boom"));
    assert_eq!(failed.next_attempt_at, Some(ts(2026, 1, 2, 4, 0, 2)));

    let retried = repo
        .retry_plan_outbox_now(
            "plan_outbox_p6",
            "ws_p6_repo",
            Some("u_p6_owner"),
            Some("operator retry"),
            outbox_now,
        )
        .await
        .unwrap()
        .expect("retried outbox");
    assert_eq!(retried.status, "pending");
    assert_eq!(retried.attempt_count, 1);
    assert!(retried.next_attempt_at.is_none());
    assert_eq!(
        retried.metadata_json["operator_retry"]["previous_status"],
        "failed"
    );

    let delayed_retry = repo
        .retry_plan_outbox_now(
            "plan_outbox_p6_delayed",
            "ws_p6_repo",
            Some("u_p6_owner"),
            Some("run now"),
            outbox_now,
        )
        .await
        .unwrap()
        .expect("delayed retry");
    assert_eq!(delayed_retry.status, "pending");
    assert!(delayed_retry.next_attempt_at.is_none());
    assert!(delayed_retry.metadata_json["operator_retry"]["previous_next_attempt_at"].is_string());
    assert!(repo
        .retry_plan_outbox_now(
            "plan_outbox_p6_delayed",
            "wrong_workspace",
            Some("u_p6_owner"),
            None,
            outbox_now,
        )
        .await
        .unwrap()
        .is_none());

    assert!(repo
        .release_plan_outbox_processing(
            "plan_outbox_p6_release",
            Some("shutdown"),
            Some("worker-a"),
            outbox_now,
        )
        .await
        .unwrap());
    let released = repo
        .get_plan_outbox("plan_outbox_p6_release")
        .await
        .unwrap()
        .expect("released outbox");
    assert_eq!(released.status, "pending");
    assert_eq!(released.attempt_count, 0);
    assert_eq!(released.last_error.as_deref(), Some("shutdown"));

    assert!(repo
        .park_plan_outbox_processing(
            "plan_outbox_p6_mention_runtime",
            "runtime_bound",
            &json!({
                "runtime_binding": "workspace_agent_mention_conversation",
                "conversation_id": "conv_p6_mention"
            }),
            Some("worker-a"),
            outbox_now,
        )
        .await
        .unwrap());
    let parked_runtime = repo
        .get_plan_outbox("plan_outbox_p6_mention_runtime")
        .await
        .unwrap()
        .expect("parked mention runtime outbox");
    assert_eq!(parked_runtime.status, "runtime_bound");
    assert!(parked_runtime.processed_at.is_none());
    assert!(parked_runtime.lease_owner.is_none());
    assert!(parked_runtime.lease_expires_at.is_none());
    assert_eq!(
        parked_runtime.metadata_json["runtime_binding"],
        "workspace_agent_mention_conversation"
    );
    assert!(repo
        .park_plan_outbox_processing_with_payload_patch(
            "plan_outbox_p6_mention_writer",
            "runtime_response_ready",
            &json!({"runtime_writer": "llm_port_single_turn"}),
            &json!({"final_content": "ready from writer"}),
            Some("worker-a"),
            outbox_now,
        )
        .await
        .unwrap());
    let writer_ready = repo
        .get_plan_outbox("plan_outbox_p6_mention_writer")
        .await
        .unwrap()
        .expect("writer-ready mention outbox");
    assert_eq!(writer_ready.status, "runtime_response_ready");
    assert_eq!(
        writer_ready.payload_json["final_content"],
        "ready from writer"
    );
    assert_eq!(
        writer_ready.metadata_json["runtime_writer"],
        "llm_port_single_turn"
    );
    assert!(writer_ready.processed_at.is_none());
    assert!(repo
        .mark_plan_outbox_completed(
            "plan_outbox_p6_mention_response",
            Some("worker-a"),
            outbox_now
        )
        .await
        .unwrap());
    let completed_response = repo
        .get_plan_outbox("plan_outbox_p6_mention_response")
        .await
        .unwrap()
        .expect("completed mention response");
    assert_eq!(completed_response.status, "completed");
    assert_eq!(completed_response.processed_at, Some(outbox_now));
    assert!(repo
        .mark_plan_outbox_completed("plan_outbox_p6_mention_error", Some("worker-a"), outbox_now)
        .await
        .unwrap());
    let future_runtime = repo
        .get_plan_outbox("plan_outbox_p6_future_runtime")
        .await
        .unwrap()
        .expect("future runtime outbox");
    assert_eq!(future_runtime.status, "pending_runtime");
    assert_eq!(future_runtime.attempt_count, 0);

    assert!(repo
        .mark_plan_outbox_completed("plan_outbox_p6_expired", Some("worker-a"), outbox_now)
        .await
        .unwrap());
    let completed = repo
        .get_plan_outbox("plan_outbox_p6_expired")
        .await
        .unwrap()
        .expect("completed outbox");
    assert_eq!(completed.status, "completed");
    assert_eq!(completed.processed_at, Some(outbox_now));

    assert!(repo
        .mark_plan_outbox_failed(
            "plan_outbox_p6_dead",
            "too many retries",
            Some("worker-a"),
            outbox_now,
        )
        .await
        .unwrap());
    let dead_letter = repo
        .get_plan_outbox("plan_outbox_p6_dead")
        .await
        .unwrap()
        .expect("dead letter outbox");
    assert_eq!(dead_letter.status, "dead_letter");
    assert!(dead_letter.next_attempt_at.is_none());
    let revived = repo
        .retry_plan_outbox_now(
            "plan_outbox_p6_dead",
            "ws_p6_repo",
            Some("u_p6_owner"),
            Some("revive"),
            outbox_now,
        )
        .await
        .unwrap()
        .expect("revived dead letter");
    assert_eq!(revived.status, "pending");
    assert_eq!(revived.attempt_count, 0);
}
