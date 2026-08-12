use std::error::Error;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    PublicWorkspacePlanAction, PublicWorkspacePlanActionInput, PublicWorkspacePlanContext,
    PublicWorkspacePlanService, PublicWorkspacePlanSnapshotInput,
};
use memstack_workspace_service_api::{
    WorkspacePlanJudgePort, WorkspacePlanJudgePortError, WorkspacePlanJudgment,
    WorkspacePlanJudgmentRequest,
};
use serde_json::json;

struct ProceedingJudge {
    calls: AtomicUsize,
}

impl ProceedingJudge {
    const fn new() -> Self {
        Self {
            calls: AtomicUsize::new(0),
        }
    }
}

#[async_trait]
impl WorkspacePlanJudgePort for ProceedingJudge {
    async fn judge(
        &self,
        request: &WorkspacePlanJudgmentRequest,
    ) -> Result<WorkspacePlanJudgment, WorkspacePlanJudgePortError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        WorkspacePlanJudgment::new(
            request,
            true,
            if request.kind().requires_selected_node() {
                request.candidate_node_ids().first().cloned()
            } else {
                None
            },
            "structured Plan test verdict".to_string(),
            "plan-judge-agent".to_string(),
            "judge_workspace_plan".to_string(),
            request.evidence().clone(),
            json!({"proceed": true}),
            4,
        )
        .map_err(|_| WorkspacePlanJudgePortError::Unavailable)
    }
}

