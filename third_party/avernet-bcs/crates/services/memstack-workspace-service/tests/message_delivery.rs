use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    PublicWorkspaceMessageDeliveryService, PublicWorkspaceMessageErrorKind,
};

#[tokio::test]
async fn delivery_service_projects_claims_and_preserves_store_fencing() -> Result<(), Box<dyn Error>>
{
    let db = seeded_db().await?;
    let service = PublicWorkspaceMessageDeliveryService::new(&db, DbSqlFlavor::Sqlite);

    let first = service.claim_deliveries("worker-1", 100, 200, 10).await?;

    assert_eq!(first.len(), 1);
    assert_eq!(first[0].tenant_id, "tenant-1");
    assert_eq!(first[0].project_id, "project-1");
    assert_eq!(first[0].workspace_id, "workspace-1");
    assert_eq!(first[0].group_id, "group-1");
    assert_eq!(first[0].session_id, "session-1");
    assert_eq!(first[0].correlation_id, "correlation-1");
    assert_eq!(first[0].message.id, "message-1");
    assert_eq!(first[0].message.content, "deliver this");
    assert_eq!(first[0].message.created_at, "1970-01-01T00:00:01.000Z");
    assert_eq!(first[0].target.agent_id, "agent-1");
    assert_eq!(first[0].target.bot_uuid, "bot-1");
    assert_eq!(first[0].target.display_name.as_deref(), Some("Agent One"));
    assert_eq!(first[0].attempt_count, 1);
    assert_eq!(first[0].worker_id, "worker-1");
    assert_eq!(first[0].lease_expires_at_ms, 200);

    let failure = service
        .fail_delivery(&first[0], 300, "provider unavailable")
        .await?;
    assert_eq!(failure.attempt_count, 1);
    assert!(!failure.dead_lettered);

    let second = service.claim_deliveries("worker-2", 300, 400, 10).await?;
    assert_eq!(second.len(), 1);
    assert_eq!(second[0].attempt_count, 2);
    assert_eq!(second[0].worker_id, "worker-2");
    service.complete_delivery(&second[0], 350).await?;

    let stale_error = match service.complete_delivery(&second[0], 351).await {
        Ok(()) => return Err("a completed lease must not be reusable".into()),
        Err(error) => error,
    };
    assert_eq!(
        stale_error.kind(),
        PublicWorkspaceMessageErrorKind::Unavailable
    );
    Ok(())
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE bcs_messages (message_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, session_id TEXT NOT NULL, env TEXT NOT NULL, sender_id TEXT NOT NULL, sender_type TEXT NOT NULL, content TEXT NOT NULL, mentions_json TEXT NOT NULL, parent_message_id TEXT, metadata_json TEXT NOT NULL, created_at INTEGER NOT NULL, workspace_id TEXT NOT NULL)",
        "CREATE TABLE workspace_message_correlations (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, bcs_session_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, correlation_id TEXT NOT NULL)",
        "CREATE TABLE workspace_message_delivery_outbox (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, group_id TEXT NOT NULL, target_order INTEGER NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, display_name TEXT, status TEXT NOT NULL, attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL, next_attempt_at_ms INTEGER NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, last_error TEXT, delivered_at_ms INTEGER, created_at_ms INTEGER NOT NULL, PRIMARY KEY(workspace_id, bcs_message_id, agent_id))",
        "INSERT INTO bcs_messages (message_id, group_id, session_id, env, sender_id, sender_type, content, mentions_json, parent_message_id, metadata_json, created_at, workspace_id) VALUES ('message-1', 'group-1', 'session-1', 'memstack', 'user-1', 'human', '\"deliver this\"', '[\"agent-1\"]', NULL, '{\"surface\":\"workspace-chat\"}', 1000, 'workspace-1')",
        "INSERT INTO workspace_message_correlations (tenant_id, project_id, workspace_id, bcs_session_id, bcs_message_id, correlation_id) VALUES ('tenant-1', 'project-1', 'workspace-1', 'session-1', 'message-1', 'correlation-1')",
        "INSERT INTO workspace_message_delivery_outbox (tenant_id, project_id, workspace_id, bcs_message_id, group_id, target_order, agent_id, bot_uuid, display_name, status, attempt_count, max_attempts, next_attempt_at_ms, created_at_ms) VALUES ('tenant-1', 'project-1', 'workspace-1', 'message-1', 'group-1', 0, 'agent-1', 'bot-1', 'Agent One', 'pending', 0, 8, 0, 1000)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}
