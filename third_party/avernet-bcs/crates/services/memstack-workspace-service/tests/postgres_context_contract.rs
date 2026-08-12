use std::error::Error;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    PublicSwitchWorkspaceContextInput, PublicWorkspaceContextError,
    PublicWorkspaceContextErrorKind, PublicWorkspaceContextService,
};
use memstack_workspace_service_api::{
    WorkspaceContextJudgePort, WorkspaceContextJudgePortError, WorkspaceContextJudgment,
    WorkspaceContextJudgmentRequest,
};
use serde_json::json;

const USER_ID: &str = "user-context-pg-contract";
const TENANT_ONE: &str = "tenant-context-pg-one";
const TENANT_TWO: &str = "tenant-context-pg-two";
const PROJECT_ONE: &str = "project-context-pg-one";
const PROJECT_TWO: &str = "project-context-pg-two";

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
            "structured PostgreSQL contract rationale".to_string(),
            vec!["candidate belongs to the supplied set".to_string()],
            "judge-context-pg-contract".to_string(),
            "select_workspace_context".to_string(),
            json!({"candidate_count": request.candidates().len()}),
            json!({"candidate_index": self.selected_index}),
            4,
        )
        .map_err(|_| WorkspaceContextJudgePortError::Unavailable)
    }
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_context_jsonb_judge_cas_replay_audit_and_outbox_are_atomic()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_memberships(&db, true).await?;
    let judge = SelectingJudge::new(1);
    let service = PublicWorkspaceContextService::new(&db, DbSqlFlavor::Postgres, &judge);

    let initialized = service.get_or_initialize(USER_ID).await?;
    assert_eq!(initialized.context.tenant_id, TENANT_TWO);
    assert_eq!(initialized.context.project_id, PROJECT_TWO);
    assert_eq!(initialized.context.revision, 0);
    assert_eq!(initialized.membership_role, "owner");
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(scoped_count(&db, "workspace_contexts").await?, 1);
    assert_eq!(scoped_count(&db, "workspace_judge_audits").await?, 1);
    assert_eq!(scoped_count(&db, "workspace_context_outbox").await?, 1);
    assert_eq!(jsonb_type(&db, "workspace_context_outbox").await?, "jsonb");
    assert_eq!(jsonb_type(&db, "workspace_judge_audits").await?, "jsonb");

    let direct = service.get_or_initialize(USER_ID).await?;
    assert_eq!(direct, initialized);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);

    let switch = PublicSwitchWorkspaceContextInput {
        user_id: USER_ID.to_string(),
        actor_api_key_id: Some("api-key-context-pg".to_string()),
        tenant_id: TENANT_ONE.to_string(),
        project_id: PROJECT_ONE.to_string(),
        expected_revision: 0,
        idempotency_key: "context-switch-pg-one".to_string(),
    };
    let switched = service.switch(&switch).await?;
    assert!(switched.changed);
    assert_eq!(switched.context.revision, 1);
    assert_eq!(switched.context.tenant_id, TENANT_ONE);

    let replayed = service.switch(&switch).await?;
    assert!(!replayed.changed);
    assert_eq!(replayed.context, switched.context);
    assert_eq!(scoped_count(&db, "workspace_context_events").await?, 1);
    assert_eq!(scoped_count(&db, "workspace_context_outbox").await?, 2);
    assert_eq!(request_hash_length(&db).await?, 64);

    let conflicting = PublicSwitchWorkspaceContextInput {
        tenant_id: TENANT_TWO.to_string(),
        project_id: PROJECT_TWO.to_string(),
        ..switch.clone()
    };
    assert!(matches!(
        service.switch(&conflicting).await,
        Err(PublicWorkspaceContextError::IdempotencyConflict)
    ));

    let stale = PublicSwitchWorkspaceContextInput {
        expected_revision: 0,
        idempotency_key: "context-switch-pg-stale".to_string(),
        ..conflicting
    };
    let error = match service.switch(&stale).await {
        Ok(_) => return Err("stale Context revision must fail".into()),
        Err(error) => error,
    };
    assert_eq!(error.kind(), PublicWorkspaceContextErrorKind::Conflict);
    assert_eq!(context_revision(&db).await?, 1);
    assert_eq!(scoped_count(&db, "workspace_context_events").await?, 1);
    assert_eq!(scoped_count(&db, "workspace_context_outbox").await?, 2);

    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_context_outbox_failure_rolls_back_context_and_judge_audit()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_memberships(&db, true).await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_context_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.user_id = 'user-context-pg-contract' THEN RAISE EXCEPTION 'injected Context outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_context_outbox BEFORE INSERT ON workspace_context_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_context_outbox()",
    ))
    .await?;

    let judge = SelectingJudge::new(0);
    let error = match PublicWorkspaceContextService::new(&db, DbSqlFlavor::Postgres, &judge)
        .get_or_initialize(USER_ID)
        .await
    {
        Ok(_) => return Err("fault-injected Context transaction must fail".into()),
        Err(error) => error,
    };
    drop_fault_trigger(&db).await?;

    assert_eq!(error.kind(), PublicWorkspaceContextErrorKind::Unavailable);
    assert_eq!(judge.calls.load(Ordering::SeqCst), 1);
    assert_eq!(scoped_count(&db, "workspace_contexts").await?, 0);
    assert_eq!(scoped_count(&db, "workspace_judge_audits").await?, 0);
    assert_eq!(scoped_count(&db, "workspace_context_outbox").await?, 0);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_context_judge_failure_persists_only_user_scoped_audit()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_memberships(&db, true).await?;
    let judge = SelectingJudge::unavailable();

    let error = match PublicWorkspaceContextService::new(&db, DbSqlFlavor::Postgres, &judge)
        .get_or_initialize(USER_ID)
        .await
    {
        Ok(_) => return Err("unavailable Context Judge must fail closed".into()),
        Err(error) => error,
    };

    assert!(matches!(
        error,
        PublicWorkspaceContextError::Judge(WorkspaceContextJudgePortError::Unavailable)
    ));
    assert_eq!(scoped_count(&db, "workspace_contexts").await?, 0);
    assert_eq!(scoped_count(&db, "workspace_judge_audits").await?, 1);
    assert_eq!(scoped_count(&db, "workspace_context_outbox").await?, 0);
    assert_eq!(failed_audit_scope(&db).await?, (None, None));
    cleanup(&db).await?;
    Ok(())
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn seed_memberships(db: &dyn DbPlugin, include_second: bool) -> Result<(), Box<dyn Error>> {
    insert_membership(db, TENANT_ONE, PROJECT_ONE, "member", "one").await?;
    if include_second {
        insert_membership(db, TENANT_TWO, PROJECT_TWO, "owner", "two").await?;
    }
    Ok(())
}

