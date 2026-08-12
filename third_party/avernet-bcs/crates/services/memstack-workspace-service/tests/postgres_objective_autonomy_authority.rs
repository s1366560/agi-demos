use std::error::Error;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicCreateWorkspaceObjectiveInput,
    PublicUpdateWorkspaceObjectiveFields, PublicWorkspaceAutonomyContext,
    PublicWorkspaceAutonomyErrorKind, PublicWorkspaceAutonomyJudgePort,
    PublicWorkspaceAutonomyJudgePortError, PublicWorkspaceAutonomyJudgment,
    PublicWorkspaceAutonomyJudgmentRequest, PublicWorkspaceAutonomyService,
    PublicWorkspaceAutonomyVerdictKind, PublicWorkspaceObjectiveContext,
    PublicWorkspaceObjectiveErrorKind, PublicWorkspaceObjectiveService, WorkspaceCreationService,
};
use serde_json::json;

const TENANT_ID: &str = "tenant-objective-autonomy-pg";
const PROJECT_ID: &str = "project-objective-autonomy-pg";
const WORKSPACE_ID: &str = "workspace-objective-autonomy-pg";
const GROUP_ID: &str = "group-objective-autonomy-pg";
const USER_ID: &str = "actor-objective-autonomy-pg";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_objective_crud_projection_replay_cas_and_history_are_consistent()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    let service = PublicWorkspaceObjectiveService::new(&db, DbSqlFlavor::Postgres);
    let create = PublicCreateWorkspaceObjectiveInput {
        context: objective_context("objective-create", 1),
        title: "Replace Workspace Core".to_string(),
        description: Some("Complete the Avernet authority".to_string()),
        objective_type: "objective".to_string(),
        parent_objective_id: None,
        progress: 0.25,
    };

    let created = service.create(&create).await?;
    let replayed = service.create(&create).await?;
    assert_eq!(created.objective, replayed.objective);
    assert_eq!(created.committed_revision, 2);
    assert!(!created.replayed);
    assert!(replayed.replayed);

    let updated = service
        .update(
            &objective_context("objective-update", 2),
            created.objective.id.as_str(),
            &PublicUpdateWorkspaceObjectiveFields {
                title: Some("Complete Avernet integration".to_string()),
                progress: Some(0.5),
                ..PublicUpdateWorkspaceObjectiveFields::default()
            },
        )
        .await?;
    assert_eq!(updated.committed_revision, 3);
    assert_eq!(updated.objective.progress, 0.5);

    let projected = service
        .project_to_task(
            &objective_context("objective-project", 3),
            created.objective.id.as_str(),
            Some("zh-CN"),
        )
        .await?;
    let projection_replay = service
        .project_to_task(
            &objective_context("objective-project", 3),
            created.objective.id.as_str(),
            Some("zh-CN"),
        )
        .await?;
    assert_eq!(projected.committed_revision, 4);
    assert!(!projected.existing);
    assert!(projection_replay.existing);
    assert!(projection_replay.replayed);
    assert_eq!(projected.task.metadata["task_role"], "goal_root");
    assert_eq!(
        projected.task.metadata["objective_id"],
        created.objective.id
    );

    let stale = require_error(
        service
            .update(
                &objective_context("objective-stale", 3),
                created.objective.id.as_str(),
                &PublicUpdateWorkspaceObjectiveFields {
                    title: Some("must roll back".to_string()),
                    ..PublicUpdateWorkspaceObjectiveFields::default()
                },
            )
            .await,
        "stale Objective revision must fail",
    );
    assert_eq!(stale.kind(), PublicWorkspaceObjectiveErrorKind::Conflict);
    assert_eq!(workspace_revision(&db).await?, 4);

    let deleted = service
        .delete(
            &objective_context("objective-delete", 4),
            created.objective.id.as_str(),
        )
        .await?;
    assert_eq!(deleted.committed_revision, 5);
    assert_eq!(workspace_revision(&db).await?, 5);
    assert_eq!(scoped_count(&db, "workspace_objectives", "TRUE").await?, 0);
    assert_eq!(scoped_count(&db, "workspace_tasks", "TRUE").await?, 1);
    assert_eq!(
        scoped_count(&db, "workspace_objective_task_projections", "TRUE").await?,
        1,
        "Objective deletion must preserve durable Task provenance"
    );
    assert_eq!(
        scoped_count(&db, "workspace_mutation_receipts", "surface = 'objective'",).await?,
        3
    );
    assert_eq!(
        scoped_count(&db, "workspace_task_receipts", "action = 'create_task'").await?,
        1
    );

    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_autonomy_uses_structured_judge_replay_and_atomic_outbox_rollback()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    seed_root_task(&db).await?;
    let judge = FirstCandidateJudge::default();
    let service = PublicWorkspaceAutonomyService::new(&db, DbSqlFlavor::Postgres, &judge);

    let first = service
        .tick(&autonomy_context("autonomy-tick", 1), true)
        .await?;
    let replay = service
        .tick(&autonomy_context("autonomy-tick", 1), true)
        .await?;
    assert_eq!(first.response, replay.response);
    assert!(first.response.triggered);
    assert_eq!(first.response.root_task_id.as_deref(), Some("root-task-pg"));
    assert_eq!(first.committed_revision, 2);
    assert!(!first.replayed);
    assert!(replay.replayed);
    assert_eq!(judge.calls.load(Ordering::Relaxed), 1);
    assert_eq!(workspace_revision(&db).await?, 2);
    assert_eq!(
        scoped_count(&db, "workspace_autonomy_ticks", "TRUE").await?,
        1
    );
    assert_eq!(
        scoped_count(
            &db,
            "workspace_judge_audits",
            "judgment_type = 'autonomy_tick' AND status = 'completed'",
        )
        .await?,
        1
    );

    install_autonomy_outbox_fault(&db).await?;
    let error = require_error(
        service
            .tick(&autonomy_context("autonomy-outbox-fail", 2), true)
            .await,
        "injected Autonomy outbox failure must fail",
    );
    drop_autonomy_outbox_fault(&db).await?;
    assert_eq!(error.kind(), PublicWorkspaceAutonomyErrorKind::Unavailable);
    assert_eq!(workspace_revision(&db).await?, 2);
    assert_eq!(
        scoped_count(&db, "workspace_autonomy_ticks", "TRUE").await?,
        1
    );
    assert_eq!(
        scoped_count(
            &db,
            "workspace_judge_audits",
            "judgment_type = 'autonomy_tick' AND status = 'completed'",
        )
        .await?,
        1,
        "Judge audit must roll back with the failed Autonomy command"
    );
    assert_eq!(
        scoped_count(&db, "workspace_mutation_receipts", "surface = 'autonomy'",).await?,
        1
    );
    assert_eq!(
        scoped_count(
            &db,
            "workspace_outbox",
            "aggregate_type = 'workspace_autonomy'",
        )
        .await?,
        1
    );

    cleanup(&db).await?;
    Ok(())
}

