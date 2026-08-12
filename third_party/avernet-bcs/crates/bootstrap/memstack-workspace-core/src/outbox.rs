//! Durable Workspace outbox delivery to the legacy Redis Streams envelope.

use std::cmp;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use anyhow::{Context, Result, anyhow, bail};
use async_trait::async_trait;
use bcs::RedisCacheConfig;
use bcs_db_api::{DbPlugin, DbRow, DbSqlFlavor, DbStatementBuilder};
use memstack_workspace_service_api::WORKSPACE_PLAN_RUNTIME_EVENT_TYPES;
use redis::aio::MultiplexedConnection;
use serde_json::{Map, Value, json};

const OUTBOX_SOURCE: &str = "memstack-workspace-core";
const EVENT_SCHEMA_VERSION: &str = "1.0";
const STREAM_PREFIX: &str = "events:";
const DEDUP_KEY_PREFIX: &str = "workspace-core:outbox:published:";
const MAX_ERROR_LENGTH: usize = 2_000;

/// Runtime controls for leasing and retrying Workspace outbox records.
#[derive(Debug, Clone)]
pub struct WorkspaceOutboxConfig {
    /// Stable process identity stored in each active lease.
    pub lease_owner: String,
    /// Maximum rows claimed by one polling pass.
    pub batch_size: u32,
    /// Duration before another dispatcher may reclaim an unfinished row.
    pub lease_seconds: u64,
    /// Delay between empty or failed polling passes.
    pub poll_interval: Duration,
    /// Initial deterministic retry delay.
    pub retry_base_seconds: u64,
    /// Maximum retry delay.
    pub retry_max_seconds: u64,
}

impl WorkspaceOutboxConfig {
    /// Validate dispatcher controls before starting the background loop.
    pub fn validate(&self) -> Result<()> {
        if self.lease_owner.trim().is_empty() {
            bail!("Workspace outbox lease owner must not be blank");
        }
        if self.batch_size == 0
            || self.lease_seconds == 0
            || self.poll_interval.is_zero()
            || self.retry_base_seconds == 0
            || self.retry_max_seconds == 0
        {
            bail!("Workspace outbox timing and batch controls must be positive");
        }
        if self.retry_base_seconds > self.retry_max_seconds {
            bail!("Workspace outbox retry base exceeds retry maximum");
        }
        Ok(())
    }
}

impl Default for WorkspaceOutboxConfig {
    fn default() -> Self {
        Self {
            lease_owner: format!("workspace-core:{}", std::process::id()),
            batch_size: 100,
            lease_seconds: 30,
            poll_interval: Duration::from_millis(250),
            retry_base_seconds: 1,
            retry_max_seconds: 300,
        }
    }
}

/// One claimed outbox record ready for compatibility delivery.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceOutboxEvent {
    pub outbox_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: Option<String>,
    pub user_id: Option<String>,
    pub event_type: String,
    pub stream_name: String,
    pub event_sequence: u64,
    pub payload: Value,
    pub metadata: Value,
    pub correlation_id: Option<String>,
    pub attempt_count: u32,
    pub max_attempts: u32,
    pub created_at: String,
    source: WorkspaceOutboxSource,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WorkspaceOutboxSource {
    Workspace,
    Context,
}

impl WorkspaceOutboxSource {
    const fn table_name(self) -> &'static str {
        match self {
            Self::Workspace => "workspace_outbox",
            Self::Context => "workspace_context_outbox",
        }
    }

    const fn other(self) -> Self {
        match self {
            Self::Workspace => Self::Context,
            Self::Context => Self::Workspace,
        }
    }
}

/// Result counters from one bounded polling pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DispatchBatchOutcome {
    pub claimed: usize,
    pub dispatched: usize,
    pub retry_scheduled: usize,
    pub dead_lettered: usize,
}

/// Publisher boundary used to keep database delivery contracts testable.
#[async_trait]
pub trait WorkspaceEventPublisher: Send + Sync + 'static {
    /// Publish once using the outbox identifier as the idempotency key.
    async fn publish(&self, event: &WorkspaceOutboxEvent) -> Result<String>;
}

/// Redis Streams publisher with an atomic deduplication marker and XADD.
#[derive(Clone)]
pub struct RedisWorkspaceEventPublisher {
    connection: MultiplexedConnection,
    max_stream_length: u64,
    dedup_ttl_seconds: u64,
}

impl RedisWorkspaceEventPublisher {
    /// Connect using the same resolved Redis configuration as Avernet BCS.
    pub async fn connect(config: &RedisCacheConfig) -> Result<Self> {
        let client = redis::Client::open(redis_connection_info(config)?)
            .context("create Workspace outbox Redis client")?;
        let timeout = Duration::from_secs(config.timeout_secs.max(1));
        let connection_config = redis::AsyncConnectionConfig::new()
            .set_connection_timeout(timeout)
            .set_response_timeout(timeout);
        let connection = client
            .get_multiplexed_async_connection_with_config(&connection_config)
            .await
            .context("connect Workspace outbox Redis publisher")?;
        Ok(Self {
            connection,
            max_stream_length: 10_000,
            dedup_ttl_seconds: 60 * 60 * 24 * 30,
        })
    }
}

