use std::error::Error;
use std::sync::{Arc, Mutex};

use anyhow::{Result, anyhow};
use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_core::outbox::{
    WorkspaceEventPublisher, WorkspaceOutboxConfig, WorkspaceOutboxDispatcher, WorkspaceOutboxEvent,
};

const USER_ID: &str = "user-context-outbox-pg-contract";
const OUTBOX_ID: &str = "context-outbox-pg-contract";

struct RecordingPublisher {
    published: Arc<Mutex<Vec<WorkspaceOutboxEvent>>>,
}

#[async_trait]
impl WorkspaceEventPublisher for RecordingPublisher {
    async fn publish(&self, event: &WorkspaceOutboxEvent) -> Result<String> {
        self.published
            .lock()
            .map_err(|error| anyhow!("record published Context event: {error}"))?
            .push(event.clone());
        Ok("1700000000000-7".to_string())
    }
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_dispatcher_claims_and_finalizes_context_outbox() -> Result<(), Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    let db: Arc<dyn DbPlugin> = Arc::new(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?);
    cleanup(db.as_ref()).await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_context_outbox (outbox_id, user_id, tenant_id, project_id, event_type, stream_name, event_sequence, payload_json, metadata_json, actor_api_key_id, idempotency_key) VALUES ('context-outbox-pg-contract', 'user-context-outbox-pg-contract', 'tenant-context-outbox-pg', 'project-context-outbox-pg', 'workspace_context.switched', 'workspace-context:user-context-outbox-pg-contract', 3, '{\"tenant_id\":\"tenant-context-outbox-pg\",\"project_id\":\"project-context-outbox-pg\",\"revision\":3}'::jsonb, '{\"request_hash\":\"contract\"}'::jsonb, 'api-key-context-outbox-pg', 'context-outbox-pg-key')",
    ))
    .await?;
    let published = Arc::new(Mutex::new(Vec::new()));
    let dispatcher = WorkspaceOutboxDispatcher::new(
        db.clone(),
        RecordingPublisher {
            published: published.clone(),
        },
        WorkspaceOutboxConfig {
            lease_owner: "context-dispatcher-pg-contract".to_string(),
            batch_size: 1,
            ..WorkspaceOutboxConfig::default()
        },
    )?;

    let outcome = dispatcher.dispatch_once().await?;

    assert_eq!(outcome.claimed, 1);
    assert_eq!(outcome.dispatched, 1);
    {
        let events = published
            .lock()
            .map_err(|error| anyhow!("inspect published Context event: {error}"))?;
        let event = events.first().ok_or("Context event was not published")?;
        assert_eq!(event.user_id.as_deref(), Some(USER_ID));
        assert_eq!(event.workspace_id, None);
    }

    let rows = db
        .query(DbStatement::with_params(
            "SELECT status, attempt_count, lease_owner, lease_expires_at, dispatched_at, metadata_json ->> 'redis_stream_id' AS redis_stream_id FROM workspace_context_outbox WHERE outbox_id = $1",
            vec![OUTBOX_ID.into()],
        ))
        .await?;
    let row = rows.first().ok_or("Context outbox row was not finalized")?;
    assert_eq!(row.get_string("status")?.as_deref(), Some("dispatched"));
    assert_eq!(row.get_i64("attempt_count")?, Some(1));
    assert_eq!(row.get_string("lease_owner")?, None);
    assert_eq!(row.get_string("lease_expires_at")?, None);
    assert!(row.get_string("dispatched_at")?.is_some());
    assert_eq!(
        row.get_string("redis_stream_id")?.as_deref(),
        Some("1700000000000-7")
    );
    cleanup(db.as_ref()).await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_context_outbox WHERE user_id = ")
            .bind(USER_ID)
            .build(),
    )
    .await?;
    Ok(())
}
