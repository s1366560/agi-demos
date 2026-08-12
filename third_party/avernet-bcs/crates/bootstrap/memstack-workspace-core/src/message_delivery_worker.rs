//! Durable recovery worker for committed Workspace message deliveries.

use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service::{
    PublicWorkspaceMessageContext, PublicWorkspaceMessageDeliveryClaim,
    PublicWorkspaceMessageDeliveryService, PublicWorkspaceMessageOutcome,
};
use tokio::task::JoinSet;

use crate::message_delivery::{WorkspaceMessageDeliveryError, WorkspaceMessageRuntime};

const MAX_DELIVERY_BATCH_SIZE: i64 = 100;

/// Bounded lease, polling, and retry controls for message delivery recovery.
#[derive(Debug, Clone)]
pub struct WorkspaceMessageDeliveryWorkerConfig {
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_duration: Duration,
    pub poll_interval: Duration,
    pub retry_base: Duration,
    pub retry_max: Duration,
}

impl WorkspaceMessageDeliveryWorkerConfig {
    /// Validate deterministic worker controls before spawning the task.
    ///
    /// # Errors
    ///
    /// Returns an error for a blank identity, out-of-range batch, zero timing,
    /// unrepresentable millisecond value, or retry base above its cap.
    pub fn validate(&self) -> Result<()> {
        if self.worker_id.trim().is_empty() {
            bail!("Workspace message delivery worker id must not be blank");
        }
        if !(1..=MAX_DELIVERY_BATCH_SIZE).contains(&self.batch_size) {
            bail!("Workspace message delivery batch size must be between 1 and 100");
        }
        for (name, duration) in [
            ("lease", self.lease_duration),
            ("poll", self.poll_interval),
            ("retry base", self.retry_base),
            ("retry maximum", self.retry_max),
        ] {
            if duration.is_zero() {
                bail!("Workspace message delivery {name} duration must be positive");
            }
            duration_ms(duration)
                .with_context(|| format!("Workspace message delivery {name} duration"))?;
        }
        if self.retry_base > self.retry_max {
            bail!("Workspace message delivery retry base exceeds retry maximum");
        }
        Ok(())
    }
}

impl Default for WorkspaceMessageDeliveryWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: format!("workspace-message-delivery:{}", std::process::id()),
            batch_size: 25,
            lease_duration: Duration::from_secs(120),
            poll_interval: Duration::from_millis(250),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(300),
        }
    }
}

/// Result counters from one bounded delivery polling pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WorkspaceMessageDeliveryBatchOutcome {
    pub claimed: usize,
    pub completed: usize,
    pub retry_scheduled: usize,
    pub dead_lettered: usize,
}

/// Polls fenced delivery claims and invokes the shared Workspace Provider runtime.
pub struct WorkspaceMessageDeliveryWorker {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    runtime: Arc<WorkspaceMessageRuntime>,
    config: WorkspaceMessageDeliveryWorkerConfig,
}

impl WorkspaceMessageDeliveryWorker {
    /// Construct a worker after validating its bounded controls.
    ///
    /// # Errors
    ///
    /// Returns an error when `config` is invalid.
    pub fn new(
        db: Arc<dyn DbPlugin>,
        sql_flavor: DbSqlFlavor,
        runtime: Arc<WorkspaceMessageRuntime>,
        config: WorkspaceMessageDeliveryWorkerConfig,
    ) -> Result<Self> {
        config.validate()?;
        Ok(Self {
            db,
            sql_flavor,
            runtime,
            config,
        })
    }

    /// Run until the owning task is cancelled.
    pub async fn run(&self) {
        loop {
            match self.dispatch_once().await {
                Ok(outcome) if outcome.claimed > 0 => {
                    tracing::debug!(
                        claimed = outcome.claimed,
                        completed = outcome.completed,
                        retry_scheduled = outcome.retry_scheduled,
                        dead_lettered = outcome.dead_lettered,
                        "Workspace message delivery batch completed"
                    );
                }
                Ok(_) => tokio::time::sleep(self.config.poll_interval).await,
                Err(error) => {
                    tracing::error!(error = %error, "Workspace message delivery polling failed");
                    tokio::time::sleep(self.config.poll_interval).await;
                }
            }
        }
    }

