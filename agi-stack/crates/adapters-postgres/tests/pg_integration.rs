//! Live-database integration tests for the production Postgres adapter.
//!
//! These are **gated on `DATABASE_URL`**: when it is unset (the default in CI and
//! most dev shells) every test short-circuits to a pass, so `cargo test
//! --workspace` never needs a database to be green. Point `DATABASE_URL` at a
//! Postgres with the `vector` extension available (e.g. the `pgvector/pgvector`
//! image) to exercise the real read/write path against a schema shaped like the
//! Python backend's.
//!
//! The tests create a **minimal subset** of the Python schema (`users`,
//! `tenants`, `projects`, `api_keys`, `memories`, `user_projects`) — only the
//! columns the Rust adapter touches, with the same names/types — then seed and
//! assert round-trips. This proves shared-DB compatibility without standing up
//! the full 110-table Python schema.

use agistack_adapters_postgres::PgPool;
use agistack_adapters_postgres::{
    connect, ensure_aux_schema, BlackboardFileRecord, BlackboardOutboxRecord, BlackboardPostRecord,
    BlackboardReplyRecord, InvitationRecord, NewDecisionRecordRecord, NewShareRecord,
    NewTrustPolicyRecord, PgApiKeyStore, PgCheckpointStore, PgInvitationRepository,
    PgMemoryRepository, PgProjectReadRepository, PgProjectSandboxRepository, PgProjectStore,
    PgShareRepository, PgSkillRepository, PgTenantRepository, PgTrustRepository, PgUserStore,
    PgVectorIndex, PgWorkspaceRepository, ProjectCreateRecord, ProjectListForUserQuery,
    ProjectLookup, ProjectMembersLookup, ProjectSandboxRecord, ProjectStatsLookup,
    ProjectUpdatePatch, SkillProjectAccess, SkillRecord, SkillUpdateRecord, SkillVersionRecord,
    TenantAccessStatus, TenantAdminStatus, TenantLookup, TenantUpdatePatch, TopologyEdgeRecord,
    TopologyNodeRecord, TrustDecisionResolution, WorkspaceAccess, WorkspacePipelineRunRecord,
    WorkspacePipelineStageRunRecord, WorkspacePlanBlackboardEntryRecord, WorkspacePlanEventRecord,
    WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord, WorkspacePlanRecord,
    WorkspaceProjectAccess, WorkspaceRecord, WorkspaceTaskRecord,
    WorkspaceTaskSessionAttemptRecord,
};
use agistack_core::agent::types::{SessionState, SessionStatus};
use agistack_core::model::{Entity, Memory};
use agistack_core::ports::{CheckpointStore, MemoryRepository, VectorIndexPort};
use serde_json::json;
use sqlx::types::chrono::{DateTime, TimeZone, Utc};

/// Return a connected pool if `DATABASE_URL` is set, else `None` (skip).
async fn pool_or_skip(test: &str) -> Option<PgPool> {
    match std::env::var("DATABASE_URL") {
        Ok(url) if !url.is_empty() => match connect(&url).await {
            Ok(pool) => Some(pool),
            Err(e) => panic!("DATABASE_URL set but connect failed for {test}: {e}"),
        },
        _ => {
            eprintln!("[skip] {test}: DATABASE_URL unset");
            None
        }
    }
}

fn ts(year: i32, month: u32, day: u32, hour: u32, min: u32, sec: u32) -> DateTime<Utc> {
    Utc.with_ymd_and_hms(year, month, day, hour, min, sec)
        .unwrap()
}

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

