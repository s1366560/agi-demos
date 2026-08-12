use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_store::{
    WorkspaceMessageScope, WorkspaceMessageStore, WorkspaceMessageStoreError, WorkspaceMessageWrite,
};

#[tokio::test]
async fn persisted_delivery_target_does_not_drift_when_binding_changes()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);
    let write = message_write();

    let created = store.create(&write).await?;
    assert!(!created.replayed);
    assert_eq!(created.delivery_targets.len(), 1);
    assert_eq!(created.delivery_targets[0].agent_id, "agent-active");
    assert_eq!(created.delivery_targets[0].bot_uuid, "bot-original");
    assert!(
        db.execute(DbStatement::new(
            "UPDATE workspace_message_delivery_outbox SET bot_uuid = 'bot-overwritten'"
        ))
        .await
        .is_err()
    );

    db.execute(DbStatement::new(
        "UPDATE workspace_agent_bindings SET bot_uuid = 'bot-rebound', display_name = 'Rebound', is_active = 0 WHERE agent_id = 'agent-active'",
    ))
    .await?;
    let replayed = store.create(&write).await?;

    assert!(replayed.replayed);
    assert_eq!(replayed.delivery_targets, created.delivery_targets);
    assert_eq!(replayed.delivery_targets[0].bot_uuid, "bot-original");
    assert_eq!(
        replayed.delivery_targets[0].display_name.as_deref(),
        Some("Original")
    );
    let current = store
        .resolve_mentions(&scope(), &["agent-active".to_string()])
        .await?;
    assert!(current.delivery_targets.is_empty());
    Ok(())
}

#[tokio::test]
async fn delivery_claim_recovers_expired_and_explicitly_failed_leases() -> Result<(), Box<dyn Error>>
{
    let db = seeded_db().await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);
    let created = store.create(&message_write()).await?;
    assert_eq!(created.delivery_targets.len(), 1);

    let first = store.claim_deliveries("worker-1", 100, 200, 10).await?;
    assert_eq!(first.len(), 1);
    assert_eq!(first[0].attempt_count, 1);
    assert_eq!(first[0].tenant_id, "tenant-1");
    assert_eq!(first[0].project_id, "project-1");
    assert_eq!(first[0].group_id, "group-1");
    assert_eq!(first[0].session_id, "session-delivery-1");
    assert_eq!(first[0].correlation_id, "correlation-delivery-1");
    assert_eq!(first[0].message.id, "message-delivery-1");
    assert_eq!(first[0].target.bot_uuid, "bot-original");
    assert!(
        store
            .claim_deliveries("worker-2", 150, 250, 10)
            .await?
            .is_empty()
    );

    let failed = store
        .fail_delivery(&first[0], 300, "provider unavailable")
        .await?;
    assert!(!failed.dead_lettered);
    assert_eq!(failed.attempt_count, 1);
    assert!(
        store
            .claim_deliveries("worker-2", 299, 399, 10)
            .await?
            .is_empty()
    );

    let second = store.claim_deliveries("worker-2", 300, 400, 10).await?;
    assert_eq!(second.len(), 1);
    assert_eq!(second[0].attempt_count, 2);
    assert!(
        store
            .claim_deliveries("worker-3", 399, 499, 10)
            .await?
            .is_empty()
    );

    let recovered = store.claim_deliveries("worker-3", 400, 500, 10).await?;
    assert_eq!(recovered.len(), 1);
    assert_eq!(recovered[0].attempt_count, 3);
    assert!(matches!(
        store.complete_delivery(&second[0], 450).await,
        Err(WorkspaceMessageStoreError::DeliveryLeaseLost)
    ));
    store.complete_delivery(&recovered[0], 500).await?;
    assert!(
        store
            .claim_deliveries("worker-4", 1_000, 1_100, 10)
            .await?
            .is_empty()
    );

    let replayed = store.create(&message_write()).await?;
    assert!(replayed.replayed);
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_message_delivery_outbox"
        )
        .await?,
        "delivered"
    );
    Ok(())
}

