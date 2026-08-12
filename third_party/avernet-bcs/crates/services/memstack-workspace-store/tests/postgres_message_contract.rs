use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_store::{
    WorkspaceMessageScope, WorkspaceMessageStore, WorkspaceMessageStoreError, WorkspaceMessageWrite,
};

const WORKSPACE_ID: &str = "workspace-store-pg-message";
const SESSION_ID: &str = "session-store-pg-message";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_message_append_replay_mentions_and_rollback_contract()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed(&db).await?;
    let store = WorkspaceMessageStore::new(&db, DbSqlFlavor::Postgres);
    let write = message_write("message-store-pg-1", "message-store-pg-key-1", 'e');

    let created = store.create(&write).await?;
    assert!(!created.replayed);
    assert_eq!(created.group_id, "group-store-pg-message");
    assert_eq!(created.message.group_id, "group-store-pg-message");
    assert_eq!(created.message.mentions, vec!["agent-store-pg-inactive"]);
    assert_eq!(created.delivery_targets.len(), 1);
    assert_eq!(
        created.delivery_targets[0].bot_uuid,
        "bot-store-pg-inactive"
    );
    db.execute(DbStatement::new(
        "UPDATE workspace_agent_bindings SET bot_uuid = 'bot-store-pg-rebound', is_active = FALSE WHERE binding_id = 'binding-store-pg-message'",
    ))
    .await?;
    let replayed = store.create(&write).await?;
    assert!(replayed.replayed);
    assert_eq!(replayed.message, created.message);
    assert_eq!(replayed.delivery_targets, created.delivery_targets);

    let first_claim = store
        .claim_deliveries("pg-message-worker-1", 100, 200, 10)
        .await?;
    assert_eq!(first_claim.len(), 1);
    assert_eq!(first_claim[0].attempt_count, 1);
    assert_eq!(first_claim[0].tenant_id, "tenant-store-contract");
    assert_eq!(first_claim[0].project_id, "project-store-contract");
    assert_eq!(first_claim[0].group_id, "group-store-pg-message");
    assert_eq!(first_claim[0].session_id, SESSION_ID);
    assert_eq!(
        first_claim[0].correlation_id,
        "correlation-message-store-pg-1"
    );
    let failure = store
        .fail_delivery(&first_claim[0], 300, "provider unavailable")
        .await?;
    assert!(!failure.dead_lettered);
    let second_claim = store
        .claim_deliveries("pg-message-worker-2", 300, 400, 10)
        .await?;
    assert_eq!(second_claim.len(), 1);
    assert_eq!(second_claim[0].attempt_count, 2);
    store.complete_delivery(&second_claim[0], 350).await?;

    let mentioned = store
        .mentions(
            &scope(),
            "actor-store-pg-message",
            false,
            "agent-store-pg-inactive",
            50,
        )
        .await?;
    assert_eq!(mentioned.len(), 1);
    assert_eq!(mentioned[0].id, "message-store-pg-1");

    let mut conflicting = write.clone();
    conflicting.request_hash = "f".repeat(64);
    assert!(matches!(
        store.create(&conflicting).await,
        Err(WorkspaceMessageStoreError::IdempotencyConflict)
    ));
    let mut invalid = message_write("message-store-pg-invalid", "message-store-pg-key-2", '1');
    invalid.mentions_json = "[\"outside-roster\"]".to_string();
    assert!(matches!(
        store.create(&invalid).await,
        Err(WorkspaceMessageStoreError::InvalidMention)
    ));
    assert_eq!(scoped_count(&db, "bcs_messages").await?, 1);
    assert_eq!(scoped_count(&db, "workspace_outbox").await?, 1);
    assert_eq!(
        scoped_count(&db, "workspace_message_correlations").await?,
        1
    );
    assert_eq!(
        scoped_count(&db, "workspace_message_delivery_outbox").await?,
        1
    );

    cleanup(&db).await?;
    Ok(())
}

fn scope() -> WorkspaceMessageScope {
    WorkspaceMessageScope {
        tenant_id: "tenant-store-contract".to_string(),
        project_id: "project-store-contract".to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
    }
}

fn message_write(
    message_id: &str,
    idempotency_key: &str,
    hash_char: char,
) -> WorkspaceMessageWrite {
    WorkspaceMessageWrite {
        scope: scope(),
        message_id: message_id.to_string(),
        session_id: SESSION_ID.to_string(),
        correlation_id: format!("correlation-{message_id}"),
        outbox_id: format!("outbox-{message_id}"),
        sender_id: "actor-store-pg-message".to_string(),
        sender_name: "actor-store-pg-message@example.com".to_string(),
        sender_is_superuser: false,
        content_json: "\"PostgreSQL message contract\"".to_string(),
        mentions_json: "[\"agent-store-pg-inactive\"]".to_string(),
        parent_message_id: None,
        metadata_json: "{\"surface\":\"workspace-chat\"}".to_string(),
        idempotency_key: idempotency_key.to_string(),
        request_hash: hash_char.to_string().repeat(64),
        created_at_ms: 1_700_000_000_000,
        event_payload_json: format!("{{\"message_id\":\"{message_id}\"}}"),
        event_metadata_json: "{\"surface_owner\":\"workspace-chat\"}".to_string(),
    }
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn seed(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by) VALUES ('workspace-store-pg-message', 'tenant-store-contract', 'project-store-contract', 'group-store-pg-message', 'PostgreSQL Message Contract', 'actor-store-pg-message')",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-store-pg-message', 'tenant-store-contract', 'project-store-contract', 'workspace-store-pg-message', 'actor-store-pg-message', 'actor-store-pg-message', 'owner')",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, participant_actor_id, email, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-store-contract', 'project-store-contract', 'workspace-store-pg-message', 'actor-store-pg-message', 'actor-store-pg-message', 'actor-store-pg-message@example.com', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, workspace_id, agent_id, bot_uuid, participant_actor_id, is_active) VALUES ('binding-store-pg-message', 'tenant-store-contract', 'project-store-contract', 'workspace-store-pg-message', 'agent-store-pg-inactive', 'bot-store-pg-inactive', 'bot-store-pg-inactive', TRUE)",
    ))
    .await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for statement in [
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_messages WHERE session_id = ")
            .bind(SESSION_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_group_sessions WHERE session_id = ")
            .bind(SESSION_ID)
            .build(),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn scoped_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let statement = match table {
        "bcs_messages" => DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("SELECT COUNT(*) AS value FROM bcs_messages WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
        "workspace_outbox" => DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
        "workspace_message_correlations" => DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "SELECT COUNT(*) AS value FROM workspace_message_correlations WHERE workspace_id = ",
            )
            .bind(WORKSPACE_ID)
            .build(),
        "workspace_message_delivery_outbox" => DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "SELECT COUNT(*) AS value FROM workspace_message_delivery_outbox WHERE workspace_id = ",
            )
            .bind(WORKSPACE_ID)
            .build(),
        _ => return Err(std::io::Error::other("unsupported table").into()),
    };
    let rows = db.query(statement).await?;
    let row = rows
        .first()
        .ok_or_else(|| std::io::Error::other("query returned no rows"))?;
    Ok(row
        .get_i64("value")?
        .ok_or_else(|| std::io::Error::other("value is NULL"))?)
}