#[derive(Default)]
struct FirstCandidateJudge {
    calls: AtomicUsize,
}

#[async_trait]
impl PublicWorkspaceAutonomyJudgePort for FirstCandidateJudge {
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError> {
        self.calls.fetch_add(1, Ordering::Relaxed);
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
            "autonomy-pg-judge".to_string(),
            "judge_workspace_autonomy".to_string(),
            json!({"candidate_ids": [root_task_id.clone()]}),
            json!({"verdict": "continue", "selected_root_task_id": root_task_id}),
            9,
        )
        .map_err(|_| PublicWorkspaceAutonomyJudgePortError::Unavailable)
    }
}

fn objective_context(
    idempotency_key: &str,
    expected_revision: u64,
) -> PublicWorkspaceObjectiveContext {
    PublicWorkspaceObjectiveContext {
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        user_id: USER_ID.to_string(),
        is_superuser: false,
        expected_revision: Some(expected_revision),
        idempotency_key: Some(idempotency_key.to_string()),
    }
}

fn autonomy_context(
    idempotency_key: &str,
    expected_revision: u64,
) -> PublicWorkspaceAutonomyContext {
    PublicWorkspaceAutonomyContext {
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        user_id: USER_ID.to_string(),
        is_superuser: false,
        expected_revision: Some(expected_revision),
        idempotency_key: Some(idempotency_key.to_string()),
    }
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn seed_project_membership(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-objective-autonomy-pg', 'project-objective-autonomy-pg', 'actor-objective-autonomy-pg', 'actor-objective-autonomy-pg', 'membership-objective-autonomy-pg', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
    ))
    .await?;
    Ok(())
}

