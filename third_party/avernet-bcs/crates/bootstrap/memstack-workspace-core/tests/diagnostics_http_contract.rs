use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "diagnostics-http-contract-token";
const PATH: &str = "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/blackboard/execution-diagnostics";

#[tokio::test]
async fn diagnostics_http_projects_durable_task_plan_and_outbox_facts() -> Result<(), Box<dyn Error>>
{
    let state = diagnostics_state(Arc::new(seeded_db().await?))?;
    let response = send_json(
        state,
        diagnostics_request(
            &format!("{PATH}?task_limit=20&tool_limit_per_conversation=40"),
            "viewer-1",
        )?,
        StatusCode::OK,
    )
    .await?;

    assert_eq!(response["workspace_id"], "workspace-1");
    assert_eq!(response["task_status_counts"]["blocked"], 1);
    assert_eq!(response["task_status_counts"]["reported"], 1);
    assert_eq!(
        response["attempt_status_counts"]["awaiting_leader_adjudication"],
        1
    );
    assert_eq!(response["tool_status_counts"], json!({}));
    assert_eq!(response["tasks"].as_array().map(Vec::len), Some(2));
    assert!(
        response["blockers"]
            .as_array()
            .is_some_and(|rows| rows.iter().any(|row| row["type"] == "outbox_dead_letter"))
    );
    assert!(
        response["pending_adjudications"]
            .as_array()
            .is_some_and(|rows| rows.iter().any(|row| row["task_id"] == "task-reported"))
    );
    assert!(
        response["evidence_gaps"]
            .as_array()
            .is_some_and(|rows| rows.iter().any(|row| {
                row["type"] == "missing_structured_evidence" && row["task_id"] == "task-reported"
            }))
    );
    assert_eq!(
        response["active_attempts"].as_array().map(Vec::len),
        Some(1)
    );
    assert_eq!(response["retry_queue"].as_array().map(Vec::len), Some(1));
    assert_eq!(response["controller_state"]["plan_id"], "plan-1");
    assert_eq!(
        response["controller_state"]["agent_runtime_detail_authority"],
        "external"
    );
    assert_eq!(response["completion_gate"]["ready"], false);
    assert_eq!(response["blocked_reason"], "Dependency unavailable");
    Ok(())
}

#[tokio::test]
async fn diagnostics_http_rejects_invalid_query_and_missing_membership()
-> Result<(), Box<dyn Error>> {
    let state = diagnostics_state(Arc::new(seeded_db().await?))?;
    let invalid = send_json(
        state.clone(),
        diagnostics_request(&format!("{PATH}?task_limit=0"), "viewer-1")?,
        StatusCode::UNPROCESSABLE_ENTITY,
    )
    .await?;
    assert_eq!(invalid["detail"][0]["loc"], json!(["query", "task_limit"]));

    let forbidden = send_json(
        state,
        diagnostics_request(PATH, "outsider-1")?,
        StatusCode::FORBIDDEN,
    )
    .await?;
    assert_eq!(forbidden, json!({"detail": "Access denied"}));
    Ok(())
}

fn diagnostics_state(
    db: Arc<LocalSqliteDbPlugin>,
) -> Result<Arc<WorkspaceCoreState>, &'static str> {
    WorkspaceCoreState::new_with_sql_flavor(db, SERVICE_TOKEN.to_string(), DbSqlFlavor::Sqlite)
        .map(Arc::new)
}

fn diagnostics_request(path: &str, user_id: &str) -> Result<Request<Body>, Box<dyn Error>> {
    Ok(Request::builder()
        .method("GET")
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", user_id)
        .body(Body::empty())?)
}

