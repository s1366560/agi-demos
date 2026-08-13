use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_store::{
    WorkspaceMessageScope, WorkspaceMessageStore, WorkspaceMessageStoreError, WorkspaceMessageWrite,
};

const MESSAGE_EVENT_SEQUENCE_BASE: i64 = 1_i64 << 62;

#[tokio::test]
async fn message_append_is_atomic_replayable_and_oldest_first() -> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);
    let first_write = write("message-1", "message-key-1", 'a', "[]", 1_000);

    let first = store.create(&first_write).await?;
    assert!(!first.replayed);
    assert_eq!(first.group_id, "group-1");
    assert_eq!(first.message.group_id, "group-1");
    assert_eq!(first.message.content, "message one");
    assert_eq!(first.message.created_at_ms, 1_000);
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT current_msg_seq AS value FROM bcs_group_sessions"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT event_sequence AS value FROM workspace_outbox").await?,
        MESSAGE_EVENT_SEQUENCE_BASE + 1
    );

    let replay = store.create(&first_write).await?;
    assert!(replay.replayed);
    assert_eq!(replay.message, first.message);
    assert_eq!(table_count(&db, "bcs_messages").await?, 1);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 1);
    assert_eq!(table_count(&db, "workspace_message_correlations").await?, 1);

    let mut conflicting = first_write.clone();
    conflicting.request_hash = "b".repeat(64);
    assert!(matches!(
        store.create(&conflicting).await,
        Err(WorkspaceMessageStoreError::IdempotencyConflict)
    ));

    let second_write = write(
        "message-2",
        "message-key-2",
        'c',
        "[\"agent-inactive\"]",
        2_000,
    );
    let second = store.create(&second_write).await?;
    assert!(!second.replayed);
    assert_eq!(second.message.mentions, vec!["agent-inactive"]);
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT current_msg_seq AS value FROM bcs_group_sessions"
        )
        .await?,
        2
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT MAX(event_sequence) AS value FROM workspace_outbox"
        )
        .await?,
        MESSAGE_EVENT_SEQUENCE_BASE + 2
    );

    let listed = store.list(&scope(), "user-owner", false, 50, None).await?;
    assert_eq!(
        listed
            .iter()
            .map(|message| message.id.as_str())
            .collect::<Vec<_>>(),
        vec!["message-1", "message-2"]
    );
    let before_second = store
        .list(&scope(), "user-owner", false, 50, Some("message-2"))
        .await?;
    assert_eq!(before_second.len(), 1);
    assert_eq!(before_second[0].id, "message-1");
    let invalid_before = store
        .list(&scope(), "user-owner", false, 50, Some("missing"))
        .await?;
    assert_eq!(invalid_before.len(), 2);

    let mentioned = store
        .mentions(&scope(), "user-owner", false, "agent-inactive", 50)
        .await?;
    assert_eq!(mentioned.len(), 1);
    assert_eq!(mentioned[0].id, "message-2");
    Ok(())
}

#[tokio::test]
async fn message_sequence_advances_past_task_session_events() -> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);

    store
        .create(&write("message-1", "message-key-1", 'a', "[]", 1_000))
        .await?;
    store
        .create(&write("message-2", "message-key-2", 'b', "[]", 2_000))
        .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Sqlite)
            .push_static(
                "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, \
                 aggregate_type, aggregate_id, event_type, stream_name, event_sequence, \
                 payload_json, metadata_json, correlation_id, idempotency_key) VALUES (",
            )
            .bind("task-session-outbox")
            .push_static(", 'tenant-1', 'project-1', 'workspace-1', 'workspace_message', ")
            .bind("task-session-message")
            .push_static(
                ", 'workspace_message_created', 'workspace:workspace-1:events', ",
            )
            .bind(MESSAGE_EVENT_SEQUENCE_BASE + 3)
            .push_static(", '{}', '{}', 'task-session-correlation', 'task-session-key')")
            .build(),
    )
    .await?;

    let third = store
        .create(&write("message-3", "message-key-3", 'c', "[]", 3_000))
        .await?;

    assert!(!third.replayed);
    assert_eq!(third.message.id, "message-3");
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT MAX(event_sequence) AS value FROM workspace_outbox"
        )
        .await?,
        MESSAGE_EVENT_SEQUENCE_BASE + 4
    );
    Ok(())
}

#[tokio::test]
async fn invalid_mention_rolls_back_every_message_write() -> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);
    let invalid = write(
        "message-invalid",
        "message-key-invalid",
        'd',
        "[\"outside-roster\"]",
        3_000,
    );

    assert!(matches!(
        store.create(&invalid).await,
        Err(WorkspaceMessageStoreError::InvalidMention)
    ));
    for table in [
        "bcs_group_sessions",
        "bcs_messages",
        "workspace_outbox",
        "workspace_message_correlations",
    ] {
        assert_eq!(table_count(&db, table).await?, 0, "table {table}");
    }
    Ok(())
}

#[tokio::test]
async fn mention_resolution_keeps_inactive_agents_but_does_not_deliver_to_them()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);

    let explicit = store
        .resolve_mentions(
            &scope(),
            &[
                "agent-inactive".to_string(),
                "member-viewer".to_string(),
                "agent-active".to_string(),
                "agent-active".to_string(),
            ],
        )
        .await?;
    assert_eq!(
        explicit.mention_ids,
        vec!["agent-inactive", "member-viewer", "agent-active"]
    );
    assert_eq!(explicit.delivery_targets.len(), 1);
    assert_eq!(explicit.delivery_targets[0].agent_id, "agent-active");
    Ok(())
}

