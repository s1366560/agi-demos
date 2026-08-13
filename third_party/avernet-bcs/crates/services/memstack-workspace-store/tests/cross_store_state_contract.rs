use std::{env, error::Error, fs};

use bcs_db_api::{DbCountExpectation, DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_local::LocalSqliteDbPlugin;
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service_api::{
    ActorId, ContractVersion, ExpectedRevision, IdempotencyKey, ProjectId, RequestHash, TenantId,
    WorkspaceActor, WorkspaceId, WorkspaceMutationAction, WorkspaceMutationCommand, WorkspaceScope,
};
use memstack_workspace_store::{
    WorkspaceDomainMutation, WorkspaceMutationPlanner, WorkspaceMutationStore,
};
use serde_json::{Value, json};

const TENANT_ID: &str = "tenant-cross-store";
const PROJECT_ID: &str = "project-cross-store";
const ACTOR_ID: &str = "actor-cross-store";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn sqlite_and_postgres_produce_identical_normalized_authority_state()
-> Result<(), Box<dyn Error>> {
    let sqlite = LocalSqliteDbPlugin::new()?;
    create_sqlite_schema(&sqlite).await?;
    let postgres = PostgresDbPlugin::connect_no_tls(&env::var("BCS_TEST_POSTGRES_URL")?, 1).await?;

    let sqlite_state = exercise_backend(&sqlite, DbSqlFlavor::Sqlite, "sqlite").await?;
    let postgres_state = exercise_backend(&postgres, DbSqlFlavor::Postgres, "postgres").await?;
    assert_eq!(sqlite_state, postgres_state);

    if let Ok(path) = env::var("WORKSPACE_CROSS_STORE_STATE_OUTPUT") {
        fs::write(
            path,
            serde_json::to_vec_pretty(&json!({
                "sqlite": sqlite_state,
                "postgres": postgres_state,
            }))?,
        )?;
    }
    Ok(())
}

async fn exercise_backend(
    db: &dyn DbPlugin,
    flavor: DbSqlFlavor,
    suffix: &str,
) -> Result<Value, Box<dyn Error>> {
    let committed_workspace_id = format!("workspace-cross-store-commit-{suffix}");
    let rollback_workspace_id = format!("workspace-cross-store-rollback-{suffix}");
    cleanup_workspace(db, flavor, &committed_workspace_id).await?;
    cleanup_workspace(db, flavor, &rollback_workspace_id).await?;
    seed_workspace(db, flavor, &committed_workspace_id).await?;
    seed_workspace(db, flavor, &rollback_workspace_id).await?;

    let commit_command = command(&committed_workspace_id, "cross-store-commit", 'a')?;
    let commit_plan = plan(flavor, &commit_command, "committed")?;
    let committed = WorkspaceMutationStore::new(db)
        .execute(&commit_command, commit_plan)
        .await?;
    let replay_plan = plan(flavor, &commit_command, "must-not-run")?;
    let replayed = WorkspaceMutationStore::new(db)
        .execute(&commit_command, replay_plan)
        .await?;
    let commit_state = scoped_state(db, flavor, &committed_workspace_id).await?;

    install_outbox_rejection(db, flavor).await?;
    let rollback_command = command(&rollback_workspace_id, "cross-store-rollback", 'b')?;
    let rollback_plan = plan(flavor, &rollback_command, "must-not-commit")?;
    let rollback_result = WorkspaceMutationStore::new(db)
        .execute(&rollback_command, rollback_plan)
        .await;
    remove_outbox_rejection(db, flavor).await?;
    if rollback_result.is_ok() {
        return Err("fault-injected outbox mutation unexpectedly committed".into());
    }
    let rollback_state = scoped_state(db, flavor, &rollback_workspace_id).await?;

    cleanup_workspace(db, flavor, &committed_workspace_id).await?;
    cleanup_workspace(db, flavor, &rollback_workspace_id).await?;

    Ok(json!({
        "contractVersion": 1,
        "commit": {
            "revisionDelta": commit_state["revision"],
            "receiptCount": commit_state["receiptCount"],
            "outboxCount": commit_state["outboxCount"],
            "domainValue": "committed",
            "eventType": commit_state["eventType"],
        },
        "crashReplay": {
            "replayed": replayed.replayed,
            "receiptStable": replayed.receipt_id == committed.receipt_id,
            "committedRevision": replayed.committed_revision,
            "receiptCount": commit_state["receiptCount"],
            "outboxCount": commit_state["outboxCount"],
        },
        "rollback": {
            "revisionDelta": rollback_state["revision"],
            "receiptCount": rollback_state["receiptCount"],
            "outboxCount": rollback_state["outboxCount"],
            "domainValuePreserved": rollback_state["domainValue"]
                == format!("initial-{rollback_workspace_id}"),
        },
    }))
}

async fn create_sqlite_schema(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for ddl in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL, name TEXT NOT NULL, created_by TEXT NOT NULL, deleted_at TEXT, deleted_by TEXT)",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    Ok(())
}

