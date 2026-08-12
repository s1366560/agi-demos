use std::error::Error;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicBindWorkspaceAgentInput, PublicUnbindWorkspaceAgentInput,
    PublicUpdateWorkspaceAgentInput, PublicWorkspaceAgentMutationService,
    PublicWorkspaceMutationContext, PublicWorkspaceMutationErrorKind, WorkspaceCreationService,
};
use memstack_workspace_service_api::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
};
use serde_json::{Value, json};

const WORKSPACE_ID: &str = "workspace-agent-pg-mutations";
const GROUP_ID: &str = "group-agent-pg-mutations";
const USER_ID: &str = "actor-agent-pg-mutations";
const AGENT_ID: &str = "agent-service-pg-planner";
const THEME_COLOR_32: &str = "12345678901234567890123456789012";

struct StaticRegistry {
    calls: AtomicUsize,
}

impl StaticRegistry {
    fn new() -> Self {
        Self {
            calls: AtomicUsize::new(0),
        }
    }

    fn calls(&self) -> usize {
        self.calls.load(Ordering::Relaxed)
    }
}

#[async_trait]
impl AgentRegistryPort for StaticRegistry {
    async fn resolve(
        &self,
        lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        AgentRegistryAgent::parse(
            lookup.agent_id().as_str(),
            "planner",
            Some("PostgreSQL Planner".to_string()),
            true,
        )
        .map(Some)
        .map_err(|_| AgentRegistryPortError::Unavailable)
    }
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_agent_mutations_keep_binding_bot_roster_receipt_and_outbox_atomic()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    let registry = StaticRegistry::new();
    let service = PublicWorkspaceAgentMutationService::new(&db, DbSqlFlavor::Postgres, &registry);

    let bound = service
        .bind(&bind_input("postgres-agent-bind", 1, 2, -1))
        .await?;
    let binding_id = bound.response["id"]
        .as_str()
        .ok_or("missing binding id")?
        .to_string();
    assert_eq!(bound.committed_revision, 2);
    assert_eq!(bound.response["theme_color"], THEME_COLOR_32);
    assert_eq!(workspace_count(&db, "workspace_agent_bindings").await?, 1);
    assert_eq!(bot_count(&db).await?, 1);
    assert_eq!(bot_participant_count(&db).await?, 1);

    let rebound = service
        .bind(&PublicBindWorkspaceAgentInput {
            context: context("postgres-agent-rebind", 2),
            agent_id: AGENT_ID.to_string(),
            display_name: Some("Renamed PostgreSQL Planner".to_string()),
            description: None,
            config: json!({"mode": "review"}),
            is_active: false,
            hex_q: Some(3),
            hex_r: Some(-1),
            theme_color: Some(THEME_COLOR_32.to_string()),
            label: Some("review".to_string()),
        })
        .await?;
    assert_eq!(rebound.committed_revision, 3);
    assert_eq!(rebound.response["id"], binding_id);
    assert_eq!(rebound.response["is_active"], false);
    assert_eq!(outbox_payload(&db, 3).await?["is_update"], true);
    assert_eq!(bot_status(&db).await?, "offline");

    let updated = service
        .update(&PublicUpdateWorkspaceAgentInput {
            context: context("postgres-agent-update", 3),
            workspace_agent_id: binding_id.clone(),
            display_name: None,
            description: Some("Updated in PostgreSQL".to_string()),
            config: None,
            is_active: Some(true),
            hex_q: Some(4),
            hex_r: Some(-2),
            theme_color: None,
            label: Some("relay".to_string()),
        })
        .await?;
    assert_eq!(updated.committed_revision, 4);
    assert_eq!(updated.response["description"], "Updated in PostgreSQL");
    assert_eq!(updated.response["config"], json!({"mode": "review"}));
    assert_eq!(updated.response["hex_q"], 4);
    assert_eq!(bot_status(&db).await?, "online");