#[tokio::test]
async fn all_mentions_first_hundred_agents_and_delivers_only_active_subset()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db_without_agents().await?;
    for index in 0..102 {
        db.execute(
            DbStatementBuilder::new(DbSqlFlavor::Sqlite)
                .push_static(
                    "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, agent_id, bot_uuid, display_name, is_active, created_at) VALUES (",
                )
                .bind(format!("binding-{index:03}"))
                .push_static(", 'tenant-1', 'project-1', 'workspace-1', ")
                .bind(format!("agent-{index:03}"))
                .push_static(", ")
                .bind(format!("bot-{index:03}"))
                .push_static(", NULL, ")
                .bind(index % 2 == 1)
                .push_static(", '2026-01-01T00:00:00Z')")
                .build(),
        )
        .await?;
    }
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Sqlite);

    let resolved = store
        .resolve_mentions(&scope(), &["all".to_string()])
        .await?;

    assert_eq!(resolved.mention_ids.len(), 100);
    assert_eq!(
        resolved.mention_ids.first().map(String::as_str),
        Some("agent-000")
    );
    assert_eq!(
        resolved.mention_ids.last().map(String::as_str),
        Some("agent-099")
    );
    assert_eq!(resolved.delivery_targets.len(), 50);
    assert!(
        resolved
            .delivery_targets
            .iter()
            .all(|target| { target.agent_id.ends_with(['1', '3', '5', '7', '9']) })
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

fn write(
    message_id: &str,
    idempotency_key: &str,
    hash_char: char,
    mentions_json: &str,
    created_at_ms: i64,
) -> WorkspaceMessageWrite {
    WorkspaceMessageWrite {
        scope: scope(),
        message_id: message_id.to_string(),
        session_id: "session-1".to_string(),
        correlation_id: format!("correlation-{message_id}"),
        outbox_id: format!("outbox-{message_id}"),
        sender_id: "user-owner".to_string(),
        sender_name: "owner@example.com".to_string(),
        sender_is_superuser: false,
        content_json: if message_id == "message-1" {
            "\"message one\"".to_string()
        } else {
            format!("\"{message_id}\"")
        },
        mentions_json: mentions_json.to_string(),
        parent_message_id: None,
        metadata_json: "{\"surface\":\"workspace-chat\"}".to_string(),
        idempotency_key: idempotency_key.to_string(),
        request_hash: hash_char.to_string().repeat(64),
        created_at_ms,
        event_payload_json: format!("{{\"message_id\":\"{message_id}\"}}"),
        event_metadata_json: "{\"surface_owner\":\"workspace-chat\"}".to_string(),
    }
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = seeded_db_without_agents().await?;
    for (binding_id, agent_id, is_active) in [
        ("binding-1", "agent-active", true),
        ("binding-2", "agent-inactive", false),
    ] {
        db.execute(
            DbStatementBuilder::new(DbSqlFlavor::Sqlite)
                .push_static(
                    "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, agent_id, bot_uuid, display_name, is_active, created_at) VALUES (",
                )
                .bind(binding_id)
                .push_static(", 'tenant-1', 'project-1', 'workspace-1', ")
                .bind(agent_id)
                .push_static(", ")
                .bind(format!("bot-{agent_id}"))
                .push_static(", NULL, ")
                .bind(is_active)
                .push_static(", '2026-01-01T00:00:00Z')")
                .build(),
        )
        .await?;
    }
    Ok(db)
}

async fn seeded_db_without_agents() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
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
        "CREATE TABLE workspace_message_delivery_outbox (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, group_id TEXT NOT NULL, target_order INTEGER NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, display_name TEXT, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 8, next_attempt_at_ms INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_expires_at_ms INTEGER, last_error TEXT, delivered_at_ms INTEGER, created_at_ms INTEGER NOT NULL, PRIMARY KEY(workspace_id, bcs_message_id, agent_id), UNIQUE(workspace_id, bcs_message_id, target_order), FOREIGN KEY(tenant_id, project_id, workspace_id) REFERENCES workspace_profiles(tenant_id, project_id, workspace_id) ON DELETE CASCADE, FOREIGN KEY(bcs_message_id) REFERENCES bcs_messages(message_id) ON DELETE CASCADE, CHECK(status IN ('pending', 'delivering', 'delivered', 'dead_letter')), CHECK(attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts), CHECK(target_order >= 0 AND next_attempt_at_ms >= 0 AND created_at_ms >= 0), CHECK(lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0), CHECK(delivered_at_ms IS NULL OR delivered_at_ms >= 0), CHECK((status = 'delivering' AND lease_owner IS NOT NULL AND lease_expires_at_ms IS NOT NULL) OR (status <> 'delivering' AND lease_owner IS NULL AND lease_expires_at_ms IS NULL)), CHECK((status = 'delivered' AND delivered_at_ms IS NOT NULL) OR (status <> 'delivered' AND delivered_at_ms IS NULL)))",
        "CREATE TRIGGER prevent_workspace_message_delivery_snapshot_update BEFORE UPDATE OF tenant_id, project_id, workspace_id, bcs_message_id, group_id, target_order, agent_id, bot_uuid, display_name, created_at_ms ON workspace_message_delivery_outbox BEGIN SELECT RAISE(ABORT, 'Workspace message delivery snapshot is immutable'); END",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    db.execute(DbStatement::new(
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1')",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, role) VALUES ('member-owner', 'tenant-1', 'project-1', 'workspace-1', 'user-owner', 'owner'), ('member-viewer', 'tenant-1', 'project-1', 'workspace-1', 'member-viewer', 'viewer')",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, email, is_active) VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-owner', 'owner@example.com', 1)",
    ))
    .await?;
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
