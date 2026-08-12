use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbTransactionStep};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service_api::{
    ActorId, BcsEnvironment, ContractVersion, ExpectedRevision, GroupId, IdempotencyKey,
    ParticipantActorId, ProjectId, RequestHash, TenantId, UserId, WorkspaceActor,
    WorkspaceCommandError, WorkspaceCreateOwner, WorkspaceCreateProfile, WorkspaceId,
    WorkspaceMemberId, WorkspaceMutationAction, WorkspaceMutationCommand, WorkspaceName,
    WorkspaceScope,
};
use memstack_workspace_store::{
    WorkspaceCreationPlanError, WorkspaceCreationPlanner, WorkspaceMutationStore,
    WorkspaceMutationStoreError,
};
use serde_json::{Value, json};

#[tokio::test]
async fn create_workspace_commits_group_profile_owner_authority_receipt_and_outbox()
-> Result<(), Box<dyn Error>> {
    let db = empty_db(true).await?;
    let command = create_command("create-success", 'a')?;
    let plan = create_plan(&command)?;

    let outcome = WorkspaceMutationStore::new(&db)
        .execute_creation(&command, plan)
        .await?;

    assert!(!outcome.replayed);
    assert_eq!(outcome.committed_revision, 1);
    for table in [
        "bcs_groups",
        "bcs_group_participants",
        "workspace_profiles",
        "workspace_members",
        "workspace_authorities",
        "workspace_mutation_receipts",
        "workspace_outbox",
    ] {
        assert_eq!(
            table_count(&db, table).await?,
            1,
            "unexpected {table} count"
        );
    }
    assert_eq!(
        scalar_string(&db, "SELECT role AS value FROM workspace_members").await?,
        "owner"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT actor_kind AS value FROM bcs_group_participants"
        )
        .await?,
        "human"
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        1
    );
    let payload: Value = serde_json::from_str(
        &scalar_string(&db, "SELECT payload_json AS value FROM workspace_outbox").await?,
    )?;
    assert_eq!(payload["user_id"], "owner-1");
    assert_eq!(payload["role"], "owner");
    assert_eq!(payload["member"]["user_id"], "owner-1");
    Ok(())
}

#[tokio::test]
async fn create_workspace_replays_matching_intent_and_rejects_hash_conflict()
-> Result<(), Box<dyn Error>> {
    let db = empty_db(true).await?;
    let command = create_command("stable-create", 'b')?;
    let store = WorkspaceMutationStore::new(&db);

    let committed = store
        .execute_creation(&command, create_plan(&command)?)
        .await?;
    let replayed = store
        .execute_creation(&command, create_plan(&command)?)
        .await?;

    assert!(!committed.replayed);
    assert!(replayed.replayed);
    assert_eq!(replayed.receipt_id, committed.receipt_id);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 1);

    let conflict = create_command("stable-create", 'c')?;
    let result = store
        .execute_creation(&conflict, create_plan(&conflict)?)
        .await;
    assert!(matches!(
        result,
        Err(WorkspaceMutationStoreError::IdempotencyConflict)
    ));
    assert_eq!(table_count(&db, "workspace_profiles").await?, 1);
    Ok(())
}

#[tokio::test]
async fn create_workspace_denies_missing_project_membership_without_partial_writes()
-> Result<(), Box<dyn Error>> {
    let db = empty_db(false).await?;
    let command = create_command("access-denied", 'd')?;

    let result = WorkspaceMutationStore::new(&db)
        .execute_creation(&command, create_plan(&command)?)
        .await;

    assert!(matches!(
        result,
        Err(WorkspaceMutationStoreError::AccessDenied)
    ));
    assert_creation_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn create_workspace_outbox_failure_rolls_back_every_prior_write() -> Result<(), Box<dyn Error>>
{
    let db = empty_db(true).await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_create_outbox BEFORE INSERT ON workspace_outbox BEGIN SELECT RAISE(ABORT, 'injected create outbox failure'); END",
    ))
    .await?;
    let command = create_command("outbox-failure", 'e')?;

    let result = WorkspaceMutationStore::new(&db)
        .execute_creation(&command, create_plan(&command)?)
        .await;

    assert!(matches!(
        result,
        Err(WorkspaceMutationStoreError::Database(_))
    ));
    assert_creation_pristine(&db).await?;
    Ok(())
}