/// Create the minimal Python-shaped tables the adapter reads/writes, plus the
/// Rust-owned auxiliary schema. Idempotent (`IF NOT EXISTS`), so tests can share a
/// database. Uses a per-test id prefix to isolate rows.
async fn ensure_python_shaped_tables(pool: &PgPool) {
    for ddl in [
        "CREATE TABLE IF NOT EXISTS users (id text PRIMARY KEY, email text)",
        "CREATE TABLE IF NOT EXISTS tenants (id text PRIMARY KEY, name text)",
        "CREATE TABLE IF NOT EXISTS user_tenants (\
            id text PRIMARY KEY, user_id text NOT NULL, tenant_id text NOT NULL, \
            role text DEFAULT 'member', permissions json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS projects (\
            id text PRIMARY KEY, tenant_id text NOT NULL, name text NOT NULL, \
            owner_id text NOT NULL, is_public boolean DEFAULT false)",
        "CREATE TABLE IF NOT EXISTS project_sandboxes (\
            id text PRIMARY KEY, project_id text NOT NULL UNIQUE, tenant_id text NOT NULL, \
            sandbox_id text NOT NULL UNIQUE, sandbox_type varchar(20) DEFAULT 'cloud' NOT NULL, \
            status varchar(20) DEFAULT 'pending' NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, started_at timestamptz, \
            last_accessed_at timestamptz DEFAULT now() NOT NULL, \
            health_checked_at timestamptz, error_message text, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            local_config json DEFAULT '{}'::json NOT NULL)",
        "CREATE TABLE IF NOT EXISTS user_projects (\
            user_id text NOT NULL, project_id text NOT NULL, role text DEFAULT 'member', \
            PRIMARY KEY (user_id, project_id))",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS role text DEFAULT 'member'",
        "CREATE TABLE IF NOT EXISTS api_keys (\
            id text PRIMARY KEY, key_hash text, name text, user_id text, \
            created_at timestamptz DEFAULT now(), expires_at timestamptz, \
            is_active boolean DEFAULT true, permissions json DEFAULT '[]'::json, \
            last_used_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS memories (\
            id text PRIMARY KEY, project_id text NOT NULL, title varchar(500) NOT NULL, \
            content text NOT NULL, content_type varchar(20) DEFAULT 'text', \
            tags json DEFAULT '[]'::json, entities json DEFAULT '[]'::json, \
            relationships json DEFAULT '[]'::json, version integer DEFAULT 1, \
            author_id text NOT NULL, collaborators json DEFAULT '[]'::json, \
            is_public boolean DEFAULT false, status text DEFAULT 'ENABLED', \
            processing_status text DEFAULT 'PENDING', meta json DEFAULT '{}'::json, \
            task_id text, created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS memory_shares (\
            id text PRIMARY KEY, memory_id text NOT NULL, share_token text UNIQUE, \
            shared_with_user_id text, shared_with_project_id text, \
            permissions json DEFAULT '{}'::json, shared_by text NOT NULL, \
            created_at timestamptz DEFAULT now(), expires_at timestamptz, \
            access_count integer DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS skills (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text, \
            name varchar(200) NOT NULL, description text NOT NULL, \
            tools json DEFAULT '[]'::json NOT NULL, status varchar(20) DEFAULT 'active' NOT NULL, \
            metadata_json json, created_at timestamptz DEFAULT now(), updated_at timestamptz, \
            scope varchar(20) DEFAULT 'tenant' NOT NULL, is_system_skill boolean DEFAULT false NOT NULL, \
            full_content text, resource_files json, license varchar(200), compatibility varchar(500), \
            allowed_tools_raw text, spec_version varchar(32) DEFAULT '1.0' NOT NULL, \
            current_version integer DEFAULT 0 NOT NULL, version_label varchar(50))",
        "CREATE TABLE IF NOT EXISTS skill_versions (\
            id text PRIMARY KEY, skill_id text NOT NULL, version_number integer NOT NULL, \
            version_label varchar(50), skill_md_content text NOT NULL, resource_files json, \
            change_summary text, created_by varchar(20) DEFAULT 'agent' NOT NULL, \
            created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS workspaces (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL, \
            name varchar(255) NOT NULL, description text, created_by text NOT NULL, \
            is_archived boolean DEFAULT false NOT NULL, metadata_json json DEFAULT '{}'::json, \
            office_status varchar(20) DEFAULT 'inactive' NOT NULL, \
            hex_layout_config_json json DEFAULT '{}'::json, \
            default_blocking_categories_json json DEFAULT '[]'::json NOT NULL, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS workspace_members (\
            id text PRIMARY KEY, workspace_id text NOT NULL, user_id text NOT NULL, \
            role varchar(20) DEFAULT 'viewer' NOT NULL, invited_by text, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS workspace_tasks (\
            id text PRIMARY KEY, workspace_id text NOT NULL, title varchar(255) NOT NULL, \
            description text, created_by text NOT NULL, assignee_user_id text, \
            assignee_agent_id text, status varchar(20) DEFAULT 'todo' NOT NULL, \
            priority integer DEFAULT 0 NOT NULL, estimated_effort varchar(50), \
            blocker_reason text, metadata_json json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, \
            completed_at timestamptz, archived_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS workspace_task_session_attempts (\
            id text PRIMARY KEY, workspace_task_id text NOT NULL, root_goal_task_id text NOT NULL, \
            workspace_id text NOT NULL, attempt_number integer NOT NULL, \
            status varchar(40) DEFAULT 'pending' NOT NULL, conversation_id text, \
            worker_agent_id text, leader_agent_id text, candidate_summary text, \
            candidate_artifacts_json json DEFAULT '[]'::json NOT NULL, \
            candidate_verifications_json json DEFAULT '[]'::json NOT NULL, \
            leader_feedback text, adjudication_reason text, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, \
            completed_at timestamptz)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_task_session_attempts_task_attempt \
            ON workspace_task_session_attempts (workspace_task_id, attempt_number)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_task_session_attempts_task_status \
            ON workspace_task_session_attempts (workspace_task_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_task_session_attempts_root_created \
            ON workspace_task_session_attempts (root_goal_task_id, created_at)",
        "CREATE TABLE IF NOT EXISTS workspace_plans (\
            id text PRIMARY KEY, workspace_id text NOT NULL, goal_id text NOT NULL, \
            status varchar(20) DEFAULT 'draft' NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plans_workspace \
            ON workspace_plans (workspace_id)",
        "CREATE TABLE IF NOT EXISTS workspace_plan_nodes (\
            id text PRIMARY KEY, plan_id text NOT NULL, parent_id text, \
            kind varchar(20) DEFAULT 'task' NOT NULL, title varchar(500) NOT NULL, \
            description text DEFAULT '' NOT NULL, depends_on json DEFAULT '[]'::json NOT NULL, \
            inputs_schema json DEFAULT '{}'::json NOT NULL, \
            outputs_schema json DEFAULT '{}'::json NOT NULL, \
            acceptance_criteria json DEFAULT '[]'::json NOT NULL, \
            feature_checkpoint json, handoff_package json, \
            recommended_capabilities json DEFAULT '[]'::json NOT NULL, \
            preferred_agent_id text, estimated_effort json DEFAULT '{}'::json NOT NULL, \
            priority integer DEFAULT 0 NOT NULL, intent varchar(20) DEFAULT 'todo' NOT NULL, \
            execution varchar(20) DEFAULT 'idle' NOT NULL, progress json DEFAULT '{}'::json NOT NULL, \
            assignee_agent_id text, current_attempt_id text, workspace_task_id text, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz, \
            completed_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_nodes_plan \
            ON workspace_plan_nodes (plan_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_nodes_parent \
            ON workspace_plan_nodes (parent_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_nodes_workspace_task \
            ON workspace_plan_nodes (workspace_task_id)",
        "CREATE TABLE IF NOT EXISTS workspace_plan_blackboard_entries (\
            id text PRIMARY KEY, plan_id text NOT NULL, key varchar(500) NOT NULL, \
            value_json json, published_by text NOT NULL, version integer NOT NULL, \
            schema_ref text, metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_plan_blackboard_plan_key_version \
            ON workspace_plan_blackboard_entries (plan_id, key, version)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_blackboard_plan \
            ON workspace_plan_blackboard_entries (plan_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_blackboard_plan_key \
            ON workspace_plan_blackboard_entries (plan_id, key)",
        "CREATE TABLE IF NOT EXISTS workspace_plan_events (\
            id text PRIMARY KEY, plan_id text NOT NULL, workspace_id text NOT NULL, \
            node_id text, attempt_id text, event_type varchar(80) NOT NULL, \
            source varchar(80) DEFAULT 'system' NOT NULL, actor_id text, \
            payload_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_events_plan_created \
            ON workspace_plan_events (plan_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_events_workspace_created \
            ON workspace_plan_events (workspace_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_events_node \
            ON workspace_plan_events (plan_id, node_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_events_attempt \
            ON workspace_plan_events (attempt_id)",
        "CREATE TABLE IF NOT EXISTS workspace_plan_outbox (\
            id text PRIMARY KEY, plan_id text, workspace_id text NOT NULL, \
            event_type varchar(80) NOT NULL, payload_json json DEFAULT '{}'::json NOT NULL, \
            status varchar(20) DEFAULT 'pending' NOT NULL, attempt_count integer DEFAULT 0 NOT NULL, \
            max_attempts integer DEFAULT 5 NOT NULL, lease_owner varchar(255), \
            lease_expires_at timestamptz, last_error text, next_attempt_at timestamptz, \
            processed_at timestamptz, metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_outbox_plan \
            ON workspace_plan_outbox (plan_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_outbox_workspace_status \
            ON workspace_plan_outbox (workspace_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_outbox_status_next_attempt \
            ON workspace_plan_outbox (status, next_attempt_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_outbox_lease \
            ON workspace_plan_outbox (lease_owner, lease_expires_at)",
        "CREATE TABLE IF NOT EXISTS workspace_pipeline_contracts (\
            id text PRIMARY KEY, workspace_id text NOT NULL, plan_id text, \
            provider varchar(40) DEFAULT 'sandbox_native' NOT NULL, code_root text, \
            commands_json json DEFAULT '[]'::json NOT NULL, \
            env_json json DEFAULT '{}'::json NOT NULL, \
            trigger_policy_json json DEFAULT '{}'::json NOT NULL, \
            timeout_seconds integer DEFAULT 600 NOT NULL, \
            auto_deploy boolean DEFAULT true NOT NULL, preview_port integer, health_url text, \
            status varchar(20) DEFAULT 'active' NOT NULL, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz, \
            CONSTRAINT uq_workspace_pipeline_contract_workspace_plan UNIQUE (workspace_id, plan_id))",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_contracts_workspace \
            ON workspace_pipeline_contracts (workspace_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_contracts_plan \
            ON workspace_pipeline_contracts (plan_id)",
        "CREATE TABLE IF NOT EXISTS workspace_pipeline_runs (\
            id text PRIMARY KEY, contract_id text NOT NULL, workspace_id text NOT NULL, \
            plan_id text, node_id text, attempt_id text, commit_ref text, \
            provider varchar(40) DEFAULT 'sandbox_native' NOT NULL, \
            status varchar(20) DEFAULT 'pending' NOT NULL, reason text, \
            started_at timestamptz, completed_at timestamptz, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_runs_workspace_created \
            ON workspace_pipeline_runs (workspace_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_runs_plan_node \
            ON workspace_pipeline_runs (plan_id, node_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_runs_attempt \
            ON workspace_pipeline_runs (attempt_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_runs_status \
            ON workspace_pipeline_runs (status)",
        "CREATE TABLE IF NOT EXISTS workspace_pipeline_stage_runs (\
            id text PRIMARY KEY, run_id text NOT NULL, workspace_id text NOT NULL, \
            stage varchar(40) NOT NULL, status varchar(20) DEFAULT 'pending' NOT NULL, \
            command text, exit_code integer, stdout_preview text, stderr_preview text, \
            log_ref text, artifact_refs_json json DEFAULT '[]'::json NOT NULL, \
            started_at timestamptz, completed_at timestamptz, duration_ms integer, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_stage_runs_run \
            ON workspace_pipeline_stage_runs (run_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_stage_runs_workspace_status \
            ON workspace_pipeline_stage_runs (workspace_id, status)",
        "CREATE TABLE IF NOT EXISTS topology_nodes (\
            id text PRIMARY KEY, workspace_id text NOT NULL, node_type varchar(20) NOT NULL, \
            ref_id text, title varchar(255) DEFAULT '' NOT NULL, \
            position_x double precision DEFAULT 0 NOT NULL, \
            position_y double precision DEFAULT 0 NOT NULL, hex_q integer, hex_r integer, \
            status varchar(20) DEFAULT 'active' NOT NULL, tags_json json DEFAULT '[]'::json, \
            data_json json DEFAULT '{}'::json, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS topology_edges (\
            id text PRIMARY KEY, workspace_id text NOT NULL, source_node_id text NOT NULL, \
            target_node_id text NOT NULL, label varchar(255), source_hex_q integer, \
            source_hex_r integer, target_hex_q integer, target_hex_r integer, \
            direction varchar(20), auto_created boolean DEFAULT false NOT NULL, \
            data_json json DEFAULT '{}'::json, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS blackboard_posts (\
            id text PRIMARY KEY, workspace_id text NOT NULL, author_id text NOT NULL, \
            title varchar(255) NOT NULL, content text NOT NULL, \
            status varchar(20) DEFAULT 'open' NOT NULL, is_pinned boolean DEFAULT false NOT NULL, \
            metadata_json json DEFAULT '{}'::json, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS blackboard_replies (\
            id text PRIMARY KEY, post_id text NOT NULL, workspace_id text NOT NULL, \
            author_id text NOT NULL, content text NOT NULL, metadata_json json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS blackboard_files (\
            id text PRIMARY KEY, workspace_id text NOT NULL, parent_path varchar(1024) DEFAULT '/' NOT NULL, \
            name varchar(255) NOT NULL, is_directory boolean DEFAULT false NOT NULL, \
            file_size integer DEFAULT 0 NOT NULL, content_type varchar(128) DEFAULT '' NOT NULL, \
            storage_key varchar(512) DEFAULT '' NOT NULL, uploader_type varchar(10) NOT NULL, \
            uploader_id text NOT NULL, uploader_name varchar(128) NOT NULL, checksum_sha256 varchar(64), \
            mime_type_detected varchar(255), created_at timestamptz DEFAULT now())",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_blackboard_files_ws_path_name \
            ON blackboard_files (workspace_id, parent_path, name)",
        "CREATE TABLE IF NOT EXISTS workspace_blackboard_outbox (\
            id text PRIMARY KEY, workspace_id text NOT NULL, tenant_id text NOT NULL, \
            project_id text NOT NULL, event_type varchar(80) NOT NULL, \
            payload_json json DEFAULT '{}'::json NOT NULL, \
            metadata_json json DEFAULT '{}'::json NOT NULL, correlation_id text, \
            status varchar(20) DEFAULT 'pending' NOT NULL, attempt_count integer DEFAULT 0 NOT NULL, \
            max_attempts integer DEFAULT 10 NOT NULL, last_error text, next_attempt_at timestamptz, \
            dispatched_at timestamptz, created_at timestamptz DEFAULT now() NOT NULL, \
            updated_at timestamptz)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("ddl failed: {ddl}\n{e}"));
    }
    ensure_aux_schema(pool).await.expect("aux schema");
}

fn sample_memory(id: &str, project_id: &str) -> Memory {
    Memory {
        id: id.to_string(),
        project_id: project_id.to_string(),
        title: "Portable core".to_string(),
        content: "Rust core compiles to wasm and native.".to_string(),
        author_id: "u_pg_it".to_string(),
        content_type: "text".to_string(),
        tags: vec!["rust".to_string(), "portable".to_string()],
        entities: vec![Entity {
            name: "Rust".to_string(),
            kind: "language".to_string(),
        }],
        version: 1,
        status: "ENABLED".to_string(),
        created_at_ms: 1_700_000_000_000,
        embedding: None,
    }
}

#[tokio::test]
async fn memory_repository_roundtrips_against_shared_schema() {
    let Some(pool) = pool_or_skip("memory_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    let project_id = "p_pg_mem";
    // Seed FK-referenced rows so the memories row is valid for Python readers too.
    sqlx::query("INSERT INTO users (id, email) VALUES ('u_pg_it', 'it@x') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_pg', 'T') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ($1, 't_pg', 'P', 'u_pg_it') ON CONFLICT DO NOTHING",
    )
    .bind(project_id)
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgMemoryRepository::new(pool.clone());
    let id = "m_pg_1";
    sqlx::query("DELETE FROM memories WHERE id = $1")
        .bind(id)
        .execute(&pool)
        .await
        .unwrap();

    // save -> find_by_id
    repo.save(sample_memory(id, project_id)).await.unwrap();
    let fetched = repo.find_by_id(id).await.unwrap().expect("memory present");
    assert_eq!(fetched.title, "Portable core");
    assert_eq!(fetched.tags, vec!["rust", "portable"]);
    assert_eq!(fetched.entities.len(), 1);
    assert_eq!(fetched.entities[0].name, "Rust");
    assert_eq!(fetched.project_id, project_id);

    // list_by_project
    let listed = repo.list_by_project(project_id, 10, 0).await.unwrap();
    assert!(listed.iter().any(|m| m.id == id));

    // search_by_project (ILIKE) — hit and miss
    let hit = repo
        .search_by_project(project_id, "portable", 10)
        .await
        .unwrap();
    assert!(hit.iter().any(|m| m.id == id));
    let miss = repo
        .search_by_project(project_id, "no_such_token_zzz", 10)
        .await
        .unwrap();
    assert!(!miss.iter().any(|m| m.id == id));

    // count_by_project override — efficient SELECT count(*) with the same ILIKE
    // filter as search. Unfiltered count includes the row; a matching search
    // counts it; a non-matching search excludes it.
    let total = repo.count_by_project(project_id, None).await.unwrap();
    assert!(total >= 1, "unfiltered count should see the saved memory");
    let count_hit = repo
        .count_by_project(project_id, Some("portable"))
        .await
        .unwrap();
    assert!(count_hit >= 1, "search count should match the saved memory");
    let count_miss = repo
        .count_by_project(project_id, Some("no_such_token_zzz"))
        .await
        .unwrap();
    assert_eq!(count_miss, 0, "non-matching search count is zero");

    // The row is byte-compatible with what Python expects: assert the DB-required
    // columns the core doesn't model were populated with valid defaults.
    let (relationships, is_public, proc_status): (String, bool, String) = sqlx::query_as(
        "SELECT relationships::text, is_public, processing_status FROM memories WHERE id = $1",
    )
    .bind(id)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(relationships, "[]");
    assert!(!is_public);
    assert_eq!(proc_status, "COMPLETED");

    // delete
    assert!(repo.delete(id).await.unwrap());
    assert!(repo.find_by_id(id).await.unwrap().is_none());
}

#[tokio::test]
async fn project_sandbox_repository_roundtrips_against_shared_schema() {
    let Some(pool) =
        pool_or_skip("project_sandbox_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    sqlx::query(
        "INSERT INTO users (id, email) VALUES ('u_sandbox_pg', 'sandbox@x') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ('t_sandbox_pg', 'Sandbox T') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_sandbox_pg', 't_sandbox_pg', 'Sandbox P', 'u_sandbox_pg') \
         ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_sandbox_pg_2', 't_sandbox_pg', 'Sandbox P2', 'u_sandbox_pg') \
         ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "DELETE FROM project_sandboxes \
         WHERE project_id IN ('p_sandbox_pg', 'p_sandbox_pg_2') \
            OR sandbox_id IN ('sandbox_pg_1', 'sandbox_pg_2', 'sandbox_pg_3')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgProjectSandboxRepository::new(pool.clone());
    let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
    let accessed_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 5, 5).unwrap();
    let saved = repo
        .upsert(ProjectSandboxRecord {
            id: "ps_sandbox_pg".to_string(),
            project_id: "p_sandbox_pg".to_string(),
            tenant_id: "t_sandbox_pg".to_string(),
            sandbox_id: "sandbox_pg_1".to_string(),
            sandbox_type: "cloud".to_string(),
            status: "creating".to_string(),
            created_at,
            started_at: None,
            last_accessed_at: accessed_at,
            health_checked_at: None,
            error_message: None,
            metadata_json: json!({ "profile": "lite" }),
            local_config: json!({}),
        })
        .await
        .unwrap();
    assert_eq!(saved.project_id, "p_sandbox_pg");
    assert_eq!(saved.status, "creating");
    assert_eq!(saved.metadata_json["profile"], "lite");

    let fetched = repo
        .find_by_project("p_sandbox_pg")
        .await
        .unwrap()
        .expect("sandbox association present");
    assert_eq!(fetched.sandbox_id, "sandbox_pg_1");
    assert_eq!(fetched.sandbox_type, "cloud");

    let started_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 6, 5).unwrap();
    let updated = repo
        .upsert(ProjectSandboxRecord {
            sandbox_id: "sandbox_pg_2".to_string(),
            status: "running".to_string(),
            started_at: Some(started_at),
            last_accessed_at: started_at,
            health_checked_at: Some(started_at),
            ..fetched
        })
        .await
        .unwrap();
    assert_eq!(updated.sandbox_id, "sandbox_pg_2");
    assert_eq!(updated.status, "running");
    assert_eq!(updated.started_at, Some(started_at));

    let by_sandbox = repo
        .find_by_sandbox("sandbox_pg_2")
        .await
        .unwrap()
        .expect("sandbox lookup present");
    assert_eq!(by_sandbox.project_id, "p_sandbox_pg");

    let second_created_at = Utc.with_ymd_and_hms(2026, 1, 2, 4, 0, 0).unwrap();
    repo.upsert(ProjectSandboxRecord {
        id: "ps_sandbox_pg_2".to_string(),
        project_id: "p_sandbox_pg_2".to_string(),
        tenant_id: "t_sandbox_pg".to_string(),
        sandbox_id: "sandbox_pg_3".to_string(),
        sandbox_type: "cloud".to_string(),
        status: "error".to_string(),
        created_at: second_created_at,
        started_at: None,
        last_accessed_at: second_created_at,
        health_checked_at: Some(second_created_at),
        error_message: Some("boom".to_string()),
        metadata_json: json!({ "profile": "standard" }),
        local_config: json!({}),
    })
    .await
    .unwrap();

    let listed = repo
        .list_by_tenant("t_sandbox_pg", None, 10, 0)
        .await
        .unwrap();
    assert_eq!(
        listed
            .iter()
            .map(|sandbox| sandbox.project_id.as_str())
            .collect::<Vec<_>>(),
        vec!["p_sandbox_pg_2", "p_sandbox_pg"]
    );

    let running = repo
        .list_by_tenant("t_sandbox_pg", Some("running"), 10, 0)
        .await
        .unwrap();
    assert_eq!(running.len(), 1);
    assert_eq!(running[0].sandbox_id, "sandbox_pg_2");

    let page = repo
        .list_by_tenant("t_sandbox_pg", None, 1, 1)
        .await
        .unwrap();
    assert_eq!(page.len(), 1);
    assert_eq!(page[0].project_id, "p_sandbox_pg");

    assert!(repo.delete_by_project("p_sandbox_pg").await.unwrap());
    assert!(repo.delete_by_project("p_sandbox_pg_2").await.unwrap());
    assert!(repo
        .find_by_project("p_sandbox_pg")
        .await
        .unwrap()
        .is_none());
}

#[tokio::test]
async fn share_repository_matches_python_memory_shares_lifecycle() {
    let Some(pool) = pool_or_skip("share_repository_matches_python_memory_shares_lifecycle").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    for (id, email) in [
        ("u_share_author", "author@x"),
        ("u_share_target", "target@x"),
        ("u_share_admin", "admin@x"),
    ] {
        sqlx::query("INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT DO NOTHING")
            .bind(id)
            .bind(email)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ('t_share', 'Share T') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_share', 't_share', 'Share P', 'u_share_author') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ('u_share_author', 'p_share', 'owner') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ('u_share_admin', 'p_share', 'admin') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();

    let memory_id = "m_share_pg";
    let share_id = "s_share_pg";
    sqlx::query("DELETE FROM memory_shares WHERE memory_id = $1 OR id = $2")
        .bind(memory_id)
        .bind(share_id)
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM memories WHERE id = $1")
        .bind(memory_id)
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO memories \
            (id, project_id, title, content, content_type, tags, entities, relationships, \
             version, author_id, collaborators, is_public, status, processing_status, meta) \
         VALUES \
            ($1, 'p_share', 'Shared memory', 'share content', 'text', \
             '[\"rust\",\"share\"]'::json, '[]'::json, '[]'::json, 1, \
             'u_share_author', '[]'::json, false, 'ENABLED', 'COMPLETED', '{}'::json)",
    )
    .bind(memory_id)
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgShareRepository::new(pool.clone());
    let memory = repo
        .find_memory(memory_id)
        .await
        .unwrap()
        .expect("share memory exists");
    assert_eq!(memory.author_id, "u_share_author");
    assert_eq!(memory.tags, json!(["rust", "share"]));
    assert!(repo.user_exists("u_share_target").await.unwrap());
    assert!(repo.project_exists("p_share").await.unwrap());
    assert!(repo
        .user_can_admin_project("u_share_admin", "p_share")
        .await
        .unwrap());
    assert!(!repo
        .user_can_admin_project("u_share_target", "p_share")
        .await
        .unwrap());

    let created = repo
        .create_share(NewShareRecord {
            id: share_id.into(),
            memory_id: memory_id.into(),
            share_token: "share_pg_token".into(),
            shared_with_user_id: Some("u_share_target".into()),
            shared_with_project_id: None,
            permissions: json!({"view": true, "edit": false}),
            shared_by: "u_share_author".into(),
            expires_at: None,
        })
        .await
        .unwrap();
    assert_eq!(created.memory_id, memory_id);
    assert_eq!(created.share_token.as_deref(), Some("share_pg_token"));
    assert_eq!(created.permissions, json!({"view": true, "edit": false}));
    assert_eq!(created.access_count, 0);
    assert!(repo
        .explicit_target_share_exists(memory_id, "user", "u_share_target")
        .await
        .unwrap());

    let listed = repo.list_for_memory(memory_id).await.unwrap();
    assert!(listed.iter().any(|s| s.id == share_id));
    let by_token = repo
        .find_share_by_token("share_pg_token")
        .await
        .unwrap()
        .expect("share by token");
    assert_eq!(by_token.id, share_id);

    repo.increment_access_count(share_id).await.unwrap();
    let touched = repo
        .find_share_by_id(share_id)
        .await
        .unwrap()
        .expect("share after access");
    assert_eq!(touched.access_count, 1);

    assert!(repo.delete_share(share_id).await.unwrap());
    assert!(repo.find_share_by_id(share_id).await.unwrap().is_none());
}

#[tokio::test]
async fn skill_repository_roundtrips_against_shared_schema() {
    let Some(pool) = pool_or_skip("skill_repository_roundtrips_against_shared_schema").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    for sql in [
        "DELETE FROM skill_versions WHERE skill_id IN ('skill_pg_1', 'skill_pg_project')",
        "DELETE FROM skills WHERE id IN ('skill_pg_1', 'skill_pg_project') OR tenant_id = 't_skill_pg'",
        "DELETE FROM user_projects WHERE project_id = 'p_skill_pg' OR user_id LIKE 'u_skill_%'",
        "DELETE FROM projects WHERE id = 'p_skill_pg'",
        "DELETE FROM user_tenants WHERE tenant_id = 't_skill_pg' OR user_id LIKE 'u_skill_%'",
        "DELETE FROM tenants WHERE id = 't_skill_pg'",
        "DELETE FROM users WHERE id IN ('u_skill_admin', 'u_skill_member', 'u_skill_viewer')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    for (user_id, email) in [
        ("u_skill_admin", "skill-admin@x"),
        ("u_skill_member", "skill-member@x"),
        ("u_skill_viewer", "skill-viewer@x"),
    ] {
        sqlx::query("INSERT INTO users (id, email) VALUES ($1, $2)")
            .bind(user_id)
            .bind(email)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_skill_pg', 'Skill T')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_skill_admin', 'u_skill_admin', 't_skill_pg', 'admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_skill_pg', 't_skill_pg', 'Skill P', 'u_skill_admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    for (user_id, role) in [("u_skill_member", "member"), ("u_skill_viewer", "viewer")] {
        sqlx::query("INSERT INTO user_projects (user_id, project_id, role) VALUES ($1, $2, $3)")
            .bind(user_id)
            .bind("p_skill_pg")
            .bind(role)
            .execute(&pool)
            .await
            .unwrap();
    }

    let repo = PgSkillRepository::new(pool.clone());
    assert_eq!(
        repo.first_tenant_for_user("u_skill_admin").await.unwrap(),
        Some("t_skill_pg".to_string())
    );
    assert!(repo
        .user_has_tenant_access("u_skill_admin", "t_skill_pg")
        .await
        .unwrap());
    assert!(repo
        .user_is_tenant_admin("u_skill_admin", "t_skill_pg")
        .await
        .unwrap());
    assert!(repo
        .user_can_access_project(
            "u_skill_member",
            "t_skill_pg",
            "p_skill_pg",
            SkillProjectAccess::Write,
        )
        .await
        .unwrap());
    assert!(!repo
        .user_can_access_project(
            "u_skill_viewer",
            "t_skill_pg",
            "p_skill_pg",
            SkillProjectAccess::Write,
        )
        .await
        .unwrap());
    assert!(repo
        .user_can_access_project(
            "u_skill_viewer",
            "t_skill_pg",
            "p_skill_pg",
            SkillProjectAccess::Read,
        )
        .await
        .unwrap());

    let created_at = Utc.with_ymd_and_hms(2026, 2, 3, 4, 5, 6).unwrap();
    let skill = SkillRecord {
        id: "skill_pg_1".to_string(),
        tenant_id: "t_skill_pg".to_string(),
        project_id: None,
        name: "code-review".to_string(),
        description: "Review code changes".to_string(),
        tools: vec!["read_file".to_string()],
        status: "active".to_string(),
        metadata_json: Some(json!({ "agentskills": { "license": "MIT" } })),
        created_at,
        updated_at: Some(created_at),
        scope: "tenant".to_string(),
        is_system_skill: false,
        full_content: Some("---\nname: code-review\n---\nReview code changes.".to_string()),
        resource_files: json!({ "README.md": "resource details" }),
        license: Some("MIT".to_string()),
        compatibility: Some("codex>=1".to_string()),
        allowed_tools_raw: Some("Read Grep".to_string()),
        spec_version: "1.0".to_string(),
        current_version: 0,
        version_label: Some("draft".to_string()),
    };

    let created = repo.create_skill(&skill).await.unwrap();
    assert_eq!(created.tools, vec!["read_file"]);
    assert_eq!(created.resource_files["README.md"], "resource details");

    let fetched = repo
        .get_skill("skill_pg_1")
        .await
        .unwrap()
        .expect("skill present");
    assert_eq!(fetched.name, "code-review");
    assert_eq!(fetched.tools, vec!["read_file"]);
    assert_eq!(fetched.license.as_deref(), Some("MIT"));

    let found = repo
        .find_skill("t_skill_pg", "code-review", "tenant", None)
        .await
        .unwrap()
        .expect("skill found by natural key");
    assert_eq!(found.id, "skill_pg_1");

    let project_skill = SkillRecord {
        id: "skill_pg_project".to_string(),
        project_id: Some("p_skill_pg".to_string()),
        name: "project-helper".to_string(),
        description: "Project scoped helper".to_string(),
        scope: "project".to_string(),
        full_content: Some("Project helper".to_string()),
        ..skill.clone()
    };
    repo.create_skill(&project_skill).await.unwrap();

    let tenant_list = repo
        .list_for_tenant("t_skill_pg", Some("active"), Some("tenant"), None, 10, 0)
        .await
        .unwrap();
    assert_eq!(tenant_list.len(), 1);
    assert_eq!(tenant_list[0].id, "skill_pg_1");

    let project_visible = repo
        .list_for_tenant("t_skill_pg", None, None, Some("p_skill_pg"), 10, 0)
        .await
        .unwrap();
    assert!(project_visible
        .iter()
        .any(|record| record.id == "skill_pg_1"));
    assert!(project_visible
        .iter()
        .any(|record| record.id == "skill_pg_project"));

    let updated_at = Utc.with_ymd_and_hms(2026, 2, 3, 5, 5, 6).unwrap();
    let updated = SkillUpdateRecord {
        description: Some("Review code and tests".to_string()),
        tools: Some(vec!["read_file".to_string(), "grep".to_string()]),
        full_content: Some(Some("Updated skill content".to_string())),
        current_version: Some(1),
        version_label: Some(Some("v1".to_string())),
        ..Default::default()
    }
    .apply_to(fetched, updated_at);
    let updated = repo.update_skill(&updated).await.unwrap();
    assert_eq!(updated.description, "Review code and tests");
    assert_eq!(updated.tools, vec!["read_file", "grep"]);
    assert_eq!(updated.current_version, 1);
    assert_eq!(updated.updated_at, Some(updated_at));

    let version = SkillVersionRecord {
        id: "skillver_pg_1".to_string(),
        skill_id: "skill_pg_1".to_string(),
        version_number: 1,
        version_label: Some("v1".to_string()),
        skill_md_content: "Updated skill content".to_string(),
        resource_files: json!({ "README.md": "v1 resource details" }),
        change_summary: Some("Manual content update".to_string()),
        created_by: "agent".to_string(),
        created_at: updated_at,
    };
    repo.create_version(&version).await.unwrap();
    assert_eq!(repo.max_version_number("skill_pg_1").await.unwrap(), 1);
    assert_eq!(repo.count_versions("skill_pg_1").await.unwrap(), 1);
    let versions = repo.list_versions("skill_pg_1", 10, 0).await.unwrap();
    assert_eq!(versions.len(), 1);
    assert_eq!(versions[0].version_label.as_deref(), Some("v1"));
    let fetched_version = repo
        .get_version("skill_pg_1", 1)
        .await
        .unwrap()
        .expect("version present");
    assert_eq!(fetched_version.skill_md_content, "Updated skill content");
    assert_eq!(
        fetched_version.resource_files["README.md"],
        "v1 resource details"
    );
    let latest_version = repo
        .get_latest_version("skill_pg_1")
        .await
        .unwrap()
        .expect("latest version present");
    assert_eq!(latest_version.version_number, 1);
    assert_eq!(latest_version.skill_md_content, "Updated skill content");

    assert!(repo.delete_skill("skill_pg_project").await.unwrap());
    assert!(repo.delete_skill("skill_pg_1").await.unwrap());
    sqlx::query("DELETE FROM skill_versions WHERE skill_id IN ('skill_pg_1', 'skill_pg_project')")
        .execute(&pool)
        .await
        .unwrap();
    assert!(repo.get_skill("skill_pg_1").await.unwrap().is_none());
}

#[tokio::test]
async fn trust_repository_matches_python_governance_lifecycle() {
    let Some(pool) = pool_or_skip("trust_repository_matches_python_governance_lifecycle").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_trust_tables(&pool).await;

    for sql in [
        "DELETE FROM trust_policies WHERE tenant_id = 't_trust_pg'",
        "DELETE FROM decision_records WHERE tenant_id = 't_trust_pg'",
        "DELETE FROM workspaces WHERE id = 'w_trust_pg'",
        "DELETE FROM user_tenants WHERE tenant_id = 't_trust_pg'",
        "DELETE FROM projects WHERE id = 'p_trust_pg'",
        "DELETE FROM tenants WHERE id = 't_trust_pg'",
        "DELETE FROM users WHERE id IN ('u_trust_admin', 'u_trust_member', 'u_trust_super')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    for (user_id, email, is_superuser) in [
        ("u_trust_admin", "admin-trust@x", false),
        ("u_trust_member", "member-trust@x", false),
        ("u_trust_super", "super-trust@x", true),
    ] {
        sqlx::query("INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3)")
            .bind(user_id)
            .bind(email)
            .bind(is_superuser)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_trust_pg', 'Trust T')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_trust_pg', 't_trust_pg', 'Trust P', 'u_trust_admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO workspaces (id, tenant_id, project_id, name, created_by) \
         VALUES ('w_trust_pg', 't_trust_pg', 'p_trust_pg', 'Trust W', 'u_trust_admin')",
    )
    .execute(&pool)
    .await
    .unwrap();
    for (id, user_id, role) in [
        ("ut_trust_admin", "u_trust_admin", "admin"),
        ("ut_trust_member", "u_trust_member", "member"),
    ] {
        sqlx::query(
            "INSERT INTO user_tenants (id, user_id, tenant_id, role) VALUES ($1, $2, $3, $4)",
        )
        .bind(id)
        .bind(user_id)
        .bind("t_trust_pg")
        .bind(role)
        .execute(&pool)
        .await
        .unwrap();
    }

    let repo = PgTrustRepository::new(pool.clone());
    assert_eq!(
        repo.tenant_access_status("u_trust_admin", "t_trust_pg", true)
            .await
            .unwrap(),
        TenantAccessStatus::Authorized
    );
    assert_eq!(
        repo.tenant_access_status("u_trust_member", "t_trust_pg", false)
            .await
            .unwrap(),
        TenantAccessStatus::Authorized
    );
    assert_eq!(
        repo.tenant_access_status("u_trust_member", "t_trust_pg", true)
            .await
            .unwrap(),
        TenantAccessStatus::NotAdmin
    );
    assert_eq!(
        repo.tenant_access_status("u_trust_super", "t_trust_pg", true)
            .await
            .unwrap(),
        TenantAccessStatus::Authorized
    );
    assert_eq!(
        repo.tenant_access_status("u_trust_admin", "missing_trust_pg", false)
            .await
            .unwrap(),
        TenantAccessStatus::TenantNotFound
    );
    assert!(repo
        .workspace_exists_in_tenant("t_trust_pg", "w_trust_pg")
        .await
        .unwrap());
    assert!(!repo
        .workspace_exists_in_tenant("t_trust_pg", "missing_workspace")
        .await
        .unwrap());

    let now = Utc::now();
    let policy = repo
        .create_policy(NewTrustPolicyRecord {
            id: "tp_trust_pg".into(),
            tenant_id: "t_trust_pg".into(),
            workspace_id: "w_trust_pg".into(),
            agent_instance_id: "agent_trust_pg".into(),
            action_type: "terminal.execute".into(),
            granted_by: "u_trust_admin".into(),
            grant_type: "always".into(),
            created_at: now,
        })
        .await
        .unwrap();
    assert_eq!(policy.workspace_id, "w_trust_pg");
    assert!(repo
        .check_always_trust("w_trust_pg", "agent_trust_pg", "terminal.execute")
        .await
        .unwrap());
    assert!(!repo
        .check_always_trust("w_trust_pg", "agent_trust_pg", "browser.open")
        .await
        .unwrap());
    let policies = repo.list_policies("w_trust_pg", None).await.unwrap();
    assert!(policies.iter().any(|p| p.id == "tp_trust_pg"));
    let agent_policies = repo
        .list_policies("w_trust_pg", Some("agent_trust_pg"))
        .await
        .unwrap();
    assert!(agent_policies.iter().any(|p| p.id == "tp_trust_pg"));

    let decision = repo
        .create_decision(NewDecisionRecordRecord {
            id: "dr_trust_pg".into(),
            tenant_id: "t_trust_pg".into(),
            workspace_id: "w_trust_pg".into(),
            agent_instance_id: "agent_trust_pg".into(),
            decision_type: "browser.open".into(),
            context_summary: Some("Open a browser".into()),
            proposal: json!({"url": "https://example.test"}),
            outcome: "pending".into(),
            created_at: now,
        })
        .await
        .unwrap();
    assert_eq!(decision.outcome, "pending");
    assert_eq!(decision.proposal, json!({"url": "https://example.test"}));
    assert!(repo.find_decision("dr_trust_pg").await.unwrap().is_some());
    let listed = repo
        .list_decisions("w_trust_pg", Some("agent_trust_pg"), Some("browser.open"))
        .await
        .unwrap();
    assert!(listed.iter().any(|r| r.id == "dr_trust_pg"));

    let resolved_at = Utc::now();
    let resolved = repo
        .resolve_decision(TrustDecisionResolution {
            record_id: "dr_trust_pg",
            reviewer_id: "u_trust_admin",
            review_type: "human",
            review_comment: "Allowed always — trust policy created",
            outcome: "success",
            resolved_at,
            new_policy: Some(NewTrustPolicyRecord {
                id: "tp_trust_pg_auto".into(),
                tenant_id: "t_trust_pg".into(),
                workspace_id: "w_trust_pg".into(),
                agent_instance_id: "agent_trust_pg".into(),
                action_type: "browser.open".into(),
                granted_by: "u_trust_admin".into(),
                grant_type: "always".into(),
                created_at: resolved_at,
            }),
        })
        .await
        .unwrap()
        .expect("resolved decision");
    assert_eq!(resolved.outcome, "success");
    assert_eq!(resolved.reviewer_id.as_deref(), Some("u_trust_admin"));
    assert_eq!(resolved.review_type.as_deref(), Some("human"));
    assert_eq!(
        resolved.review_comment.as_deref(),
        Some("Allowed always — trust policy created")
    );
    assert!(resolved.resolved_at.is_some());
    assert!(repo
        .check_always_trust("w_trust_pg", "agent_trust_pg", "browser.open")
        .await
        .unwrap());
    assert!(repo
        .resolve_decision(TrustDecisionResolution {
            record_id: "missing_decision",
            reviewer_id: "u_trust_admin",
            review_type: "human",
            review_comment: "Allowed once",
            outcome: "success",
            resolved_at: Utc::now(),
            new_policy: None,
        },)
        .await
        .unwrap()
        .is_none());
}

#[tokio::test]
async fn vector_index_roundtrips_and_scopes_by_project() {
    let Some(pool) = pool_or_skip("vector_index_roundtrips_and_scopes_by_project").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    let index = PgVectorIndex::new(pool.clone());

    let (pa, pb) = ("p_vec_a", "p_vec_b");
    for p in [pa, pb] {
        sqlx::query("DELETE FROM agistack_memory_vectors WHERE project_id = $1")
            .bind(p)
            .execute(&pool)
            .await
            .unwrap();
    }

    index.upsert(pa, "v1", &[1.0, 0.0, 0.0]).await.unwrap();
    index.upsert(pa, "v2", &[0.0, 1.0, 0.0]).await.unwrap();
    // Same id/vector in a *different* project — must never leak across scope.
    index.upsert(pb, "v1", &[1.0, 0.0, 0.0]).await.unwrap();

    let hits = index.query(pa, &[0.9, 0.1, 0.0], 2).await.unwrap();
    assert_eq!(hits.len(), 2);
    assert_eq!(hits[0].id, "v1", "nearest should be v1");
    assert!(hits[0].score > hits[1].score);

    // Project scoping: querying pb only ever returns pb's ids.
    let pb_hits = index.query(pb, &[1.0, 0.0, 0.0], 10).await.unwrap();
    assert_eq!(pb_hits.len(), 1);
    assert_eq!(pb_hits[0].id, "v1");

    index.remove(pa, "v1").await.unwrap();
    let after = index.query(pa, &[1.0, 0.0, 0.0], 10).await.unwrap();
    assert!(!after.iter().any(|h| h.id == "v1"));
}

#[tokio::test]
async fn checkpoint_store_roundtrips_session_state() {
    let Some(pool) = pool_or_skip("checkpoint_store_roundtrips_session_state").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    let store = PgCheckpointStore::new(pool.clone());

    let sid = "s_pg_ckpt";
    store.delete(sid).await.unwrap();
    assert!(store.load(sid).await.unwrap().is_none());

    let mut state = SessionState::new(sid, "achieve the goal", Some("p_ckpt"));
    state.round = 3;
    state.status = SessionStatus::Running;
    store.save(&state).await.unwrap();

    let loaded = store.load(sid).await.unwrap().expect("checkpoint present");
    assert_eq!(loaded.session_id, sid);
    assert_eq!(loaded.goal, "achieve the goal");
    assert_eq!(loaded.round, 3);

    store.delete(sid).await.unwrap();
    assert!(store.load(sid).await.unwrap().is_none());
}

#[tokio::test]
async fn api_key_and_project_stores_verify_and_scope() {
    let Some(pool) = pool_or_skip("api_key_and_project_stores_verify_and_scope").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    // Seed a user, project, and an api_keys row whose key_hash is the SHA-256 of a
    // known raw key — exactly how Python stores it.
    sqlx::query("INSERT INTO users (id, email) VALUES ('u_auth', 'a@x') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_auth', 'T') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_auth', 't_auth', 'P', 'u_auth') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();

    // sha256("ms_sk_testkey_pg") computed by Python's hashlib.sha256(...).hexdigest().
    let raw_key = "ms_sk_testkey_pg";
    let key_hash = {
        use std::process::Command;
        // Derive via openssl to avoid hardcoding; falls back to a known constant.
        let out = Command::new("sh")
            .arg("-c")
            .arg(format!(
                "printf '%s' '{raw_key}' | shasum -a 256 | cut -d' ' -f1"
            ))
            .output();
        match out {
            Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
            _ => String::new(),
        }
    };
    assert!(!key_hash.is_empty(), "could not compute sha256 for test");

    sqlx::query("DELETE FROM api_keys WHERE id = 'k_auth'")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO api_keys (id, key_hash, name, user_id, is_active) \
         VALUES ('k_auth', $1, 'test', 'u_auth', true)",
    )
    .bind(&key_hash)
    .execute(&pool)
    .await
    .unwrap();

    let keys = PgApiKeyStore::new(pool.clone());
    let now_ms = 1_700_000_000_000;

    // Correct key resolves to the user and is usable.
    let rec = keys
        .find_by_raw_key(raw_key)
        .await
        .unwrap()
        .expect("key found");
    assert_eq!(rec.user_id, "u_auth");
    assert!(rec.is_usable_at(now_ms));

    // Wrong key resolves to nothing.
    assert!(keys.find_by_raw_key("ms_sk_wrong").await.unwrap().is_none());

    // Project scope + access.
    let projects = PgProjectStore::new(pool.clone());
    let proj = projects
        .find_by_id("p_auth")
        .await
        .unwrap()
        .expect("project found");
    assert_eq!(proj.tenant_id, "t_auth");
    assert!(projects.user_can_access("u_auth", &proj).await.unwrap()); // owner
    assert!(!projects.user_can_access("u_other", &proj).await.unwrap()); // no membership
}

/// Additively extend the minimal `users`/`tenants` tables with the identity
/// columns the P2 adapters read, and create `user_tenants`. `ADD COLUMN IF NOT
/// EXISTS` keeps this idempotent and compatible with the memory/auth tests that
/// created the base tables — it never drops or rewrites existing columns.
async fn ensure_identity_tables(pool: &PgPool) {
    for ddl in [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password text",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name text",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superuser boolean DEFAULT false",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password boolean DEFAULT false",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS slug text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS description text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS owner_id text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan text DEFAULT 'free'",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_projects integer DEFAULT 10",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_users integer DEFAULT 5",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_storage bigint DEFAULT 1073741824",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS updated_at timestamptz",
        "CREATE TABLE IF NOT EXISTS user_tenants (\
            id text PRIMARY KEY, user_id text NOT NULL, tenant_id text NOT NULL, \
            role text DEFAULT 'member', created_at timestamptz DEFAULT now())",
        "ALTER TABLE user_tenants ADD COLUMN IF NOT EXISTS permissions json DEFAULT '{}'::json",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("identity ddl failed: {ddl}\n{e}"));
    }
}

