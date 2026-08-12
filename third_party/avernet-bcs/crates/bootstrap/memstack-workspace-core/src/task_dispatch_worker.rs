//! Bounded fenced worker for durable Workspace execution Task dispatches.

use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service::{
    PublicWorkspaceTaskDispatchClaim, PublicWorkspaceTaskDispatchService,
};
use tokio::task::JoinSet;

use crate::task_dispatch::{WorkspaceTaskDeliveryError, WorkspaceTaskRuntime};

const MAX_DELIVERY_BATCH_SIZE: i64 = 100;

/// Bounded lease, polling, and retry controls for Task delivery recovery.
#[derive(Debug, Clone)]
pub struct WorkspaceTaskDispatchWorkerConfig {
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_duration: Duration,
    pub poll_interval: Duration,
    pub retry_base: Duration,
    pub retry_max: Duration,
}

impl WorkspaceTaskDispatchWorkerConfig {
    /// Validate deterministic worker controls before spawning the task.
    ///
    /// # Errors
    ///
    /// Returns an error for a blank identity, invalid batch, zero timing,
    /// unrepresentable duration, or retry base above its cap.
    pub fn validate(&self) -> Result<()> {
        if self.worker_id.trim().is_empty() {
            bail!("Workspace Task dispatch worker id must not be blank");
        }
        if !(1..=MAX_DELIVERY_BATCH_SIZE).contains(&self.batch_size) {
            bail!("Workspace Task dispatch batch size must be between 1 and 100");
        }
        for (name, duration) in [
            ("lease", self.lease_duration),
            ("poll", self.poll_interval),
            ("retry base", self.retry_base),
            ("retry maximum", self.retry_max),
        ] {
            if duration.is_zero() {
                bail!("Workspace Task dispatch {name} duration must be positive");
            }
            duration_ms(duration)
                .with_context(|| format!("Workspace Task dispatch {name} duration"))?;
        }
        if self.retry_base > self.retry_max {
            bail!("Workspace Task dispatch retry base exceeds retry maximum");
        }
        Ok(())
    }
}

impl Default for WorkspaceTaskDispatchWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: format!("workspace-task-dispatch:{}", std::process::id()),
            batch_size: 25,
            lease_duration: Duration::from_secs(120),
            poll_interval: Duration::from_millis(250),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(300),
        }
    }
}

/// Result counters from one bounded Task dispatch pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WorkspaceTaskDispatchBatchOutcome {
    pub claimed: usize,
    pub completed: usize,
    pub terminal_skipped: usize,
    pub retry_scheduled: usize,
    pub dead_lettered: usize,
}

/// Polls fenced Task claims and invokes the existing Agent Runtime Provider.
pub struct WorkspaceTaskDispatchWorker {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    runtime: Arc<WorkspaceTaskRuntime>,
    config: WorkspaceTaskDispatchWorkerConfig,
}

