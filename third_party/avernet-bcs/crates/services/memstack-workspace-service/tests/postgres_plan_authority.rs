use std::error::Error;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicWorkspacePlanAction, PublicWorkspacePlanActionInput,
    PublicWorkspacePlanContext, PublicWorkspacePlanErrorKind, PublicWorkspacePlanService,
    PublicWorkspacePlanSnapshotInput, WorkspaceCreationService,
};
use memstack_workspace_service_api::{
    WorkspacePlanJudgePort, WorkspacePlanJudgePortError, WorkspacePlanJudgment,
    WorkspacePlanJudgmentRequest,
};
use serde_json::json;

const TENANT_ID: &str = "tenant-plan-pg-contract";
const PROJECT_ID: &str = "project-plan-pg-contract";
const WORKSPACE_ID: &str = "workspace-plan-pg-contract";
const GROUP_ID: &str = "group-plan-pg-contract";
const USER_ID: &str = "actor-plan-pg-contract";
const PLAN_ID: &str = "plan-pg-contract";
const NODE_ID: &str = "node-plan-pg-contract";

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
            request
                .kind()
                .requires_selected_node()
                .then(|| request.candidate_node_ids().first().cloned())
                .flatten(),
            "structured PostgreSQL Plan verdict".to_string(),
            "plan-pg-judge-agent".to_string(),
            "judge_workspace_plan".to_string(),
            request.evidence().clone(),
            json!({"proceed": true}),
            5,
        )
        .map_err(|_| WorkspacePlanJudgePortError::Unavailable)
    }
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_plan_authority_replays_cas_and_commits_judge_event_outbox_atomically()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_plan(&db, "blocked").await?;
    let judge = ProceedingJudge::new();
    let service = PublicWorkspacePlanService::new(&db, DbSqlFlavor::Postgres, &judge);
    let snapshot = service
        .snapshot(&PublicWorkspacePlanSnapshotInput {
            context: context(),
            plan_id: None,
            include_details: true,
            outbox_limit: 20,
            event_limit: 50,
        })
        .await?;
    assert_eq!(
        snapshot.plan.as_ref().map(|plan| plan.id.as_str()),
        Some(PLAN_ID)
    );

    let input = action(
        PublicWorkspacePlanAction::RequestNodeReplan,
        Some(NODE_ID),
        "plan-pg-replan",
        Some(1),
    );
    let committed = service.act(&input).await?;
    let replayed = service.act(&input).await?;
    assert_eq!(committed, replayed);
    assert_eq!(committed.node_id.as_deref(), Some(NODE_ID));
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(plan_revision(&db).await?, 2);
    assert_eq!(node_status(&db).await?, "pending");
    assert_eq!(workspace_count(&db, "workspace_judge_audits").await?, 1);
    assert_eq!(workspace_count(&db, "workspace_plan_events").await?, 1);
    assert_eq!(plan_outbox_count(&db).await?, 1);

    let stale = match service
        .act(&action(
            PublicWorkspacePlanAction::PauseIteration,
            None,
            "plan-pg-stale",
            Some(1),
        ))
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("stale Plan revision must fail".into()),
    };
    assert_eq!(stale.kind(), PublicWorkspacePlanErrorKind::Conflict);
    assert_eq!(plan_revision(&db).await?, 2);
    assert_eq!(workspace_count(&db, "workspace_plan_events").await?, 1);
    assert_eq!(plan_outbox_count(&db).await?, 1);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_plan_outbox_failure_rolls_back_transition_event_and_revision()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_plan(&db, "pending").await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_plan_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-plan-pg-contract' AND NEW.aggregate_type = 'workspace_plan' THEN RAISE EXCEPTION 'injected plan outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_plan_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_plan_outbox()",
    ))
    .await?;
    let judge = ProceedingJudge::new();
    let service = PublicWorkspacePlanService::new(&db, DbSqlFlavor::Postgres, &judge);

    let error = match service
        .act(&action(
            PublicWorkspacePlanAction::PauseIteration,
            None,
            "plan-pg-rollback",
            Some(1),
        ))
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("outbox failure must abort the complete Plan transaction".into()),
    };
    drop_fault_trigger(&db).await?;

    assert_eq!(error.kind(), PublicWorkspacePlanErrorKind::Unavailable);
    assert_eq!(plan_revision(&db).await?, 1);
    assert_eq!(plan_status(&db).await?, "active");
    assert_eq!(workspace_count(&db, "workspace_plan_events").await?, 0);
    assert_eq!(workspace_count(&db, "workspace_judge_audits").await?, 0);
    assert_eq!(plan_outbox_count(&db).await?, 0);
    cleanup(&db).await?;
    Ok(())
}