async fn insert_membership(
    db: &dyn DbPlugin,
    tenant_id: &str,
    project_id: &str,
    role: &str,
    suffix: &str,
) -> Result<(), Box<dyn Error>> {
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, \
                 participant_actor_id, source_membership_id, role, permissions_json, is_active, \
                 identity_authority, source_created_at, source_updated_at) VALUES (",
            )
            .bind(tenant_id)
            .push_static(", ")
            .bind(project_id)
            .push_static(", ")
            .bind(USER_ID)
            .push_static(", ")
            .bind(format!("human:{USER_ID}"))
            .push_static(", ")
            .bind(format!("membership-context-pg-{suffix}"))
            .push_static(", ")
            .bind(role)
            .push_static(", '{}'::jsonb, TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            .build(),
    )
    .await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    drop_fault_trigger(db).await?;
    for table in [
        "workspace_context_outbox",
        "workspace_context_events",
        "workspace_contexts",
        "workspace_judge_audits",
        "project_principal_memberships",
    ] {
        let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM ")
            .push_static(table)
            .push_static(" WHERE user_id = ")
            .bind(USER_ID)
            .build();
        db.execute(statement).await?;
    }
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_context_outbox ON workspace_context_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_context_outbox()",
    ))
    .await?;
    Ok(())
}

async fn scoped_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_contexts" => {
            "SELECT COUNT(*) AS value FROM workspace_contexts WHERE user_id = $1"
        }
        "workspace_context_events" => {
            "SELECT COUNT(*) AS value FROM workspace_context_events WHERE user_id = $1"
        }
        "workspace_context_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_context_outbox WHERE user_id = $1"
        }
        "workspace_judge_audits" => {
            "SELECT COUNT(*) AS value FROM workspace_judge_audits WHERE user_id = $1"
        }
        _ => return Err("unsupported table".into()),
    };
    query_i64(db, sql).await
}

async fn context_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT revision AS value FROM workspace_contexts WHERE user_id = $1",
    )
    .await
}

async fn request_hash_length(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT length(request_hash) AS value FROM workspace_context_events WHERE user_id = $1",
    )
    .await
}

async fn jsonb_type(db: &dyn DbPlugin, table: &str) -> Result<String, Box<dyn Error>> {
    let sql = match table {
        "workspace_context_outbox" => {
            "SELECT pg_typeof(payload_json)::text AS value FROM workspace_context_outbox WHERE user_id = $1 LIMIT 1"
        }
        "workspace_judge_audits" => {
            "SELECT pg_typeof(input_json)::text AS value FROM workspace_judge_audits WHERE user_id = $1 LIMIT 1"
        }
        _ => return Err("unsupported JSONB table".into()),
    };
    let rows = db
        .query(DbStatement::with_params(sql, vec![USER_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing JSONB row")?
        .get_string("value")?
        .ok_or("missing JSONB type")?)
}

async fn failed_audit_scope(
    db: &dyn DbPlugin,
) -> Result<(Option<String>, Option<String>), Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT tenant_id, project_id FROM workspace_judge_audits WHERE user_id = $1",
            vec![USER_ID.into()],
        ))
        .await?;
    let row = rows.first().ok_or("missing failed Judge audit")?;
    Ok((row.get_string("tenant_id")?, row.get_string("project_id")?))
}

async fn query_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![USER_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}
