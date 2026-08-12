use std::error::Error;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    PublicSwitchWorkspaceContextInput, PublicWorkspaceContextError, PublicWorkspaceContextService,
};
use memstack_workspace_service_api::{
    WorkspaceContextJudgePort, WorkspaceContextJudgePortError, WorkspaceContextJudgment,
    WorkspaceContextJudgmentRequest,
};
use serde_json::json;

struct SelectingJudge {
    selected_index: usize,
    calls: AtomicUsize,
    unavailable: bool,
}

impl SelectingJudge {
    fn new(selected_index: usize) -> Self {
        Self {
            selected_index,
            calls: AtomicUsize::new(0),
            unavailable: false,
        }
    }

    fn unavailable() -> Self {
        Self {
            selected_index: 0,
            calls: AtomicUsize::new(0),
            unavailable: true,
        }
    }
}

#[async_trait]
impl WorkspaceContextJudgePort for SelectingJudge {
    async fn select(
        &self,
        request: &WorkspaceContextJudgmentRequest,
    ) -> Result<WorkspaceContextJudgment, WorkspaceContextJudgePortError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if self.unavailable {
            return Err(WorkspaceContextJudgePortError::Unavailable);
        }
        let selected = request
            .candidates()
            .get(self.selected_index)
            .cloned()
            .ok_or(WorkspaceContextJudgePortError::Unavailable)?;
        WorkspaceContextJudgment::new(
            request,
            self.selected_index,
            selected,
            "structured test rationale".to_string(),
            vec!["candidate is in the supplied set".to_string()],
            "judge-agent".to_string(),
            "select_workspace_context".to_string(),
            json!({"candidate_count": request.candidates().len()}),
            json!({"candidate_index": self.selected_index}),
            3,
        )
        .map_err(|_| WorkspaceContextJudgePortError::Unavailable)
    }
}

#[tokio::test]
async fn context_service_judges_ambiguity_and_commits_cas_replay_audit_and_outbox()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let judge = SelectingJudge::new(1);
    let service = PublicWorkspaceContextService::new(&db, DbSqlFlavor::Sqlite, &judge);

    let initialized = service.get_or_initialize("user-1").await?;
    assert_eq!(initialized.context.tenant_id, "tenant-2");
    assert_eq!(initialized.context.project_id, "project-2");
    assert_eq!(initialized.context.revision, 0);
    assert_eq!(initialized.membership_role, "owner");
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(table_count(&db, "workspace_judge_audits").await?, 1);
    assert_eq!(table_count(&db, "workspace_context_outbox").await?, 1);

    let direct = service.get_or_initialize("user-1").await?;
    assert_eq!(direct, initialized);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);

    let switch = PublicSwitchWorkspaceContextInput {
        user_id: "user-1".to_string(),
        actor_api_key_id: Some("api-key-1".to_string()),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        expected_revision: 0,
        idempotency_key: "switch-1".to_string(),
    };
    let switched = service.switch(&switch).await?;
    assert!(switched.changed);
    assert_eq!(switched.context.revision, 1);
    assert_eq!(switched.context.tenant_id, "tenant-1");

    let replayed = service.switch(&switch).await?;
    assert!(!replayed.changed);
    assert_eq!(replayed.context, switched.context);
    assert_eq!(table_count(&db, "workspace_context_events").await?, 1);
    assert_eq!(table_count(&db, "workspace_context_outbox").await?, 2);

    let conflicting = PublicSwitchWorkspaceContextInput {
        project_id: "project-2".to_string(),
        ..switch.clone()
    };
    assert!(matches!(
        service.switch(&conflicting).await,
        Err(PublicWorkspaceContextError::IdempotencyConflict)
    ));

    db.execute(DbStatement::new(
        "UPDATE project_principal_memberships SET is_active = 0 WHERE user_id = 'user-1'",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, role, is_active) VALUES ('tenant-3', 'project-3', 'user-1', 'member', 1)",
    ))
    .await?;
    let repaired = service.get_or_initialize("user-1").await?;
    assert_eq!(repaired.context.tenant_id, "tenant-3");
    assert_eq!(repaired.context.revision, 2);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(table_count(&db, "workspace_context_events").await?, 2);
    assert_eq!(table_count(&db, "workspace_context_outbox").await?, 3);
    Ok(())
}

#[tokio::test]
async fn context_service_audits_judge_failure_without_writing_context() -> Result<(), Box<dyn Error>>
{
    let db = seeded_db().await?;
    let judge = SelectingJudge::unavailable();
    let service = PublicWorkspaceContextService::new(&db, DbSqlFlavor::Sqlite, &judge);

    assert!(matches!(
        service.get_or_initialize("user-1").await,
        Err(PublicWorkspaceContextError::Judge(
            WorkspaceContextJudgePortError::Unavailable
        ))
    ));
    assert_eq!(table_count(&db, "workspace_judge_audits").await?, 1);
    assert_eq!(table_count(&db, "workspace_contexts").await?, 0);
    assert_eq!(table_count(&db, "workspace_context_outbox").await?, 0);
    Ok(())
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE workspace_contexts (user_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_context_events (event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, actor_api_key_id TEXT, from_tenant_id TEXT, from_project_id TEXT, to_tenant_id TEXT NOT NULL, to_project_id TEXT NOT NULL, revision INTEGER NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, value_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(user_id, idempotency_key), UNIQUE(user_id, revision))",
        "CREATE TABLE workspace_judge_audits (audit_id TEXT PRIMARY KEY, tenant_id TEXT, project_id TEXT, workspace_id TEXT, plan_id TEXT, plan_node_id TEXT, user_id TEXT, judgment_type TEXT NOT NULL, agent_id TEXT NOT NULL, tool_name TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL, rationale TEXT NOT NULL, latency_ms INTEGER NOT NULL, status TEXT NOT NULL, error_detail TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE workspace_context_outbox (outbox_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, actor_api_key_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 12, next_attempt_at TEXT, lease_owner TEXT, lease_expires_at TEXT, dispatched_at TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id, idempotency_key), UNIQUE(user_id, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    for statement in [
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, role, is_active) VALUES ('tenant-1', 'project-1', 'user-1', 'member', 1)",
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, role, is_active) VALUES ('tenant-2', 'project-2', 'user-1', 'owner', 1)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_contexts" => "SELECT COUNT(*) AS value FROM workspace_contexts",
        "workspace_context_events" => "SELECT COUNT(*) AS value FROM workspace_context_events",
        "workspace_context_outbox" => "SELECT COUNT(*) AS value FROM workspace_context_outbox",
        "workspace_judge_audits" => "SELECT COUNT(*) AS value FROM workspace_judge_audits",
        _ => return Err("unsupported table".into()),
    };
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing count row")?
        .get_i64("value")?
        .ok_or("missing count")?)
}