#[async_trait]
impl WorkspaceEventPublisher for RedisWorkspaceEventPublisher {
    async fn publish(&self, event: &WorkspaceOutboxEvent) -> Result<String> {
        let stream_key = redis_stream_key(&event.stream_name)?;
        let dedup_key = format!("{DEDUP_KEY_PREFIX}{}", event.outbox_id);
        let routing_key = routing_key(&event.stream_name);
        let envelope = event_envelope(event);
        let event_json = serde_json::to_string(&envelope).context("serialize outbox envelope")?;
        let correlation_id = event.correlation_id.as_deref().unwrap_or_default();
        let script = redis::Script::new(
            r#"
local existing = redis.call('GET', KEYS[2])
if existing then
  return existing
end
local stream_id = redis.call(
  'XADD', KEYS[1], 'MAXLEN', '~', ARGV[2], '*',
  'event_id', ARGV[3],
  'event_type', ARGV[4],
  'schema_version', ARGV[5],
  'data', ARGV[6],
  'timestamp', ARGV[7],
  'routing_key', ARGV[8],
  'correlation_id', ARGV[9]
)
redis.call('SET', KEYS[2], stream_id, 'EX', ARGV[1])
return stream_id
"#,
        );
        let mut connection = self.connection.clone();
        script
            .key(stream_key)
            .key(dedup_key)
            .arg(self.dedup_ttl_seconds)
            .arg(self.max_stream_length)
            .arg(&event.outbox_id)
            .arg(&event.event_type)
            .arg(EVENT_SCHEMA_VERSION)
            .arg(event_json)
            .arg(&event.created_at)
            .arg(routing_key)
            .arg(correlation_id)
            .invoke_async(&mut connection)
            .await
            .context("publish Workspace outbox event")
    }
}

/// Poll, lease, publish, and finalize Workspace outbox rows.
pub struct WorkspaceOutboxDispatcher<PublisherT> {
    db: Arc<dyn DbPlugin>,
    publisher: PublisherT,
    config: WorkspaceOutboxConfig,
    sql_flavor: DbSqlFlavor,
    context_first: AtomicBool,
}