async fn ensure_project_read_tables(pool: &PgPool) {
    for ddl in [
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS description text",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS memory_rules json DEFAULT '{}'::json",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS graph_config json DEFAULT '{}'::json",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS graph_store_id text",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS retrieval_store_id text",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS sandbox_type text DEFAULT 'cloud'",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS sandbox_config json DEFAULT '{}'::json",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS agent_conversation_mode text DEFAULT 'single_agent'",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at timestamptz",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS id text",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS permissions json DEFAULT '{}'::json",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()",
        "CREATE TABLE IF NOT EXISTS conversations (\
            id text PRIMARY KEY, project_id text NOT NULL, tenant_id text NOT NULL, \
            user_id text NOT NULL, title varchar(500) NOT NULL, status varchar(20) DEFAULT 'active', \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS parent_conversation_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS fork_source_id text",
        "CREATE TABLE IF NOT EXISTS messages (\
            id text PRIMARY KEY, conversation_id text NOT NULL, reply_to_id text, \
            content text, created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS workspaces (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL, \
            name varchar(255) NOT NULL, description text, created_by text NOT NULL, \
            is_archived boolean DEFAULT false, metadata_json json DEFAULT '{}'::json, \
            office_status text DEFAULT 'inactive', hex_layout_config_json json DEFAULT '{}'::json, \
            default_blocking_categories_json json DEFAULT '[]'::json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS project_delete_audit_entries (\
            id text PRIMARY KEY, project_id text NOT NULL REFERENCES projects(id))",
        "CREATE TABLE IF NOT EXISTS project_delete_audit_children (\
            id text PRIMARY KEY, entry_id text NOT NULL REFERENCES project_delete_audit_entries(id))",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("project read ddl failed: {ddl}\n{e}"));
    }
}