fn context() -> PublicWorkspacePlanContext {
    PublicWorkspacePlanContext {
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        actor_id: USER_ID.to_string(),
        actor_is_superuser: false,
    }
}

fn action(
    action: PublicWorkspacePlanAction,
    node_id: Option<&str>,
    idempotency_key: &str,
    expected_revision: Option<u64>,
) -> PublicWorkspacePlanActionInput {
    PublicWorkspacePlanActionInput {
        context: context(),
        action,
        node_id: node_id.map(str::to_string),
        outbox_id: None,
        reason: Some("operator supplied structured reason".to_string()),
        evidence_refs: vec!["evidence://postgres-plan-contract".to_string()],
        idempotency_key: Some(idempotency_key.to_string()),
        expected_revision,
    }
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn seed_plan(db: &dyn DbPlugin, node_status: &str) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-plan-pg-contract', 'project-plan-pg-contract', 'actor-plan-pg-contract', 'actor-plan-pg-contract', 'membership-plan-pg-contract', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
    ))
    .await?;
    WorkspaceCreationService::new(db, DbSqlFlavor::Postgres)
        .create(&CreateWorkspaceInput {
            scope: CreateWorkspaceScopeInput {
                tenant_id: TENANT_ID.to_string(),
                project_id: PROJECT_ID.to_string(),
                workspace_id: WORKSPACE_ID.to_string(),
                group_id: GROUP_ID.to_string(),
            },
            owner: CreateWorkspaceOwnerInput {
                member_id: "member-plan-pg-contract".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL Plan Workspace".to_string(),
                description: Some("Plan authority contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "plan-pg-workspace-create".to_string(),
        })
        .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_plans (plan_id, tenant_id, project_id, workspace_id, collaboration_definition_id, collaboration_definition_version, goal, goal_json, status, revision, metadata_json, created_at, updated_at) VALUES ('plan-pg-contract', 'tenant-plan-pg-contract', 'project-plan-pg-contract', 'workspace-plan-pg-contract', 'definition-plan-pg-contract', 1, 'Ship the PostgreSQL Plan contract', '{\"id\":\"node-plan-pg-contract\"}'::jsonb, 'active', 1, '{\"iteration_loop\":{\"loop_status\":\"active\"}}'::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    ))
    .await?;
    db.execute(DbStatement::with_params(
        "INSERT INTO workspace_plan_nodes (node_id, tenant_id, project_id, workspace_id, plan_id, kind, title, description, intent, status, sequence_number, dependencies_json, acceptance_criteria_json, recommended_capabilities_json, priority, progress_json, metadata_json, created_at, updated_at) VALUES ('node-plan-pg-contract', 'tenant-plan-pg-contract', 'project-plan-pg-contract', 'workspace-plan-pg-contract', 'plan-pg-contract', 'goal', 'Ship migration', 'Root goal', 'todo', $1, 0, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 0, '{\"percent\":0}'::jsonb, '{}'::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        vec![node_status.into()],
    ))
    .await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    drop_fault_trigger(db).await?;
    for statement in [
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_judge_audits WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_group_participants WHERE group_id = ")
            .bind(GROUP_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_groups WHERE group_id = ")
            .bind(GROUP_ID)
            .build(),
        DbStatement::new(
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-plan-pg-contract'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_plan_outbox ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_plan_outbox()",
    ))
    .await?;
    Ok(())
}

async fn workspace_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_plan_events" => {
            "SELECT COUNT(*) AS value FROM workspace_plan_events WHERE workspace_id = $1"
        }
        "workspace_judge_audits" => {
            "SELECT COUNT(*) AS value FROM workspace_judge_audits WHERE workspace_id = $1"
        }
        _ => return Err("unsupported table".into()),
    };
    query_i64(db, sql).await
}

async fn plan_outbox_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1 AND aggregate_type = 'workspace_plan'",
    )
    .await
}

async fn plan_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT revision AS value FROM workspace_plans WHERE workspace_id = $1",
    )
    .await
}

async fn plan_status(db: &dyn DbPlugin) -> Result<String, Box<dyn Error>> {
    query_string(
        db,
        "SELECT status AS value FROM workspace_plans WHERE workspace_id = $1",
    )
    .await
}

async fn node_status(db: &dyn DbPlugin) -> Result<String, Box<dyn Error>> {
    query_string(
        db,
        "SELECT status AS value FROM workspace_plan_nodes WHERE workspace_id = $1",
    )
    .await
}

async fn query_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![WORKSPACE_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn query_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![WORKSPACE_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}
