use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicCreateTopologyEdgeInput, PublicCreateTopologyNodeInput,
    PublicUpdateTopologyNodeFields, PublicWorkspaceTopologyContext,
    PublicWorkspaceTopologyErrorKind, PublicWorkspaceTopologyService, WorkspaceCreationService,
};
use serde_json::json;

const TENANT_ID: &str = "tenant-topology-pg-contract";
const PROJECT_ID: &str = "project-topology-pg-contract";
const WORKSPACE_ID: &str = "workspace-topology-pg-contract";
const GROUP_ID: &str = "group-topology-pg-contract";
const USER_ID: &str = "actor-topology-pg-contract";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_topology_preserves_nullable_direction_widths_cas_and_coordinates()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    let service = PublicWorkspaceTopologyService::new(&db, DbSqlFlavor::Postgres);
    let ref_id = "r".repeat(255);
    let status = "s".repeat(32);

    let source = service
        .create_node(&create_node_input(
            "topology-pg-source",
            1,
            1,
            0,
            Some(ref_id.clone()),
            status.clone(),
        ))
        .await?;
    let target = service
        .create_node(&create_node_input(
            "topology-pg-target",
            2,
            2,
            -1,
            None,
            "active".to_string(),
        ))
        .await?;
    assert_eq!(source.value.ref_id.as_deref(), Some(ref_id.as_str()));
    assert_eq!(source.value.status, status);

    let edge = service
        .create_edge(&PublicCreateTopologyEdgeInput {
            context: topology_context("topology-pg-edge", Some(3)),
            source_node_id: source.value.id.clone(),
            target_node_id: target.value.id.clone(),
            label: Some("depends".to_string()),
            direction: None,
            auto_created: false,
            data: json!({"weight": 1}),
        })
        .await?;
    assert_eq!(edge.value.direction, None);
    assert_eq!(edge.value.source_hex_q, Some(1));
    assert_eq!(edge.value.target_hex_r, Some(-1));

    let updated = service
        .update_node(
            &topology_context("topology-pg-move", Some(4)),
            source.value.id.as_str(),
            &PublicUpdateTopologyNodeFields {
                hex_q: Some(3),
                hex_r: Some(-1),
                data: Some(json!({"moved": true})),
                ..PublicUpdateTopologyNodeFields::default()
            },
        )
        .await?;
    assert_eq!(updated.committed_revision, 5);
    let stored_edge = service
        .get_edge(
            &topology_context("topology-pg-read", None),
            edge.value.id.as_str(),
        )
        .await?;
    assert_eq!(stored_edge.source_hex_q, Some(3));
    assert_eq!(stored_edge.source_hex_r, Some(-1));

    let stale_error = match service
        .update_node(
            &topology_context("topology-pg-stale", Some(4)),
            source.value.id.as_str(),
            &PublicUpdateTopologyNodeFields {
                title: Some("must roll back".to_string()),
                ..PublicUpdateTopologyNodeFields::default()
            },
        )
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("stale topology revision must fail".into()),
    };
    assert_eq!(
        stale_error.kind(),
        PublicWorkspaceTopologyErrorKind::Conflict
    );
    assert_eq!(workspace_revision(&db).await?, 5);
    assert_eq!(workspace_count(&db, "workspace_topology_nodes").await?, 2);
    assert_eq!(workspace_count(&db, "workspace_topology_edges").await?, 1);
    assert_eq!(
        workspace_count(&db, "workspace_mutation_receipts").await?,
        5
    );
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 5);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_topology_outbox_failure_rolls_back_domain_receipt_and_revision()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_topology_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-topology-pg-contract' AND NEW.aggregate_type = 'topology' THEN RAISE EXCEPTION 'injected topology outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_topology_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_topology_outbox()",
    ))
    .await?;

    let error = match PublicWorkspaceTopologyService::new(&db, DbSqlFlavor::Postgres)
        .create_node(&create_node_input(
            "topology-pg-rollback",
            1,
            1,
            0,
            None,
            "active".to_string(),
        ))
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("fault-injected topology outbox must fail".into()),
    };
    drop_fault_trigger(&db).await?;

    assert_eq!(error.kind(), PublicWorkspaceTopologyErrorKind::Unavailable);
    assert_eq!(workspace_revision(&db).await?, 1);
    assert_eq!(workspace_count(&db, "workspace_topology_nodes").await?, 0);
    assert_eq!(
        workspace_count(&db, "workspace_mutation_receipts").await?,
        1
    );
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 1);
    cleanup(&db).await?;
    Ok(())
}

fn create_node_input(
    idempotency_key: &str,
    expected_revision: u64,
    hex_q: i64,
    hex_r: i64,
    ref_id: Option<String>,
    status: String,
) -> PublicCreateTopologyNodeInput {
    PublicCreateTopologyNodeInput {
        context: topology_context(idempotency_key, Some(expected_revision)),
        node_type: "corridor".to_string(),
        ref_id,
        title: "PostgreSQL topology node".to_string(),
        position_x: 10.0,
        position_y: 20.0,
        hex_q: Some(hex_q),
        hex_r: Some(hex_r),
        status,
        tags: json!(["contract"]),
        data: json!({}),
    }
}

fn topology_context(
    idempotency_key: &str,
    expected_revision: Option<u64>,
) -> PublicWorkspaceTopologyContext {
    PublicWorkspaceTopologyContext {
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

async fn seed_project_membership(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-topology-pg-contract', 'project-topology-pg-contract', 'actor-topology-pg-contract', 'actor-topology-pg-contract', 'membership-topology-pg-contract', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
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
                member_id: "member-topology-pg-contract".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL Topology Workspace".to_string(),
                description: Some("Topology authority contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "topology-pg-workspace-create".to_string(),
        })
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
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-topology-pg-contract'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_topology_outbox ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_topology_outbox()",
    ))
    .await?;
    Ok(())
}

async fn workspace_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_topology_nodes" => {
            "SELECT COUNT(*) AS value FROM workspace_topology_nodes WHERE workspace_id = $1"
        }
        "workspace_topology_edges" => {
            "SELECT COUNT(*) AS value FROM workspace_topology_edges WHERE workspace_id = $1"
        }
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1"
        }
        "workspace_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1"
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
