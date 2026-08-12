use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicCreateBlackboardPostInput, PublicCreateBlackboardReplyInput,
    PublicUpdateBlackboardPostFields, PublicUpdateBlackboardReplyInput,
    PublicWorkspaceBlackboardContext, PublicWorkspaceBlackboardErrorKind,
    PublicWorkspaceBlackboardService, WorkspaceCreationService,
};
use serde_json::json;

const TENANT_ID: &str = "tenant-blackboard-pg-contract";
const PROJECT_ID: &str = "project-blackboard-pg-contract";
const WORKSPACE_ID: &str = "workspace-blackboard-pg-contract";
const GROUP_ID: &str = "group-blackboard-pg-contract";
const USER_ID: &str = "actor-blackboard-pg-contract";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_blackboard_preserves_replay_cas_jsonb_ordering_and_events()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    let service = PublicWorkspaceBlackboardService::new(&db, DbSqlFlavor::Postgres);
    let input = PublicCreateBlackboardPostInput {
        context: blackboard_context("blackboard-pg-create", Some(1)),
        title: "PostgreSQL rollout".to_string(),
        content: "Track durable contract evidence".to_string(),
        status: "open".to_string(),
        is_pinned: false,
        metadata: json!({"source": "postgres-contract"}),
    };

    let created = service.create_post(&input).await?;
    let replayed = service.create_post(&input).await?;
    assert_eq!(created.post, replayed.post);
    assert_eq!(created.committed_revision, replayed.committed_revision);
    assert_eq!(created.outbox_id, replayed.outbox_id);
    assert!(!created.replayed);
    assert!(replayed.replayed);
    assert_eq!(created.committed_revision, 2);
    assert_eq!(created.post.metadata["source"], "postgres-contract");

    let updated = service
        .update_post(
            &blackboard_context("blackboard-pg-update", Some(2)),
            created.post.id.as_str(),
            &PublicUpdateBlackboardPostFields {
                title: Some("PostgreSQL rollout verified".to_string()),
                metadata: Some(json!({"reviewed": true})),
                ..PublicUpdateBlackboardPostFields::default()
            },
        )
        .await?;
    assert_eq!(updated.committed_revision, 3);
    assert_eq!(updated.post.metadata["reviewed"], true);
    assert_eq!(updated.post.metadata["surface_owner"], "blackboard");
    assert_eq!(updated.post.metadata["authority_class"], "authoritative");

    let pinned = service
        .set_post_pinned(
            &blackboard_context("blackboard-pg-pin", Some(3)),
            created.post.id.as_str(),
            true,
        )
        .await?;
    assert!(pinned.post.is_pinned);

    let reply = service
        .create_reply(
            created.post.id.as_str(),
            &PublicCreateBlackboardReplyInput {
                context: blackboard_context("blackboard-pg-reply-create", Some(4)),
                content: "Evidence attached".to_string(),
                metadata: json!({"sequence": 1}),
            },
        )
        .await?;
    let updated_reply = service
        .update_reply(
            &blackboard_context("blackboard-pg-reply-update", Some(5)),
            created.post.id.as_str(),
            reply.reply.id.as_str(),
            &PublicUpdateBlackboardReplyInput {
                content: "Evidence verified".to_string(),
                metadata: Some(json!({"reviewed": true})),
            },
        )
        .await?;
    assert_eq!(updated_reply.committed_revision, 6);

    let posts = service
        .list_posts(&blackboard_context("blackboard-pg-read", None), 50, 0)
        .await?;
    let replies = service
        .list_replies(
            &blackboard_context("blackboard-pg-read", None),
            created.post.id.as_str(),
            200,
            0,
        )
        .await?;
    assert_eq!(posts, vec![pinned.post]);
    assert_eq!(replies, vec![updated_reply.reply.clone()]);

    let stale = match service
        .update_post(
            &blackboard_context("blackboard-pg-stale", Some(5)),
            created.post.id.as_str(),
            &PublicUpdateBlackboardPostFields {
                title: Some("must roll back".to_string()),
                ..PublicUpdateBlackboardPostFields::default()
            },
        )
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("stale Blackboard revision must fail".into()),
    };
    assert_eq!(stale.kind(), PublicWorkspaceBlackboardErrorKind::Conflict);
    assert_eq!(workspace_revision(&db).await?, 6);
    assert_eq!(blackboard_receipt_count(&db).await?, 5);
    assert_eq!(blackboard_outbox_count(&db).await?, 5);

    assert_eq!(
        service
            .delete_reply(
                &blackboard_context("blackboard-pg-reply-delete", Some(6)),
                created.post.id.as_str(),
                reply.reply.id.as_str(),
            )
            .await?,
        json!({"success": true})
    );
    assert_eq!(
        service
            .delete_post(
                &blackboard_context("blackboard-pg-post-delete", Some(7)),
                created.post.id.as_str(),
            )
            .await?,
        json!({"success": true})
    );
    assert_eq!(workspace_revision(&db).await?, 8);
    assert_eq!(blackboard_post_count(&db).await?, 0);
    assert_eq!(blackboard_reply_count(&db).await?, 0);
    assert_eq!(blackboard_receipt_count(&db).await?, 7);
    assert_eq!(blackboard_outbox_count(&db).await?, 7);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_blackboard_outbox_failure_rolls_back_domain_receipt_and_revision()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_blackboard_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-blackboard-pg-contract' AND NEW.aggregate_type = 'blackboard' THEN RAISE EXCEPTION 'injected Blackboard outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_blackboard_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_blackboard_outbox()",
    ))
    .await?;

    let error = match PublicWorkspaceBlackboardService::new(&db, DbSqlFlavor::Postgres)
        .create_post(&PublicCreateBlackboardPostInput {
            context: blackboard_context("blackboard-pg-rollback", Some(1)),
            title: "Must roll back".to_string(),
            content: "Fault injection".to_string(),
            status: "open".to_string(),
            is_pinned: false,
            metadata: json!({}),
        })
        .await
    {
        Err(error) => error,
        Ok(_) => return Err("fault-injected Blackboard outbox must fail".into()),
    };
    drop_fault_trigger(&db).await?;

    assert_eq!(
        error.kind(),
        PublicWorkspaceBlackboardErrorKind::Unavailable
    );
    assert_eq!(workspace_revision(&db).await?, 1);
    assert_eq!(blackboard_post_count(&db).await?, 0);
    assert_eq!(blackboard_receipt_count(&db).await?, 0);
    assert_eq!(blackboard_outbox_count(&db).await?, 0);
    cleanup(&db).await?;
    Ok(())
}

fn blackboard_context(
    idempotency_key: &str,
    expected_revision: Option<u64>,
) -> PublicWorkspaceBlackboardContext {
    PublicWorkspaceBlackboardContext {
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
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-blackboard-pg-contract', 'project-blackboard-pg-contract', 'actor-blackboard-pg-contract', 'actor-blackboard-pg-contract', 'membership-blackboard-pg-contract', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
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
                member_id: "member-blackboard-pg-contract".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL Blackboard Workspace".to_string(),
                description: Some("Blackboard authority contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "blackboard-pg-workspace-create".to_string(),
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
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-blackboard-pg-contract'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_blackboard_outbox ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_blackboard_outbox()",
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

async fn blackboard_post_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_blackboard_posts WHERE workspace_id = $1",
    )
    .await
}

async fn blackboard_reply_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_blackboard_replies WHERE workspace_id = $1",
    )
    .await
}

async fn blackboard_receipt_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1 AND surface = 'blackboard'",
    )
    .await
}

async fn blackboard_outbox_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1 AND aggregate_type = 'blackboard'",
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
