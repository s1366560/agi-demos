use std::sync::Arc;

use anyhow::{Context, Result, anyhow};
use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbRow, DbSqlFlavor, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "collaboration-postgres-contract-token";
const TENANT_ID: &str = "tenant-collaboration-pg";
const PROJECT_ID: &str = "project-collaboration-pg";
const WORKSPACE_ID: &str = "workspace-collaboration-pg";
const USER_ID: &str = "user-collaboration-pg";
const PATH: &str = "/api/v1/tenants/tenant-collaboration-pg/projects/project-collaboration-pg/workspaces/workspace-collaboration-pg/collaboration/mutations";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn collaboration_mutation_is_atomic_replayable_and_rollback_safe_on_postgres() -> Result<()> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")
        .context("BCS_TEST_POSTGRES_URL must be set for the collaboration contract")?;
    let db: Arc<dyn DbPlugin> = Arc::new(
        PostgresDbPlugin::connect_no_tls(&database_url, 2)
            .await
            .context("connect PostgreSQL collaboration contract database")?,
    );
    cleanup_workspace(db.as_ref()).await?;
    seed_workspace(db.as_ref()).await?;
    let state = Arc::new(
        WorkspaceCoreState::new(db.clone(), SERVICE_TOKEN.to_string())
            .map_err(|error| anyhow!(error))?,
    );

    let outcome = exercise_collaboration_contract(state, db.as_ref()).await;
    let cleanup = cleanup_workspace(db.as_ref()).await;
    outcome?;
    cleanup?;
    Ok(())
}

async fn exercise_collaboration_contract(
    state: Arc<WorkspaceCoreState>,
    db: &dyn DbPlugin,
) -> Result<()> {
    let command = mutation_command(
        0,
        "collaboration-pg-create-001",
        json!({
            "title": "PostgreSQL collaboration task",
            "description": "shared receipt and outbox authority",
            "metadata": {"source": "postgres-contract"},
            "priority": "P1"
        }),
    );
    let created = send_mutation(
        state.clone(),
        &command,
        0,
        "collaboration-pg-create-001",
        StatusCode::OK,
    )
    .await?;
    assert_eq!(created["contract_version"], "2.0.0");
    assert_eq!(created["revision"], 1);
    assert_eq!(created["duplicate"], false);

    let receipt = receipt_row(db, "collaboration-pg-create-001").await?;
    assert_eq!(
        receipt.get_string("receipt_id")?.as_deref(),
        created["receipt_id"].as_str()
    );
    assert_eq!(
        receipt.get_string("contract_version")?.as_deref(),
        Some("2.0.0")
    );
    assert_eq!(receipt.get_string("surface")?.as_deref(), Some("goals"));
    assert_eq!(
        receipt.get_string("action")?.as_deref(),
        Some("create_task")
    );
    assert_eq!(receipt.get_i64("expected_revision")?, Some(0));
    assert_eq!(receipt.get_i64("committed_revision")?, Some(1));
    assert_eq!(workspace_revision(db).await?, 1);
    assert_eq!(scope_count(db, "workspace_tasks").await?, 1);
    assert_eq!(scope_count(db, "workspace_mutation_receipts").await?, 1);
    assert_eq!(scope_count(db, "workspace_task_receipts").await?, 0);
    assert_eq!(scope_count(db, "workspace_outbox").await?, 1);

    let replayed = send_mutation(
        state.clone(),
        &command,
        0,
        "collaboration-pg-create-001",
        StatusCode::OK,
    )
    .await?;
    assert_eq!(replayed["receipt_id"], created["receipt_id"]);
    assert_eq!(replayed["revision"], 1);
    assert_eq!(replayed["duplicate"], true);
    assert_eq!(scope_count(db, "workspace_tasks").await?, 1);
    assert_eq!(scope_count(db, "workspace_mutation_receipts").await?, 1);
    assert_eq!(scope_count(db, "workspace_outbox").await?, 1);

    let stale = mutation_command(
        0,
        "collaboration-pg-stale-001",
        json!({"title": "stale PostgreSQL collaboration task"}),
    );
    let stale_response = send_mutation(
        state.clone(),
        &stale,
        0,
        "collaboration-pg-stale-001",
        StatusCode::CONFLICT,
    )
    .await?;
    assert_eq!(
        stale_response["detail"]["reason_code"],
        "workspace_collaboration_revision_conflict"
    );
    assert_eq!(workspace_revision(db).await?, 1);
    assert_eq!(scope_count(db, "workspace_tasks").await?, 1);
    assert_eq!(scope_count(db, "workspace_mutation_receipts").await?, 1);

    seed_outbox_conflict(db, "collaboration-pg-rollback-001").await?;
    let rollback = mutation_command(
        1,
        "collaboration-pg-rollback-001",
        json!({"title": "must roll back with the transaction"}),
    );
    let rollback_response = send_mutation(
        state,
        &rollback,
        1,
        "collaboration-pg-rollback-001",
        StatusCode::CONFLICT,
    )
    .await?;
    assert_eq!(
        rollback_response["detail"]["reason_code"],
        "workspace_collaboration_idempotency_conflict"
    );
    assert_eq!(workspace_revision(db).await?, 1);
    assert_eq!(scope_count(db, "workspace_tasks").await?, 1);
    assert_eq!(scope_count(db, "workspace_mutation_receipts").await?, 1);
    assert_eq!(scope_count(db, "workspace_outbox").await?, 2);
    assert_eq!(
        idempotency_count(
            db,
            "workspace_mutation_receipts",
            "collaboration-pg-rollback-001",
        )
        .await?,
        0
    );
    assert_eq!(
        task_title_count(db, "must roll back with the transaction").await?,
        0
    );
    Ok(())
}