    /// Process one bounded claim batch.
    ///
    /// # Errors
    ///
    /// Returns claim, fencing, time, or persistence failures.
    pub async fn dispatch_once(&self) -> Result<WorkspaceMessageDeliveryBatchOutcome> {
        self.dispatch_once_at(now_ms()?).await
    }

    async fn dispatch_once_at(&self, now_ms: i64) -> Result<WorkspaceMessageDeliveryBatchOutcome> {
        let lease_expires_at_ms = now_ms
            .checked_add(duration_ms(self.config.lease_duration)?)
            .context("Workspace message delivery lease deadline overflowed")?;
        let service = PublicWorkspaceMessageDeliveryService::new(self.db.as_ref(), self.sql_flavor);
        let claims = service
            .claim_deliveries(
                self.config.worker_id.as_str(),
                now_ms,
                lease_expires_at_ms,
                self.config.batch_size,
            )
            .await
            .context("claim Workspace message deliveries")?;
        let mut outcome = WorkspaceMessageDeliveryBatchOutcome {
            claimed: claims.len(),
            ..WorkspaceMessageDeliveryBatchOutcome::default()
        };
        let retry_base_ms = duration_ms(self.config.retry_base)?;
        let retry_max_ms = duration_ms(self.config.retry_max)?;
        let mut deliveries = JoinSet::new();
        for claim in claims {
            let db = Arc::clone(&self.db);
            let runtime = Arc::clone(&self.runtime);
            let sql_flavor = self.sql_flavor;
            deliveries.spawn(async move {
                dispatch_claim(
                    db,
                    sql_flavor,
                    runtime,
                    claim,
                    now_ms,
                    retry_base_ms,
                    retry_max_ms,
                )
                .await
            });
        }
        let mut first_error = None;
        while let Some(result) = deliveries.join_next().await {
            match result {
                Ok(Ok(ClaimDispatchOutcome::Completed)) => outcome.completed += 1,
                Ok(Ok(ClaimDispatchOutcome::RetryScheduled)) => outcome.retry_scheduled += 1,
                Ok(Ok(ClaimDispatchOutcome::DeadLettered)) => outcome.dead_lettered += 1,
                Ok(Err(error)) => {
                    first_error.get_or_insert(error);
                }
                Err(error) => {
                    first_error.get_or_insert_with(|| anyhow::Error::new(error));
                }
            }
        }
        first_error.map_or(Ok(outcome), Err)
    }