async fn send_json(
    state: Arc<WorkspaceCoreState>,
    request: Request<Body>,
    expected_status: StatusCode,
) -> Result<Value, Box<dyn Error>> {
    let response = workspace_router(state).oneshot(request).await?;
    assert_eq!(response.status(), expected_status);
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX).await?,
    )?)
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, assignee_user_id TEXT, assignee_agent_id TEXT, status TEXT NOT NULL, priority INTEGER NOT NULL, estimated_effort TEXT, blocker_reason TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, archived_at TEXT)",
        "CREATE TABLE workspace_task_attempts (attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT NOT NULL, root_goal_task_id TEXT NOT NULL, attempt_number INTEGER NOT NULL, status TEXT NOT NULL, conversation_id TEXT, worker_agent_id TEXT, leader_agent_id TEXT, candidate_summary TEXT, candidate_artifacts_json TEXT NOT NULL, candidate_verifications_json TEXT NOT NULL, leader_feedback TEXT, adjudication_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, UNIQUE(task_id, attempt_number))",
        "CREATE TABLE workspace_agent_runtime_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT, attempt_id TEXT, conversation_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_execution_terminals (terminal_id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL, execution_status TEXT NOT NULL)",
        "CREATE TABLE workspace_plans (plan_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, source_task_id TEXT, goal TEXT NOT NULL, goal_json TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_plan_nodes (node_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, workspace_task_id TEXT, parent_id TEXT, kind TEXT NOT NULL, title TEXT NOT NULL, description TEXT, intent TEXT, status TEXT NOT NULL, sequence_number INTEGER NOT NULL, dependencies_json TEXT NOT NULL, acceptance_criteria_json TEXT NOT NULL, feature_checkpoint_json TEXT, handoff_package_json TEXT, recommended_capabilities_json TEXT NOT NULL, priority INTEGER NOT NULL, progress_json TEXT NOT NULL, assignee_agent_id TEXT, current_attempt_id TEXT, timeout_deadline_at TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_plan_blackboard_entries (entry_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, created_by_actor_id TEXT, version INTEGER NOT NULL, schema_ref TEXT, metadata_json TEXT NOT NULL)",
        "CREATE TABLE workspace_plan_events (event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, event_sequence INTEGER NOT NULL, node_id TEXT, attempt_id TEXT, event_type TEXT NOT NULL, source TEXT NOT NULL, actor_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(plan_id, event_sequence))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 10, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, next_attempt_at TEXT, dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_pipeline_runs (run_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT, provider TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, node_id TEXT, attempt_id TEXT, commit_ref TEXT, metadata_json TEXT NOT NULL, started_at TEXT, completed_at TEXT, created_at TEXT NOT NULL)",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('member-viewer', 'tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer')",
        "INSERT INTO workspace_tasks VALUES ('task-blocked', 'tenant-1', 'project-1', 'workspace-1', 'Blocked task', NULL, 'owner-1', NULL, NULL, 'blocked', 1, NULL, 'Dependency unavailable', '{}', '2026-08-11T00:00:00Z', '2026-08-11T00:01:00Z', NULL, NULL)",
        "INSERT INTO workspace_tasks VALUES ('task-reported', 'tenant-1', 'project-1', 'workspace-1', 'Reported task', NULL, 'owner-1', NULL, 'agent-1', 'reported', 2, NULL, NULL, '{\"current_attempt_id\":\"attempt-1\"}', '2026-08-11T00:00:00Z', '2026-08-11T00:02:00Z', NULL, NULL)",
        "INSERT INTO workspace_task_attempts VALUES ('attempt-1', 'tenant-1', 'project-1', 'workspace-1', 'task-reported', 'task-reported', 1, 'awaiting_leader_adjudication', 'conversation-1', 'agent-1', 'leader-1', 'Candidate report', '[]', '[]', NULL, NULL, '2026-08-11T00:01:00Z', '2026-08-11T00:02:00Z', NULL)",
        "INSERT INTO workspace_agent_runtime_correlations VALUES ('correlation-1', 'tenant-1', 'project-1', 'workspace-1', 'task-reported', 'attempt-1', 'conversation-1', 'running', '2026-08-11T00:02:00Z', NULL)",
        "INSERT INTO workspace_plans VALUES ('plan-1', 'tenant-1', 'project-1', 'workspace-1', NULL, 'Finish migration', '{}', 'active', 4, '{}', '2026-08-11T00:00:00Z', '2026-08-11T00:02:00Z', NULL)",
        "INSERT INTO workspace_plan_nodes VALUES ('node-1', 'tenant-1', 'project-1', 'workspace-1', 'plan-1', 'task-blocked', NULL, 'task', 'Blocked node', NULL, NULL, 'blocked', 0, '[]', '[]', NULL, NULL, '[]', 1, '{}', NULL, NULL, NULL, '{}', '2026-08-11T00:00:00Z', '2026-08-11T00:02:00Z', NULL)",
        "INSERT INTO workspace_outbox VALUES ('outbox-1', 'tenant-1', 'project-1', 'workspace-1', 'workspace_plan', 'plan-1', 'workspace_plan_updated', 'workspace.events', 1, '{}', '{}', NULL, 'diagnostics-outbox-1', 'dead_letter', 10, 10, NULL, NULL, 'delivery failed', NULL, NULL, '2026-08-11T00:00:00Z', '2026-08-11T00:02:00Z')",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}