#[tokio::test]
async fn create_workspace_rolls_back_at_every_checked_write_boundary() -> Result<(), Box<dyn Error>>
{
    let cases = [
        (
            "group",
            "CREATE TRIGGER reject_create_group BEFORE INSERT ON bcs_groups BEGIN SELECT RAISE(IGNORE); END",
            true,
        ),
        (
            "profile",
            "CREATE TRIGGER reject_create_profile BEFORE INSERT ON workspace_profiles BEGIN SELECT RAISE(IGNORE); END",
            true,
        ),
        (
            "receipt",
            "CREATE TRIGGER reject_create_receipt BEFORE INSERT ON workspace_mutation_receipts BEGIN SELECT RAISE(IGNORE); END",
            false,
        ),
        (
            "member",
            "CREATE TRIGGER reject_create_member BEFORE INSERT ON workspace_members BEGIN SELECT RAISE(IGNORE); END",
            true,
        ),
        (
            "participant",
            "CREATE TRIGGER reject_create_participant BEFORE INSERT ON bcs_group_participants BEGIN SELECT RAISE(IGNORE); END",
            true,
        ),
        (
            "authority",
            "CREATE TRIGGER reject_create_authority BEFORE INSERT ON workspace_authorities BEGIN SELECT RAISE(IGNORE); END",
            true,
        ),
        (
            "finalize",
            "CREATE TRIGGER reject_create_finalize BEFORE UPDATE OF committed_revision ON workspace_mutation_receipts BEGIN SELECT RAISE(IGNORE); END",
            false,
        ),
        (
            "final_query",
            "CREATE TRIGGER remove_create_receipt AFTER UPDATE OF committed_revision ON workspace_mutation_receipts BEGIN DELETE FROM workspace_mutation_receipts WHERE receipt_id = NEW.receipt_id; END",
            false,
        ),
    ];

    for (label, trigger, domain_conflict) in cases {
        let db = empty_db(true).await?;
        db.execute(DbStatement::new(trigger)).await?;
        let command = create_command(&format!("failure-{label}"), '4')?;

        let result = WorkspaceMutationStore::new(&db)
            .execute_creation(&command, create_plan(&command)?)
            .await;

        if domain_conflict {
            assert!(
                matches!(result, Err(WorkspaceMutationStoreError::DomainConflict)),
                "unexpected {label} result: {result:?}"
            );
        } else {
            assert!(
                matches!(result, Err(WorkspaceMutationStoreError::Database(_))),
                "unexpected {label} result: {result:?}"
            );
        }
        assert_creation_pristine(&db).await?;
    }
    Ok(())
}

#[tokio::test]
async fn create_workspace_existing_id_with_another_intent_is_a_structured_conflict()
-> Result<(), Box<dyn Error>> {
    let db = empty_db(true).await?;
    let first = create_command("first-create", 'f')?;
    WorkspaceMutationStore::new(&db)
        .execute_creation(&first, create_plan(&first)?)
        .await?;

    let second = create_command("second-create", '1')?;
    let result = WorkspaceMutationStore::new(&db)
        .execute_creation(&second, create_plan(&second)?)
        .await;

    assert!(matches!(
        result,
        Err(WorkspaceMutationStoreError::WorkspaceAlreadyExists)
    ));
    assert_eq!(table_count(&db, "workspace_mutation_receipts").await?, 1);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 1);
    Ok(())
}