    #[cfg(test)]
    fn retry_backoff_ms(&self, attempt_count: i64) -> Result<i64> {
        let base = duration_ms(self.config.retry_base)?;
        let maximum = duration_ms(self.config.retry_max)?;
        Ok(retry_backoff_ms(base, maximum, attempt_count))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ClaimDispatchOutcome {
    Completed,
    RetryScheduled,
    DeadLettered,
}

async fn dispatch_claim(
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    runtime: Arc<WorkspaceMessageRuntime>,
    claim: PublicWorkspaceMessageDeliveryClaim,
    now_ms: i64,
    retry_base_ms: i64,
    retry_max_ms: i64,
) -> Result<ClaimDispatchOutcome> {
    let service = PublicWorkspaceMessageDeliveryService::new(db.as_ref(), sql_flavor);
    let context = claim_context(&claim);
    let message_outcome = claim_outcome(&claim);
    match runtime.dispatch(&context, &message_outcome).await {
        Ok(()) => {
            service
                .complete_delivery(&claim, now_ms)
                .await
                .context("complete fenced Workspace message delivery")?;
            Ok(ClaimDispatchOutcome::Completed)
        }
        Err(error) => {
            let stable_error = stable_delivery_error(&error);
            let next_attempt_at_ms = now_ms
                .checked_add(retry_backoff_ms(
                    retry_base_ms,
                    retry_max_ms,
                    claim.attempt_count,
                ))
                .context("Workspace message delivery retry deadline overflowed")?;
            let failure = service
                .fail_delivery(&claim, next_attempt_at_ms, stable_error)
                .await
                .context("release fenced Workspace message delivery")?;
            tracing::warn!(
                workspace_id = %claim.workspace_id,
                message_id = %claim.message.id,
                agent_id = %claim.target.agent_id,
                attempt_count = claim.attempt_count,
                error_code = stable_error,
                dead_lettered = failure.dead_lettered,
                "Workspace Provider delivery failed"
            );
            Ok(if failure.dead_lettered {
                ClaimDispatchOutcome::DeadLettered
            } else {
                ClaimDispatchOutcome::RetryScheduled
            })
        }
    }
}

fn retry_backoff_ms(base_ms: i64, maximum_ms: i64, attempt_count: i64) -> i64 {
    let exponent = u32::try_from(attempt_count.saturating_sub(1))
        .unwrap_or(u32::MAX)
        .min(20);
    base_ms
        .saturating_mul(2_i64.saturating_pow(exponent))
        .min(maximum_ms)
}

fn claim_context(claim: &PublicWorkspaceMessageDeliveryClaim) -> PublicWorkspaceMessageContext {
    PublicWorkspaceMessageContext {
        tenant_id: claim.tenant_id.clone(),
        project_id: claim.project_id.clone(),
        workspace_id: claim.workspace_id.clone(),
        user_id: claim.message.sender_id.clone(),
        user_is_superuser: false,
        authenticated_email: None,
    }
}

fn claim_outcome(claim: &PublicWorkspaceMessageDeliveryClaim) -> PublicWorkspaceMessageOutcome {
    PublicWorkspaceMessageOutcome {
        message: claim.message.clone(),
        group_id: claim.group_id.clone(),
        session_id: claim.session_id.clone(),
        correlation_id: claim.correlation_id.clone(),
        delivery_targets: vec![claim.target.clone()],
        replayed: true,
    }
}

fn stable_delivery_error(error: &WorkspaceMessageDeliveryError) -> &'static str {
    match error {
        WorkspaceMessageDeliveryError::RunContextConflict => {
            "workspace_provider_run_context_conflict"
        }
        WorkspaceMessageDeliveryError::DeadlineOverflow => {
            "workspace_provider_callback_deadline_overflow"
        }
        WorkspaceMessageDeliveryError::Rejected { .. } => "workspace_provider_delivery_rejected",
        WorkspaceMessageDeliveryError::Delivery { .. } => "workspace_provider_delivery_failed",
        WorkspaceMessageDeliveryError::Task(_) => "workspace_provider_delivery_task_failed",
    }
}

fn duration_ms(duration: Duration) -> Result<i64> {
    i64::try_from(duration.as_millis()).context("duration milliseconds exceed i64")
}

fn now_ms() -> Result<i64> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .context("system clock is before Unix epoch")?;
    duration_ms(elapsed)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use async_trait::async_trait;
    use bcs_db_api::DbStatement;
    use bcs_db_local::LocalSqliteDbPlugin;
    use bcs_domain::BotDeliveryTarget;
    use bcs_service_api::{
        BotDeliveryCommand, BotDeliveryPort, BotDeliveryResult, BotRunContext, BotRunContextPort,
        ServiceError, ServiceResult,
    };
    use tokio::sync::{Mutex, Semaphore};

    use super::*;
    use crate::message_delivery::{WorkspaceMessageRuntime, WorkspaceMessageRuntimeConfig};

    #[derive(Default)]
    struct RecordingDelivery {
        commands: Mutex<Vec<BotDeliveryCommand>>,
        fail_with: Option<String>,
    }