#[tokio::test]
async fn delivery_snapshot_failure_rolls_back_message_and_event() -> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER reject_delivery_snapshot BEFORE INSERT ON workspace_message_delivery_outbox BEGIN SELECT RAISE(ABORT, 'injected delivery snapshot failure'); END",
    ))
    .await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);

    assert!(matches!(
        store.create(&message_write()).await,
        Err(WorkspaceMessageStoreError::Database(_))
    ));
    for table in [
        "bcs_group_sessions",
        "bcs_messages",
        "workspace_outbox",
        "workspace_message_correlations",
        "workspace_message_delivery_outbox",
    ] {
        assert_eq!(table_count(&db, table).await?, 0, "table {table}");
    }
    Ok(())
}

#[tokio::test]
async fn expired_last_attempt_is_dead_lettered_instead_of_remaining_leased()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);
    store.create(&message_write()).await?;
    db.execute(DbStatement::new(
        "UPDATE workspace_message_delivery_outbox SET max_attempts = 1",
    ))
    .await?;
    let first = store.claim_deliveries("worker-1", 100, 200, 10).await?;
    assert_eq!(first.len(), 1);
    assert_eq!(first[0].attempt_count, 1);

    assert!(
        store
            .claim_deliveries("worker-2", 200, 300, 10)
            .await?
            .is_empty()
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT status AS value FROM workspace_message_delivery_outbox"
        )
        .await?,
        "dead_letter"
    );
    Ok(())
}

fn scope() -> WorkspaceMessageScope {
    WorkspaceMessageScope {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
    }
}

