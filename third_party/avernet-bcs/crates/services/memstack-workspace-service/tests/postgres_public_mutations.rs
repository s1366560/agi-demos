use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicAddWorkspaceMemberInput, PublicDeleteWorkspaceInput,
    PublicRemoveWorkspaceMemberInput, PublicUpdateWorkspaceInput, PublicUpdateWorkspaceMemberInput,
    PublicWorkspaceMemberMutationService, PublicWorkspaceMutationContext,
    PublicWorkspaceMutationErrorKind, PublicWorkspaceMutationService, WorkspaceCreationService,
    WorkspaceMemberRole,
};
use serde_json::json;

const WORKSPACE_ID: &str = "workspace-service-pg-mutations";
const GROUP_ID: &str = "group-service-pg-mutations";
const USER_ID: &str = "actor-service-pg-mutations";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_public_update_and_delete_preserve_receipts_and_outbox()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    WorkspaceCreationService::new(&db, DbSqlFlavor::Postgres)
        .create(&create_input())
        .await?;
    let service = PublicWorkspaceMutationService::new(&db, DbSqlFlavor::Postgres);

    let updated = service
        .update(&PublicUpdateWorkspaceInput {
            context: context("postgres-update", 1),
            name: Some("PostgreSQL Updated".to_string()),
            description: Some("Updated in PostgreSQL".to_string()),
            is_archived: Some(true),
            metadata: Some(json!({"workspace_type": "general", "updated": true})),
        })
        .await?;
    let delete_input = PublicDeleteWorkspaceInput {
        context: context("postgres-delete", 2),
    };
    let deleted = service.delete(&delete_input).await?;
    let replayed = service.delete(&delete_input).await?;

    assert_eq!(updated.committed_revision, 2);
    assert_eq!(deleted.committed_revision, 3);
    assert!(replayed.replayed);
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
        )
        .await?,
        3
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1",
        )
        .await?,
        3
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1",
        )
        .await?,
        3
    );
    assert_eq!(
        scoped_string(
            &db,
            "SELECT deleted_by AS value FROM workspace_profiles WHERE workspace_id = $1",
        )
        .await?,
        USER_ID
    );
    assert_eq!(
        group_string(
            &db,
            "SELECT lifecycle_status AS value FROM bcs_groups WHERE group_id = $1",
        )
        .await?,
        "deleted"
    );
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_delete_outbox_failure_rolls_back_profile_group_and_revision()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    WorkspaceCreationService::new(&db, DbSqlFlavor::Postgres)
        .create(&create_input())
        .await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_service_delete_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-service-pg-mutations' AND NEW.event_type = 'workspace_deleted' THEN RAISE EXCEPTION 'injected delete outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_service_delete_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_service_delete_outbox()",
    ))
    .await?;

    let error = match PublicWorkspaceMutationService::new(&db, DbSqlFlavor::Postgres)
        .delete(&PublicDeleteWorkspaceInput {
            context: context("postgres-delete-rollback", 1),
        })
        .await
    {
        Ok(_) => return Err("fault-injected delete must fail".into()),
        Err(error) => error,
    };
    drop_fault_trigger(&db).await?;

    assert_eq!(error.kind(), PublicWorkspaceMutationErrorKind::Unavailable);
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
        )
        .await?,
        1
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_profiles WHERE workspace_id = $1 AND deleted_at IS NULL",
        )
        .await?,
        1
    );
    assert_eq!(
        group_string(
            &db,
            "SELECT lifecycle_status AS value FROM bcs_groups WHERE group_id = $1",
        )
        .await?,
        "active"
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1",
        )
        .await?,
        1
    );
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_member_mutations_keep_acl_and_bcs_roster_atomic() -> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    seed_secondary_project_membership(&db).await?;
    WorkspaceCreationService::new(&db, DbSqlFlavor::Postgres)
        .create(&create_input())
        .await?;
    let service = PublicWorkspaceMemberMutationService::new(&db, DbSqlFlavor::Postgres);
    let add_input = PublicAddWorkspaceMemberInput {
        context: context("postgres-member-add", 1),
        user_id: "member-service-pg-mutations".to_string(),
        role: WorkspaceMemberRole::Viewer,
    };

    let added = service.add(&add_input).await?;
    let replayed_add = service.add(&add_input).await?;
    let updated = service
        .update(&PublicUpdateWorkspaceMemberInput {
            context: context("postgres-member-update", 2),
            user_id: "member-service-pg-mutations".to_string(),
            role: WorkspaceMemberRole::Editor,
        })
        .await?;
    let remove_input = PublicRemoveWorkspaceMemberInput {
        context: context("postgres-member-remove", 3),
        user_id: "member-service-pg-mutations".to_string(),
    };
    let removed = service.remove(&remove_input).await?;
    let replayed_remove = service.remove(&remove_input).await?;

    assert_eq!(added.committed_revision, 2);
    assert!(replayed_add.replayed);
    assert_eq!(updated.committed_revision, 3);
    assert_eq!(removed.committed_revision, 4);
    assert!(replayed_remove.replayed);
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_members WHERE workspace_id = $1",
        )
        .await?,
        1
    );
    assert_eq!(
        group_i64(
            &db,
            "SELECT COUNT(*) AS value FROM bcs_group_participants WHERE group_id = $1",
        )
        .await?,
        1
    );
    assert_eq!(
        scoped_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1",
        )
        .await?,
        4
    );
    cleanup(&db).await?;
    Ok(())
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

