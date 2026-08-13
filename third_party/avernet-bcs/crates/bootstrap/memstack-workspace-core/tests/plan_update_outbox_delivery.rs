use std::error::Error;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use async_trait::async_trait;
use bcs::RedisCacheConfig;
use bcs_db_api::{
    DbError, DbExecuteResult, DbHealth, DbPlugin, DbResult, DbSqlFlavor, DbStatement,
    DbTransactionStep, DbTransactionStepResult,
};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::outbox::{
    RedisWorkspaceEventPublisher, WorkspaceOutboxConfig, WorkspaceOutboxDispatcher,
};
use redis::streams::StreamReadReply;

const OUTBOX_ID: &str = "plan-update-outbox-delivery";
const STREAM_KEY: &str = "events:workspace:workspace-1:workspace_plan_updated";
const DEDUP_KEY: &str = "workspace-core:outbox:published:plan-update-outbox-delivery";

struct FailFirstFinalizeDb {
    inner: Arc<LocalSqliteDbPlugin>,
    fail_finalize: AtomicBool,
}

impl FailFirstFinalizeDb {
    fn new(inner: Arc<LocalSqliteDbPlugin>) -> Self {
        Self {
            inner,
            fail_finalize: AtomicBool::new(true),
        }
    }
}

#[async_trait]
impl DbPlugin for FailFirstFinalizeDb {
    async fn query(&self, statement: DbStatement) -> DbResult<Vec<bcs_db_api::DbRow>> {
        self.inner.query(statement).await
    }

    async fn execute(&self, statement: DbStatement) -> DbResult<DbExecuteResult> {
        if statement.sql().contains("status = 'dispatched'")
            && self.fail_finalize.swap(false, Ordering::SeqCst)
        {
            return Err(DbError::Backend(
                "injected crash after publish before outbox finalize".to_string(),
            ));
        }
        self.inner.execute(statement).await
    }

    async fn transaction(
        &self,
        steps: Vec<DbTransactionStep>,
    ) -> DbResult<Vec<DbTransactionStepResult>> {
        self.inner.transaction(steps).await
    }

    async fn health_check(&self) -> DbResult<DbHealth> {
        self.inner.health_check().await
    }
}