    let unbind_input = PublicUnbindWorkspaceAgentInput {
        context: context("postgres-agent-unbind", 4),
        workspace_agent_id: binding_id,
    };
    let unbound = service.unbind(&unbind_input).await?;
    let replayed = service.unbind(&unbind_input).await?;
    assert_eq!(unbound.committed_revision, 5);
    assert!(replayed.replayed);
    assert_eq!(workspace_revision(&db).await?, 5);
    assert_eq!(workspace_count(&db, "workspace_agent_bindings").await?, 0);
    assert_eq!(bot_count(&db).await?, 0);
    assert_eq!(bot_participant_count(&db).await?, 0);
    assert_eq!(
        workspace_count(&db, "workspace_mutation_receipts").await?,
        5
    );
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 5);
    assert_eq!(registry.calls(), 2);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_agent_outbox_failure_rolls_back_binding_bot_roster_and_revision()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_agent_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-agent-pg-mutations' AND NEW.event_type = 'workspace_agent_bound' THEN RAISE EXCEPTION 'injected Agent outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_agent_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_agent_outbox()",
    ))
    .await?;

    let registry = StaticRegistry::new();
    let error =
        match PublicWorkspaceAgentMutationService::new(&db, DbSqlFlavor::Postgres, &registry)
            .bind(&bind_input("postgres-agent-rollback", 1, 2, -1))
            .await
        {
            Ok(_) => return Err("fault-injected Agent outbox must fail".into()),
            Err(error) => error,
        };
    drop_fault_trigger(&db).await?;

    assert_eq!(error.kind(), PublicWorkspaceMutationErrorKind::Unavailable);
    assert_eq!(workspace_revision(&db).await?, 1);
    assert_eq!(workspace_count(&db, "workspace_agent_bindings").await?, 0);
    assert_eq!(bot_count(&db).await?, 0);
    assert_eq!(bot_participant_count(&db).await?, 0);
    assert_eq!(
        workspace_count(&db, "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 1);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_agent_geometry_constraints_topology_conflict_and_cas_are_atomic()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;

    for statement in [
        "INSERT INTO workspace_topology_nodes (node_id, tenant_id, project_id, workspace_id, node_type, title, hex_q, hex_r) VALUES ('invalid-center', 'tenant-agent-contract', 'project-agent-contract', 'workspace-agent-pg-mutations', 'corridor', 'Center', 0, 0)",
        "INSERT INTO workspace_topology_nodes (node_id, tenant_id, project_id, workspace_id, node_type, title, hex_q, hex_r) VALUES ('invalid-pair', 'tenant-agent-contract', 'project-agent-contract', 'workspace-agent-pg-mutations', 'corridor', 'Pair', 2, NULL)",
        "INSERT INTO workspace_topology_nodes (node_id, tenant_id, project_id, workspace_id, node_type, title, hex_q, hex_r) VALUES ('invalid-radius', 'tenant-agent-contract', 'project-agent-contract', 'workspace-agent-pg-mutations', 'corridor', 'Radius', 24, 24)",
    ] {
        assert!(
            db.execute(DbStatement::new(statement)).await.is_err(),
            "invalid topology geometry must be rejected by PostgreSQL"
        );
    }
    db.execute(DbStatement::new(
        "INSERT INTO workspace_topology_nodes (node_id, tenant_id, project_id, workspace_id, node_type, title, hex_q, hex_r) VALUES ('occupied-node', 'tenant-agent-contract', 'project-agent-contract', 'workspace-agent-pg-mutations', 'corridor', 'Occupied', 3, -1)",
    ))
    .await?;

    let registry = StaticRegistry::new();
    let service = PublicWorkspaceAgentMutationService::new(&db, DbSqlFlavor::Postgres, &registry);
    let bound = service
        .bind(&bind_input("postgres-agent-conflict-bind", 1, 2, -1))
        .await?;
    let binding_id = bound.response["id"]
        .as_str()
        .ok_or("missing binding id")?
        .to_string();

    let occupied_error = match service
        .update(&PublicUpdateWorkspaceAgentInput {
            context: context("postgres-agent-topology-conflict", 2),
            workspace_agent_id: binding_id.clone(),
            display_name: Some("Must roll back".to_string()),
            description: None,
            config: None,
            is_active: Some(false),
            hex_q: Some(3),
            hex_r: Some(-1),
            theme_color: None,
            label: None,
        })
        .await
    {
        Ok(_) => return Err("occupied topology position must fail".into()),
        Err(error) => error,
    };
    assert_eq!(
        occupied_error.kind(),
        PublicWorkspaceMutationErrorKind::Validation
    );
    assert_eq!(workspace_revision(&db).await?, 2);
    assert_eq!(binding_i64(&db, "hex_q").await?, 2);
    assert_eq!(
        binding_string(&db, "display_name").await?,
        "PostgreSQL Planner"
    );
    assert_eq!(bot_status(&db).await?, "online");
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 2);

    let stale_error = match service
        .update(&PublicUpdateWorkspaceAgentInput {
            context: context("postgres-agent-stale-update", 1),
            workspace_agent_id: binding_id,
            display_name: Some("Stale update".to_string()),
            description: None,
            config: None,
            is_active: None,
            hex_q: None,
            hex_r: None,
            theme_color: None,
            label: None,
        })
        .await
    {
        Ok(_) => return Err("stale authority revision must fail".into()),
        Err(error) => error,
    };
    assert_eq!(
        stale_error.kind(),
        PublicWorkspaceMutationErrorKind::Conflict
    );
    assert_eq!(workspace_revision(&db).await?, 2);
    assert_eq!(
        binding_string(&db, "display_name").await?,
        "PostgreSQL Planner"
    );
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 2);
    cleanup(&db).await?;
    Ok(())
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn create_workspace(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    WorkspaceCreationService::new(db, DbSqlFlavor::Postgres)
        .create(&CreateWorkspaceInput {
            scope: CreateWorkspaceScopeInput {
                tenant_id: "tenant-agent-contract".to_string(),
                project_id: "project-agent-contract".to_string(),
                workspace_id: WORKSPACE_ID.to_string(),
                group_id: GROUP_ID.to_string(),
            },
            owner: CreateWorkspaceOwnerInput {
                member_id: "member-agent-pg-mutations".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL Agent Workspace".to_string(),
                description: Some("Agent mutation contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "postgres-agent-workspace-create".to_string(),
        })
        .await?;
    Ok(())
}

fn bind_input(
    idempotency_key: &str,
    revision: u64,
    hex_q: i64,
    hex_r: i64,
) -> PublicBindWorkspaceAgentInput {
    PublicBindWorkspaceAgentInput {
        context: context(idempotency_key, revision),
        agent_id: AGENT_ID.to_string(),
        display_name: Some("PostgreSQL Planner".to_string()),
        description: Some("Plans work".to_string()),
        config: json!({"mode": "plan"}),
        is_active: true,
        hex_q: Some(hex_q),
        hex_r: Some(hex_r),
        theme_color: Some(THEME_COLOR_32.to_string()),
        label: Some("planner".to_string()),
    }
}

fn context(idempotency_key: &str, revision: u64) -> PublicWorkspaceMutationContext {
    PublicWorkspaceMutationContext {
        tenant_id: "tenant-agent-contract".to_string(),
        project_id: "project-agent-contract".to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        user_id: USER_ID.to_string(),
        expected_revision: Some(revision),
        idempotency_key: Some(idempotency_key.to_string()),
    }
}

async fn seed_project_membership(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-agent-contract', 'project-agent-contract', 'actor-agent-pg-mutations', 'actor-agent-pg-mutations', 'membership-agent-pg-mutations', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
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
            .push_static("DELETE FROM bcs_bots WHERE created_by = ")
            .bind(USER_ID)
            .push_static(" AND agent_code = ")
            .bind(AGENT_ID)
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
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-agent-pg-mutations'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_agent_outbox ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_agent_outbox()",
    ))
    .await?;
    Ok(())
}