async fn ensure_tenant_delete_tables(pool: &PgPool) {
    ensure_project_read_tables(pool).await;
    for ddl in [
        "CREATE TABLE IF NOT EXISTS tenant_delete_audit_entries (\
            id text PRIMARY KEY, tenant_id text NOT NULL REFERENCES tenants(id))",
        "CREATE TABLE IF NOT EXISTS tenant_delete_audit_children (\
            id text PRIMARY KEY, entry_id text NOT NULL REFERENCES tenant_delete_audit_entries(id))",
        "CREATE TABLE IF NOT EXISTS tenant_delete_loose_notes (\
            id text PRIMARY KEY, tenant_id text NOT NULL, note text)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("tenant delete ddl failed: {ddl}\n{e}"));
    }
}

async fn ensure_invitation_tables(pool: &PgPool) {
    for ddl in [
        "CREATE TABLE IF NOT EXISTS invitations (\
            id text PRIMARY KEY, tenant_id text NOT NULL, email text NOT NULL, role text DEFAULT 'member', \
            token text NOT NULL, status text DEFAULT 'pending', invited_by text NOT NULL, \
            accepted_by text, expires_at timestamptz NOT NULL, created_at timestamptz DEFAULT now(), \
            deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_invitations_tenant ON invitations (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_invitations_token ON invitations (token)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("invitation ddl failed: {ddl}\n{e}"));
    }
}