impl<PublisherT> WorkspaceOutboxDispatcher<PublisherT>
where
    PublisherT: WorkspaceEventPublisher,
{
    /// Construct a dispatcher after validating bounded runtime controls.
    pub fn new(
        db: Arc<dyn DbPlugin>,
        publisher: PublisherT,
        config: WorkspaceOutboxConfig,
    ) -> Result<Self> {
        Self::new_with_sql_flavor(db, publisher, config, DbSqlFlavor::Postgres)
    }

    /// Construct a Cloud or Desktop dispatcher with explicit SQL semantics.
    pub fn new_with_sql_flavor(
        db: Arc<dyn DbPlugin>,
        publisher: PublisherT,
        config: WorkspaceOutboxConfig,
        sql_flavor: DbSqlFlavor,
    ) -> Result<Self> {
        config.validate()?;
        if sql_flavor == DbSqlFlavor::Mysql {
            bail!("Workspace outbox supports only PostgreSQL and SQLite");
        }
        Ok(Self {
            db,
            publisher,
            config,
            sql_flavor,
            context_first: AtomicBool::new(false),
        })
    }

    /// Run until the owning task is cancelled.
    pub async fn run(&self) {
        loop {
            match self.dispatch_once().await {
                Ok(outcome) if outcome.claimed > 0 => {
                    tracing::debug!(
                        claimed = outcome.claimed,
                        dispatched = outcome.dispatched,
                        retry_scheduled = outcome.retry_scheduled,
                        dead_lettered = outcome.dead_lettered,
                        "Workspace outbox batch completed"
                    );
                }
                Ok(_) => tokio::time::sleep(self.config.poll_interval).await,
                Err(error) => {
                    tracing::error!(error = %error, "Workspace outbox polling failed");
                    tokio::time::sleep(self.config.poll_interval).await;
                }
            }
        }
    }

    /// Process one bounded batch for deterministic tests and operational probes.
    pub async fn dispatch_once(&self) -> Result<DispatchBatchOutcome> {
        let events = self.claim().await?;
        let mut outcome = DispatchBatchOutcome {
            claimed: events.len(),
            ..DispatchBatchOutcome::default()
        };
        for event in events {
            match self.publisher.publish(&event).await {
                Ok(stream_id) => {
                    self.mark_dispatched(&event, &stream_id).await?;
                    outcome.dispatched += 1;
                }
                Err(error) => {
                    let dead_lettered = event.attempt_count >= event.max_attempts;
                    self.mark_failed(&event, &error.to_string(), dead_lettered)
                        .await?;
                    if dead_lettered {
                        outcome.dead_lettered += 1;
                    } else {
                        outcome.retry_scheduled += 1;
                    }
                }
            }
        }
        Ok(outcome)
    }

    async fn claim(&self) -> Result<Vec<WorkspaceOutboxEvent>> {
        let context_first = self.context_first.fetch_xor(true, Ordering::Relaxed);
        let preferred = if context_first {
            WorkspaceOutboxSource::Context
        } else {
            WorkspaceOutboxSource::Workspace
        };
        let secondary = preferred.other();
        let preferred_budget = self.config.batch_size.div_ceil(2);
        let mut events = self.claim_from(preferred, preferred_budget).await?;
        let remaining = self
            .config
            .batch_size
            .saturating_sub(u32::try_from(events.len()).context("count claimed outbox rows")?);
        if remaining > 0 {
            events.extend(self.claim_from(secondary, remaining).await?);
        }
        let remaining = self
            .config
            .batch_size
            .saturating_sub(u32::try_from(events.len()).context("count claimed outbox rows")?);
        if remaining > 0 {
            events.extend(self.claim_from(preferred, remaining).await?);
        }
        Ok(events)
    }

    async fn claim_from(
        &self,
        source: WorkspaceOutboxSource,
        limit: u32,
    ) -> Result<Vec<WorkspaceOutboxEvent>> {
        if limit == 0 {
            return Ok(Vec::new());
        }
        let lease_seconds = i64::try_from(self.config.lease_seconds)
            .context("Workspace outbox lease seconds exceed PostgreSQL BIGINT")?;
        let returned_columns = match (source, self.sql_flavor) {
            (WorkspaceOutboxSource::Workspace, DbSqlFlavor::Postgres) => {
                "o.outbox_id, o.tenant_id, o.project_id, o.workspace_id, \
                 NULL::VARCHAR AS user_id, o.event_type, o.stream_name, o.event_sequence, \
                 o.payload_json, o.metadata_json, o.correlation_id, \
                 o.publication_attempt_count AS attempt_count, \
                 o.publication_max_attempts AS max_attempts, o.created_at"
            }
            (WorkspaceOutboxSource::Context, DbSqlFlavor::Postgres) => {
                "o.outbox_id, o.tenant_id, o.project_id, NULL::VARCHAR AS workspace_id, \
                 o.user_id, o.event_type, o.stream_name, o.event_sequence, o.payload_json, \
                 o.metadata_json, NULL::VARCHAR AS correlation_id, o.attempt_count, \
                 o.max_attempts, o.created_at"
            }
            (WorkspaceOutboxSource::Workspace, DbSqlFlavor::Sqlite | DbSqlFlavor::Mysql) => {
                "outbox_id, tenant_id, project_id, workspace_id, NULL AS user_id, event_type, \
                 stream_name, event_sequence, payload_json, metadata_json, correlation_id, \
                 publication_attempt_count AS attempt_count, \
                 publication_max_attempts AS max_attempts, created_at"
            }
            (WorkspaceOutboxSource::Context, DbSqlFlavor::Sqlite | DbSqlFlavor::Mysql) => {
                "outbox_id, tenant_id, project_id, NULL AS workspace_id, user_id, event_type, \
                 stream_name, event_sequence, payload_json, metadata_json, \
                 NULL AS correlation_id, attempt_count, max_attempts, created_at"
            }
        };
        let statement = match self.sql_flavor {
            DbSqlFlavor::Postgres => {
                let builder = DbStatementBuilder::new(self.sql_flavor)
                    .push_static("WITH candidates AS (SELECT outbox_id FROM ")
                    .push_static(source.table_name())
                    .push_static(" WHERE ");
                let builder = claim_ready_filter(builder, source, self.sql_flavor)
                    .push_static(" ORDER BY created_at, outbox_id FOR UPDATE SKIP LOCKED LIMIT ")
                    .bind(u64::from(limit))
                    .push_static(") UPDATE ")
                    .push_static(source.table_name())
                    .push_static(" o SET status = 'dispatching', ");
                publication_attempt_increment(builder, source)
                    .push_static(", lease_owner = ")
                    .bind(self.config.lease_owner.as_str())
                    .push_static(", lease_expires_at = CURRENT_TIMESTAMP + ")
                    .bind(lease_seconds)
                    .push_static(
                        "::BIGINT * INTERVAL '1 second', updated_at = CURRENT_TIMESTAMP FROM candidates c \
                         WHERE o.outbox_id = c.outbox_id RETURNING ",
                    )
                    .push_static(returned_columns)
                    .build()
            }
            DbSqlFlavor::Sqlite | DbSqlFlavor::Mysql => {
                let builder = DbStatementBuilder::new(self.sql_flavor)
                    .push_static("UPDATE ")
                    .push_static(source.table_name())
                    .push_static(" SET status = 'dispatching', ");
                let builder = publication_attempt_increment(builder, source)
                    .push_static(", lease_owner = ")
                    .bind(self.config.lease_owner.as_str())
                    .push_static(", lease_expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ")
                    .bind(format!("+{lease_seconds} seconds"))
                    .push_static("), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE rowid IN (SELECT rowid FROM ")
                    .push_static(source.table_name())
                    .push_static(" WHERE ");
                claim_ready_filter(builder, source, self.sql_flavor)
                    .push_static(" ORDER BY created_at, outbox_id LIMIT ")
                    .bind(u64::from(limit))
                    .push_static(") RETURNING ")
                    .push_static(returned_columns)
                    .build()
            }
        };
        self.db
            .query(statement)
            .await
            .with_context(|| format!("claim {} records", source.table_name()))?
            .iter()
            .map(|row| outbox_event_from_row(row, source))
            .collect()
    }

    async fn mark_dispatched(&self, event: &WorkspaceOutboxEvent, stream_id: &str) -> Result<()> {
        let metadata = json!({"redis_stream_id": stream_id}).to_string();
        let mut builder = DbStatementBuilder::new(self.sql_flavor)
            .push_static("UPDATE ")
            .push_static(event.source.table_name())
            .push_static(
                " SET status = 'dispatched', dispatched_at = \
                 COALESCE(dispatched_at, ",
            )
            .push_static(current_timestamp_sql(self.sql_flavor))
            .push_static(
                "), lease_owner = NULL, \
                 lease_expires_at = NULL, last_error = NULL, next_attempt_at = NULL, \
                 metadata_json = ",
            );
        builder = match self.sql_flavor {
            DbSqlFlavor::Postgres => builder
                .push_static("metadata_json || ")
                .bind(metadata)
                .push_static("::jsonb"),
            DbSqlFlavor::Sqlite => builder
                .push_static("json_patch(metadata_json, ")
                .bind(metadata)
                .push_static(")"),
            DbSqlFlavor::Mysql => builder
                .push_static("JSON_MERGE_PATCH(metadata_json, ")
                .bind(metadata)
                .push_static(")"),
        };
        let statement = builder
            .push_static(", updated_at = ")
            .push_static(current_timestamp_sql(self.sql_flavor))
            .push_static(" WHERE outbox_id = ")
            .bind(event.outbox_id.as_str())
            .push_static(" AND status = 'dispatching' AND lease_owner = ")
            .bind(self.config.lease_owner.as_str())
            .build();
        let result = self
            .db
            .execute(statement)
            .await
            .context("mark Workspace outbox record dispatched")?;
        if result.affected_rows != 1 {
            bail!("Workspace outbox dispatch lease was lost");
        }
        Ok(())
    }

    async fn mark_failed(
        &self,
        event: &WorkspaceOutboxEvent,
        error: &str,
        dead_lettered: bool,
    ) -> Result<()> {
        let status = if dead_lettered {
            "dead_letter"
        } else {
            "retry"
        };
        let backoff_seconds = i64::try_from(self.retry_backoff_seconds(event.attempt_count))
            .context("Workspace outbox retry delay exceeds PostgreSQL BIGINT")?;
        let builder = DbStatementBuilder::new(self.sql_flavor)
            .push_static("UPDATE ")
            .push_static(event.source.table_name())
            .push_static(" SET status = ")
            .bind(status)
            .push_static(", lease_owner = NULL, lease_expires_at = NULL, last_error = ")
            .bind(truncate_error(error))
            .push_static(", next_attempt_at = CASE WHEN ")
            .bind(dead_lettered)
            .push_static(" THEN NULL ELSE ");
        let builder = match self.sql_flavor {
            DbSqlFlavor::Postgres => builder
                .push_static("CURRENT_TIMESTAMP + ")
                .bind(backoff_seconds)
                .push_static("::BIGINT * INTERVAL '1 second'"),
            DbSqlFlavor::Sqlite | DbSqlFlavor::Mysql => builder
                .push_static("strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ")
                .bind(format!("+{backoff_seconds} seconds"))
                .push_static(")"),
        };
        let statement = builder
            .push_static(" END, updated_at = ")
            .push_static(current_timestamp_sql(self.sql_flavor))
            .push_static(" WHERE outbox_id = ")
            .bind(event.outbox_id.as_str())
            .push_static(" AND status = 'dispatching' AND lease_owner = ")
            .bind(self.config.lease_owner.as_str())
            .build();
        let result = self
            .db
            .execute(statement)
            .await
            .context("mark Workspace outbox record failed")?;
        if result.affected_rows != 1 {
            bail!("Workspace outbox failure lease was lost");
        }
        Ok(())
    }

    fn retry_backoff_seconds(&self, attempt_count: u32) -> u64 {
        let exponent = cmp::min(attempt_count, 20);
        self.config
            .retry_base_seconds
            .saturating_mul(2_u64.saturating_pow(exponent))
            .min(self.config.retry_max_seconds)
    }
}

