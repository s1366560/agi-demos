use std::error::Error;

use bcs_db_api::{DbCountExpectation, DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service_api::{
    ActorId, BcsEnvironment, ContractVersion, ExpectedRevision, GroupId, IdempotencyKey,
    ParticipantActorId, ProjectId, RequestHash, TenantId, UserId, WorkspaceActor,
    WorkspaceCreateOwner, WorkspaceCreateProfile, WorkspaceId, WorkspaceMemberId,
    WorkspaceMutationAction, WorkspaceMutationCommand, WorkspaceName, WorkspaceScope,
};
use memstack_workspace_store::{
    WorkspaceCreationPlanner, WorkspaceDomainMutation, WorkspaceMutationPlanner,
    WorkspaceMutationStore, WorkspaceMutationStoreError,
};
use serde_json::json;

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_create_workspace_commits_bcs_roster_and_workspace_authority()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    let workspace_id = "workspace-store-pg-create";
    let group_id = "group-store-pg-create";
    cleanup_created_workspace(&db, workspace_id, group_id).await?;
    seed_project_membership(&db).await?;
    let command = create_workspace_command(workspace_id, "postgres-create", '9')?;
    let profile = WorkspaceCreateProfile::new(
        GroupId::parse(group_id)?,
        BcsEnvironment::parse("memstack")?,
        WorkspaceName::parse("PostgreSQL Create Contract")?,
        Some("Atomic create contract".to_string()),
        json!({"workspace_type": "general"}),
    )?;
    let owner = WorkspaceCreateOwner::new(
        WorkspaceMemberId::parse("member-store-pg-create")?,
        UserId::parse("actor-create-contract")?,
        ParticipantActorId::parse("actor-create-contract")?,
    );
    let plan = WorkspaceCreationPlanner::new(DbSqlFlavor::Postgres).plan(
        &command,
        profile,
        owner,
        json!({"id": workspace_id, "name": "PostgreSQL Create Contract"}),
        json!({
            "workspace_id": workspace_id,
            "member_id": "member-store-pg-create",
            "user_id": "actor-create-contract",
            "role": "owner",
            "invited_by": "actor-create-contract",
            "member": {
                "id": "member-store-pg-create",
                "workspace_id": workspace_id,
                "user_id": "actor-create-contract",
                "role": "owner",
                "invited_by": "actor-create-contract"
            }
        }),
    )?;

    let outcome = WorkspaceMutationStore::new(&db)
        .execute_creation(&command, plan)
        .await?;

    assert_eq!(outcome.committed_revision, 1);
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM bcs_groups WHERE group_id = $1",
            group_id,
        )
        .await?,
        1
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM bcs_group_participants WHERE group_id = $1",
            group_id,
        )
        .await?,
        1
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
            workspace_id,
        )
        .await?,
        1
    );
    cleanup_created_workspace(&db, workspace_id, group_id).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_commits_domain_revision_receipt_and_outbox() -> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    let workspace_id = "workspace-store-pg-success";
    seed_workspace(&db, workspace_id).await?;
    let command = command(workspace_id, "postgres-success", '7')?;
    let plan = plan(&command, "PostgreSQL committed")?;

    let outcome = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await?;

    assert_eq!(outcome.committed_revision, 1);
    assert!(!outcome.replayed);
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
            workspace_id,
        )
        .await?,
        1
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1",
            workspace_id,
        )
        .await?,
        1
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1",
            workspace_id,
        )
        .await?,
        1
    );
    cleanup_workspace(&db, workspace_id).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_outbox_failure_rolls_back_every_prior_write() -> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    let workspace_id = "workspace-store-pg-rollback";
    seed_workspace(&db, workspace_id).await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_store_contract_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-store-pg-rollback' THEN RAISE EXCEPTION 'injected Workspace store outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_store_contract_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_store_contract_outbox()",
    ))
    .await?;
    let command = command(workspace_id, "postgres-rollback", '8')?;
    let plan = plan(&command, "must not commit")?;

    let result = WorkspaceMutationStore::new(&db)
        .execute(&command, plan)
        .await;
    drop_fault_trigger(&db).await?;

    assert!(matches!(
        result,
        Err(WorkspaceMutationStoreError::Database(_))
    ));
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
            workspace_id,
        )
        .await?,
        0
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1",
            workspace_id,
        )
        .await?,
        0
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1",
            workspace_id,
        )
        .await?,
        0
    );
    let name = scoped_string(
        &db,
        "SELECT name AS value FROM workspace_profiles WHERE workspace_id = $1",
        workspace_id,
    )
    .await?;
    assert_eq!(name, format!("Contract {workspace_id}"));
    cleanup_workspace(&db, workspace_id).await?;
    Ok(())
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn seed_workspace(db: &dyn DbPlugin, workspace_id: &str) -> Result<(), Box<dyn Error>> {
    cleanup_workspace(db, workspace_id).await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by) VALUES (",
            )
            .bind(workspace_id)
            .push_static(", 'tenant-store-contract', 'project-store-contract', ")
            .bind(format!("group-{workspace_id}"))
            .push_static(", ")
            .bind(format!("Contract {workspace_id}"))
            .push_static(", 'actor-store-contract')")
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES (",
            )
            .bind(format!("member-{workspace_id}"))
            .push_static(", 'tenant-store-contract', 'project-store-contract', ")
            .bind(workspace_id)
            .push_static(", 'actor-store-contract', 'actor-store-contract', 'owner')")
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES (",
            )
            .bind(workspace_id)
            .push_static(", 'tenant-store-contract', 'project-store-contract', 0)")
            .build(),
    )
    .await?;
    Ok(())
}