async fn ensure_trust_tables(pool: &PgPool) {
    ensure_identity_tables(pool).await;
    for ddl in [
        "CREATE TABLE IF NOT EXISTS workspaces (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL, \
            name varchar(255) NOT NULL, description text, created_by text NOT NULL, \
            is_archived boolean DEFAULT false, metadata_json json DEFAULT '{}'::json, \
            office_status text DEFAULT 'inactive', hex_layout_config_json json DEFAULT '{}'::json, \
            default_blocking_categories_json json DEFAULT '[]'::json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS trust_policies (\
            id text PRIMARY KEY, tenant_id text NOT NULL, workspace_id text NOT NULL, \
            agent_instance_id text NOT NULL, action_type text NOT NULL, granted_by text NOT NULL, \
            grant_type text NOT NULL, created_at timestamptz DEFAULT now(), deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_trust_policies_tenant_ws \
            ON trust_policies (tenant_id, workspace_id)",
        "CREATE TABLE IF NOT EXISTS decision_records (\
            id text PRIMARY KEY, tenant_id text NOT NULL, workspace_id text NOT NULL, \
            agent_instance_id text NOT NULL, decision_type text NOT NULL, context_summary text, \
            proposal json DEFAULT '{}'::json, outcome text DEFAULT 'pending', reviewer_id text, \
            review_type text, review_comment text, resolved_at timestamptz, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_decision_records_tenant_ws \
            ON decision_records (tenant_id, workspace_id)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("trust ddl failed: {ddl}\n{e}"));
    }
}