#[tokio::test]
async fn snapshot_is_tenant_scoped_and_has_legacy_top_level_contract() -> Result<(), Box<dyn Error>>
{
    let db = seeded_db("pending").await?;
    let judge = ProceedingJudge::new();
    let service = PublicWorkspacePlanService::new(&db, DbSqlFlavor::Sqlite, &judge);

    let snapshot = service
        .snapshot(&PublicWorkspacePlanSnapshotInput {
            context: context(),
            plan_id: None,
            include_details: true,
            outbox_limit: 20,
            event_limit: 50,
        })
        .await?;

    assert_eq!(snapshot.workspace_id, "workspace-1");
    let plan = snapshot.plan.ok_or("plan missing")?;
    assert_eq!(plan.id, "plan-1");
    assert_eq!(plan.nodes.len(), 1);
    assert_eq!(plan.nodes[0].id, "node-1");
    assert!(snapshot.root_goal.is_some());
    assert!(snapshot.iteration.is_some());
    assert!(snapshot.delivery.is_some());
    assert_eq!(judge.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn pause_commits_plan_cas_event_and_outbox_and_replays() -> Result<(), Box<dyn Error>> {
    let db = seeded_db("pending").await?;
    let judge = ProceedingJudge::new();
    let service = PublicWorkspacePlanService::new(&db, DbSqlFlavor::Sqlite, &judge);
    let input = action(PublicWorkspacePlanAction::PauseIteration, None, "pause-1");

    let committed = service.act(&input).await?;
    let replayed = service.act(&input).await?;

    assert_eq!(committed, replayed);
    assert_eq!(committed.message, "Automatic iteration loop paused.");
    assert_eq!(
        scalar_string(&db, "SELECT status AS value FROM workspace_plans").await?,
        "suspended"
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_plans").await?,
        2
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_plan_events").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    assert_eq!(judge.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn replan_requires_judge_and_commits_audit_node_event_and_outbox()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db("blocked").await?;
    let judge = ProceedingJudge::new();
    let service = PublicWorkspacePlanService::new(&db, DbSqlFlavor::Sqlite, &judge);

    let result = service
        .act(&action(
            PublicWorkspacePlanAction::RequestNodeReplan,
            Some("node-1"),
            "replan-1",
        ))
        .await?;

    assert_eq!(result.node_id.as_deref(), Some("node-1"));
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        scalar_string(&db, "SELECT status AS value FROM workspace_plan_nodes").await?,
        "pending"
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_judge_audits").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_plan_events").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    Ok(())
}

fn context() -> PublicWorkspacePlanContext {
    PublicWorkspacePlanContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        actor_id: "user-owner".to_string(),
        actor_is_superuser: false,
    }
}

fn action(
    action: PublicWorkspacePlanAction,
    node_id: Option<&str>,
    idempotency_key: &str,
) -> PublicWorkspacePlanActionInput {
    PublicWorkspacePlanActionInput {
        context: context(),
        action,
        node_id: node_id.map(str::to_string),
        outbox_id: None,
        reason: Some("operator supplied structured reason".to_string()),
        evidence_refs: vec!["evidence://plan-contract".to_string()],
        idempotency_key: Some(idempotency_key.to_string()),
        expected_revision: None,
    }
}

async fn seeded_db(node_status: &str) -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_plans (plan_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, source_task_id TEXT, goal TEXT NOT NULL, goal_json TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_plan_nodes (node_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, workspace_task_id TEXT, parent_id TEXT, kind TEXT NOT NULL, title TEXT NOT NULL, description TEXT, intent TEXT, status TEXT NOT NULL, sequence_number INTEGER NOT NULL, dependencies_json TEXT NOT NULL, acceptance_criteria_json TEXT NOT NULL, feature_checkpoint_json TEXT, handoff_package_json TEXT, recommended_capabilities_json TEXT NOT NULL, priority INTEGER NOT NULL, progress_json TEXT NOT NULL, assignee_agent_id TEXT, current_attempt_id TEXT, timeout_deadline_at TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT)",
        "CREATE TABLE workspace_plan_blackboard_entries (entry_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, created_by_actor_id TEXT, version INTEGER NOT NULL, schema_ref TEXT, metadata_json TEXT NOT NULL)",
        "CREATE TABLE workspace_plan_events (event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, event_sequence INTEGER NOT NULL, node_id TEXT, attempt_id TEXT, event_type TEXT NOT NULL, source TEXT NOT NULL, actor_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(plan_id, event_sequence))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 10, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, next_attempt_at TEXT, dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_pipeline_runs (run_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT, provider TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, node_id TEXT, attempt_id TEXT, commit_ref TEXT, metadata_json TEXT NOT NULL, started_at TEXT, completed_at TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE workspace_judge_audits (audit_id TEXT PRIMARY KEY, tenant_id TEXT, project_id TEXT, workspace_id TEXT, plan_id TEXT, plan_node_id TEXT, judgment_type TEXT NOT NULL, agent_id TEXT NOT NULL, tool_name TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL, rationale TEXT NOT NULL, latency_ms INTEGER NOT NULL, status TEXT NOT NULL, error_detail TEXT, created_at TEXT NOT NULL)",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    for statement in [
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id) VALUES ('workspace-1', 'tenant-1', 'project-1')".to_string(),
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, role) VALUES ('member-1', 'tenant-1', 'project-1', 'workspace-1', 'user-owner', 'owner')".to_string(),
        "INSERT INTO workspace_plans (plan_id, tenant_id, project_id, workspace_id, goal, goal_json, status, revision, metadata_json, created_at, updated_at) VALUES ('plan-1', 'tenant-1', 'project-1', 'workspace-1', 'Ship the migration', '{\"id\":\"node-1\"}', 'active', 1, '{\"iteration_loop\":{\"loop_status\":\"active\"}}', '2026-08-11T00:00:00Z', '2026-08-11T00:00:00Z')".to_string(),
        format!("INSERT INTO workspace_plan_nodes (node_id, tenant_id, project_id, workspace_id, plan_id, kind, title, description, intent, status, sequence_number, dependencies_json, acceptance_criteria_json, recommended_capabilities_json, priority, progress_json, metadata_json, created_at, updated_at) VALUES ('node-1', 'tenant-1', 'project-1', 'workspace-1', 'plan-1', 'goal', 'Ship migration', 'Root goal', 'todo', '{node_status}', 0, '[]', '[]', '[]', 0, '{{\"percent\":0}}', '{{}}', '2026-08-11T00:00:00Z', '2026-08-11T00:00:00Z')"),
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}
