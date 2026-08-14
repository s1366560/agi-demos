use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicCreateWorkspaceTaskInput, PublicWorkspaceTaskContext,
    PublicWorkspaceTaskDispatchService, PublicWorkspaceTaskErrorKind, PublicWorkspaceTaskService,
    WorkspaceCreationService,
};
use serde_json::json;

const TENANT_ID: &str = "tenant-task-pg-contract";
const PROJECT_ID: &str = "project-task-pg-contract";
const WORKSPACE_ID: &str = "workspace-task-pg-contract";
const GROUP_ID: &str = "group-task-pg-contract";
const USER_ID: &str = "actor-task-pg-contract";
const BINDING_ID: &str = "binding-task-pg-contract";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_task_authority_replays_dispatches_and_fences_provider_handoff()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_workspace(&db).await?;
    let tasks = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Postgres);
    let create_input = execution_task("task-pg-create", 1);

    let created = tasks.create(&create_input).await?;
    assert!(tasks.create(&create_input).await?.replayed);
    let assign_context = task_context("task-pg-assign", Some(2));
    let assigned = tasks
        .assign_agent(
            &assign_context,
            created.task.id.as_str(),
            BINDING_ID,
            Some("zh-CN"),
        )
        .await?;
    assert_eq!(assigned.committed_revision, 3);
    assert_eq!(
        assigned.task.workspace_agent_id.as_deref(),
        Some(BINDING_ID)
    );
    assert!(
        tasks
            .assign_agent(
                &assign_context,
                created.task.id.as_str(),
                BINDING_ID,
                Some("zh-CN"),
            )
            .await?
            .replayed
    );
    assert_eq!(
        workspace_count(&db, "workspace_task_dispatch_outbox").await?,
        1
    );
    assert!(
        db.execute(DbStatement::new(
            "UPDATE workspace_task_dispatch_outbox SET bot_uuid = 'overwritten' WHERE workspace_id = 'workspace-task-pg-contract'",
        ))
        .await
        .is_err()
    );

    let dispatches = PublicWorkspaceTaskDispatchService::new(&db, DbSqlFlavor::Postgres);
    let claimed = dispatches
        .claim_dispatches("task-pg-worker", 100, 200, 10)
        .await?;
    assert_eq!(claimed.len(), 1);
    assert_eq!(claimed[0].task_id, created.task.id);
    assert_eq!(claimed[0].group_id, GROUP_ID);
    assert_eq!(claimed[0].plan_id.as_deref(), Some("plan-task-pg"));
    dispatches.prepare_correlation(&claimed[0]).await?;
    dispatches.complete_dispatch(&claimed[0], 150).await?;
    assert_eq!(
        query_string(
            &db,
            "SELECT status AS value FROM workspace_agent_runtime_correlations WHERE workspace_id = $1",
        )
        .await?,
        "running"
    );
    assert!(
        dispatches
            .complete_dispatch(&claimed[0], 151)
            .await
            .is_err()
    );

    assert_eq!(workspace_revision(&db).await?, 3);
    assert_eq!(workspace_count(&db, "workspace_task_receipts").await?, 2);
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 3);
    assert_eq!(
        workspace_count(&db, "workspace_agent_runtime_correlations").await?,
        1
    );
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_task_dispatch_failure_rolls_back_assignment_receipt_revision_and_event()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_workspace(&db).await?;
    let tasks = PublicWorkspaceTaskService::new(&db, DbSqlFlavor::Postgres);
    let created = tasks
        .create(&execution_task("task-pg-rollback-create", 1))
        .await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_task_dispatch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-task-pg-contract' THEN RAISE EXCEPTION 'injected task dispatch failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_task_dispatch BEFORE INSERT ON workspace_task_dispatch_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_task_dispatch()",
    ))
    .await?;

    let error = match tasks
        .assign_agent(
            &task_context("task-pg-rollback-assign", Some(2)),
            created.task.id.as_str(),
            BINDING_ID,
            None,
        )
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("dispatch failure must abort the Task transaction".into()),
    };
    drop_fault_trigger(&db).await?;

    assert_eq!(error.kind(), PublicWorkspaceTaskErrorKind::Unavailable);
    assert_eq!(workspace_revision(&db).await?, 2);
    assert_eq!(workspace_count(&db, "workspace_task_receipts").await?, 1);
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 2);
    assert_eq!(
        workspace_count(&db, "workspace_task_dispatch_outbox").await?,
        0
    );
    let persisted = tasks
        .get(
            &task_context("task-pg-read", None),
            created.task.id.as_str(),
        )
        .await?;
    assert!(persisted.assignee_agent_id.is_none());
    assert!(persisted.workspace_agent_id.is_none());
    cleanup(&db).await?;
    Ok(())
}

fn execution_task(idempotency_key: &str, expected_revision: u64) -> PublicCreateWorkspaceTaskInput {
    PublicCreateWorkspaceTaskInput {
        context: task_context(idempotency_key, Some(expected_revision)),
        title: "PostgreSQL durable execution task".to_string(),
        description: Some("Persist before Provider delivery".to_string()),
        assignee_user_id: None,
        metadata: Some(json!({
            "task_role": "execution_task",
            "plan_id": "plan-task-pg",
            "plan_node_id": "node-task-pg"
        })),
        preferred_language: None,
        priority: Some("P1".to_string()),
        estimated_effort: Some("2h".to_string()),
        blocker_reason: None,
    }
}

fn task_context(
    idempotency_key: &str,
    expected_revision: Option<u64>,
) -> PublicWorkspaceTaskContext {
    PublicWorkspaceTaskContext {
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        user_id: USER_ID.to_string(),
        expected_revision,
        idempotency_key: expected_revision.map(|_| idempotency_key.to_string()),
    }
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn seed_workspace(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-task-pg-contract', 'project-task-pg-contract', 'actor-task-pg-contract', 'actor-task-pg-contract', 'membership-task-pg-contract', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
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
                member_id: "member-task-pg-contract".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL Task Workspace".to_string(),
                description: Some("Task authority contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "task-pg-workspace-create".to_string(),
        })
        .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, agent_id, bot_uuid, participant_actor_id, display_name, config_json, is_active, status) VALUES ('binding-task-pg-contract', 'tenant-task-pg-contract', 'project-task-pg-contract', 'workspace-task-pg-contract', 'agent-task-pg-contract', 'bot-task-pg-contract', 'bot:task-pg-contract', 'Task Agent', '{}'::jsonb, TRUE, 'idle')",
    ))
    .await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    drop_fault_trigger(db).await?;
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
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-task-pg-contract'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_task_dispatch ON workspace_task_dispatch_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_task_dispatch()",
    ))
    .await?;
    Ok(())
}

async fn workspace_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_task_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_task_receipts WHERE workspace_id = $1"
        }
        "workspace_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1"
        }
        "workspace_task_dispatch_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_task_dispatch_outbox WHERE workspace_id = $1"
        }
        "workspace_agent_runtime_correlations" => {
            "SELECT COUNT(*) AS value FROM workspace_agent_runtime_correlations WHERE workspace_id = $1"
        }
        _ => return Err("unsupported table".into()),
    };
    query_i64(db, sql).await
}

async fn workspace_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
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