    #[async_trait]
    impl BotDeliveryPort for RecordingDelivery {
        async fn is_available(&self, _target: &BotDeliveryTarget) -> bool {
            true
        }

        async fn deliver(&self, command: BotDeliveryCommand) -> ServiceResult<BotDeliveryResult> {
            let target_bot_id = command.target_bot_id().to_string();
            self.commands.lock().await.push(command);
            if let Some(error) = &self.fail_with {
                return Err(ServiceError::InternalError(error.clone()));
            }
            Ok(BotDeliveryResult {
                target_bot_id,
                delivered: true,
                error: None,
            })
        }
    }

    struct BlockingDelivery {
        started: Arc<Semaphore>,
        release: Arc<Semaphore>,
    }

    impl BlockingDelivery {
        fn new() -> Self {
            Self {
                started: Arc::new(Semaphore::new(0)),
                release: Arc::new(Semaphore::new(0)),
            }
        }
    }

    #[async_trait]
    impl BotDeliveryPort for BlockingDelivery {
        async fn is_available(&self, _target: &BotDeliveryTarget) -> bool {
            true
        }

        async fn deliver(&self, command: BotDeliveryCommand) -> ServiceResult<BotDeliveryResult> {
            self.started.add_permits(1);
            let permit = self.release.acquire().await.map_err(|error| {
                ServiceError::InternalError(format!("delivery release closed: {error}"))
            })?;
            permit.forget();
            Ok(BotDeliveryResult {
                target_bot_id: command.target_bot_id().to_string(),
                delivered: true,
                error: None,
            })
        }
    }

    #[derive(Default)]
    struct RecordingRunContext {
        contexts: Mutex<HashMap<String, BotRunContext>>,
    }

    #[async_trait]
    impl BotRunContextPort for RecordingRunContext {
        async fn put_context(&self, context: BotRunContext) {
            self.contexts
                .lock()
                .await
                .insert(context.run_id.clone(), context);
        }

        async fn get_context(&self, run_id: &str) -> Option<BotRunContext> {
            self.contexts.lock().await.get(run_id).cloned()
        }

        async fn try_begin_terminal(&self, _run_id: &str) -> bool {
            true
        }

        async fn mark_terminal(&self, run_id: &str) -> bool {
            let mut contexts = self.contexts.lock().await;
            let Some(context) = contexts.get_mut(run_id) else {
                return false;
            };
            context.terminal = true;
            true
        }

        async fn release_terminal(&self, _run_id: &str) {}
    }

    fn worker_config() -> WorkspaceMessageDeliveryWorkerConfig {
        WorkspaceMessageDeliveryWorkerConfig {
            worker_id: "worker-1".to_string(),
            batch_size: 10,
            lease_duration: Duration::from_secs(30),
            poll_interval: Duration::from_millis(10),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(8),
        }
    }

    fn runtime(delivery: Arc<dyn BotDeliveryPort>) -> Result<Arc<WorkspaceMessageRuntime>> {
        Ok(Arc::new(
            WorkspaceMessageRuntime::new(
                delivery,
                Arc::new(RecordingRunContext::default()),
                WorkspaceMessageRuntimeConfig {
                    webhook_url: "http://127.0.0.1:18080/provider".to_string(),
                    webhook_token: "provider-token".to_string(),
                    callback_timeout_ms: 60_000,
                },
            )
            .map_err(anyhow::Error::msg)?,
        ))
    }