fn mutation_command(expected_revision: u64, idempotency_key: &str, payload: Value) -> Value {
    json!({
        "contract_version": "2.0.0",
        "surface": "goals",
        "action": "create_task",
        "expected_revision": expected_revision,
        "idempotency_key": idempotency_key,
        "payload": payload,
    })
}

async fn send_mutation(
    state: Arc<WorkspaceCoreState>,
    command: &Value,
    expected_revision: u64,
    idempotency_key: &str,
    expected_status: StatusCode,
) -> Result<Value> {
    let request = Request::builder()
        .method("POST")
        .uri(PATH)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header(header::CONTENT_TYPE, "application/json")
        .header("x-memstack-user-id", USER_ID)
        .header("x-expected-revision", expected_revision.to_string())
        .header("idempotency-key", idempotency_key)
        .body(Body::from(command.to_string()))?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await?;
    let payload = serde_json::from_slice(&body)?;
    if status != expected_status {
        return Err(anyhow!(
            "unexpected collaboration status: actual={status}, expected={expected_status}, body={payload}"
        ));
    }
    Ok(payload)
}

async fn seed_workspace(db: &dyn DbPlugin) -> Result<()> {
    for statement in [
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by) VALUES (",
            )
            .bind(WORKSPACE_ID)
            .push_static(", ")
            .bind(TENANT_ID)
            .push_static(", ")
            .bind(PROJECT_ID)
            .push_static(", 'group-collaboration-pg', 'Collaboration PostgreSQL Contract', ")
            .bind(USER_ID)
            .push_static(")")
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-collaboration-pg', ",
            )
            .bind(TENANT_ID)
            .push_static(", ")
            .bind(PROJECT_ID)
            .push_static(", ")
            .bind(WORKSPACE_ID)
            .push_static(", ")
            .bind(USER_ID)
            .push_static(", 'principal-collaboration-pg', 'owner')")
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id) VALUES (",
            )
            .bind(WORKSPACE_ID)
            .push_static(", ")
            .bind(TENANT_ID)
            .push_static(", ")
            .bind(PROJECT_ID)
            .push_static(")")
            .build(),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn seed_outbox_conflict(db: &dyn DbPlugin, idempotency_key: &str) -> Result<()> {
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, idempotency_key) VALUES ('outbox-collaboration-pg-blocker', ",
            )
            .bind(TENANT_ID)
            .push_static(", ")
            .bind(PROJECT_ID)
            .push_static(", ")
            .bind(WORKSPACE_ID)
            .push_static(", 'contract_blocker', 'contract_blocker', 'contract_blocker', 'workspace.events', 99, '{}'::jsonb, '{}'::jsonb, ")
            .bind(idempotency_key)
            .push_static(")")
            .build(),
    )
    .await?;
    Ok(())
}