#[tokio::test]
async fn project_store_splits_read_write_and_admin_access() {
    let Some(pool) = pool_or_skip("project_store_splits_read_write_and_admin_access").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;

    for sql in [
        "DELETE FROM user_tenants WHERE user_id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
        "DELETE FROM user_projects WHERE user_id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
        "DELETE FROM projects WHERE id IN \
         ('p_owned_authz', 'p_viewer_authz', 'p_admin_authz', 'p_public_authz', 'p_tenant_authz')",
        "DELETE FROM tenants WHERE id = 't_authz'",
        "DELETE FROM users WHERE id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_authz', 'T')")
        .execute(&pool)
        .await
        .unwrap();
    for user_id in [
        "u_owner_authz",
        "u_viewer_authz",
        "u_admin_authz",
        "u_public_authz",
        "u_tenant_authz",
    ] {
        sqlx::query("INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, false)")
            .bind(user_id)
            .bind(format!("{user_id}@x"))
            .execute(&pool)
            .await
            .unwrap();
    }
    for (project_id, is_public) in [
        ("p_owned_authz", false),
        ("p_viewer_authz", false),
        ("p_admin_authz", false),
        ("p_public_authz", true),
        ("p_tenant_authz", false),
    ] {
        sqlx::query(
            "INSERT INTO projects (id, tenant_id, name, owner_id, is_public) \
             VALUES ($1, 't_authz', $2, 'u_owner_authz', $3)",
        )
        .bind(project_id)
        .bind(project_id)
        .bind(is_public)
        .execute(&pool)
        .await
        .unwrap();
    }
    for (user_id, project_id, role) in [
        ("u_viewer_authz", "p_viewer_authz", "viewer"),
        ("u_admin_authz", "p_admin_authz", "admin"),
    ] {
        sqlx::query("INSERT INTO user_projects (user_id, project_id, role) VALUES ($1, $2, $3)")
            .bind(user_id)
            .bind(project_id)
            .bind(role)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_authz', 'u_tenant_authz', 't_authz', 'owner')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let projects = PgProjectStore::new(pool.clone());

    let owned = projects
        .find_by_id("p_owned_authz")
        .await
        .unwrap()
        .expect("owned project");
    assert!(projects
        .user_can_access("u_owner_authz", &owned)
        .await
        .unwrap());
    assert!(projects
        .user_can_write("u_owner_authz", &owned)
        .await
        .unwrap());
    assert!(projects
        .user_can_admin("u_owner_authz", &owned)
        .await
        .unwrap());

    let viewer = projects
        .find_by_id("p_viewer_authz")
        .await
        .unwrap()
        .expect("viewer project");
    assert!(projects
        .user_can_access("u_viewer_authz", &viewer)
        .await
        .unwrap());
    assert!(!projects
        .user_can_write("u_viewer_authz", &viewer)
        .await
        .unwrap());
    assert!(!projects
        .user_can_admin("u_viewer_authz", &viewer)
        .await
        .unwrap());

    let admin = projects
        .find_by_id("p_admin_authz")
        .await
        .unwrap()
        .expect("admin project");
    assert!(projects
        .user_can_access("u_admin_authz", &admin)
        .await
        .unwrap());
    assert!(projects
        .user_can_write("u_admin_authz", &admin)
        .await
        .unwrap());
    assert!(projects
        .user_can_admin("u_admin_authz", &admin)
        .await
        .unwrap());

    let public = projects
        .find_by_id("p_public_authz")
        .await
        .unwrap()
        .expect("public project");
    assert!(projects
        .user_can_access("u_public_authz", &public)
        .await
        .unwrap());
    assert!(!projects
        .user_can_write("u_public_authz", &public)
        .await
        .unwrap());
    assert!(!projects
        .user_can_admin("u_public_authz", &public)
        .await
        .unwrap());

    let tenant = projects
        .find_by_id("p_tenant_authz")
        .await
        .unwrap()
        .expect("tenant project");
    assert!(projects
        .user_can_admin("u_tenant_authz", &tenant)
        .await
        .unwrap());
}

/// P2 login vertical: prove the store-level round-trip against the shared schema.
/// 1. `find_auth_by_email` returns the Python-shaped auth record.
/// 2. `insert_api_key` (mint on login) writes a key that `find_by_raw_key` then
///    resolves — this exercises the exact SHA-256 digest parity the two sides
///    share (mint hashes the plaintext; auth hashes the presented raw key).
/// 3. `PgTenantRepository` scopes tenant reads by membership (count/list/get with
///    404-then-403 ordering).
#[tokio::test]
async fn login_and_tenant_reads_roundtrip_against_shared_schema() {
    let Some(pool) = pool_or_skip("login_and_tenant_reads_roundtrip_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    ensure_tenant_delete_tables(&pool).await;

    // Clean any prior run for a deterministic assertion set.
    for sql in [
        "DELETE FROM tenant_delete_audit_children WHERE id = 'tenant_audit_child'",
        "DELETE FROM tenant_delete_audit_entries \
         WHERE id = 'tenant_audit_entry' OR tenant_id = 't_p2_delete'",
        "DELETE FROM tenant_delete_loose_notes WHERE tenant_id = 't_p2_delete'",
        "DELETE FROM project_delete_audit_children WHERE id = 'tenant_project_audit_child'",
        "DELETE FROM project_delete_audit_entries \
         WHERE id = 'tenant_project_audit_entry' OR project_id = 'p_p2_delete'",
        "DELETE FROM messages WHERE id = 'msg_tenant_delete' OR conversation_id = 'c_tenant_delete'",
        "DELETE FROM conversations \
         WHERE id = 'c_tenant_delete' OR project_id = 'p_p2_delete' OR tenant_id = 't_p2_delete'",
        "DELETE FROM workspaces \
         WHERE id = 'w_tenant_delete' OR project_id = 'p_p2_delete' OR tenant_id = 't_p2_delete'",
        "DELETE FROM user_projects WHERE project_id = 'p_p2_delete'",
        "DELETE FROM projects WHERE id = 'p_p2_delete' OR tenant_id = 't_p2_delete'",
        "DELETE FROM user_tenants WHERE user_id IN ('u_p2', 'u_p2_target') \
         OR tenant_id IN ('t_p2_created', 't_p2_member', 't_p2_other', 't_p2_delete')",
        "DELETE FROM api_keys WHERE user_id = 'u_p2'",
        "DELETE FROM tenants WHERE id IN ('t_p2_created', 't_p2_member', 't_p2_other', 't_p2_delete')",
        "DELETE FROM users WHERE id IN ('u_p2', 'u_p2_target')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    // A user with a Python-stored bcrypt hash (the real `userpassword` vector).
    let stored_hash = "$2b$12$7zqrguT7EVNDjaBFQ03ITe6Q5Y1YiOL6Vu45Q6rjaLF3VfNYU/VD6";
    sqlx::query(
        "INSERT INTO users (id, email, full_name, hashed_password, is_active, is_superuser, \
         must_change_password) VALUES ('u_p2', 'p2@memstack.ai', 'P2 User', $1, true, false, false)",
    )
    .bind(stored_hash)
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO users (id, email, full_name, is_active, is_superuser) \
         VALUES ('u_p2_target', 'target-p2@memstack.ai', 'P2 Target', true, false)",
    )
    .execute(&pool)
    .await
    .unwrap();

    let users = PgUserStore::new(pool.clone());

    // (1) Auth lookup returns the shaped record.
    let rec = users
        .find_auth_by_email("p2@memstack.ai")
        .await
        .unwrap()
        .expect("user found");
    assert_eq!(rec.id, "u_p2");
    assert_eq!(rec.hashed_password, stored_hash);
    assert!(rec.is_active);
    assert!(!rec.is_superuser);
    assert!(users
        .find_auth_by_email("missing@x")
        .await
        .unwrap()
        .is_none());

    // (2) Mint a key exactly as login does, then resolve it via the auth store.
    let raw_key = "ms_sk_p2_login_session_key_0000000000000000000000000000000000000000";
    users
        .insert_api_key(
            "k_p2",
            raw_key,
            "Login Session p2@memstack.ai",
            "u_p2",
            None,
            &["read".to_string(), "write".to_string()],
        )
        .await
        .unwrap();
    let keys = PgApiKeyStore::new(pool.clone());
    let resolved = keys
        .find_by_raw_key(raw_key)
        .await
        .unwrap()
        .expect("minted key resolves");
    assert_eq!(resolved.user_id, "u_p2");
    assert!(resolved.is_usable_at(1_700_000_000_000));

    // (3) Tenant membership scoping.
    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) \
         VALUES ('t_p2_member', 'Member Tenant', 'member-tenant', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) \
         VALUES ('t_p2_other', 'Other Tenant', 'other-tenant', 'u_other')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_p2', 'u_p2', 't_p2_member', 'admin')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let tenants = PgTenantRepository::new(pool.clone());
    assert_eq!(tenants.count_for_user("u_p2", None).await.unwrap(), 1);
    let page = tenants.list_for_user("u_p2", None, 0, 20).await.unwrap();
    assert_eq!(page.len(), 1);
    assert_eq!(page[0].id, "t_p2_member");
    assert_eq!(page[0].slug, "member-tenant");

    // Found (member), by id and by slug.
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_p2_member").await.unwrap(),
        TenantLookup::Found(t) if t.id == "t_p2_member"
    ));
    assert!(matches!(
        tenants.get_for_user("u_p2", "member-tenant").await.unwrap(),
        TenantLookup::Found(_)
    ));
    // Exists but no membership -> Forbidden (403), not NotFound.
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_p2_other").await.unwrap(),
        TenantLookup::Forbidden
    ));
    // Does not exist -> NotFound (404).
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_nope").await.unwrap(),
        TenantLookup::NotFound
    ));

    // (4) Tenant create/update and member mutations match Python-owned tables.
    let created = tenants
        .create_tenant(
            "t_p2_created",
            "ut_p2_created_owner",
            "u_p2",
            "Acme Corporation",
            Some("Created by Rust"),
            &json!({"admin": true, "create_projects": true, "manage_users": true}),
        )
        .await
        .unwrap();
    assert_eq!(created.slug, "acme-corporation");
    assert_eq!(created.owner_id, "u_p2");
    assert_eq!(created.plan, "free");
    assert_eq!(created.max_projects, 10);
    assert_eq!(created.max_users, 5);

    let owner_membership: (String, serde_json::Value) = sqlx::query_as(
        "SELECT role, permissions FROM user_tenants \
         WHERE tenant_id = 't_p2_created' AND user_id = 'u_p2'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(owner_membership.0, "owner");
    assert_eq!(owner_membership.1["manage_users"], true);

    let updated = tenants
        .update_owned_tenant(
            "u_p2",
            "t_p2_created",
            &TenantUpdatePatch {
                name: Some("Acme Updated".into()),
                description: Some(None),
                plan: Some("enterprise".into()),
                max_projects: Some(20),
                max_users: Some(50),
                max_storage: Some(2_147_483_648),
            },
        )
        .await
        .unwrap()
        .expect("owned tenant update");
    assert_eq!(updated.name, "Acme Updated");
    assert_eq!(updated.slug, "acme-corporation");
    assert_eq!(updated.description, None);
    assert_eq!(updated.plan, "enterprise");
    assert!(tenants
        .update_owned_tenant("u_p2_target", "t_p2_created", &TenantUpdatePatch::default())
        .await
        .unwrap()
        .is_none());

    assert!(tenants.tenant_exists("t_p2_created").await.unwrap());
    assert!(tenants
        .user_owns_tenant("u_p2", "t_p2_created")
        .await
        .unwrap());
    assert!(!tenants
        .user_owns_tenant("u_p2_target", "t_p2_created")
        .await
        .unwrap());
    assert!(tenants.user_exists("u_p2_target").await.unwrap());
    assert!(tenants
        .tenant_member_role("t_p2_created", "u_p2_target")
        .await
        .unwrap()
        .is_none());

    tenants
        .add_tenant_member(
            "ut_p2_created_target",
            "t_p2_created",
            "u_p2_target",
            "editor",
            &json!({"read": true, "write": true}),
        )
        .await
        .unwrap();
    assert_eq!(
        tenants
            .tenant_member_role("t_p2_created", "u_p2_target")
            .await
            .unwrap()
            .expect("tenant membership")
            .role,
        "editor"
    );
    assert!(tenants
        .update_tenant_member(
            "t_p2_created",
            "u_p2_target",
            "owner",
            &json!({"read": true, "write": true}),
        )
        .await
        .unwrap());
    let member_after_update: (String, serde_json::Value) = sqlx::query_as(
        "SELECT role, permissions FROM user_tenants \
         WHERE tenant_id = 't_p2_created' AND user_id = 'u_p2_target'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(member_after_update.0, "owner");
    assert_eq!(member_after_update.1["write"], true);

    assert!(tenants
        .remove_tenant_member("t_p2_created", "u_p2_target")
        .await
        .unwrap());
    assert!(!tenants
        .remove_tenant_member("t_p2_created", "u_p2_target")
        .await
        .unwrap());

    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) \
         VALUES ('t_p2_delete', 'Delete Tenant', 'delete-tenant', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) \
         VALUES ('ut_p2_delete_owner', 'u_p2', 't_p2_delete', 'owner', '{\"manage_users\": true}'::json)",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_p2_delete', 't_p2_delete', 'Tenant Delete Project', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
         VALUES ('up_p2_delete_owner', 'u_p2', 'p_p2_delete', 'owner', '{\"admin\": true}'::json)",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO conversations (id, project_id, tenant_id, user_id, title) \
         VALUES ('c_tenant_delete', 'p_p2_delete', 't_p2_delete', 'u_p2', 'Tenant delete conversation')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO messages (id, conversation_id, content) \
         VALUES ('msg_tenant_delete', 'c_tenant_delete', 'delete me')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO workspaces (id, tenant_id, project_id, name, created_by) \
         VALUES ('w_tenant_delete', 't_p2_delete', 'p_p2_delete', 'Delete workspace', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO project_delete_audit_entries (id, project_id) \
         VALUES ('tenant_project_audit_entry', 'p_p2_delete')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO project_delete_audit_children (id, entry_id) \
         VALUES ('tenant_project_audit_child', 'tenant_project_audit_entry')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenant_delete_audit_entries (id, tenant_id) \
         VALUES ('tenant_audit_entry', 't_p2_delete')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenant_delete_audit_children (id, entry_id) \
         VALUES ('tenant_audit_child', 'tenant_audit_entry')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenant_delete_loose_notes (id, tenant_id, note) \
         VALUES ('tenant_loose_note', 't_p2_delete', 'no physical FK')",
    )
    .execute(&pool)
    .await
    .unwrap();

    assert!(!tenants
        .delete_owned_tenant("u_p2_target", "t_p2_delete")
        .await
        .unwrap());
    assert!(tenants
        .delete_owned_tenant("u_p2", "t_p2_delete")
        .await
        .unwrap());
    assert!(!tenants.tenant_exists("t_p2_delete").await.unwrap());
    for (table, predicate) in [
        ("user_tenants", "tenant_id = 't_p2_delete'"),
        ("projects", "id = 'p_p2_delete'"),
        ("user_projects", "project_id = 'p_p2_delete'"),
        ("conversations", "id = 'c_tenant_delete'"),
        ("messages", "id = 'msg_tenant_delete'"),
        ("workspaces", "id = 'w_tenant_delete'"),
        (
            "project_delete_audit_entries",
            "id = 'tenant_project_audit_entry'",
        ),
        (
            "project_delete_audit_children",
            "id = 'tenant_project_audit_child'",
        ),
        ("tenant_delete_audit_entries", "id = 'tenant_audit_entry'"),
        ("tenant_delete_audit_children", "id = 'tenant_audit_child'"),
        ("tenant_delete_loose_notes", "id = 'tenant_loose_note'"),
    ] {
        let sql = format!("SELECT count(*) FROM {table} WHERE {predicate}");
        let (count,): (i64,) = sqlx::query_as(&sql).fetch_one(&pool).await.unwrap();
        assert_eq!(count, 0, "{table} still has rows matching {predicate}");
    }
}