    async fn seeded_db() -> Result<Arc<LocalSqliteDbPlugin>> {
        let db = Arc::new(LocalSqliteDbPlugin::new()?);
        for statement in [
            "CREATE TABLE bcs_messages (message_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, session_id TEXT NOT NULL, env TEXT NOT NULL, sender_id TEXT NOT NULL, sender_type TEXT NOT NULL, content TEXT NOT NULL, mentions_json TEXT NOT NULL, parent_message_id TEXT, metadata_json TEXT NOT NULL, created_at INTEGER NOT NULL, workspace_id TEXT NOT NULL)",
            "CREATE TABLE workspace_message_correlations (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, bcs_session_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, correlation_id TEXT NOT NULL)",
            "CREATE TABLE workspace_message_delivery_outbox (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, bcs_message_id TEXT NOT NULL, group_id TEXT NOT NULL, target_order INTEGER NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, display_name TEXT, status TEXT NOT NULL, attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL, next_attempt_at_ms INTEGER NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, last_error TEXT, delivered_at_ms INTEGER, created_at_ms INTEGER NOT NULL, PRIMARY KEY(workspace_id, bcs_message_id, agent_id))",
            "INSERT INTO bcs_messages (message_id, group_id, session_id, env, sender_id, sender_type, content, mentions_json, parent_message_id, metadata_json, created_at, workspace_id) VALUES ('message-1', 'group-1', 'session-1', 'memstack', 'user-1', 'human', '\"deliver this\"', '[\"agent-1\"]', NULL, '{}', 1000, 'workspace-1')",
            "INSERT INTO workspace_message_correlations (tenant_id, project_id, workspace_id, bcs_session_id, bcs_message_id, correlation_id) VALUES ('tenant-1', 'project-1', 'workspace-1', 'session-1', 'message-1', 'correlation-1')",
            "INSERT INTO workspace_message_delivery_outbox (tenant_id, project_id, workspace_id, bcs_message_id, group_id, target_order, agent_id, bot_uuid, display_name, status, attempt_count, max_attempts, next_attempt_at_ms, created_at_ms) VALUES ('tenant-1', 'project-1', 'workspace-1', 'message-1', 'group-1', 0, 'agent-1', 'bot-1', 'Agent One', 'pending', 0, 8, 0, 1000)",
        ] {
            db.execute(DbStatement::new(statement)).await?;
        }
        Ok(db)
    }

    async fn add_second_delivery(db: &LocalSqliteDbPlugin) -> Result<()> {
        db.execute(DbStatement::new(
            "INSERT INTO workspace_message_delivery_outbox (tenant_id, project_id, workspace_id, bcs_message_id, group_id, target_order, agent_id, bot_uuid, display_name, status, attempt_count, max_attempts, next_attempt_at_ms, created_at_ms) VALUES ('tenant-1', 'project-1', 'workspace-1', 'message-1', 'group-1', 1, 'agent-2', 'bot-2', 'Agent Two', 'pending', 0, 8, 0, 1000)",
        ))
        .await?;
        Ok(())
    }

    #[test]
    fn config_and_retry_backoff_are_bounded() -> Result<()> {
        assert!(
            WorkspaceMessageDeliveryWorkerConfig::default().lease_duration
                >= Duration::from_secs(120)
        );
        let mut config = worker_config();
        config.validate()?;
        config.worker_id = " ".to_string();
        assert!(config.validate().is_err());

        let db = Arc::new(LocalSqliteDbPlugin::new()?);
        let worker = WorkspaceMessageDeliveryWorker::new(
            db,
            DbSqlFlavor::Sqlite,
            runtime(Arc::new(RecordingDelivery::default()))?,
            worker_config(),
        )?;
        assert_eq!(worker.retry_backoff_ms(1)?, 1_000);
        assert_eq!(worker.retry_backoff_ms(2)?, 2_000);
        assert_eq!(worker.retry_backoff_ms(100)?, 8_000);
        Ok(())
    }

    #[tokio::test]
    async fn one_batch_dispatches_claims_concurrently_before_finalizing() -> Result<()> {
        let db = seeded_db().await?;
        add_second_delivery(db.as_ref()).await?;
        let delivery = Arc::new(BlockingDelivery::new());
        let worker = Arc::new(WorkspaceMessageDeliveryWorker::new(
            db,
            DbSqlFlavor::Sqlite,
            runtime(delivery.clone())?,
            worker_config(),
        )?);
        let task = tokio::spawn({
            let worker = Arc::clone(&worker);
            async move { worker.dispatch_once_at(2_000).await }
        });

        let started = delivery.started.acquire_many(2).await?;
        started.forget();
        delivery.release.add_permits(2);
        let outcome = task.await??;

        assert_eq!(outcome.claimed, 2);
        assert_eq!(outcome.completed, 2);
        Ok(())
    }

