use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    PublicCreateBlackboardPostInput, PublicCreateBlackboardReplyInput,
    PublicUpdateBlackboardPostFields, PublicUpdateBlackboardReplyInput,
    PublicWorkspaceBlackboardContext, PublicWorkspaceBlackboardService,
};
use serde_json::json;

#[tokio::test]
async fn blackboard_posts_and_replies_commit_replay_and_emit_atomically()
-> Result<(), Box<dyn Error>> {
    let db = seeded_blackboard_db().await?;
    let service = PublicWorkspaceBlackboardService::new(&db, DbSqlFlavor::Sqlite);
    let create = PublicCreateBlackboardPostInput {
        context: blackboard_context("create-post-1", Some(0)),
        title: "Authority rollout".to_string(),
        content: "Track durable delivery evidence".to_string(),
        status: "open".to_string(),
        is_pinned: false,
        metadata: json!({"source": "contract"}),
    };

    let created = service.create_post(&create).await?;
    let replayed = service.create_post(&create).await?;
    assert!(!created.replayed);
    assert!(replayed.replayed);
    assert_eq!(replayed.post, created.post);
    assert_eq!(created.post.metadata["surface_owner"], "blackboard");
    assert_eq!(created.post.metadata["authority_class"], "authoritative");

    let pinned = service
        .set_post_pinned(
            &blackboard_context("pin-post-1", Some(1)),
            created.post.id.as_str(),
            true,
        )
        .await?;
    assert!(pinned.post.is_pinned);

    let reply = service
        .create_reply(
            created.post.id.as_str(),
            &PublicCreateBlackboardReplyInput {
                context: blackboard_context("create-reply-1", Some(2)),
                content: "Evidence attached".to_string(),
                metadata: json!({}),
            },
        )
        .await?;
    let updated_reply = service
        .update_reply(
            &blackboard_context("update-reply-1", Some(3)),
            created.post.id.as_str(),
            reply.reply.id.as_str(),
            &PublicUpdateBlackboardReplyInput {
                content: "Evidence verified".to_string(),
                metadata: Some(json!({"reviewed": true})),
            },
        )
        .await?;
    assert_eq!(updated_reply.reply.content, "Evidence verified");
    assert_eq!(updated_reply.reply.metadata["reviewed"], true);

    let posts = service
        .list_posts(&blackboard_context("read", None), 50, 0)
        .await?;
    let replies = service
        .list_replies(
            &blackboard_context("read", None),
            created.post.id.as_str(),
            200,
            0,
        )
        .await?;
    assert_eq!(posts, vec![pinned.post]);
    assert_eq!(replies, vec![updated_reply.reply]);
    assert_eq!(table_count(&db, "workspace_mutation_receipts").await?, 4);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 4);
    assert_eq!(authority_revision(&db).await?, 4);
    Ok(())
}

#[tokio::test]
async fn blackboard_update_delete_and_permissions_preserve_scope() -> Result<(), Box<dyn Error>> {
    let db = seeded_blackboard_db().await?;
    let service = PublicWorkspaceBlackboardService::new(&db, DbSqlFlavor::Sqlite);
    let created = service
        .create_post(&PublicCreateBlackboardPostInput {
            context: blackboard_context("create-post-2", Some(0)),
            title: "Initial".to_string(),
            content: "Initial content".to_string(),
            status: "open".to_string(),
            is_pinned: false,
            metadata: json!({}),
        })
        .await?;
    let updated = service
        .update_post(
            &blackboard_context("update-post-2", Some(1)),
            created.post.id.as_str(),
            &PublicUpdateBlackboardPostFields {
                title: Some("Updated".to_string()),
                status: Some("archived".to_string()),
                ..PublicUpdateBlackboardPostFields::default()
            },
        )
        .await?;
    assert_eq!(updated.post.title, "Updated");
    assert_eq!(updated.post.status, "archived");

    let viewer_context = PublicWorkspaceBlackboardContext {
        user_id: "viewer-1".to_string(),
        ..blackboard_context("viewer-write", Some(2))
    };
    assert!(
        service
            .set_post_pinned(&viewer_context, created.post.id.as_str(), true)
            .await
            .is_err()
    );

    let deleted = service
        .delete_post(
            &blackboard_context("delete-post-2", Some(2)),
            created.post.id.as_str(),
        )
        .await?;
    assert_eq!(deleted, json!({"success": true}));
    assert!(
        service
            .get_post(&blackboard_context("read", None), created.post.id.as_str())
            .await
            .is_err()
    );
    assert_eq!(authority_revision(&db).await?, 3);
    Ok(())
}

async fn seeded_blackboard_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_blackboard_posts (post_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, author_actor_id TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, is_pinned INTEGER NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT)",
        "CREATE TABLE workspace_blackboard_replies (reply_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, post_id TEXT NOT NULL, author_actor_id TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT)",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer')",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

fn blackboard_context(
    idempotency_key: &str,
    expected_revision: Option<u64>,
) -> PublicWorkspaceBlackboardContext {
    PublicWorkspaceBlackboardContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        user_id: "user-1".to_string(),
        expected_revision,
        idempotency_key: (idempotency_key != "read").then(|| idempotency_key.to_string()),
    }
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing count")?
        .get_i64("value")?
        .ok_or("missing count value")?)
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
        ))
        .await?
        .first()
        .ok_or("missing authority")?
        .get_i64("value")?
        .ok_or("missing revision")?)
}