#[tokio::test]
async fn invitations_roundtrip_against_shared_schema() {
    let Some(pool) = pool_or_skip("invitations_roundtrip_against_shared_schema").await else {
        return;
    };
    ensure_identity_tables(&pool).await;
    ensure_invitation_tables(&pool).await;

    for cleanup in [
        "DELETE FROM user_tenants WHERE user_id IN ('u_inv_owner', 'u_inv_member', 'u_inv_accept')",
        "DELETE FROM invitations WHERE tenant_id IN ('t_inv', 't_inv_other') OR id IN ('inv_one', 'inv_two')",
        "DELETE FROM tenants WHERE id IN ('t_inv', 't_inv_other')",
        "DELETE FROM users WHERE id IN ('u_inv_owner', 'u_inv_member', 'u_inv_accept')",
    ] {
        sqlx::query(cleanup).execute(&pool).await.unwrap();
    }

    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES \
         ('u_inv_owner', 'owner-inv@example.test', false), \
         ('u_inv_member', 'member-inv@example.test', false), \
         ('u_inv_accept', 'accept-inv@example.test', false)",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) VALUES \
         ('t_inv', 'Invitation Tenant', 'invitation-tenant', 'u_inv_owner'), \
         ('t_inv_other', 'Other Invitation Tenant', 'other-invitation-tenant', 'u_inv_owner')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) VALUES \
         ('ut_inv_owner', 'u_inv_owner', 't_inv', 'owner'), \
         ('ut_inv_member', 'u_inv_member', 't_inv', 'member')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgInvitationRepository::new(pool.clone());
    assert_eq!(
        repo.tenant_admin_status("u_inv_owner", "t_inv")
            .await
            .unwrap(),
        TenantAdminStatus::Authorized
    );
    assert_eq!(
        repo.tenant_admin_status("u_inv_member", "t_inv")
            .await
            .unwrap(),
        TenantAdminStatus::NotAdmin
    );
    assert_eq!(
        repo.tenant_admin_status("u_inv_owner", "missing")
            .await
            .unwrap(),
        TenantAdminStatus::TenantNotFound
    );

    let created_at = sqlx::types::chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap();
    let expires_at = sqlx::types::chrono::DateTime::from_timestamp(1_700_604_800, 0).unwrap();
    let invitation = InvitationRecord {
        id: "inv_one".into(),
        tenant_id: "t_inv".into(),
        email: "invitee@example.test".into(),
        role: "member".into(),
        token: "inv-token-one".into(),
        status: "pending".into(),
        invited_by: "u_inv_owner".into(),
        accepted_by: None,
        expires_at,
        created_at,
        deleted_at: None,
    };
    repo.create(&invitation).await.unwrap();

    assert!(repo
        .find_pending_by_email_and_tenant(" INVITEE@EXAMPLE.TEST ", "t_inv")
        .await
        .unwrap()
        .is_some());
    assert_eq!(repo.count_pending_by_tenant("t_inv").await.unwrap(), 1);
    let listed = repo.list_pending_by_tenant("t_inv", 50, 0).await.unwrap();
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].id, "inv_one");
    assert_eq!(
        repo.find_by_token("inv-token-one")
            .await
            .unwrap()
            .expect("token lookup")
            .email,
        "invitee@example.test"
    );

    repo.update_status("inv_one", "accepted", Some("u_inv_accept"))
        .await
        .unwrap();
    let accepted = repo.find_by_id("inv_one").await.unwrap().unwrap();
    assert_eq!(accepted.status, "accepted");
    assert_eq!(accepted.accepted_by.as_deref(), Some("u_inv_accept"));
    repo.ensure_user_tenant_membership("ut_inv_accept", "u_inv_accept", "t_inv", "member")
        .await
        .unwrap();
    let membership = sqlx::query_as::<_, (String,)>(
        "SELECT role FROM user_tenants WHERE user_id = 'u_inv_accept' AND tenant_id = 't_inv'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(membership.0, "member");

    let mut cancel = invitation.clone();
    cancel.id = "inv_two".into();
    cancel.token = "inv-token-two".into();
    cancel.status = "pending".into();
    cancel.accepted_by = None;
    repo.create(&cancel).await.unwrap();
    repo.soft_delete("inv_two", created_at).await.unwrap();
    let cancelled = repo.find_by_id("inv_two").await.unwrap().unwrap();
    assert_eq!(cancelled.status, "cancelled");
    assert!(cancelled.deleted_at.is_some());
}

