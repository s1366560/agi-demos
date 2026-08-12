use std::error::Error;

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep,
};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service_api::{
    ActorId, ContractVersion, ExpectedRevision, IdempotencyKey, ProjectId, RequestHash, TenantId,
    WorkspaceActor, WorkspaceCommandError, WorkspaceId, WorkspaceMutationAction,
    WorkspaceMutationCommand, WorkspaceScope,
};
use memstack_workspace_store::{
    WorkspaceDomainMutation, WorkspaceMutationPlanner, WorkspaceMutationStore,
    WorkspaceMutationStoreError,
};
use serde_json::json;

const INITIAL_REVISION: u64 = 7;

#[tokio::test]
async fn successful_mutation_commits_domain_revision_receipt_and_outbox()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db("owner").await?;
    let command = mutation_command(
        INITIAL_REVISION,
        "success-key",
        'a',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let plan = mutation_plan(&command, domain_update("updated"))?;
    let outcome = WorkspaceMutationStore::new(&db)
        .execute(&command, plan.clone())
        .await?;

    assert!(!outcome.replayed);
    assert_eq!(outcome.receipt_id, plan.receipt_id());
    assert_eq!(outcome.committed_revision, INITIAL_REVISION + 1);
    assert_eq!(
        outcome.response,
        json!({"id": "workspace-1", "name": "updated"})
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities",).await?,
        8
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    assert_eq!(
        scalar_string(&db, "SELECT value FROM domain_records").await?,
        "updated"
    );
    assert_eq!(
        scalar_string(&db, "SELECT event_type AS value FROM workspace_outbox").await?,
        "workspace_updated"
    );
    Ok(())
}

#[tokio::test]
async fn domain_row_count_failure_rolls_back_every_write() -> Result<(), Box<dyn Error>> {
    let db = seeded_db("owner").await?;
    let command = mutation_command(
        INITIAL_REVISION,
        "domain-failure-key",
        'b',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let missing_domain = DbStatementBuilder::new(DbSqlFlavor::Sqlite)
        .push_static("UPDATE domain_records SET value = ")
        .bind("partial")
        .push_static(" WHERE workspace_id = ")
        .bind("missing-workspace")
        .build();
    let plan = mutation_plan(&command, missing_domain)?;

    let error = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;

    assert!(matches!(
        error,
        Err(WorkspaceMutationStoreError::DomainConflict)
    ));
    assert_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn stale_revision_rolls_back_receipt_before_domain_write() -> Result<(), Box<dyn Error>> {
    let db = seeded_db("owner").await?;
    let command = mutation_command(
        INITIAL_REVISION - 1,
        "revision-conflict-key",
        'c',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let plan = mutation_plan(&command, domain_update("must-not-commit"))?;

    let error = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;

    assert!(matches!(
        error,
        Err(WorkspaceMutationStoreError::RevisionConflict)
    ));
    assert_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn viewer_access_failure_does_not_reserve_a_receipt() -> Result<(), Box<dyn Error>> {
    let db = seeded_db("viewer").await?;
    let command = mutation_command(
        INITIAL_REVISION,
        "access-denied-key",
        'd',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let plan = mutation_plan(&command, domain_update("must-not-commit"))?;

    let error = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;

    assert!(matches!(
        error,
        Err(WorkspaceMutationStoreError::AccessDenied)
    ));
    assert_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn receipt_reservation_failure_rolls_back_before_domain_write() -> Result<(), Box<dyn Error>>
{
    let db = seeded_db("owner").await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_receipt_insert BEFORE INSERT ON workspace_mutation_receipts BEGIN SELECT RAISE(IGNORE); END",
    ))
    .await?;
    let command = mutation_command(
        INITIAL_REVISION,
        "receipt-failure-key",
        '2',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let plan = mutation_plan(&command, domain_update("must-not-commit"))?;

    let error = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;

    assert!(matches!(
        error,
        Err(WorkspaceMutationStoreError::Database(
            DbError::TransactionExpectation { step_index: 1, .. }
        ))
    ));
    assert_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn authority_cas_failure_rolls_back_domain_and_receipt() -> Result<(), Box<dyn Error>> {
    let db = seeded_db("owner").await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_authority_cas BEFORE UPDATE ON workspace_authorities BEGIN SELECT RAISE(IGNORE); END",
    ))
    .await?;
    let command = mutation_command(
        INITIAL_REVISION,
        "cas-failure-key",
        '3',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let plan = mutation_plan(&command, domain_update("must-not-commit"))?;

    let error = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;

    assert!(matches!(
        error,
        Err(WorkspaceMutationStoreError::RevisionConflict)
    ));
    assert_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn outbox_failure_rolls_back_domain_revision_and_receipt() -> Result<(), Box<dyn Error>> {
    let db = seeded_db("owner").await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_outbox BEFORE INSERT ON workspace_outbox BEGIN SELECT RAISE(ABORT, 'injected outbox failure'); END",
    ))
    .await?;
    let command = mutation_command(
        INITIAL_REVISION,
        "outbox-failure-key",
        '4',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let plan = mutation_plan(&command, domain_update("must-not-commit"))?;

    let error = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;

    assert!(matches!(
        error,
        Err(WorkspaceMutationStoreError::Database(DbError::Backend(_)))
    ));
    assert_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn receipt_finalize_failure_rolls_back_outbox_and_prior_writes() -> Result<(), Box<dyn Error>>
{
    let db = seeded_db("owner").await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_receipt_finalize BEFORE UPDATE OF committed_revision ON workspace_mutation_receipts BEGIN SELECT RAISE(ABORT, 'injected receipt finalize failure'); END",
    ))
    .await?;
    let command = mutation_command(
        INITIAL_REVISION,
        "finalize-failure-key",
        '5',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let plan = mutation_plan(&command, domain_update("must-not-commit"))?;

    let error = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;

    assert!(matches!(
        error,
        Err(WorkspaceMutationStoreError::Database(DbError::Backend(_)))
    ));
    assert_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn final_receipt_query_failure_rolls_back_the_complete_transaction()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db("owner").await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER remove_finalized_receipt AFTER UPDATE OF committed_revision ON workspace_mutation_receipts BEGIN DELETE FROM workspace_mutation_receipts WHERE receipt_id = NEW.receipt_id; END",
    ))
    .await?;
    let command = mutation_command(
        INITIAL_REVISION,
        "receipt-query-failure-key",
        '6',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let plan = mutation_plan(&command, domain_update("must-not-commit"))?;

    let error = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;

    assert!(matches!(
        error,
        Err(WorkspaceMutationStoreError::Database(
            DbError::TransactionExpectation { step_index: 7, .. }
        ))
    ));
    assert_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn matching_idempotency_hash_replays_and_mismatched_hash_is_rejected()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db("owner").await?;
    let first = mutation_command(
        INITIAL_REVISION,
        "stable-intent",
        'e',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let first_plan = mutation_plan(&first, domain_update("first"))?;
    let store = WorkspaceMutationStore::new(&db);
    let committed = store.execute(&first, first_plan).await?;

    let replay_plan = mutation_plan(&first, domain_update("must-not-run"))?;
    let replayed = store.execute(&first, replay_plan).await?;

    assert!(!committed.replayed);
    assert!(replayed.replayed);
    assert_eq!(replayed.receipt_id, committed.receipt_id);
    assert_eq!(
        scalar_string(&db, "SELECT value FROM domain_records").await?,
        "first"
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );

    let conflicting = mutation_command(
        INITIAL_REVISION + 1,
        "stable-intent",
        'f',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let conflicting_plan = mutation_plan(&conflicting, domain_update("must-not-run"))?;
    let conflict = store.execute(&conflicting, conflicting_plan).await;
    assert!(matches!(
        conflict,
        Err(WorkspaceMutationStoreError::IdempotencyConflict)
    ));
    assert_eq!(
        scalar_string(&db, "SELECT value FROM domain_records").await?,
        "first"
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities",).await?,
        8
    );
    Ok(())
}

#[test]
fn statement_plans_use_native_postgres_and_sqlite_placeholders() -> Result<(), Box<dyn Error>> {
    let command = mutation_command(
        INITIAL_REVISION,
        "placeholder-key",
        '1',
        WorkspaceMutationAction::UpdateWorkspace,
    )?;
    let postgres_domain = DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static("UPDATE domain_records SET value = ")
        .bind("updated")
        .push_static(" WHERE workspace_id = ")
        .bind("workspace-1")
        .build();
    let postgres = WorkspaceMutationPlanner::new(DbSqlFlavor::Postgres).plan_existing(
        &command,
        vec![WorkspaceDomainMutation::new(
            postgres_domain,
            DbCountExpectation::exactly(1),
        )],
        json!({"id": "workspace-1", "name": "updated"}),
        json!({"workspace_id": "workspace-1"}),
    )?;
    assert_eq!(postgres.steps().len(), 8);
    assert_statement_placeholders(&postgres, DbSqlFlavor::Postgres);

    let sqlite = mutation_plan(&command, domain_update("updated"))?;
    assert_statement_placeholders(&sqlite, DbSqlFlavor::Sqlite);
    Ok(())
}

fn mutation_command(
    expected_revision: u64,
    idempotency_key: &str,
    hash_char: char,
    action: WorkspaceMutationAction,
) -> Result<WorkspaceMutationCommand, WorkspaceCommandError> {
    Ok(WorkspaceMutationCommand::new(
        WorkspaceScope::new(
            TenantId::parse("tenant-1")?,
            ProjectId::parse("project-1")?,
            WorkspaceId::parse("workspace-1")?,
        ),
        WorkspaceActor::new(ActorId::parse("actor-1")?, false),
        ContractVersion::parse("2.0.0")?,
        action,
        ExpectedRevision::new(expected_revision),
        IdempotencyKey::parse(idempotency_key)?,
        RequestHash::parse(hash_char.to_string().repeat(64))?,
    ))
}

fn mutation_plan(
    command: &WorkspaceMutationCommand,
    domain_statement: DbStatement,
) -> Result<memstack_workspace_store::WorkspaceMutationPlan, Box<dyn Error>> {
    Ok(
        WorkspaceMutationPlanner::new(DbSqlFlavor::Sqlite).plan_existing(
            command,
            vec![WorkspaceDomainMutation::new(
                domain_statement,
                DbCountExpectation::exactly(1),
            )],
            json!({"id": "workspace-1", "name": "updated"}),
            json!({"workspace_id": "workspace-1"}),
        )?,
    )
}

fn domain_update(value: &str) -> DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Sqlite)
        .push_static("UPDATE domain_records SET value = ")
        .bind(value)
        .push_static(" WHERE workspace_id = ")
        .bind("workspace-1")
        .build()
}

async fn seeded_db(role: &str) -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT, deleted_by TEXT)",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE domain_records (workspace_id TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    db.execute(DbStatement::new(
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id) VALUES ('workspace-1', 'tenant-1', 'project-1')",
    ))
    .await?;
    db.execute(DbStatement::with_params(
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, role) VALUES ('member-1', 'tenant-1', 'project-1', 'workspace-1', 'actor-1', ?)",
        vec![role.into()],
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES ('workspace-1', 'tenant-1', 'project-1', 7)",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO domain_records (workspace_id, value) VALUES ('workspace-1', 'initial')",
    ))
    .await?;
    Ok(db)
}