#[test]
fn create_workspace_requires_create_action_and_revision_zero() -> Result<(), Box<dyn Error>> {
    let profile = create_profile()?;
    let owner = create_owner()?;
    let update_command = WorkspaceMutationCommand::new(
        create_scope()?,
        WorkspaceActor::new(ActorId::parse("owner-1")?, false),
        ContractVersion::parse("2.0.0")?,
        WorkspaceMutationAction::UpdateWorkspace,
        ExpectedRevision::new(0),
        IdempotencyKey::parse("wrong-action")?,
        RequestHash::parse("2".repeat(64))?,
    );
    assert!(
        WorkspaceCreationPlanner::new(DbSqlFlavor::Sqlite)
            .plan(
                &update_command,
                profile.clone(),
                owner.clone(),
                create_response(),
                create_event_payload(),
            )
            .is_err()
    );

    let revision_command = WorkspaceMutationCommand::new(
        create_scope()?,
        WorkspaceActor::new(ActorId::parse("owner-1")?, false),
        ContractVersion::parse("2.0.0")?,
        WorkspaceMutationAction::CreateWorkspace,
        ExpectedRevision::new(1),
        IdempotencyKey::parse("wrong-revision")?,
        RequestHash::parse("3".repeat(64))?,
    );
    assert!(
        WorkspaceCreationPlanner::new(DbSqlFlavor::Sqlite)
            .plan(
                &revision_command,
                profile,
                owner,
                create_response(),
                create_event_payload(),
            )
            .is_err()
    );
    Ok(())
}

#[test]
fn create_workspace_statements_use_native_postgres_and_sqlite_placeholders()
-> Result<(), Box<dyn Error>> {
    let command = create_command("placeholder-create", '5')?;
    let postgres = WorkspaceCreationPlanner::new(DbSqlFlavor::Postgres).plan(
        &command,
        create_profile()?,
        create_owner()?,
        create_response(),
        create_event_payload(),
    )?;
    assert_creation_placeholders(&postgres, DbSqlFlavor::Postgres);

    let sqlite = create_plan(&command)?;
    assert_creation_placeholders(&sqlite, DbSqlFlavor::Sqlite);
    Ok(())
}

#[test]
fn create_workspace_rejects_an_event_for_another_owner() -> Result<(), Box<dyn Error>> {
    let command = create_command("wrong-owner-event", '6')?;
    let result = WorkspaceCreationPlanner::new(DbSqlFlavor::Sqlite).plan(
        &command,
        create_profile()?,
        create_owner()?,
        create_response(),
        json!({
            "workspace_id": "workspace-1",
            "member_id": "member-1",
            "user_id": "another-owner",
            "role": "owner",
            "invited_by": "owner-1",
            "member": {
                "id": "member-1",
                "workspace_id": "workspace-1",
                "user_id": "another-owner",
                "role": "owner",
                "invited_by": "owner-1"
            }
        }),
    );

    assert!(matches!(
        result,
        Err(WorkspaceCreationPlanError::OwnerEventMismatch)
    ));
    Ok(())
}

fn create_command(
    idempotency_key: &str,
    hash_char: char,
) -> Result<WorkspaceMutationCommand, WorkspaceCommandError> {
    Ok(WorkspaceMutationCommand::new(
        create_scope()?,
        WorkspaceActor::new(ActorId::parse("owner-1")?, false),
        ContractVersion::parse("2.0.0")?,
        WorkspaceMutationAction::CreateWorkspace,
        ExpectedRevision::new(0),
        IdempotencyKey::parse(idempotency_key)?,
        RequestHash::parse(hash_char.to_string().repeat(64))?,
    ))
}

fn create_scope() -> Result<WorkspaceScope, WorkspaceCommandError> {
    Ok(WorkspaceScope::new(
        TenantId::parse("tenant-1")?,
        ProjectId::parse("project-1")?,
        WorkspaceId::parse("workspace-1")?,
    ))
}

fn create_profile() -> Result<WorkspaceCreateProfile, WorkspaceCommandError> {
    WorkspaceCreateProfile::new(
        GroupId::parse("group-workspace-1")?,
        BcsEnvironment::parse("memstack")?,
        WorkspaceName::parse("Team Space")?,
        Some("Shared workspace".to_string()),
        json!({"workspace_type": "general"}),
    )
}

fn create_owner() -> Result<WorkspaceCreateOwner, WorkspaceCommandError> {
    Ok(WorkspaceCreateOwner::new(
        WorkspaceMemberId::parse("member-1")?,
        UserId::parse("owner-1")?,
        ParticipantActorId::parse("owner-1")?,
    ))
}