    #[tokio::test]
    async fn stale_worker_cannot_finalize_a_reclaimed_delivery_lease() -> Result<()> {
        let db = seeded_db().await?;
        let delivery = Arc::new(BlockingDelivery::new());
        let mut config = worker_config();
        config.lease_duration = Duration::from_millis(100);
        let worker = Arc::new(WorkspaceMessageDeliveryWorker::new(
            db.clone(),
            DbSqlFlavor::Sqlite,
            runtime(delivery.clone())?,
            config,
        )?);
        let task = tokio::spawn({
            let worker = Arc::clone(&worker);
            async move { worker.dispatch_once_at(2_000).await }
        });
        let started = delivery.started.acquire().await?;
        started.forget();

        let service = PublicWorkspaceMessageDeliveryService::new(db.as_ref(), DbSqlFlavor::Sqlite);
        let reclaimed = service
            .claim_deliveries("worker-2", 2_100, 3_000, 1)
            .await?;
        assert_eq!(reclaimed.len(), 1);
        delivery.release.add_permits(1);

        assert!(task.await?.is_err());
        let rows = db
            .query(DbStatement::new(
                "SELECT status, lease_owner, lease_expires_at_ms FROM workspace_message_delivery_outbox",
            ))
            .await?;
        assert_eq!(rows[0].get_string("status")?.as_deref(), Some("delivering"));
        assert_eq!(
            rows[0].get_string("lease_owner")?.as_deref(),
            Some("worker-2")
        );
        assert_eq!(rows[0].get_i64("lease_expires_at_ms")?, Some(3_000));
        Ok(())
    }

    #[tokio::test]
    async fn dispatch_once_claims_one_target_and_completes_its_fenced_lease() -> Result<()> {
        let db = seeded_db().await?;
        let delivery = Arc::new(RecordingDelivery::default());
        let worker = WorkspaceMessageDeliveryWorker::new(
            db.clone(),
            DbSqlFlavor::Sqlite,
            runtime(delivery.clone())?,
            worker_config(),
        )?;

        let outcome = worker.dispatch_once_at(2_000).await?;

        assert_eq!(outcome.claimed, 1);
        assert_eq!(outcome.completed, 1);
        assert_eq!(delivery.commands.lock().await.len(), 1);
        assert_eq!(worker.dispatch_once_at(2_001).await?.claimed, 0);
        Ok(())
    }

    #[tokio::test]
    async fn failed_delivery_uses_stable_redacted_error_and_bounded_retry() -> Result<()> {
        let db = seeded_db().await?;
        let delivery = Arc::new(RecordingDelivery {
            fail_with: Some("Authorization: Bearer must-not-persist".to_string()),
            ..RecordingDelivery::default()
        });
        let worker = WorkspaceMessageDeliveryWorker::new(
            db.clone(),
            DbSqlFlavor::Sqlite,
            runtime(delivery)?,
            worker_config(),
        )?;

        let outcome = worker.dispatch_once_at(2_000).await?;

        assert_eq!(outcome.claimed, 1);
        assert_eq!(outcome.retry_scheduled, 1);
        let rows = db
            .query(DbStatement::new(
                "SELECT status, next_attempt_at_ms, last_error FROM workspace_message_delivery_outbox",
            ))
            .await?;
        assert_eq!(rows[0].get_string("status")?.as_deref(), Some("pending"));
        assert_eq!(rows[0].get_i64("next_attempt_at_ms")?, Some(3_000));
        assert_eq!(
            rows[0].get_string("last_error")?.as_deref(),
            Some("workspace_provider_delivery_failed")
        );
        Ok(())
    }
}