fn claim_ready_filter(
    builder: DbStatementBuilder,
    source: WorkspaceOutboxSource,
    flavor: DbSqlFlavor,
) -> DbStatementBuilder {
    match source {
        WorkspaceOutboxSource::Context => builder
            .push_static(
                "((status IN ('pending', 'retry') AND \
             (next_attempt_at IS NULL OR next_attempt_at <= ",
            )
            .push_static(current_timestamp_sql(flavor))
            .push_static(")) OR (status = 'dispatching' AND lease_expires_at < ")
            .push_static(current_timestamp_sql(flavor))
            .push_static("))"),
        WorkspaceOutboxSource::Workspace => {
            let builder = builder.push_static("((");
            let builder = plan_runtime_event_filter(builder)
                .push_static(
                    " AND ((status IN ('runtime_dispatched', 'retry') AND \
                     (next_attempt_at IS NULL OR next_attempt_at <= ",
                )
                .push_static(current_timestamp_sql(flavor))
                .push_static(")) OR (status = 'dispatching' AND lease_expires_at < ")
                .push_static(current_timestamp_sql(flavor))
                .push_static("))) OR (NOT (");
            plan_runtime_event_filter(builder)
                .push_static(
                    ") AND ((status IN ('pending', 'retry') AND \
                 (next_attempt_at IS NULL OR next_attempt_at <= ",
                )
                .push_static(current_timestamp_sql(flavor))
                .push_static(")) OR (status = 'dispatching' AND lease_expires_at < ")
                .push_static(current_timestamp_sql(flavor))
                .push_static("))))")
        }
    }
}