async fn assert_pristine(db: &LocalSqliteDbPlugin) -> Result<(), Box<dyn Error>> {
    assert_eq!(
        scalar_i64(db, "SELECT revision AS value FROM workspace_authorities",).await?,
        7
    );
    assert_eq!(
        scalar_i64(
            db,
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        )
        .await?,
        0
    );
    assert_eq!(
        scalar_i64(db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        0
    );
    assert_eq!(
        scalar_string(db, "SELECT value FROM domain_records").await?,
        "initial"
    );
    Ok(())
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows.first().ok_or("query returned no rows")?;
    Ok(row.get_i64("value")?.ok_or("value is NULL")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows.first().ok_or("query returned no rows")?;
    Ok(row.get_string("value")?.ok_or("value is NULL")?)
}

fn assert_statement_placeholders(
    plan: &memstack_workspace_store::WorkspaceMutationPlan,
    flavor: DbSqlFlavor,
) {
    assert_statement(plan.receipt_lookup(), flavor);
    for step in plan.steps() {
        let statement = match step {
            DbTransactionStep::Query(statement)
            | DbTransactionStep::Execute(statement)
            | DbTransactionStep::QueryChecked { statement, .. }
            | DbTransactionStep::ExecuteChecked { statement, .. } => statement,
        };
        assert_statement(statement, flavor);
    }
}

fn assert_statement(statement: &DbStatement, flavor: DbSqlFlavor) {
    match flavor {
        DbSqlFlavor::Postgres => {
            assert!(!statement.sql().contains('?'));
            let positions = postgres_placeholder_positions(statement.sql());
            assert_eq!(
                positions,
                (1..=statement.params().len()).collect::<Vec<_>>()
            );
        }
        DbSqlFlavor::Sqlite | DbSqlFlavor::Mysql => {
            assert!(!statement.sql().contains('$'));
            assert_eq!(
                statement.sql().matches('?').count(),
                statement.params().len()
            );
        }
    }
}

fn postgres_placeholder_positions(sql: &str) -> Vec<usize> {
    let bytes = sql.as_bytes();
    let mut positions = Vec::new();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] != b'$' {
            index += 1;
            continue;
        }
        index += 1;
        let start = index;
        while index < bytes.len() && bytes[index].is_ascii_digit() {
            index += 1;
        }
        if let Ok(position) = sql[start..index].parse::<usize>() {
            positions.push(position);
        }
    }
    positions
}
