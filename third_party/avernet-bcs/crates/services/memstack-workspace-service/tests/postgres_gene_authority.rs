use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicCreateWorkspaceGeneInput, PublicUpdateWorkspaceGeneFields,
    PublicWorkspaceGeneContext, PublicWorkspaceGeneErrorKind, PublicWorkspaceGeneService,
    WorkspaceCreationService,
};
use serde_json::{Value, json};

const TENANT_ID: &str = "tenant-gene-pg-contract";
const PROJECT_ID: &str = "project-gene-pg-contract";
const WORKSPACE_ID: &str = "workspace-gene-pg-contract";
const GROUP_ID: &str = "group-gene-pg-contract";
const USER_ID: &str = "actor-gene-pg-contract";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_gene_preserves_jsonb_semantic_version_replay_cas_and_events()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    let service = PublicWorkspaceGeneService::new(&db, DbSqlFlavor::Postgres);
    let input = create_gene_input("gene-pg-create", 1);

    let created = service.create(&input).await?;
    let replayed = service.create(&input).await?;
    assert_eq!(created.gene, replayed.gene);
    assert_eq!(created.committed_revision, replayed.committed_revision);
    assert_eq!(created.outbox_id, replayed.outbox_id);
    assert!(!created.replayed);
    assert!(replayed.replayed);
    assert_eq!(created.committed_revision, 2);
    assert_eq!(created.gene.version, "1.2.0");
    assert_eq!(created.gene.created_by, USER_ID);
    assert_eq!(workspace_revision(&db).await?, 2);
    assert_eq!(gene_count(&db).await?, 1);
    assert_eq!(gene_receipt_count(&db).await?, 1);
    assert_eq!(gene_outbox_count(&db).await?, 1);
    assert_eq!(
        gene_content(&db).await?,
        json!({"temperature": 0.2, "tools": ["plan"]})
    );

    let listed = service
        .list(
            &gene_context("gene-pg-read", None),
            Some("skill"),
            Some(true),
            100,
            0,
        )
        .await?;
    assert_eq!(listed, vec![created.gene.clone()]);

    let updated = service
        .update(
            &gene_context("gene-pg-update", Some(2)),
            created.gene.id.as_str(),
            &PublicUpdateWorkspaceGeneFields {
                name: Some("PostgreSQL Planner v2".to_string()),
                config_json: Some("{\"tools\":[\"plan\"],\"temperature\":0.1}".to_string()),
                version: Some("2.0.0".to_string()),
                is_active: Some(false),
                ..PublicUpdateWorkspaceGeneFields::default()
            },
        )
        .await?;
    assert_eq!(updated.committed_revision, 3);
    assert_eq!(updated.gene.version, "2.0.0");
    assert!(!updated.gene.is_active);
    assert_eq!(gene_version(&db).await?, 2);
    assert_eq!(gene_source_version(&db).await?, "2.0.0");

    let stale = match service
        .update(
            &gene_context("gene-pg-stale", Some(2)),
            created.gene.id.as_str(),
            &PublicUpdateWorkspaceGeneFields {
                name: Some("must roll back".to_string()),
                ..PublicUpdateWorkspaceGeneFields::default()
            },
        )
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("stale Gene revision must fail".into()),
    };
    assert_eq!(stale.kind(), PublicWorkspaceGeneErrorKind::Conflict);
    assert_eq!(workspace_revision(&db).await?, 3);
    assert_eq!(gene_receipt_count(&db).await?, 2);
    assert_eq!(gene_outbox_count(&db).await?, 2);

    service
        .delete(
            &gene_context("gene-pg-delete", Some(3)),
            created.gene.id.as_str(),
        )
        .await?;
    service
        .delete(
            &gene_context("gene-pg-delete", Some(3)),
            created.gene.id.as_str(),
        )
        .await?;
    assert_eq!(workspace_revision(&db).await?, 4);
    assert_eq!(gene_count(&db).await?, 0);
    assert_eq!(gene_receipt_count(&db).await?, 3);
    assert_eq!(gene_outbox_count(&db).await?, 3);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_gene_outbox_failure_rolls_back_gene_receipt_and_revision()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_gene_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-gene-pg-contract' AND NEW.aggregate_type = 'gene' THEN RAISE EXCEPTION 'injected Gene outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_gene_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_gene_outbox()",
    ))
    .await?;

    let error = match PublicWorkspaceGeneService::new(&db, DbSqlFlavor::Postgres)
        .create(&create_gene_input("gene-pg-rollback", 1))
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("fault-injected Gene outbox must fail".into()),
    };
    drop_fault_trigger(&db).await?;

    assert_eq!(error.kind(), PublicWorkspaceGeneErrorKind::Unavailable);
    assert_eq!(workspace_revision(&db).await?, 1);
    assert_eq!(gene_count(&db).await?, 0);
    assert_eq!(gene_receipt_count(&db).await?, 0);
    assert_eq!(gene_outbox_count(&db).await?, 0);
    cleanup(&db).await?;
    Ok(())
}

fn create_gene_input(
    idempotency_key: &str,
    expected_revision: u64,
) -> PublicCreateWorkspaceGeneInput {
    PublicCreateWorkspaceGeneInput {
        context: gene_context(idempotency_key, Some(expected_revision)),
        name: "PostgreSQL Planner".to_string(),
        category: "skill".to_string(),
        description: Some("Gene authority contract".to_string()),
        config_json: Some("{\"temperature\":0.2,\"tools\":[\"plan\"]}".to_string()),
        version: "1.2.0".to_string(),
        is_active: true,
    }
}

fn gene_context(
    idempotency_key: &str,
    expected_revision: Option<u64>,
) -> PublicWorkspaceGeneContext {
    PublicWorkspaceGeneContext {
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        user_id: USER_ID.to_string(),
        is_superuser: false,
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
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-gene-pg-contract', 'project-gene-pg-contract', 'actor-gene-pg-contract', 'actor-gene-pg-contract', 'membership-gene-pg-contract', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
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
                member_id: "member-gene-pg-contract".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL Gene Workspace".to_string(),
                description: Some("Gene authority contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "gene-pg-workspace-create".to_string(),
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
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-gene-pg-contract'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_gene_outbox ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_gene_outbox()",
    ))
    .await?;
    Ok(())
}

async fn workspace_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
    )
    .await
}

async fn gene_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_genes WHERE workspace_id = $1",
    )
    .await
}

async fn gene_receipt_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1 AND surface = 'gene'",
    )
    .await
}

async fn gene_outbox_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1 AND aggregate_type = 'gene'",
    )
    .await
}

async fn gene_version(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT version AS value FROM workspace_genes WHERE workspace_id = $1",
    )
    .await
}

async fn gene_source_version(db: &dyn DbPlugin) -> Result<String, Box<dyn Error>> {
    query_string(
        db,
        "SELECT source_version AS value FROM workspace_genes WHERE workspace_id = $1",
    )
    .await
}

async fn gene_content(db: &dyn DbPlugin) -> Result<Value, Box<dyn Error>> {
    let encoded = query_string(
        db,
        "SELECT content_json::text AS value FROM workspace_genes WHERE workspace_id = $1",
    )
    .await?;
    Ok(serde_json::from_str(encoded.as_str())?)
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