async fn cleanup_workspace(db: &dyn DbPlugin) -> Result<()> {
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .push_static(" AND tenant_id = ")
            .bind(TENANT_ID)
            .push_static(" AND project_id = ")
            .bind(PROJECT_ID)
            .build(),
    )
    .await?;
    Ok(())
}

async fn receipt_row(db: &dyn DbPlugin, idempotency_key: &str) -> Result<DbRow> {
    db.query(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "SELECT receipt_id, contract_version, surface, action, expected_revision, committed_revision FROM workspace_mutation_receipts WHERE workspace_id = ",
            )
            .bind(WORKSPACE_ID)
            .push_static(" AND actor_id = ")
            .bind(USER_ID)
            .push_static(" AND idempotency_key = ")
            .bind(idempotency_key)
            .build(),
    )
    .await?
    .into_iter()
    .next()
    .ok_or_else(|| anyhow!("collaboration receipt is missing"))
}

async fn workspace_revision(db: &dyn DbPlugin) -> Result<i64> {
    db.query(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("SELECT revision FROM workspace_authorities WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
    )
    .await?
    .first()
    .ok_or_else(|| anyhow!("workspace authority is missing"))?
    .get_i64("revision")?
    .ok_or_else(|| anyhow!("workspace revision is missing"))
}

async fn scope_count(db: &dyn DbPlugin, table: &str) -> Result<i64> {
    let sql = match table {
        "workspace_tasks" => "SELECT COUNT(*) AS total FROM workspace_tasks WHERE workspace_id = ",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS total FROM workspace_mutation_receipts WHERE workspace_id = "
        }
        "workspace_task_receipts" => {
            "SELECT COUNT(*) AS total FROM workspace_task_receipts WHERE workspace_id = "
        }
        "workspace_outbox" => {
            "SELECT COUNT(*) AS total FROM workspace_outbox WHERE workspace_id = "
        }
        _ => return Err(anyhow!("unsupported PostgreSQL contract table: {table}")),
    };
    db.query(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(sql)
            .bind(WORKSPACE_ID)
            .build(),
    )
    .await?
    .first()
    .ok_or_else(|| anyhow!("scope count row is missing"))?
    .get_i64("total")?
    .ok_or_else(|| anyhow!("scope count is missing"))
}

async fn idempotency_count(db: &dyn DbPlugin, table: &str, idempotency_key: &str) -> Result<i64> {
    let sql = match table {
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS total FROM workspace_mutation_receipts WHERE workspace_id = "
        }
        _ => return Err(anyhow!("unsupported idempotency table: {table}")),
    };
    db.query(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(sql)
            .bind(WORKSPACE_ID)
            .push_static(" AND idempotency_key = ")
            .bind(idempotency_key)
            .build(),
    )
    .await?
    .first()
    .ok_or_else(|| anyhow!("idempotency count row is missing"))?
    .get_i64("total")?
    .ok_or_else(|| anyhow!("idempotency count is missing"))
}

async fn task_title_count(db: &dyn DbPlugin, title: &str) -> Result<i64> {
    db.query(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("SELECT COUNT(*) AS total FROM workspace_tasks WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .push_static(" AND title = ")
            .bind(title)
            .build(),
    )
    .await?
    .first()
    .ok_or_else(|| anyhow!("task title count row is missing"))?
    .get_i64("total")?
    .ok_or_else(|| anyhow!("task title count is missing"))
}