#[tokio::test]
#[ignore = "requires BCS_TEST_REDIS_PORT"]
async fn workspace_plan_updated_outbox_publishes_consumer_once_and_replays_after_crash()
-> Result<(), Box<dyn Error>> {
    let redis_port = std::env::var("BCS_TEST_REDIS_PORT")?.parse::<u16>()?;
    let redis_config = RedisCacheConfig::new("workspace-core-test", "plan-update")
        .with_host("127.0.0.1")
        .with_port(redis_port);
    let redis_client = redis::Client::open(redis_config.to_redis_url())?;
    let mut redis = redis_client.get_multiplexed_async_connection().await?;
    let _: i64 = redis::cmd("DEL")
        .arg(STREAM_KEY)
        .arg(DEDUP_KEY)
        .query_async(&mut redis)
        .await?;
    let publisher = RedisWorkspaceEventPublisher::connect(&redis_config).await?;
    let sqlite = seeded_db().await?;
    let crash_db = Arc::new(FailFirstFinalizeDb::new(sqlite.clone()));
    let crashing_dispatcher = WorkspaceOutboxDispatcher::new_with_sql_flavor(
        crash_db,
        publisher.clone(),
        dispatcher_config("plan-update-publisher-before-crash"),
        DbSqlFlavor::Sqlite,
    )?;

    let first_dispatch = crashing_dispatcher.dispatch_once().await;

    assert!(first_dispatch.is_err());
    assert_eq!(
        outbox_string(sqlite.as_ref(), "status").await?,
        "dispatching"
    );
    assert_eq!(
        outbox_i64(sqlite.as_ref(), "publication_attempt_count").await?,
        1
    );
    let stream_length: i64 = redis::cmd("XLEN")
        .arg(STREAM_KEY)
        .query_async(&mut redis)
        .await?;
    assert_eq!(stream_length, 1);

    sqlite
        .execute(DbStatement::new(
            "UPDATE workspace_outbox SET lease_expires_at = '1970-01-01T00:00:00.000Z' WHERE outbox_id = 'plan-update-outbox-delivery'",
        ))
        .await?;
    let replay_dispatcher = WorkspaceOutboxDispatcher::new_with_sql_flavor(
        sqlite.clone(),
        publisher,
        dispatcher_config("plan-update-publisher-after-crash"),
        DbSqlFlavor::Sqlite,
    )?;

    let replay = replay_dispatcher.dispatch_once().await?;

    assert_eq!(replay.claimed, 1);
    assert_eq!(replay.dispatched, 1);
    assert_eq!(
        outbox_string(sqlite.as_ref(), "status").await?,
        "dispatched"
    );
    assert_eq!(
        outbox_i64(sqlite.as_ref(), "publication_attempt_count").await?,
        2
    );
    let stream_length: i64 = redis::cmd("XLEN")
        .arg(STREAM_KEY)
        .query_async(&mut redis)
        .await?;
    assert_eq!(stream_length, 1);

    let consumer_group = "plan-update-consumer-group";
    let _: String = redis::cmd("XGROUP")
        .arg("CREATE")
        .arg(STREAM_KEY)
        .arg(consumer_group)
        .arg("0-0")
        .query_async(&mut redis)
        .await?;
    let consumed: StreamReadReply = redis::cmd("XREADGROUP")
        .arg("GROUP")
        .arg(consumer_group)
        .arg("consumer-1")
        .arg("COUNT")
        .arg(10)
        .arg("STREAMS")
        .arg(STREAM_KEY)
        .arg(">")
        .query_async(&mut redis)
        .await?;
    let entry = consumed
        .keys
        .first()
        .and_then(|stream| stream.ids.first())
        .ok_or("workspace_plan_updated was not consumed")?;
    let event_id: String = redis::from_redis_value(
        entry
            .map
            .get("event_id")
            .ok_or("event_id is missing from consumed event")?,
    )?;
    let event_type: String = redis::from_redis_value(
        entry
            .map
            .get("event_type")
            .ok_or("event_type is missing from consumed event")?,
    )?;
    let data: String = redis::from_redis_value(
        entry
            .map
            .get("data")
            .ok_or("data is missing from consumed event")?,
    )?;
    let data: serde_json::Value = serde_json::from_str(&data)?;
    assert_eq!(event_id, OUTBOX_ID);
    assert_eq!(event_type, "workspace_plan_updated");
    assert_eq!(data["payload"]["workspace_id"], "workspace-1");
    assert_eq!(data["payload"]["plan_id"], "plan-1");
    assert_eq!(data["payload"]["action"], "operator_iteration_loop_paused");
    let acknowledged: i64 = redis::cmd("XACK")
        .arg(STREAM_KEY)
        .arg(consumer_group)
        .arg(&entry.id)
        .query_async(&mut redis)
        .await?;
    assert_eq!(acknowledged, 1);
    let duplicate: StreamReadReply = redis::cmd("XREADGROUP")
        .arg("GROUP")
        .arg(consumer_group)
        .arg("consumer-2")
        .arg("COUNT")
        .arg(10)
        .arg("STREAMS")
        .arg(STREAM_KEY)
        .arg(">")
        .query_async(&mut redis)
        .await?;
    assert!(duplicate.keys.is_empty());

    let _: i64 = redis::cmd("DEL")
        .arg(STREAM_KEY)
        .arg(DEDUP_KEY)
        .query_async(&mut redis)
        .await?;
    Ok(())
}

fn dispatcher_config(lease_owner: &str) -> WorkspaceOutboxConfig {
    WorkspaceOutboxConfig {
        lease_owner: lease_owner.to_string(),
        batch_size: 1,
        lease_seconds: 30,
        ..WorkspaceOutboxConfig::default()
    }
}

async fn seeded_db() -> Result<Arc<LocalSqliteDbPlugin>, Box<dyn Error>> {
    let db = Arc::new(LocalSqliteDbPlugin::new()?);
    db.execute(DbStatement::new(
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 10, publication_attempt_count INTEGER NOT NULL DEFAULT 0, publication_max_attempts INTEGER NOT NULL DEFAULT 10, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, next_attempt_at TEXT, dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, correlation_id, idempotency_key, status, created_at, updated_at) VALUES ('plan-update-outbox-delivery', 'tenant-1', 'project-1', 'workspace-1', 'workspace_plan', 'plan-1', 'workspace_plan_updated', 'workspace:workspace-1:workspace_plan_updated', 2, '{\"workspace_id\":\"workspace-1\",\"plan_id\":\"plan-1\",\"revision\":2,\"action\":\"operator_iteration_loop_paused\"}', '{\"source\":\"memstack-workspace-core.plan\"}', 'plan-1', 'pause-1:workspace_plan_updated', 'pending', '2026-08-13T00:00:00.000Z', '2026-08-13T00:00:00.000Z')",
    ))
    .await?;
    Ok(db)
}

async fn outbox_string(db: &dyn DbPlugin, column: &str) -> Result<String, Box<dyn Error>> {
    let sql = match column {
        "status" => "SELECT status AS value FROM workspace_outbox",
        _ => return Err("unsupported string column".into()),
    };
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("outbox row is missing")?
        .get_string("value")?
        .ok_or("outbox string value is missing")?)
}

async fn outbox_i64(db: &dyn DbPlugin, column: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match column {
        "publication_attempt_count" => {
            "SELECT publication_attempt_count AS value FROM workspace_outbox"
        }
        _ => return Err("unsupported integer column".into()),
    };
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("outbox row is missing")?
        .get_i64("value")?
        .ok_or("outbox integer value is missing")?)
}