fn create_plan(
    command: &WorkspaceMutationCommand,
) -> Result<memstack_workspace_store::WorkspaceCreationPlan, Box<dyn Error>> {
    Ok(WorkspaceCreationPlanner::new(DbSqlFlavor::Sqlite).plan(
        command,
        create_profile()?,
        create_owner()?,
        create_response(),
        create_event_payload(),
    )?)
}

fn create_response() -> Value {
    json!({
        "id": "workspace-1",
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "name": "Team Space",
        "created_by": "owner-1",
        "description": "Shared workspace",
        "is_archived": false,
        "metadata": {"workspace_type": "general"},
        "office_status": "inactive",
        "hex_layout_config": {},
        "created_at": "2026-08-10T00:00:00Z",
        "updated_at": "2026-08-10T00:00:00Z"
    })
}

fn create_event_payload() -> Value {
    json!({
        "workspace_id": "workspace-1",
        "member_id": "member-1",
        "user_id": "owner-1",
        "role": "owner",
        "invited_by": "owner-1",
        "member": {
            "id": "member-1",
            "workspace_id": "workspace-1",
            "user_id": "owner-1",
            "role": "owner",
            "invited_by": "owner-1"
        }
    })
}

async fn empty_db(project_member: bool) -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE bcs_groups (group_id TEXT NOT NULL, label TEXT, status TEXT NOT NULL, driver_bot TEXT NOT NULL, originator TEXT, env TEXT NOT NULL, routing_policy_json TEXT, context TEXT, group_kind TEXT NOT NULL DEFAULT 'normal', version INTEGER NOT NULL DEFAULT 1, record_status TEXT NOT NULL DEFAULT 'active', lifecycle_status TEXT NOT NULL DEFAULT 'active', group_strategy TEXT NOT NULL DEFAULT 'chat', created_by TEXT, visibility TEXT NOT NULL DEFAULT 'private', UNIQUE(group_id, env))",
        "CREATE TABLE bcs_group_participants (group_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, role TEXT NOT NULL, env TEXT NOT NULL, actor_kind TEXT NOT NULL DEFAULT 'bot', mode TEXT NOT NULL DEFAULT 'auto', UNIQUE(env, group_id, bot_uuid))",
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, is_archived INTEGER NOT NULL DEFAULT 0, office_status TEXT NOT NULL DEFAULT 'inactive', hex_layout_config_json TEXT NOT NULL DEFAULT '{}', default_blocking_categories_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', deleted_at TEXT, deleted_by TEXT, UNIQUE(tenant_id, project_id, workspace_id), UNIQUE(tenant_id, project_id, name))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, invited_by TEXT, UNIQUE(workspace_id, user_id), UNIQUE(workspace_id, participant_actor_id))",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    if project_member {
        db.execute(DbStatement::new(
            "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, is_active) VALUES ('tenant-1', 'project-1', 'owner-1', 'owner-1', 1)",
        ))
        .await?;
    }
    Ok(db)
}

async fn assert_creation_pristine(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for table in [
        "bcs_groups",
        "bcs_group_participants",
        "workspace_profiles",
        "workspace_members",
        "workspace_authorities",
        "workspace_mutation_receipts",
        "workspace_outbox",
    ] {
        assert_eq!(table_count(db, table).await?, 0, "unexpected {table} rows");
    }
    Ok(())
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "bcs_groups" => "SELECT COUNT(*) AS value FROM bcs_groups",
        "bcs_group_participants" => "SELECT COUNT(*) AS value FROM bcs_group_participants",
        "workspace_profiles" => "SELECT COUNT(*) AS value FROM workspace_profiles",
        "workspace_members" => "SELECT COUNT(*) AS value FROM workspace_members",
        "workspace_authorities" => "SELECT COUNT(*) AS value FROM workspace_authorities",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    scalar_i64(db, sql).await
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

fn assert_creation_placeholders(
    plan: &memstack_workspace_store::WorkspaceCreationPlan,
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
            assert_eq!(
                postgres_placeholder_positions(statement.sql()),
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