#[tokio::test]
async fn project_reads_roundtrip_against_shared_schema() {
    let Some(pool) = pool_or_skip("project_reads_roundtrip_against_shared_schema").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    ensure_project_read_tables(&pool).await;

    for sql in [
        "DELETE FROM project_delete_audit_children WHERE id IN ('p2_audit_child')",
        "DELETE FROM project_delete_audit_entries WHERE id IN ('p2_audit_entry') \
         OR project_id IN ('p_p2_created')",
        "DELETE FROM messages WHERE id IN ('msg_p2_created_parent', 'msg_p2_created_child') \
         OR conversation_id IN ('c_p2_delete_parent', 'c_p2_delete_child')",
        "DELETE FROM conversations WHERE project_id IN ('p_p2_default', 'p_p2_other', 'p_p2_hidden', 'p_p2_created')",
        "DELETE FROM workspaces WHERE project_id IN ('p_p2_created')",
        "DELETE FROM memories WHERE project_id IN ('p_p2_default', 'p_p2_other', 'p_p2_hidden', 'p_p2_created')",
        "DELETE FROM user_projects WHERE user_id IN ('u_p2_projects', 'u_p2_other') \
         OR project_id IN ('p_p2_default', 'p_p2_other', 'p_p2_hidden', 'p_p2_orphan', 'p_p2_created')",
        "DELETE FROM projects WHERE id IN ('p_p2_default', 'p_p2_other', 'p_p2_hidden', 'p_p2_created')",
        "DELETE FROM user_tenants WHERE user_id IN ('u_p2_projects', 'u_p2_other') \
         OR tenant_id IN ('t_p2_projects', 't_p2_elsewhere')",
        "DELETE FROM tenants WHERE id IN ('t_p2_projects', 't_p2_elsewhere')",
        "DELETE FROM users WHERE id IN ('u_p2_projects', 'u_p2_other')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    sqlx::query(
        "INSERT INTO users (id, email, full_name, is_superuser) VALUES \
         ('u_p2_projects', 'projects@memstack.ai', 'Project Owner', false), \
         ('u_p2_other', 'other-projects@memstack.ai', 'Other Owner', false)",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) VALUES \
         ('t_p2_projects', 'Projects Tenant', 'projects-tenant', 'u_p2_projects'), \
         ('t_p2_elsewhere', 'Other Tenant', 'other-tenant', 'u_p2_other')",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role, permissions) VALUES \
         ('ut_p2_projects', 'u_p2_projects', 't_p2_projects', 'admin', '{\"create_projects\": true}'::json), \
         ('ut_p2_other', 'u_p2_other', 't_p2_elsewhere', 'member', '{}'::json)",
    )
    .execute(&pool)
    .await
    .unwrap();

    for (id, tenant_id, name, owner, is_public, created_at) in [
        (
            "p_p2_default",
            "t_p2_projects",
            "Default project",
            "u_p2_projects",
            false,
            "2024-01-01T00:00:00Z",
        ),
        (
            "p_p2_other",
            "t_p2_projects",
            "Other Project",
            "u_p2_other",
            true,
            "2025-01-01T00:00:00Z",
        ),
        (
            "p_p2_hidden",
            "t_p2_elsewhere",
            "Hidden Project",
            "u_p2_other",
            false,
            "2025-02-01T00:00:00Z",
        ),
    ] {
        sqlx::query(
            "INSERT INTO projects \
             (id, tenant_id, name, description, owner_id, is_public, created_at, memory_rules, graph_config) \
             VALUES ($1, $2, $3, $3, $4, $5, $6::timestamptz, '{}'::json, '{}'::json)",
        )
        .bind(id)
        .bind(tenant_id)
        .bind(name)
        .bind(owner)
        .bind(is_public)
        .bind(created_at)
        .execute(&pool)
        .await
        .unwrap();
    }

    for (user_id, project_id, role, created_at, permissions) in [
        (
            "u_p2_projects",
            "p_p2_default",
            "owner",
            "2024-01-02T00:00:00Z",
            serde_json::json!({"admin": true, "read": true, "write": true, "delete": true}),
        ),
        (
            "u_p2_projects",
            "p_p2_other",
            "viewer",
            "2024-01-03T00:00:00Z",
            serde_json::json!({"read": true, "write": false}),
        ),
        (
            "u_p2_other",
            "p_p2_hidden",
            "owner",
            "2024-01-04T00:00:00Z",
            serde_json::json!({"admin": true, "read": true, "write": true, "delete": true}),
        ),
        (
            "u_p2_projects",
            "p_p2_orphan",
            "viewer",
            "2024-01-05T00:00:00Z",
            serde_json::json!({"read": true, "write": false}),
        ),
    ] {
        sqlx::query(
            "INSERT INTO user_projects (user_id, project_id, role, created_at, permissions) \
             VALUES ($1, $2, $3, $4::timestamptz, $5)",
        )
        .bind(user_id)
        .bind(project_id)
        .bind(role)
        .bind(created_at)
        .bind(permissions)
        .execute(&pool)
        .await
        .unwrap();
    }

    sqlx::query(
        "INSERT INTO memories (id, project_id, title, content, author_id, created_at) VALUES \
         ('m_p2_project_1', 'p_p2_default', 'M1', 'hello', 'u_p2_projects', '2024-02-01T00:00:00Z'), \
         ('m_p2_project_2', 'p_p2_default', 'M2', 'world!!', 'u_p2_projects', '2024-03-01T00:00:00Z')",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "INSERT INTO conversations (id, project_id, tenant_id, user_id, title, created_at) VALUES \
         ('c_p2_project_1', 'p_p2_default', 't_p2_projects', 'u_p2_projects', 'C1', '2024-04-01T00:00:00Z'), \
         ('c_p2_project_2', 'p_p2_default', 't_p2_projects', 'u_p2_projects', 'C2', '2024-04-02T00:00:00Z'), \
         ('c_p2_project_3', 'p_p2_other', 't_p2_projects', 'u_p2_projects', 'C3', '2024-04-03T00:00:00Z')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let projects = PgProjectReadRepository::new(pool.clone());
    let page = projects
        .list_for_user(ProjectListForUserQuery {
            user_id: "u_p2_projects",
            tenant_id: Some("t_p2_projects"),
            search: None,
            visibility: "all",
            owner_id: None,
            offset: 0,
            limit: 20,
        })
        .await
        .unwrap();
    assert_eq!(page.total, 2);
    assert_eq!(page.projects[0].id, "p_p2_default");
    assert_eq!(page.projects[0].stats.memory_count, 2);
    assert_eq!(page.projects[0].stats.storage_used, 12);
    assert_eq!(page.projects[0].stats.member_count, 1);
    assert_eq!(page.projects[1].id, "p_p2_other");
    assert_eq!(page.owner_ids, vec!["u_p2_other", "u_p2_projects"]);

    let public = projects
        .list_for_user(ProjectListForUserQuery {
            user_id: "u_p2_projects",
            tenant_id: Some("t_p2_projects"),
            search: None,
            visibility: "public",
            owner_id: None,
            offset: 0,
            limit: 20,
        })
        .await
        .unwrap();
    assert_eq!(public.total, 1);
    assert_eq!(public.projects[0].id, "p_p2_other");

    let searched = projects
        .list_for_user(ProjectListForUserQuery {
            user_id: "u_p2_projects",
            tenant_id: Some("t_p2_projects"),
            search: Some("default"),
            visibility: "all",
            owner_id: None,
            offset: 0,
            limit: 20,
        })
        .await
        .unwrap();
    assert_eq!(searched.total, 1);
    assert_eq!(searched.projects[0].id, "p_p2_default");

    assert!(matches!(
        projects
            .get_for_user("u_p2_projects", "p_p2_default", Some("t_p2_projects"))
            .await
            .unwrap(),
        ProjectLookup::Found(p) if p.id == "p_p2_default"
    ));
    assert!(matches!(
        projects
            .get_for_user("u_p2_projects", "p_p2_default", Some("t_p2_elsewhere"))
            .await
            .unwrap(),
        ProjectLookup::TenantMismatch
    ));
    assert!(matches!(
        projects
            .get_for_user("u_p2_projects", "p_p2_hidden", None)
            .await
            .unwrap(),
        ProjectLookup::Forbidden
    ));
    assert!(matches!(
        projects
            .get_for_user("u_p2_projects", "p_p2_orphan", None)
            .await
            .unwrap(),
        ProjectLookup::NotFound
    ));

    let stats = projects
        .stats_for_user("u_p2_projects", "p_p2_default")
        .await
        .unwrap();
    match stats {
        ProjectStatsLookup::Found(stats) => {
            assert_eq!(stats.memory_count, 2);
            assert_eq!(stats.storage_used, 12);
            assert_eq!(stats.member_count, 1);
            assert_eq!(stats.conversation_count, 2);
            assert_eq!(stats.recent_activity.len(), 2);
            assert_eq!(stats.recent_activity[0].id, "m_p2_project_2");
            assert_eq!(stats.recent_activity[0].user, "Project Owner");
            assert_eq!(stats.recent_activity[0].target, "M2");
        }
        other => panic!("expected stats, got {other:?}"),
    }
    assert!(matches!(
        projects
            .stats_for_user("u_p2_projects", "p_p2_hidden")
            .await
            .unwrap(),
        ProjectStatsLookup::Forbidden
    ));
    assert!(matches!(
        projects
            .stats_for_user("u_p2_projects", "p_p2_orphan")
            .await
            .unwrap(),
        ProjectStatsLookup::NotFound
    ));

    let members = projects
        .members_for_user("u_p2_projects", "p_p2_default")
        .await
        .unwrap();
    match members {
        ProjectMembersLookup::Found(members) => {
            assert_eq!(members.total, 1);
            assert_eq!(members.members.len(), 1);
            assert_eq!(members.members[0].user_id, "u_p2_projects");
            assert_eq!(members.members[0].email, "projects@memstack.ai");
            assert_eq!(members.members[0].name.as_deref(), Some("Project Owner"));
            assert_eq!(members.members[0].role, "owner");
            assert_eq!(members.members[0].permissions["admin"], true);
        }
        other => panic!("expected members, got {other:?}"),
    }
    assert!(matches!(
        projects
            .members_for_user("u_p2_projects", "p_p2_hidden")
            .await
            .unwrap(),
        ProjectMembersLookup::Forbidden
    ));
    assert!(matches!(
        projects
            .members_for_user("u_p2_projects", "p_p2_orphan")
            .await
            .unwrap(),
        ProjectMembersLookup::InvalidId
    ));
    assert!(matches!(
        projects
            .members_for_user("u_p2_projects", "not-a-uuid")
            .await
            .unwrap(),
        ProjectMembersLookup::InvalidId
    ));
    assert!(matches!(
        projects
            .members_for_user("u_p2_projects", "00000000-0000-0000-0000-000000000000")
            .await
            .unwrap(),
        ProjectMembersLookup::NotFound
    ));

    assert!(projects
        .user_is_project_admin("u_p2_projects", "p_p2_default")
        .await
        .unwrap());
    assert!(!projects
        .user_is_project_admin("u_p2_projects", "p_p2_other")
        .await
        .unwrap());
    assert!(projects.project_exists("p_p2_default").await.unwrap());
    assert!(!projects.project_exists("p_p2_missing").await.unwrap());
    assert!(projects.user_exists("u_p2_other").await.unwrap());
    assert!(projects
        .project_member_role("p_p2_default", "u_p2_other")
        .await
        .unwrap()
        .is_none());

    projects
        .add_project_member(
            "up_p2_added",
            "p_p2_default",
            "u_p2_other",
            "editor",
            &json!({"read": true, "write": true}),
        )
        .await
        .unwrap();
    let added = projects
        .project_member_role("p_p2_default", "u_p2_other")
        .await
        .unwrap()
        .expect("added membership");
    assert_eq!(added.role, "editor");
    let add_permissions: serde_json::Value = sqlx::query_as::<_, (serde_json::Value,)>(
        "SELECT permissions FROM user_projects WHERE project_id = 'p_p2_default' AND user_id = 'u_p2_other'",
    )
    .fetch_one(&pool)
    .await
    .unwrap()
    .0;
    assert_eq!(add_permissions["write"], true);

    assert!(projects
        .update_project_member(
            "p_p2_default",
            "u_p2_other",
            "editor",
            &json!({"read": true, "write": false}),
        )
        .await
        .unwrap());
    let update_permissions: serde_json::Value = sqlx::query_as::<_, (serde_json::Value,)>(
        "SELECT permissions FROM user_projects WHERE project_id = 'p_p2_default' AND user_id = 'u_p2_other'",
    )
    .fetch_one(&pool)
    .await
    .unwrap()
    .0;
    assert_eq!(update_permissions["write"], false);

    assert!(projects
        .remove_project_member("p_p2_default", "u_p2_other")
        .await
        .unwrap());
    assert!(!projects
        .remove_project_member("p_p2_default", "u_p2_other")
        .await
        .unwrap());
    assert!(projects
        .project_member_role("p_p2_default", "u_p2_other")
        .await
        .unwrap()
        .is_none());

    assert!(projects
        .user_is_tenant_project_admin("u_p2_projects", "t_p2_projects")
        .await
        .unwrap());
    assert!(!projects
        .user_is_tenant_project_admin("u_p2_other", "t_p2_elsewhere")
        .await
        .unwrap());

    let created = projects
        .create_project(&ProjectCreateRecord {
            id: "p_p2_created".to_string(),
            membership_id: "up_p2_created_owner".to_string(),
            tenant_id: "t_p2_projects".to_string(),
            name: "Created Project".to_string(),
            description: Some("created from Rust".to_string()),
            owner_id: "u_p2_projects".to_string(),
            memory_rules: json!({"max_episodes": 3000, "retention_days": 90}),
            graph_config: json!({"max_nodes": 7000}),
            graph_store_id: None,
            retrieval_store_id: None,
            sandbox_type: "cloud".to_string(),
            sandbox_config: json!({}),
            is_public: true,
            agent_conversation_mode: "multi_agent_shared".to_string(),
            owner_permissions: json!({"admin": true, "read": true, "write": true, "delete": true}),
        })
        .await
        .unwrap();
    assert_eq!(created.id, "p_p2_created");
    assert_eq!(created.owner_id, "u_p2_projects");
    assert_eq!(created.member_ids, vec!["u_p2_projects"]);
    assert_eq!(created.stats.member_count, 1);
    assert_eq!(created.agent_conversation_mode, "multi_agent_shared");
    let owner_role = projects
        .project_member_role("p_p2_created", "u_p2_projects")
        .await
        .unwrap()
        .expect("created owner membership");
    assert_eq!(owner_role.role, "owner");

    let updated = projects
        .update_project(
            "p_p2_created",
            &ProjectUpdatePatch {
                name: Some("Updated Project".to_string()),
                description: Some(None),
                memory_rules: Some(json!({"retention_days": 60})),
                graph_config: Some(json!({"max_nodes": 9000})),
                graph_store_id: Some(None),
                retrieval_store_id: Some(None),
                sandbox_config: Some(json!({
                    "sandbox_type": "local",
                    "local_config": {"host": "localhost", "port": 8765}
                })),
                is_public: Some(false),
                agent_conversation_mode: Some("multi_agent_isolated".to_string()),
            },
        )
        .await
        .unwrap()
        .expect("updated project");
    assert_eq!(updated.name, "Updated Project");
    assert!(updated.description.is_none());
    assert_eq!(updated.memory_rules["retention_days"], 60);
    assert_eq!(updated.graph_config["max_nodes"], 9000);
    assert!(!updated.is_public);
    assert_eq!(updated.sandbox_config["sandbox_type"], "local");
    assert_eq!(updated.agent_conversation_mode, "multi_agent_isolated");
    assert!(projects
        .update_project("p_p2_missing", &ProjectUpdatePatch::default())
        .await
        .unwrap()
        .is_none());

    assert!(projects
        .user_is_project_owner("u_p2_projects", "p_p2_created")
        .await
        .unwrap());
    assert!(!projects
        .user_is_project_owner("u_p2_other", "p_p2_created")
        .await
        .unwrap());

    sqlx::query(
        "INSERT INTO conversations \
         (id, project_id, tenant_id, user_id, title, parent_conversation_id, fork_source_id) VALUES \
         ('c_p2_delete_parent', 'p_p2_created', 't_p2_projects', 'u_p2_projects', 'Delete parent', NULL, NULL), \
         ('c_p2_delete_child', 'p_p2_created', 't_p2_projects', 'u_p2_projects', 'Delete child', \
          'c_p2_delete_parent', 'c_p2_delete_parent')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO messages (id, conversation_id, reply_to_id, content) VALUES \
         ('msg_p2_created_parent', 'c_p2_delete_parent', NULL, 'parent'), \
         ('msg_p2_created_child', 'c_p2_delete_child', 'msg_p2_created_parent', 'child')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO workspaces (id, tenant_id, project_id, name, created_by) \
         VALUES ('w_p2_created', 't_p2_projects', 'p_p2_created', 'Delete workspace', 'u_p2_projects')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO project_delete_audit_entries (id, project_id) \
         VALUES ('p2_audit_entry', 'p_p2_created')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO project_delete_audit_children (id, entry_id) \
         VALUES ('p2_audit_child', 'p2_audit_entry')",
    )
    .execute(&pool)
    .await
    .unwrap();

    assert!(projects.delete_project("p_p2_created").await.unwrap());
    for (table, predicate) in [
        ("projects", "id = 'p_p2_created'"),
        ("user_projects", "project_id = 'p_p2_created'"),
        ("conversations", "project_id = 'p_p2_created'"),
        (
            "messages",
            "id IN ('msg_p2_created_parent', 'msg_p2_created_child')",
        ),
        ("workspaces", "project_id = 'p_p2_created'"),
        (
            "project_delete_audit_entries",
            "project_id = 'p_p2_created'",
        ),
        ("project_delete_audit_children", "id = 'p2_audit_child'"),
    ] {
        let sql = format!("SELECT count(*) FROM {table} WHERE {predicate}");
        let count = sqlx::query_as::<_, (i64,)>(&sql)
            .fetch_one(&pool)
            .await
            .unwrap()
            .0;
        assert_eq!(count, 0, "{table} rows should be removed by project delete");
    }
}