async fn workspace_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_agent_bindings" => {
            "SELECT COUNT(*) AS value FROM workspace_agent_bindings WHERE workspace_id = $1"
        }
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1"
        }
        "workspace_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1"
        }
        _ => return Err("unsupported table".into()),
    };
    query_i64(db, sql, WORKSPACE_ID).await
}

async fn bot_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM bcs_bots WHERE created_by = $1 AND agent_code = 'agent-service-pg-planner'",
        USER_ID,
    )
    .await
}

async fn bot_participant_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM bcs_group_participants WHERE group_id = $1 AND actor_kind = 'bot'",
        GROUP_ID,
    )
    .await
}

async fn workspace_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
        WORKSPACE_ID,
    )
    .await
}

async fn binding_i64(db: &dyn DbPlugin, field: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match field {
        "hex_q" => "SELECT hex_q AS value FROM workspace_agent_bindings WHERE workspace_id = $1",
        _ => return Err("unsupported field".into()),
    };
    query_i64(db, sql, WORKSPACE_ID).await
}

async fn binding_string(db: &dyn DbPlugin, field: &str) -> Result<String, Box<dyn Error>> {
    let sql = match field {
        "display_name" => {
            "SELECT display_name AS value FROM workspace_agent_bindings WHERE workspace_id = $1"
        }
        _ => return Err("unsupported field".into()),
    };
    query_string(db, sql, WORKSPACE_ID).await
}

async fn bot_status(db: &dyn DbPlugin) -> Result<String, Box<dyn Error>> {
    query_string(
        db,
        "SELECT status AS value FROM bcs_bots WHERE created_by = $1 AND agent_code = 'agent-service-pg-planner'",
        USER_ID,
    )
    .await
}

async fn outbox_payload(db: &dyn DbPlugin, event_sequence: i64) -> Result<Value, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT payload_json::text AS value FROM workspace_outbox WHERE workspace_id = $1 AND event_sequence = $2",
            vec![WORKSPACE_ID.into(), event_sequence.into()],
        ))
        .await?;
    let value = rows
        .first()
        .ok_or("missing outbox row")?
        .get_string("value")?
        .ok_or("missing outbox payload")?;
    Ok(serde_json::from_str(&value)?)
}

async fn query_i64(db: &dyn DbPlugin, sql: &str, parameter: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![parameter.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn query_string(
    db: &dyn DbPlugin,
    sql: &str,
    parameter: &str,
) -> Result<String, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![parameter.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}