async fn create_workspace(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    WorkspaceCreationService::new(db, DbSqlFlavor::Postgres)
        .create(&CreateWorkspaceInput {
            scope: CreateWorkspaceScopeInput {
                tenant_id: TENANT_ID.to_string(),
                project_id: PROJECT_ID.to_string(),
                workspace_id: WORKSPACE_ID.to_string(),
                group_id: GROUP_ID.to_string(),
            },
            owner: CreateWorkspaceOwnerInput {
                member_id: "member-objective-autonomy-pg".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL Objective Autonomy Workspace".to_string(),
                description: Some("Objective and Autonomy authority contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "objective-autonomy-workspace-create".to_string(),
        })
        .await?;
    Ok(())
}

async fn seed_root_task(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, description, created_by, status, priority, metadata_json) VALUES ('root-task-pg', 'tenant-objective-autonomy-pg', 'project-objective-autonomy-pg', 'workspace-objective-autonomy-pg', 'Root objective', 'Proceed through the structured judge', 'actor-objective-autonomy-pg', 'todo', 2, '{\"task_role\":\"goal_root\"}'::jsonb)",
    ))
    .await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    drop_autonomy_outbox_fault(db).await?;
    for statement in [
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
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-objective-autonomy-pg'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn install_autonomy_outbox_fault(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_autonomy_outbox_contract() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-objective-autonomy-pg' AND NEW.aggregate_type = 'workspace_autonomy' THEN RAISE EXCEPTION 'injected Autonomy outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_autonomy_outbox_contract BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_autonomy_outbox_contract()",
    ))
    .await?;
    Ok(())
}

async fn drop_autonomy_outbox_fault(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_autonomy_outbox_contract ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_autonomy_outbox_contract()",
    ))
    .await?;
    Ok(())
}

async fn workspace_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
            vec![WORKSPACE_ID.into()],
        ))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing authority")?
        .get_i64("value")?
        .ok_or("missing revision")?)
}

async fn scoped_count(
    db: &dyn DbPlugin,
    table: &'static str,
    predicate: &'static str,
) -> Result<i64, Box<dyn Error>> {
    let allowed = [
        "workspace_autonomy_ticks",
        "workspace_judge_audits",
        "workspace_mutation_receipts",
        "workspace_objective_task_projections",
        "workspace_objectives",
        "workspace_outbox",
        "workspace_task_receipts",
        "workspace_tasks",
    ];
    if !allowed.contains(&table) {
        return Err("unsupported table".into());
    }
    let allowed_predicates = [
        "TRUE",
        "action = 'create_task'",
        "aggregate_type = 'workspace_autonomy'",
        "judgment_type = 'autonomy_tick' AND status = 'completed'",
        "surface = 'autonomy'",
        "surface = 'objective'",
    ];
    if !allowed_predicates.contains(&predicate) {
        return Err("unsupported predicate".into());
    }
    let sql =
        format!("SELECT COUNT(*) AS value FROM {table} WHERE workspace_id = $1 AND {predicate}");
    let rows = db
        .query(DbStatement::with_params(sql, vec![WORKSPACE_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing count")?
        .get_i64("value")?
        .ok_or("missing count value")?)
}

fn require_error<T, E>(result: Result<T, E>, message: &str) -> E {
    match result {
        Ok(_) => panic!("{message}"),
        Err(error) => error,
    }
}