fn create_input() -> CreateWorkspaceInput {
    CreateWorkspaceInput {
        scope: CreateWorkspaceScopeInput {
            tenant_id: "tenant-service-contract".to_string(),
            project_id: "project-service-contract".to_string(),
            workspace_id: WORKSPACE_ID.to_string(),
            group_id: GROUP_ID.to_string(),
        },
        owner: CreateWorkspaceOwnerInput {
            member_id: "member-service-pg-mutations".to_string(),
            user_id: USER_ID.to_string(),
            is_superuser: false,
        },
        content: CreateWorkspaceContentInput {
            name: "PostgreSQL Workspace".to_string(),
            description: Some("Public mutation contract".to_string()),
            metadata: json!({"workspace_type": "general"}),
        },
        idempotency_key: "postgres-create-service-mutations".to_string(),
    }
}

fn context(idempotency_key: &str, revision: u64) -> PublicWorkspaceMutationContext {
    PublicWorkspaceMutationContext {
        tenant_id: "tenant-service-contract".to_string(),
        project_id: "project-service-contract".to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        user_id: USER_ID.to_string(),
        expected_revision: Some(revision),
        idempotency_key: Some(idempotency_key.to_string()),
    }
}

async fn seed_project_membership(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-service-contract', 'project-service-contract', 'actor-service-pg-mutations', 'actor-service-pg-mutations', 'membership-service-pg-mutations', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
    ))
    .await?;
    Ok(())
}

async fn seed_secondary_project_membership(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-service-contract', 'project-service-contract', 'member-service-pg-mutations', 'member-service-pg-mutations', 'membership-service-pg-member', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
    ))
    .await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    drop_fault_trigger(db).await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_group_participants WHERE group_id = ")
            .bind(GROUP_ID)
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_groups WHERE group_id = ")
            .bind(GROUP_ID)
            .build(),
    )
    .await?;
    db.execute(DbStatement::new(
        "DELETE FROM project_principal_memberships WHERE source_membership_id IN ('membership-service-pg-mutations', 'membership-service-pg-member')",
    ))
    .await?;
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_service_delete_outbox ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_service_delete_outbox()",
    ))
    .await?;
    Ok(())
}

async fn scoped_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![WORKSPACE_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn scoped_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![WORKSPACE_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}

async fn group_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![GROUP_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}

async fn group_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![GROUP_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}