async fn seed_workspace(
    db: &dyn DbPlugin,
    flavor: DbSqlFlavor,
    workspace_id: &str,
) -> Result<(), Box<dyn Error>> {
    db.execute(
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by) VALUES (")
            .bind(workspace_id)
            .push_static(", ")
            .bind(TENANT_ID)
            .push_static(", ")
            .bind(PROJECT_ID)
            .push_static(", ")
            .bind(format!("group-{workspace_id}"))
            .push_static(", ")
            .bind(format!("initial-{workspace_id}"))
            .push_static(", ")
            .bind(ACTOR_ID)
            .push_static(")")
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES (")
            .bind(format!("member-{workspace_id}"))
            .push_static(", ")
            .bind(TENANT_ID)
            .push_static(", ")
            .bind(PROJECT_ID)
            .push_static(", ")
            .bind(workspace_id)
            .push_static(", ")
            .bind(ACTOR_ID)
            .push_static(", ")
            .bind(ACTOR_ID)
            .push_static(", 'owner')")
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES (")
            .bind(workspace_id)
            .push_static(", ")
            .bind(TENANT_ID)
            .push_static(", ")
            .bind(PROJECT_ID)
            .push_static(", 0)")
            .build(),
    )
    .await?;
    Ok(())
}

fn command(
    workspace_id: &str,
    idempotency_key: &str,
    hash_character: char,
) -> Result<WorkspaceMutationCommand, Box<dyn Error>> {
    Ok(WorkspaceMutationCommand::new(
        WorkspaceScope::new(
            TenantId::parse(TENANT_ID)?,
            ProjectId::parse(PROJECT_ID)?,
            WorkspaceId::parse(workspace_id)?,
        ),
        WorkspaceActor::new(ActorId::parse(ACTOR_ID)?, false),
        ContractVersion::parse("2.0.0")?,
        WorkspaceMutationAction::UpdateWorkspace,
        ExpectedRevision::new(0),
        IdempotencyKey::parse(idempotency_key)?,
        RequestHash::parse(hash_character.to_string().repeat(64))?,
    ))
}

fn plan(
    flavor: DbSqlFlavor,
    command: &WorkspaceMutationCommand,
    name: &str,
) -> Result<memstack_workspace_store::WorkspaceMutationPlan, Box<dyn Error>> {
    let domain = DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_profiles SET name = ")
        .bind(name)
        .push_static(" WHERE tenant_id = ")
        .bind(command.scope().tenant_id().as_str())
        .push_static(" AND project_id = ")
        .bind(command.scope().project_id().as_str())
        .push_static(" AND workspace_id = ")
        .bind(command.scope().workspace_id().as_str())
        .build();
    Ok(WorkspaceMutationPlanner::new(flavor).plan_existing(
        command,
        vec![WorkspaceDomainMutation::new(
            domain,
            DbCountExpectation::exactly(1),
        )],
        json!({"id": command.scope().workspace_id().as_str(), "name": name}),
        json!({"workspace_id": command.scope().workspace_id().as_str()}),
    )?)
}

async fn scoped_state(
    db: &dyn DbPlugin,
    flavor: DbSqlFlavor,
    workspace_id: &str,
) -> Result<Value, Box<dyn Error>> {
    let statement = DbStatementBuilder::new(flavor)
        .push_static("SELECT authority.revision, profile.name AS domain_value, (SELECT COUNT(*) FROM workspace_mutation_receipts receipt WHERE receipt.workspace_id = authority.workspace_id) AS receipt_count, (SELECT COUNT(*) FROM workspace_outbox event WHERE event.workspace_id = authority.workspace_id) AS outbox_count, (SELECT event_type FROM workspace_outbox event WHERE event.workspace_id = authority.workspace_id LIMIT 1) AS event_type FROM workspace_authorities authority JOIN workspace_profiles profile ON profile.workspace_id = authority.workspace_id WHERE authority.workspace_id = ")
        .bind(workspace_id)
        .build();
    let rows = db.query(statement).await?;
    let row = rows
        .first()
        .ok_or("authority state query returned no rows")?;
    Ok(json!({
        "revision": row.get_i64("revision")?.ok_or("revision is NULL")?,
        "receiptCount": row.get_i64("receipt_count")?.ok_or("receipt count is NULL")?,
        "outboxCount": row.get_i64("outbox_count")?.ok_or("outbox count is NULL")?,
        "domainValue": row.get_string("domain_value")?.ok_or("domain value is NULL")?,
        "eventType": row.get_string("event_type")?,
    }))
}

async fn install_outbox_rejection(
    db: &dyn DbPlugin,
    flavor: DbSqlFlavor,
) -> Result<(), Box<dyn Error>> {
    match flavor {
        DbSqlFlavor::Sqlite => {
            db.execute(DbStatement::new(
                "CREATE TRIGGER reject_cross_store_outbox BEFORE INSERT ON workspace_outbox BEGIN SELECT RAISE(ABORT, 'injected outbox failure'); END",
            ))
            .await?;
        }
        DbSqlFlavor::Postgres => {
            db.execute(DbStatement::new(
                "CREATE OR REPLACE FUNCTION avernet.reject_cross_store_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id LIKE 'workspace-cross-store-rollback-%' THEN RAISE EXCEPTION 'injected cross-store outbox failure'; END IF; RETURN NEW; END $$",
            ))
            .await?;
            db.execute(DbStatement::new(
                "CREATE TRIGGER trg_reject_cross_store_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_cross_store_outbox()",
            ))
            .await?;
        }
        DbSqlFlavor::Mysql => return Err("MySQL is outside this paired contract".into()),
    }
    Ok(())
}

async fn remove_outbox_rejection(
    db: &dyn DbPlugin,
    flavor: DbSqlFlavor,
) -> Result<(), Box<dyn Error>> {
    match flavor {
        DbSqlFlavor::Sqlite => {
            db.execute(DbStatement::new("DROP TRIGGER reject_cross_store_outbox"))
                .await?;
        }
        DbSqlFlavor::Postgres => {
            db.execute(DbStatement::new(
                "DROP TRIGGER IF EXISTS trg_reject_cross_store_outbox ON workspace_outbox",
            ))
            .await?;
            db.execute(DbStatement::new(
                "DROP FUNCTION IF EXISTS avernet.reject_cross_store_outbox()",
            ))
            .await?;
        }
        DbSqlFlavor::Mysql => return Err("MySQL is outside this paired contract".into()),
    }
    Ok(())
}

async fn cleanup_workspace(
    db: &dyn DbPlugin,
    flavor: DbSqlFlavor,
    workspace_id: &str,
) -> Result<(), Box<dyn Error>> {
    db.execute(
        DbStatementBuilder::new(flavor)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(workspace_id)
            .build(),
    )
    .await?;
    Ok(())
}