impl WorkspaceTaskDispatchWorker {
    /// Construct a worker after validating bounded controls.
    ///
    /// # Errors
    ///
    /// Returns an error when `config` is invalid.
    pub fn new(
        db: Arc<dyn DbPlugin>,
        sql_flavor: DbSqlFlavor,
        runtime: Arc<WorkspaceTaskRuntime>,
        config: WorkspaceTaskDispatchWorkerConfig,
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
                        terminal_skipped = outcome.terminal_skipped,
                        retry_scheduled = outcome.retry_scheduled,
                        dead_lettered = outcome.dead_lettered,
                        "Workspace Task dispatch batch completed"
                    );
                }
                Ok(_) => tokio::time::sleep(self.config.poll_interval).await,
                Err(error) => {
                    tracing::error!(error = %error, "Workspace Task dispatch polling failed");
                    tokio::time::sleep(self.config.poll_interval).await;
                }
            }
        }
    }

    /// Process one bounded claim batch.
    ///
    /// # Errors
    ///
    /// Returns claim, fencing, clock, or persistence failures.
    pub async fn dispatch_once(&self) -> Result<WorkspaceTaskDispatchBatchOutcome> {
        self.dispatch_once_at(now_ms()?).await
    }

    pub(crate) async fn dispatch_once_at(
        &self,
        now_ms: i64,
    ) -> Result<WorkspaceTaskDispatchBatchOutcome> {
        let lease_expires_at_ms = now_ms
            .checked_add(duration_ms(self.config.lease_duration)?)
            .context("Workspace Task dispatch lease deadline overflowed")?;
        let service = PublicWorkspaceTaskDispatchService::new(self.db.as_ref(), self.sql_flavor);
        let claims = service
            .claim_dispatches(
                self.config.worker_id.as_str(),
                now_ms,
                lease_expires_at_ms,
                self.config.batch_size,
            )
            .await
            .context("claim Workspace Task dispatches")?;
        let mut outcome = WorkspaceTaskDispatchBatchOutcome {
            claimed: claims.len(),
            ..WorkspaceTaskDispatchBatchOutcome::default()
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
                Ok(Ok(ClaimDispatchOutcome::TerminalSkipped)) => outcome.terminal_skipped += 1,
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
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ClaimDispatchOutcome {
    Completed,
    TerminalSkipped,
    RetryScheduled,
    DeadLettered,
}

async fn dispatch_claim(
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    runtime: Arc<WorkspaceTaskRuntime>,
    claim: PublicWorkspaceTaskDispatchClaim,
    now_ms: i64,
    retry_base_ms: i64,
    retry_max_ms: i64,
) -> Result<ClaimDispatchOutcome> {
    let service = PublicWorkspaceTaskDispatchService::new(db.as_ref(), sql_flavor);
    if task_is_terminal(&claim.task_status) {
        service
            .complete_dispatch(&claim, now_ms)
            .await
            .context("complete terminal Workspace Task dispatch")?;
        return Ok(ClaimDispatchOutcome::TerminalSkipped);
    }
    if service.prepare_correlation(&claim).await.is_err() {
        return release_failed_claim(
            &service,
            &claim,
            now_ms,
            retry_base_ms,
            retry_max_ms,
            "workspace_task_runtime_correlation_failed",
        )
        .await;
    }
    match runtime.dispatch(&claim).await {
        Ok(()) => {
            service
                .complete_dispatch(&claim, now_ms)
                .await
                .context("complete fenced Workspace Task dispatch")?;
            Ok(ClaimDispatchOutcome::Completed)
        }
        Err(error) => {
            release_failed_claim(
                &service,
                &claim,
                now_ms,
                retry_base_ms,
                retry_max_ms,
                stable_delivery_error(&error),
            )
            .await
        }
    }
}

async fn release_failed_claim(
    service: &PublicWorkspaceTaskDispatchService<'_>,
    claim: &PublicWorkspaceTaskDispatchClaim,
    now_ms: i64,
    retry_base_ms: i64,
    retry_max_ms: i64,
    stable_error: &'static str,
) -> Result<ClaimDispatchOutcome> {
    let next_attempt_at_ms = now_ms
        .checked_add(retry_backoff_ms(
            retry_base_ms,
            retry_max_ms,
            claim.attempt_count,
        ))
        .context("Workspace Task dispatch retry deadline overflowed")?;
    let failure = service
        .fail_dispatch(claim, next_attempt_at_ms, stable_error)
        .await
        .context("release fenced Workspace Task dispatch")?;
    tracing::warn!(
        workspace_id = %claim.workspace_id,
        task_id = %claim.task_id,
        agent_id = %claim.agent_id,
        attempt_count = claim.attempt_count,
        error_code = stable_error,
        dead_lettered = failure.dead_lettered,
        "Workspace Task Provider delivery failed"
    );
    Ok(if failure.dead_lettered {
        ClaimDispatchOutcome::DeadLettered
    } else {
        ClaimDispatchOutcome::RetryScheduled
    })
}

fn task_is_terminal(status: &str) -> bool {
    status == "done"
}

fn stable_delivery_error(error: &WorkspaceTaskDeliveryError) -> &'static str {
    match error {
        WorkspaceTaskDeliveryError::RunContextConflict => {
            "workspace_task_provider_run_context_conflict"
        }
        WorkspaceTaskDeliveryError::DeadlineOverflow => {
            "workspace_task_provider_callback_deadline_overflow"
        }
        WorkspaceTaskDeliveryError::Rejected { .. } => "workspace_task_provider_delivery_rejected",
        WorkspaceTaskDeliveryError::Delivery { .. } => "workspace_task_provider_delivery_failed",
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
    use std::sync::atomic::{AtomicBool, Ordering};

    use async_trait::async_trait;
    use bcs_db_api::DbStatement;
    use bcs_db_local::LocalSqliteDbPlugin;
    use bcs_domain::BotDeliveryTarget;
    use bcs_protocol::{BcsFrame, BotDeliveryKind};
    use bcs_service_api::{
        BotDeliveryCommand, BotDeliveryPort, BotDeliveryResult, BotRunContext, BotRunContextPort,
        ServiceError, ServiceResult,
    };
    use tokio::sync::Mutex;

    use super::*;
    use crate::task_dispatch::{WorkspaceTaskRuntime, WorkspaceTaskRuntimeConfig};

    #[derive(Debug, Clone, Copy)]
    enum DeliveryBehavior {
        Accepted,
        Rejected,
        Failed,
    }

    struct RecordingDelivery {
        db: Arc<dyn DbPlugin>,
        behavior: DeliveryBehavior,
        commands: Mutex<Vec<BotDeliveryCommand>>,
        correlation_seen: AtomicBool,
    }

    impl RecordingDelivery {
        fn new(db: Arc<dyn DbPlugin>, behavior: DeliveryBehavior) -> Self {
            Self {
                db,
                behavior,
                commands: Mutex::new(Vec::new()),
                correlation_seen: AtomicBool::new(false),
            }
        }
    }

    #[async_trait]
    impl BotDeliveryPort for RecordingDelivery {
        async fn is_available(&self, _target: &BotDeliveryTarget) -> bool {
            true
        }

        async fn deliver(&self, command: BotDeliveryCommand) -> ServiceResult<BotDeliveryResult> {
            let rows = self
                .db
                .query(DbStatement::new(format!(
                    "SELECT correlation_id FROM workspace_agent_runtime_correlations WHERE correlation_id = '{}'",
                    command.run_id
                )))
                .await
                .map_err(|error| ServiceError::InternalError(error.to_string()))?;
            self.correlation_seen
                .store(rows.len() == 1, Ordering::SeqCst);
            let target_bot_id = command.target_bot_id().to_string();
            self.commands.lock().await.push(command);
            match self.behavior {
                DeliveryBehavior::Accepted => Ok(BotDeliveryResult {
                    target_bot_id,
                    delivered: true,
                    error: None,
                }),
                DeliveryBehavior::Rejected => Ok(BotDeliveryResult {
                    target_bot_id,
                    delivered: false,
                    error: None,
                }),
                DeliveryBehavior::Failed => Err(ServiceError::InternalError(
                    "network unavailable".to_string(),
                )),
            }
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

    fn worker_config(worker_id: &str) -> WorkspaceTaskDispatchWorkerConfig {
        WorkspaceTaskDispatchWorkerConfig {
            worker_id: worker_id.to_string(),
            batch_size: 10,
            lease_duration: Duration::from_millis(100),
            poll_interval: Duration::from_millis(10),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(8),
        }
    }

    fn runtime(
        delivery: Arc<dyn BotDeliveryPort>,
        run_context: Arc<dyn BotRunContextPort>,
    ) -> Result<Arc<WorkspaceTaskRuntime>> {
        Ok(Arc::new(
            WorkspaceTaskRuntime::new(
                delivery,
                run_context,
                WorkspaceTaskRuntimeConfig {
                    webhook_url: "http://127.0.0.1:18080/provider".to_string(),
                    webhook_token: "provider-token".to_string(),
                    callback_timeout_ms: 60_000,
                },
            )
            .map_err(anyhow::Error::msg)?,
        ))
    }

    #[tokio::test]
    async fn accepted_dispatch_persists_correlation_before_provider_and_acks_lease() -> Result<()> {
        let db = seeded_db("todo").await?;
        let db: Arc<dyn DbPlugin> = Arc::new(db);
        let delivery = Arc::new(RecordingDelivery::new(
            Arc::clone(&db),
            DeliveryBehavior::Accepted,
        ));
        let worker = WorkspaceTaskDispatchWorker::new(
            Arc::clone(&db),
            DbSqlFlavor::Sqlite,
            runtime(
                Arc::clone(&delivery) as Arc<dyn BotDeliveryPort>,
                Arc::new(RecordingRunContext::default()),
            )?,
            worker_config("worker-accepted"),
        )?;

        let outcome = worker.dispatch_once_at(100).await?;

        assert_eq!(outcome.claimed, 1);
        assert_eq!(outcome.completed, 1);
        assert!(delivery.correlation_seen.load(Ordering::SeqCst));
        assert_eq!(
            scalar_string(
                db.as_ref(),
                "SELECT status AS value FROM workspace_task_dispatch_outbox"
            )
            .await?,
            "delivered"
        );
        assert_eq!(
            scalar_i64(
                db.as_ref(),
                "SELECT COUNT(*) AS value FROM workspace_agent_runtime_correlations"
            )
            .await?,
            1
        );
        let commands = delivery.commands.lock().await;
        assert_eq!(commands.len(), 1);
        assert_eq!(commands[0].delivery_kind, BotDeliveryKind::Inject);
        assert_eq!(commands[0].run_id, "delivery-1");
        let BcsFrame::Request(frame) = &commands[0].frame else {
            bail!("Task dispatch must use a request frame");
        };
        assert_eq!(frame.method, "chat.inject");
        assert_eq!(frame.id, "delivery-1");
        let params = frame.params.as_ref().context("Task dispatch params")?;
        assert_eq!(params["bcs_group_id"], "group-1");
        assert_eq!(params["bcs_session_id"], "conversation-1");
        assert_eq!(params["extensions"]["task_id"], "task-1");
        assert_eq!(params["extensions"]["conversation_id"], "conversation-1");
        Ok(())
    }

    #[tokio::test]
    async fn rejected_and_failed_provider_calls_schedule_stable_retries() -> Result<()> {
        for (behavior, expected_error) in [
            (
                DeliveryBehavior::Rejected,
                "workspace_task_provider_delivery_rejected",
            ),
            (
                DeliveryBehavior::Failed,
                "workspace_task_provider_delivery_failed",
            ),
        ] {
            let db = seeded_db("todo").await?;
            let db: Arc<dyn DbPlugin> = Arc::new(db);
            let delivery = Arc::new(RecordingDelivery::new(Arc::clone(&db), behavior));
            let worker = WorkspaceTaskDispatchWorker::new(
                Arc::clone(&db),
                DbSqlFlavor::Sqlite,
                runtime(
                    Arc::clone(&delivery) as Arc<dyn BotDeliveryPort>,
                    Arc::new(RecordingRunContext::default()),
                )?,
                worker_config("worker-failure"),
            )?;

            let outcome = worker.dispatch_once_at(100).await?;

            assert_eq!(outcome.retry_scheduled, 1);
            assert!(delivery.correlation_seen.load(Ordering::SeqCst));
            assert_eq!(
                scalar_string(
                    db.as_ref(),
                    "SELECT last_error AS value FROM workspace_task_dispatch_outbox"
                )
                .await?,
                expected_error
            );
            assert_eq!(
                scalar_string(
                    db.as_ref(),
                    "SELECT status AS value FROM workspace_task_dispatch_outbox"
                )
                .await?,
                "pending"
            );
        }
        Ok(())
    }

    #[tokio::test]
    async fn terminal_task_is_acked_without_provider_or_runtime_correlation() -> Result<()> {
        let db = seeded_db("done").await?;
        let db: Arc<dyn DbPlugin> = Arc::new(db);
        let delivery = Arc::new(RecordingDelivery::new(
            Arc::clone(&db),
            DeliveryBehavior::Accepted,
        ));
        let worker = WorkspaceTaskDispatchWorker::new(
            Arc::clone(&db),
            DbSqlFlavor::Sqlite,
            runtime(
                Arc::clone(&delivery) as Arc<dyn BotDeliveryPort>,
                Arc::new(RecordingRunContext::default()),
            )?,
            worker_config("worker-terminal"),
        )?;

        let outcome = worker.dispatch_once_at(100).await?;

        assert_eq!(outcome.terminal_skipped, 1);
        assert!(delivery.commands.lock().await.is_empty());
        assert_eq!(
            scalar_i64(
                db.as_ref(),
                "SELECT COUNT(*) AS value FROM workspace_agent_runtime_correlations"
            )
            .await?,
            0
        );
        assert_eq!(
            scalar_string(
                db.as_ref(),
                "SELECT status AS value FROM workspace_task_dispatch_outbox"
            )
            .await?,
            "delivered"
        );
        Ok(())
    }

    #[tokio::test]
    async fn correlation_conflict_prevents_provider_side_effect() -> Result<()> {
        let db = seeded_db("todo").await?;
        db.execute(DbStatement::new(
            "INSERT INTO workspace_agent_runtime_correlations (correlation_id, tenant_id, project_id, workspace_id, user_id, task_id, attempt_id, plan_id, plan_node_id, conversation_id, delivery_request_id, provider_run_id, bcs_group_id, provider_id, provider_bot_ref, status, created_at, updated_at) VALUES ('delivery-1', 'tenant-1', 'project-1', 'workspace-1', 'user-1', 'different-task', 'attempt-1', 'plan-1', 'node-1', 'conversation-1', 'delivery-1', 'delivery-1', 'group-1', 'memstack-workspace-agent-runtime', 'agent-1', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ))
        .await?;
        let db: Arc<dyn DbPlugin> = Arc::new(db);
        let delivery = Arc::new(RecordingDelivery::new(
            Arc::clone(&db),
            DeliveryBehavior::Accepted,
        ));
        let worker = WorkspaceTaskDispatchWorker::new(
            Arc::clone(&db),
            DbSqlFlavor::Sqlite,
            runtime(
                Arc::clone(&delivery) as Arc<dyn BotDeliveryPort>,
                Arc::new(RecordingRunContext::default()),
            )?,
            worker_config("worker-conflict"),
        )?;

        let outcome = worker.dispatch_once_at(100).await?;

        assert_eq!(outcome.retry_scheduled, 1);
        assert!(delivery.commands.lock().await.is_empty());
        assert_eq!(
            scalar_string(
                db.as_ref(),
                "SELECT last_error AS value FROM workspace_task_dispatch_outbox"
            )
            .await?,
            "workspace_task_runtime_correlation_failed"
        );
        Ok(())
    }

    #[tokio::test]
    async fn crash_after_correlation_reclaims_with_the_same_provider_run_id() -> Result<()> {
        let db = seeded_db("todo").await?;
        let db: Arc<dyn DbPlugin> = Arc::new(db);
        let crashed = PublicWorkspaceTaskDispatchService::new(db.as_ref(), DbSqlFlavor::Sqlite);
        let claim = crashed
            .claim_dispatches("worker-crashed", 100, 200, 1)
            .await?;
        assert_eq!(claim.len(), 1);
        crashed.prepare_correlation(&claim[0]).await?;

        let delivery = Arc::new(RecordingDelivery::new(
            Arc::clone(&db),
            DeliveryBehavior::Accepted,
        ));
        let worker = WorkspaceTaskDispatchWorker::new(
            Arc::clone(&db),
            DbSqlFlavor::Sqlite,
            runtime(
                Arc::clone(&delivery) as Arc<dyn BotDeliveryPort>,
                Arc::new(RecordingRunContext::default()),
            )?,
            worker_config("worker-recovery"),
        )?;

        let outcome = worker.dispatch_once_at(200).await?;

        assert_eq!(outcome.completed, 1);
        let commands = delivery.commands.lock().await;
        assert_eq!(commands.len(), 1);
        assert_eq!(commands[0].run_id, claim[0].delivery_request_id);
        assert_eq!(
            scalar_i64(
                db.as_ref(),
                "SELECT COUNT(*) AS value FROM workspace_agent_runtime_correlations"
            )
            .await?,
            1
        );
        Ok(())
    }

    #[tokio::test]
    async fn terminal_run_context_suppresses_duplicate_provider_side_effect() -> Result<()> {
        let db = seeded_db("todo").await?;
        let db: Arc<dyn DbPlugin> = Arc::new(db);
        let service = PublicWorkspaceTaskDispatchService::new(db.as_ref(), DbSqlFlavor::Sqlite);
        let claim = service.claim_dispatches("worker-1", 100, 200, 1).await?;
        service.prepare_correlation(&claim[0]).await?;
        let delivery = Arc::new(RecordingDelivery::new(
            Arc::clone(&db),
            DeliveryBehavior::Accepted,
        ));
        let runtime = runtime(
            Arc::clone(&delivery) as Arc<dyn BotDeliveryPort>,
            Arc::new(RecordingRunContext::default()),
        )?;

        runtime.dispatch(&claim[0]).await?;
        runtime.dispatch(&claim[0]).await?;

        assert_eq!(delivery.commands.lock().await.len(), 1);
        Ok(())
    }

    async fn seeded_db(task_status: &str) -> Result<LocalSqliteDbPlugin> {
        let db = LocalSqliteDbPlugin::new()?;
        for statement in [
            "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, status TEXT NOT NULL)",
            "CREATE TABLE workspace_task_dispatch_outbox (dispatch_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, task_id TEXT NOT NULL, attempt_id TEXT, plan_id TEXT, plan_node_id TEXT, user_id TEXT NOT NULL, agent_id TEXT NOT NULL, workspace_agent_binding_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, group_id TEXT NOT NULL, conversation_id TEXT NOT NULL, delivery_request_id TEXT NOT NULL UNIQUE, task_title TEXT NOT NULL, task_description TEXT, status TEXT NOT NULL, attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL, next_attempt_at_ms INTEGER NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, lease_generation INTEGER NOT NULL, last_error TEXT, delivered_at_ms INTEGER, created_at_ms INTEGER NOT NULL)",
            "CREATE TABLE workspace_agent_runtime_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT, task_id TEXT, attempt_id TEXT, plan_id TEXT, plan_node_id TEXT, conversation_id TEXT NOT NULL, delivery_request_id TEXT UNIQUE, provider_run_id TEXT UNIQUE, bcs_group_id TEXT, provider_id TEXT, provider_bot_ref TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        ] {
            db.execute(DbStatement::new(statement)).await?;
        }
        db.execute(DbStatement::new(format!(
            "INSERT INTO workspace_tasks (task_id, status) VALUES ('task-1', '{task_status}')"
        )))
        .await?;
        db.execute(DbStatement::new(
            "INSERT INTO workspace_task_dispatch_outbox (dispatch_id, tenant_id, project_id, workspace_id, task_id, attempt_id, plan_id, plan_node_id, user_id, agent_id, workspace_agent_binding_id, bot_uuid, group_id, conversation_id, delivery_request_id, task_title, task_description, status, attempt_count, max_attempts, next_attempt_at_ms, lease_generation, created_at_ms) VALUES ('dispatch-1', 'tenant-1', 'project-1', 'workspace-1', 'task-1', 'attempt-1', 'plan-1', 'node-1', 'user-1', 'agent-1', 'binding-1', 'bot-1', 'group-1', 'conversation-1', 'delivery-1', 'Execute work', 'Preserve the durable contract', 'pending', 0, 8, 0, 0, 1)",
        ))
        .await?;
        Ok(db)
    }

    async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64> {
        db.query(DbStatement::new(sql))
            .await?
            .first()
            .context("scalar query returned no rows")?
            .get_i64("value")?
            .context("scalar value is NULL")
    }

    async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String> {
        db.query(DbStatement::new(sql))
            .await?
            .first()
            .context("scalar query returned no rows")?
            .get_string("value")?
            .context("scalar value is NULL")
    }
}