async fn cleanup_workspace(db: &dyn DbPlugin, workspace_id: &str) -> Result<(), Box<dyn Error>> {
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(workspace_id)
            .build(),
    )
    .await?;
    Ok(())
}

async fn seed_project_membership(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-store-contract', 'project-store-contract', 'actor-create-contract', 'actor-create-contract', 'membership-store-pg-create', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
    ))
    .await?;
    Ok(())
}

async fn cleanup_created_workspace(
    db: &dyn DbPlugin,
    workspace_id: &str,
    group_id: &str,
) -> Result<(), Box<dyn Error>> {
    cleanup_workspace(db, workspace_id).await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_group_participants WHERE group_id = ")
            .bind(group_id)
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_groups WHERE group_id = ")
            .bind(group_id)
            .build(),
    )
    .await?;
    db.execute(DbStatement::new(
        "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-store-pg-create'",
    ))
    .await?;
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_store_contract_outbox ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_store_contract_outbox()",
    ))
    .await?;
    Ok(())
}

fn command(
    workspace_id: &str,
    idempotency_key: &str,
    hash_char: char,
) -> Result<WorkspaceMutationCommand, Box<dyn Error>> {
    Ok(WorkspaceMutationCommand::new(
        WorkspaceScope::new(
            TenantId::parse("tenant-store-contract")?,
            ProjectId::parse("project-store-contract")?,
            WorkspaceId::parse(workspace_id)?,
        ),
        WorkspaceActor::new(ActorId::parse("actor-store-contract")?, false),
        ContractVersion::parse("2.0.0")?,
        WorkspaceMutationAction::UpdateWorkspace,
        ExpectedRevision::new(0),
        IdempotencyKey::parse(idempotency_key)?,
        RequestHash::parse(hash_char.to_string().repeat(64))?,
    ))
}

fn create_workspace_command(
    workspace_id: &str,
    idempotency_key: &str,
    hash_char: char,
) -> Result<WorkspaceMutationCommand, Box<dyn Error>> {
    Ok(WorkspaceMutationCommand::new(
        WorkspaceScope::new(
            TenantId::parse("tenant-store-contract")?,
            ProjectId::parse("project-store-contract")?,
            WorkspaceId::parse(workspace_id)?,
        ),
        WorkspaceActor::new(ActorId::parse("actor-create-contract")?, false),
        ContractVersion::parse("2.0.0")?,
        WorkspaceMutationAction::CreateWorkspace,
        ExpectedRevision::new(0),
        IdempotencyKey::parse(idempotency_key)?,
        RequestHash::parse(hash_char.to_string().repeat(64))?,
    ))
}

fn plan(
    command: &WorkspaceMutationCommand,
    name: &str,
) -> Result<memstack_workspace_store::WorkspaceMutationPlan, Box<dyn Error>> {
    let domain = DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static("UPDATE workspace_profiles SET name = ")
        .bind(name)
        .push_static(" WHERE tenant_id = ")
        .bind(command.scope().tenant_id().as_str())
        .push_static(" AND project_id = ")
        .bind(command.scope().project_id().as_str())
        .push_static(" AND workspace_id = ")
        .bind(command.scope().workspace_id().as_str())
        .build();
    Ok(
        WorkspaceMutationPlanner::new(DbSqlFlavor::Postgres).plan_existing(
            command,
            vec![WorkspaceDomainMutation::new(
                domain,
                DbCountExpectation::exactly(1),
            )],
            json!({"id": command.scope().workspace_id().as_str(), "name": name}),
            json!({"workspace_id": command.scope().workspace_id().as_str()}),
        )?,
    )
}

async fn scoped_i64(
    db: &dyn DbPlugin,
    sql: &str,
    workspace_id: &str,
) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![workspace_id.into()]))
        .await?;
    let row = rows
        .first()
        .ok_or_else(|| std::io::Error::other("query returned no rows"))?;
    Ok(row
        .get_i64("value")?
        .ok_or_else(|| std::io::Error::other("value is NULL"))?)
}

async fn scoped_string(
    db: &dyn DbPlugin,
    sql: &str,
    workspace_id: &str,
) -> Result<String, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![workspace_id.into()]))
        .await?;
    let row = rows
        .first()
        .ok_or_else(|| std::io::Error::other("query returned no rows"))?;
    Ok(row
        .get_string("value")?
        .ok_or_else(|| std::io::Error::other("value is NULL"))?)
}