const fn current_timestamp_sql(flavor: DbSqlFlavor) -> &'static str {
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Mysql => "CURRENT_TIMESTAMP",
        DbSqlFlavor::Sqlite => "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
    }
}

fn plan_runtime_event_filter(mut builder: DbStatementBuilder) -> DbStatementBuilder {
    builder = builder.push_static("event_type IN (");
    for (index, event_type) in WORKSPACE_PLAN_RUNTIME_EVENT_TYPES.iter().enumerate() {
        if index > 0 {
            builder = builder.push_static(", ");
        }
        builder = builder.bind(*event_type);
    }
    builder.push_static(")")
}

fn publication_attempt_increment(
    builder: DbStatementBuilder,
    source: WorkspaceOutboxSource,
) -> DbStatementBuilder {
    match source {
        WorkspaceOutboxSource::Workspace => {
            builder.push_static("publication_attempt_count = publication_attempt_count + 1")
        }
        WorkspaceOutboxSource::Context => builder.push_static("attempt_count = attempt_count + 1"),
    }
}

fn outbox_event_from_row(
    row: &DbRow,
    source: WorkspaceOutboxSource,
) -> Result<WorkspaceOutboxEvent> {
    let event_sequence = required_u64(row, "event_sequence")?;
    let attempt_count = required_u32(row, "attempt_count")?;
    let max_attempts = required_u32(row, "max_attempts")?;
    let workspace_id = row
        .get_string("workspace_id")
        .context("read workspace_id")?;
    let user_id = row.get_string("user_id").context("read user_id")?;
    match source {
        WorkspaceOutboxSource::Workspace if workspace_id.is_none() => {
            bail!("workspace_id is missing from Workspace outbox record");
        }
        WorkspaceOutboxSource::Context if user_id.is_none() => {
            bail!("user_id is missing from Context outbox record");
        }
        WorkspaceOutboxSource::Workspace | WorkspaceOutboxSource::Context => {}
    }
    Ok(WorkspaceOutboxEvent {
        outbox_id: required_string(row, "outbox_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id,
        user_id,
        event_type: required_string(row, "event_type")?,
        stream_name: required_string(row, "stream_name")?,
        event_sequence,
        payload: required_json(row, "payload_json")?,
        metadata: required_json(row, "metadata_json")?,
        correlation_id: row
            .get_string("correlation_id")
            .context("read correlation_id")?,
        attempt_count,
        max_attempts,
        created_at: required_string(row, "created_at")?,
        source,
    })
}

fn event_envelope(event: &WorkspaceOutboxEvent) -> Value {
    let mut metadata = event.metadata.as_object().cloned().unwrap_or_default();
    metadata.extend(Map::from_iter([
        ("outbox_id".to_string(), json!(&event.outbox_id)),
        ("tenant_id".to_string(), json!(&event.tenant_id)),
        ("project_id".to_string(), json!(&event.project_id)),
        ("event_sequence".to_string(), json!(event.event_sequence)),
    ]));
    if let Some(workspace_id) = &event.workspace_id {
        metadata.insert("workspace_id".to_string(), json!(workspace_id));
    }
    if let Some(user_id) = &event.user_id {
        metadata.insert("user_id".to_string(), json!(user_id));
    }
    json!({
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": &event.outbox_id,
        "event_type": &event.event_type,
        "timestamp": &event.created_at,
        "source": OUTBOX_SOURCE,
        "correlation_id": &event.correlation_id,
        "causation_id": Value::Null,
        "payload": &event.payload,
        "metadata": metadata,
    })
}

fn redis_stream_key(stream_name: &str) -> Result<String> {
    let stream_name = stream_name.trim();
    if stream_name.is_empty() {
        bail!("Workspace outbox stream name must not be blank");
    }
    if stream_name.starts_with(STREAM_PREFIX) {
        Ok(stream_name.to_string())
    } else {
        Ok(format!("{STREAM_PREFIX}{stream_name}"))
    }
}

fn routing_key(stream_name: &str) -> &str {
    stream_name
        .strip_prefix(STREAM_PREFIX)
        .unwrap_or(stream_name)
}

fn redis_connection_info(config: &RedisCacheConfig) -> Result<redis::ConnectionInfo> {
    let credentials = config.auth_credentials().map_err(|error| anyhow!(error))?;
    let (username, password) = match credentials {
        Some(credentials) => (credentials.username, Some(credentials.password)),
        None => (None, None),
    };
    let mut redis = redis::RedisConnectionInfo {
        db: 0,
        ..Default::default()
    };
    redis.username = username;
    redis.password = password;
    Ok(redis::ConnectionInfo {
        addr: redis::ConnectionAddr::Tcp(config.host.clone(), config.port),
        redis,
    })
}

fn required_string(row: &DbRow, name: &str) -> Result<String> {
    row.get_string(name)
        .with_context(|| format!("read {name}"))?
        .ok_or_else(|| anyhow!("{name} is missing"))
}

fn required_u64(row: &DbRow, name: &str) -> Result<u64> {
    let value = row
        .get_i64(name)
        .with_context(|| format!("read {name}"))?
        .ok_or_else(|| anyhow!("{name} is missing"))?;
    u64::try_from(value).with_context(|| format!("{name} is negative"))
}

fn required_u32(row: &DbRow, name: &str) -> Result<u32> {
    u32::try_from(required_u64(row, name)?).with_context(|| format!("{name} exceeds u32"))
}

fn required_json(row: &DbRow, name: &str) -> Result<Value> {
    serde_json::from_str(&required_string(row, name)?)
        .with_context(|| format!("parse {name} as JSON"))
}

fn truncate_error(error: &str) -> String {
    error.chars().take(MAX_ERROR_LENGTH).collect()
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::sync::Mutex;

    use async_trait::async_trait;
    use bcs_db_api::{
        DbError, DbExecuteResult, DbHealth, DbResult, DbStatement, DbTransactionStep,
        DbTransactionStepResult, DbValue,
    };

    use super::*;

    struct ContractDb {
        claimed_workspace: Mutex<Vec<DbRow>>,
        claimed_context: Mutex<Vec<DbRow>>,
        executed: Mutex<Vec<DbStatement>>,
    }

    #[async_trait]
    impl DbPlugin for ContractDb {
        async fn query(&self, statement: DbStatement) -> DbResult<Vec<DbRow>> {
            let claimed = if statement.sql().contains("workspace_context_outbox") {
                &self.claimed_context
            } else {
                &self.claimed_workspace
            };
            let mut claimed = claimed
                .lock()
                .map_err(|error| DbError::Backend(format!("claim test lock: {error}")))?;
            Ok(std::mem::take(&mut *claimed))
        }

        async fn execute(&self, statement: DbStatement) -> DbResult<DbExecuteResult> {
            let mut executed = self
                .executed
                .lock()
                .map_err(|error| DbError::Backend(format!("execute test lock: {error}")))?;
            executed.push(statement);
            Ok(DbExecuteResult {
                affected_rows: 1,
                last_insert_id: None,
            })
        }

        async fn transaction(
            &self,
            _steps: Vec<DbTransactionStep>,
        ) -> DbResult<Vec<DbTransactionStepResult>> {
            Ok(Vec::new())
        }

        async fn health_check(&self) -> DbResult<DbHealth> {
            Ok(DbHealth::healthy())
        }
    }

    struct ContractPublisher {
        fail: bool,
        published: Mutex<Vec<WorkspaceOutboxEvent>>,
    }

    #[async_trait]
    impl WorkspaceEventPublisher for ContractPublisher {
        async fn publish(&self, event: &WorkspaceOutboxEvent) -> Result<String> {
            let mut published = self
                .published
                .lock()
                .map_err(|error| anyhow!("publish test lock: {error}"))?;
            published.push(event.clone());
            if self.fail {
                bail!("Redis unavailable");
            }
            Ok("1700000000000-0".to_string())
        }
    }

    fn outbox_row(attempt_count: i64, max_attempts: i64) -> DbRow {
        DbRow::new(BTreeMap::from([
            ("outbox_id".to_string(), DbValue::from("outbox-1")),
            ("tenant_id".to_string(), DbValue::from("tenant-1")),
            ("project_id".to_string(), DbValue::from("project-1")),
            ("workspace_id".to_string(), DbValue::from("workspace-1")),
            ("user_id".to_string(), DbValue::Null),
            (
                "event_type".to_string(),
                DbValue::from("workspace.execution.completed"),
            ),
            (
                "stream_name".to_string(),
                DbValue::from("workspace:workspace-1:events"),
            ),
            ("event_sequence".to_string(), DbValue::from(4_i64)),
            (
                "payload_json".to_string(),
                DbValue::from(r#"{"content":"done"}"#),
            ),
            (
                "metadata_json".to_string(),
                DbValue::from(r#"{"report_hash":"abc"}"#),
            ),
            ("correlation_id".to_string(), DbValue::from("correlation-1")),
            ("attempt_count".to_string(), DbValue::from(attempt_count)),
            ("max_attempts".to_string(), DbValue::from(max_attempts)),
            (
                "created_at".to_string(),
                DbValue::from("2026-08-10T00:00:00Z"),
            ),
        ]))
    }

    fn context_outbox_row(attempt_count: i64, max_attempts: i64) -> DbRow {
        DbRow::new(BTreeMap::from([
            ("outbox_id".to_string(), DbValue::from("context-outbox-1")),
            ("tenant_id".to_string(), DbValue::from("tenant-1")),
            ("project_id".to_string(), DbValue::from("project-1")),
            ("workspace_id".to_string(), DbValue::Null),
            ("user_id".to_string(), DbValue::from("user-1")),
            (
                "event_type".to_string(),
                DbValue::from("workspace_context.switched"),
            ),
            (
                "stream_name".to_string(),
                DbValue::from("workspace-context:user-1"),
            ),
            ("event_sequence".to_string(), DbValue::from(2_i64)),
            (
                "payload_json".to_string(),
                DbValue::from(r#"{"tenant_id":"tenant-1","project_id":"project-1"}"#),
            ),
            (
                "metadata_json".to_string(),
                DbValue::from(r#"{"request_hash":"abc"}"#),
            ),
            ("correlation_id".to_string(), DbValue::Null),
            ("attempt_count".to_string(), DbValue::from(attempt_count)),
            ("max_attempts".to_string(), DbValue::from(max_attempts)),
            (
                "created_at".to_string(),
                DbValue::from("2026-08-11T00:00:00Z"),
            ),
        ]))
    }

    fn dispatcher(
        attempt_count: i64,
        max_attempts: i64,
        fail: bool,
    ) -> Result<(
        Arc<ContractDb>,
        WorkspaceOutboxDispatcher<ContractPublisher>,
    )> {
        dispatcher_with_rows(
            vec![outbox_row(attempt_count, max_attempts)],
            Vec::new(),
            fail,
        )
    }

    fn dispatcher_with_rows(
        workspace_rows: Vec<DbRow>,
        context_rows: Vec<DbRow>,
        fail: bool,
    ) -> Result<(
        Arc<ContractDb>,
        WorkspaceOutboxDispatcher<ContractPublisher>,
    )> {
        let db = Arc::new(ContractDb {
            claimed_workspace: Mutex::new(workspace_rows),
            claimed_context: Mutex::new(context_rows),
            executed: Mutex::new(Vec::new()),
        });
        let publisher = ContractPublisher {
            fail,
            published: Mutex::new(Vec::new()),
        };
        let dispatcher = WorkspaceOutboxDispatcher::new(
            db.clone(),
            publisher,
            WorkspaceOutboxConfig {
                lease_owner: "dispatcher-1".to_string(),
                ..WorkspaceOutboxConfig::default()
            },
        )?;
        Ok((db, dispatcher))
    }

    #[tokio::test]
    async fn successful_publish_marks_outbox_dispatched() -> Result<()> {
        let (db, dispatcher) = dispatcher(1, 3, false)?;

        let outcome = dispatcher.dispatch_once().await?;

        assert_eq!(outcome.dispatched, 1);
        let statements = db
            .executed
            .lock()
            .map_err(|error| anyhow!("execute assertion lock: {error}"))?;
        assert_eq!(statements.len(), 1);
        assert!(statements[0].sql().contains("status = 'dispatched'"));
        Ok(())
    }

    #[tokio::test]
    async fn failed_publish_schedules_bounded_retry() -> Result<()> {
        let (db, dispatcher) = dispatcher(1, 3, true)?;

        let outcome = dispatcher.dispatch_once().await?;

        assert_eq!(outcome.retry_scheduled, 1);
        let statements = db
            .executed
            .lock()
            .map_err(|error| anyhow!("retry assertion lock: {error}"))?;
        assert_eq!(
            statements[0].params().first(),
            Some(&DbValue::from("retry"))
        );
        assert_eq!(statements[0].params().get(3), Some(&DbValue::from(2_i64)));
        Ok(())
    }

    #[tokio::test]
    async fn exhausted_publish_moves_to_dead_letter() -> Result<()> {
        let (db, dispatcher) = dispatcher(3, 3, true)?;

        let outcome = dispatcher.dispatch_once().await?;

        assert_eq!(outcome.dead_lettered, 1);
        let statements = db
            .executed
            .lock()
            .map_err(|error| anyhow!("dead-letter assertion lock: {error}"))?;
        assert_eq!(
            statements[0].params().first(),
            Some(&DbValue::from("dead_letter"))
        );
        Ok(())
    }

    #[tokio::test]
    async fn context_publish_claims_and_finalizes_dedicated_outbox() -> Result<()> {
        let (db, dispatcher) =
            dispatcher_with_rows(Vec::new(), vec![context_outbox_row(1, 3)], false)?;

        let outcome = dispatcher.dispatch_once().await?;

        assert_eq!(outcome.dispatched, 1);
        let statements = db
            .executed
            .lock()
            .map_err(|error| anyhow!("Context execute assertion lock: {error}"))?;
        assert_eq!(statements.len(), 1);
        assert!(
            statements[0]
                .sql()
                .contains("UPDATE workspace_context_outbox")
        );
        assert!(statements[0].sql().contains("status = 'dispatched'"));
        Ok(())
    }

    #[test]
    fn workspace_claim_filter_hands_plan_events_to_publication_only_after_runtime_dispatch() {
        let statement = claim_ready_filter(
            DbStatementBuilder::new(DbSqlFlavor::Postgres),
            WorkspaceOutboxSource::Workspace,
            DbSqlFlavor::Postgres,
        )
        .build();

        assert!(
            statement
                .sql()
                .contains("status IN ('runtime_dispatched', 'retry')")
        );
        assert!(statement.sql().contains("status IN ('pending', 'retry')"));
        assert!(statement.sql().contains("NOT (event_type IN"));
        for event_type in WORKSPACE_PLAN_RUNTIME_EVENT_TYPES {
            assert_eq!(
                statement
                    .params()
                    .iter()
                    .filter(|value| **value == DbValue::from(event_type))
                    .count(),
                2
            );
        }
    }

    #[test]
    fn workspace_publication_uses_a_retry_budget_independent_from_plan_dispatch() {
        let workspace = publication_attempt_increment(
            DbStatementBuilder::new(DbSqlFlavor::Postgres),
            WorkspaceOutboxSource::Workspace,
        )
        .build();
        let context = publication_attempt_increment(
            DbStatementBuilder::new(DbSqlFlavor::Postgres),
            WorkspaceOutboxSource::Context,
        )
        .build();

        assert_eq!(
            workspace.sql(),
            "publication_attempt_count = publication_attempt_count + 1"
        );
        assert_eq!(context.sql(), "attempt_count = attempt_count + 1");
    }

    #[test]
    fn envelope_matches_legacy_unified_event_bus_contract() -> Result<()> {
        let event = outbox_event_from_row(&outbox_row(1, 3), WorkspaceOutboxSource::Workspace)?;

        let envelope = event_envelope(&event);

        assert_eq!(
            redis_stream_key(&event.stream_name)?,
            "events:workspace:workspace-1:events"
        );
        assert_eq!(envelope["event_id"], "outbox-1");
        assert_eq!(envelope["event_type"], "workspace.execution.completed");
        assert_eq!(envelope["payload"]["content"], "done");
        assert_eq!(envelope["metadata"]["event_sequence"], 4);
        assert_eq!(envelope["metadata"]["workspace_id"], "workspace-1");
        assert!(envelope["metadata"].get("user_id").is_none());
        Ok(())
    }

    #[test]
    fn context_envelope_preserves_user_scope_without_fake_workspace() -> Result<()> {
        let event =
            outbox_event_from_row(&context_outbox_row(1, 3), WorkspaceOutboxSource::Context)?;

        let envelope = event_envelope(&event);

        assert_eq!(
            redis_stream_key(&event.stream_name)?,
            "events:workspace-context:user-1"
        );
        assert_eq!(envelope["event_id"], "context-outbox-1");
        assert_eq!(envelope["event_type"], "workspace_context.switched");
        assert_eq!(envelope["metadata"]["user_id"], "user-1");
        assert!(envelope["metadata"].get("workspace_id").is_none());
        Ok(())
    }
}
