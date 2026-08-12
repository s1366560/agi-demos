use std::error::Error;
use std::sync::Arc;

use async_trait::async_trait;
use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use memstack_workspace_service::{
    PublicWorkspaceAutonomyJudgePort, PublicWorkspaceAutonomyJudgePortError,
    PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgmentRequest,
    PublicWorkspaceAutonomyVerdictKind,
};
use memstack_workspace_service_api::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, ProviderRegistryRoute,
    TenantId, WorkspaceContextJudgePort, WorkspaceContextJudgePortError, WorkspaceContextJudgment,
    WorkspaceContextJudgmentRequest,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "autonomy-http-contract-token";
const PATH: &str = "/api/v1/workspaces/workspace-1/autonomy/tick";

struct UnusedAgentRegistry;

#[async_trait]
impl AgentRegistryPort for UnusedAgentRegistry {
    async fn resolve(
        &self,
        _lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError> {
        Err(AgentRegistryPortError::Unavailable)
    }
}

struct UnusedProviderRegistry;

#[async_trait]
impl ProviderRegistryPort for UnusedProviderRegistry {
    async fn resolve(
        &self,
        _lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        Err(ProviderRegistryPortError::Unavailable)
    }

    async fn tenant_default(
        &self,
        _tenant_id: &TenantId,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        Err(ProviderRegistryPortError::Unavailable)
    }
}

struct UnusedContextJudge;

#[async_trait]
impl WorkspaceContextJudgePort for UnusedContextJudge {
    async fn select(
        &self,
        _request: &WorkspaceContextJudgmentRequest,
    ) -> Result<WorkspaceContextJudgment, WorkspaceContextJudgePortError> {
        Err(WorkspaceContextJudgePortError::Unavailable)
    }
}

struct FirstCandidateAutonomyJudge;

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for FirstCandidateAutonomyJudge {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        let root_task_id = request
            .candidates()
            .first()
            .map(|candidate| candidate.root_task_id.clone())
            .ok_or(PublicWorkspaceAutonomyJudgePortError::Unavailable)?;
        PublicWorkspaceAutonomyJudgment::new(
            request,
            PublicWorkspaceAutonomyVerdictKind::Continue,
            Some(root_task_id.clone()),
            "the structured root candidate is ready".to_string(),
            "autonomy-judge-agent".to_string(),
            "judge_workspace_autonomy".to_string(),
            json!({"candidate_ids": [root_task_id.clone()]}),
            json!({"verdict": "continue", "selected_root_task_id": root_task_id}),
            7,
        )
        .map_err(|_| PublicWorkspaceAutonomyJudgePortError::Unavailable)
    }
}

#[tokio::test]
async fn autonomy_tick_uses_structured_judge_and_replays_durable_terminal_response()
-> Result<(), Box<dyn Error>> {
    let db = Arc::new(seeded_db().await?);
    let state = Arc::new(WorkspaceCoreState::new_with_all_authorities(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
        Arc::new(UnusedAgentRegistry),
        Arc::new(UnusedProviderRegistry),
        Arc::new(UnusedContextJudge),
        Arc::new(FirstCandidateAutonomyJudge),
    )?);

    let first = send(
        state.clone(),
        Some(json!({"force": true})),
        Some(0),
        "tick-http-1",
    )
    .await?;
    assert_eq!(first.0, StatusCode::OK);
    assert_eq!(
        first.1,
        json!({"triggered": true, "root_task_id": "root-task-1", "reason": "triggered"})
    );
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_autonomy_ticks").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_judge_audits").await?, 1);
    assert_eq!(
        table_count(db.as_ref(), "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(table_count(db.as_ref(), "workspace_outbox").await?, 1);

    let replay = send(state, Some(json!({"force": true})), Some(0), "tick-http-1").await?;
    assert_eq!(replay, first);
    assert_eq!(authority_revision(db.as_ref()).await?, 1);
    assert_eq!(table_count(db.as_ref(), "workspace_judge_audits").await?, 1);
    Ok(())
}

async fn send(
    state: Arc<WorkspaceCoreState>,
    body: Option<Value>,
    revision: Option<u64>,
    idempotency_key: &str,
) -> Result<(StatusCode, Value), Box<dyn Error>> {
    let mut builder = Request::builder()
        .method("POST")
        .uri(PATH)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "user-1")
        .header("idempotency-key", idempotency_key)
        .header(header::CONTENT_TYPE, "application/json");
    if let Some(revision) = revision {
        builder = builder.header("if-match", revision.to_string());
    }
    let request = builder.body(match body {
        Some(body) => Body::from(serde_json::to_vec(&body)?),
        None => Body::empty(),
    })?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let body = serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await?)?;
    Ok((status, body))
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, assignee_user_id TEXT, assignee_agent_id TEXT, status TEXT NOT NULL, priority INTEGER NOT NULL, estimated_effort TEXT, blocker_reason TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, completed_at TEXT, archived_at TEXT)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_judge_audits (audit_id TEXT PRIMARY KEY, tenant_id TEXT, project_id TEXT, workspace_id TEXT, plan_id TEXT, plan_node_id TEXT, judgment_type TEXT NOT NULL, agent_id TEXT NOT NULL, tool_name TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL, rationale TEXT NOT NULL, latency_ms INTEGER NOT NULL, status TEXT NOT NULL, error_detail TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE workspace_autonomy_ticks (tick_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, root_task_id TEXT, actor_id TEXT NOT NULL, force INTEGER NOT NULL, verdict TEXT NOT NULL, reason TEXT NOT NULL, judge_audit_id TEXT, created_at TEXT NOT NULL)",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, description, created_by, status, priority, metadata_json, created_at) VALUES ('root-task-1', 'tenant-1', 'project-1', 'workspace-1', 'Root objective', 'Proceed through the structured judge', 'user-1', 'todo', 2, '{\"task_role\":\"goal_root\"}', CURRENT_TIMESTAMP)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_autonomy_ticks" => "SELECT COUNT(*) AS value FROM workspace_autonomy_ticks",
        "workspace_judge_audits" => "SELECT COUNT(*) AS value FROM workspace_judge_audits",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing count")?
        .get_i64("value")?
        .ok_or("missing count value")?)
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
        ))
        .await?
        .first()
        .ok_or("missing authority")?
        .get_i64("value")?
        .ok_or("missing revision")?)
}