fn message_write() -> WorkspaceMessageWrite {
    WorkspaceMessageWrite {
        scope: scope(),
        message_id: "message-delivery-1".to_string(),
        session_id: "session-delivery-1".to_string(),
        correlation_id: "correlation-delivery-1".to_string(),
        outbox_id: "outbox-delivery-1".to_string(),
        sender_id: "user-owner".to_string(),
        sender_name: "owner@example.com".to_string(),
        sender_is_superuser: false,
        content_json: "\"deliver this\"".to_string(),
        mentions_json: "[\"agent-active\"]".to_string(),
        parent_message_id: None,
        metadata_json: "{\"surface\":\"workspace-chat\"}".to_string(),
        idempotency_key: "message-delivery-key-1".to_string(),
        request_hash: "a".repeat(64),
        created_at_ms: 1_000,
        event_payload_json: "{\"message_id\":\"message-delivery-1\"}".to_string(),
        event_metadata_json: "{\"surface_owner\":\"workspace-chat\"}".to_string(),
    }
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL, deleted_at TEXT, UNIQUE(tenant_id, project_id, workspace_id))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_principal_identities (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, email TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY(tenant_id, project_id, workspace_id, user_id))",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, display_name TEXT, is_active INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(workspace_id, agent_id))",
        "CREATE TABLE bcs_group_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, group_id TEXT NOT NULL, env TEXT NOT NULL, status TEXT NOT NULL, session_kind TEXT NOT NULL, caller_id TEXT, caller_principal TEXT, created_by TEXT, participants TEXT NOT NULL, current_msg_seq INTEGER NOT NULL DEFAULT 0, meta TEXT, UNIQUE(env, session_id))",
        "CREATE TABLE bcs_messages (message_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, session_id TEXT NOT NULL, session_seq INTEGER NOT NULL, env TEXT NOT NULL, sender_id TEXT NOT NULL, sender_type TEXT NOT NULL, message_type TEXT NOT NULL, content TEXT NOT NULL, client_msg_id TEXT, status TEXT NOT NULL, created_at INTEGER NOT NULL, run_id TEXT NOT NULL, workspace_id TEXT, mentions_json TEXT NOT NULL, parent_message_id TEXT, metadata_json TEXT NOT NULL, source_hash TEXT, UNIQUE(session_id, session_seq))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_message_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, legacy_message_id TEXT NOT NULL, conversation_id TEXT NOT NULL, bcs_session_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, message_kind TEXT NOT NULL, is_terminal INTEGER NOT NULL, idempotency_key TEXT, request_hash TEXT, event_outbox_id TEXT, UNIQUE(workspace_id, legacy_message_id), UNIQUE(bcs_session_id, bcs_message_id), UNIQUE(workspace_id, idempotency_key))",
        "CREATE TABLE workspace_message_delivery_outbox (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, group_id TEXT NOT NULL, target_order INTEGER NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, display_name TEXT, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 8, next_attempt_at_ms INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_expires_at_ms INTEGER, last_error TEXT, delivered_at_ms INTEGER, created_at_ms INTEGER NOT NULL, PRIMARY KEY(workspace_id, bcs_message_id, agent_id), UNIQUE(workspace_id, bcs_message_id,target_order), FOREIGN KEY(tenant_id, project_id, workspace_id) REFERENCES workspace_profiles(tenant_id, project_id, workspace_id) ON DELETE CASCADE, FOREIGN KEY(bcs_message_id) REFERENCES bcs_messages(message_id) ON DELETE CASCADE, CHECK(status IN ('pending', 'delivering', 'delivered', 'dead_letter')), CHECK(attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts), CHECK(target_order >= 0 AND next_attempt_at_ms >= 0 AND created_at_ms >= 0), CHECK(lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0), CHECK(delivered_at_ms IS NULL OR delivered_at_ms >= 0), CHECK((status = 'delivering' AND lease_owner IS NOT NULL AND lease_expires_at_ms IS NOT NULL) OR (status <> 'delivering' AND lease_owner IS NULL AND lease_expires_at_ms IS NULL)), CHECK((status = 'delivered' AND delivered_at_ms IS NOT NULL) OR (status <> 'delivered' AND delivered_at_ms IS NULL)))",
        "CREATE TRIGGER prevent_workspace_message_delivery_snapshot_update BEFORE UPDATE OF tenant_id, project_id, workspace_id, bcs_message_id, group_id, target_order, agent_id, bot_uuid, display_name, created_at_ms ON workspace_message_delivery_outbox BEGIN SELECT RAISE(ABORT, 'Workspace message delivery snapshot is immutable'); END",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    for dml in [
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1')",
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, role) VALUES ('member-owner', 'tenant-1', 'project-1', 'workspace-1', 'user-owner', 'owner')",
        "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, email, is_active) VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-owner', 'owner@example.com', 1)",
        "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, agent_id, bot_uuid, display_name, is_active, created_at) VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', 'agent-active', 'bot-original', 'Original', 1, '2026-01-01T00:00:00Z')",
    ] {
        db.execute(DbStatement::new(dml)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "bcs_group_sessions" => "SELECT COUNT(*) AS value FROM bcs_group_sessions",
        "bcs_messages" => "SELECT COUNT(*) AS value FROM bcs_messages",
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        "workspace_message_correlations" => {
            "SELECT COUNT(*) AS value FROM workspace_message_correlations"
        }
        "workspace_message_delivery_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_message_delivery_outbox"
        }
        _ => return Err(std::io::Error::other("unsupported table").into()),
    };
    scalar_i64(db, sql).await
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows
        .first()
        .ok_or_else(|| std::io::Error::other("query returned no rows"))?;
    Ok(row
        .get_i64("value")?
        .ok_or_else(|| std::io::Error::other("value is NULL"))?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    let row = rows
        .first()
        .ok_or_else(|| std::io::Error::other("query returned no rows"))?;
    Ok(row
        .get_string("value")?
        .ok_or_else(|| std::io::Error::other("value is NULL"))?)
}
