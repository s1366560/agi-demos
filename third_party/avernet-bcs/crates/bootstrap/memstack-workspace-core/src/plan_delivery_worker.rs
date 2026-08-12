//! Bounded, fenced recovery worker for committed Workspace Plan runtime actions.

use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service::{
    PublicWorkspacePlanDeliveryClaim, PublicWorkspacePlanDeliveryService,
};
use memstack_workspace_service_api::WorkspacePlanDispatchPort;
use tokio::task::JoinSet;

const MAX_DELIVERY_BATCH_SIZE: i64 = 100;

/// Bounded lease, polling, and retry controls for Plan runtime delivery.
#[derive(Debug, Clone)]
pub struct WorkspacePlanDeliveryWorkerConfig {
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_duration: Duration,
    pub poll_interval: Duration,
    pub retry_base: Duration,
    pub retry_max: Duration,
}

impl WorkspacePlanDeliveryWorkerConfig {
    /// Validate deterministic worker controls before starting the task.
    ///
    /// # Errors
    ///
    /// Returns an error for blank identity, invalid batch size, zero timing,
    /// unrepresentable durations, or a retry base above its cap.
    pub fn validate(&self) -> Result<()> {
        if self.worker_id.trim().is_empty() {
            bail!("Workspace Plan delivery worker id must not be blank");
        }
        if !(1..=MAX_DELIVERY_BATCH_SIZE).contains(&self.batch_size) {
            bail!("Workspace Plan delivery batch size must be between 1 and 100");
        }
        for (name, duration) in [
            ("lease", self.lease_duration),
            ("poll", self.poll_interval),
            ("retry base", self.retry_base),
            ("retry maximum", self.retry_max),
        ] {
            if duration.is_zero() {
                bail!("Workspace Plan delivery {name} duration must be positive");
            }
            duration_ms(duration)
                .with_context(|| format!("Workspace Plan delivery {name} duration"))?;
        }
        if self.retry_base > self.retry_max {
            bail!("Workspace Plan delivery retry base exceeds retry maximum");
        }
        Ok(())
    }
}

impl Default for WorkspacePlanDeliveryWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: format!("workspace-plan-delivery:{}", std::process::id()),
            batch_size: 25,
            lease_duration: Duration::from_secs(120),
            poll_interval: Duration::from_millis(250),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(300),
        }
    }
}

/// Result counters from one bounded Plan delivery pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WorkspacePlanDeliveryBatchOutcome {
    pub claimed: usize,
    pub completed: usize,
    pub retry_scheduled: usize,
    pub dead_lettered: usize,
}

/// Polls fenced Plan claims and invokes the structured Agent Runtime boundary.
pub struct WorkspacePlanDeliveryWorker {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    dispatcher: Arc<dyn WorkspacePlanDispatchPort>,
    config: WorkspacePlanDeliveryWorkerConfig,
}

impl WorkspacePlanDeliveryWorker {
    /// Construct a worker after validating bounded controls.
    ///
    /// # Errors
    ///
    /// Returns an error when `config` is invalid.
    pub fn new(
        db: Arc<dyn DbPlugin>,
        sql_flavor: DbSqlFlavor,
        dispatcher: Arc<dyn WorkspacePlanDispatchPort>,
        config: WorkspacePlanDeliveryWorkerConfig,
    ) -> Result<Self> {
        config.validate()?;
        Ok(Self {
            db,
            sql_flavor,
            dispatcher,
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
                        "Workspace Plan delivery batch completed"
                    );
                }
                Ok(_) => tokio::time::sleep(self.config.poll_interval).await,
                Err(error) => {
                    tracing::error!(error = %error, "Workspace Plan delivery polling failed");
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
    pub async fn dispatch_once(&self) -> Result<WorkspacePlanDeliveryBatchOutcome> {
        self.dispatch_once_at(now_ms()?).await
    }

    pub(crate) async fn dispatch_once_at(
        &self,
        now_ms: i64,
    ) -> Result<WorkspacePlanDeliveryBatchOutcome> {
        let lease_expires_at_ms = now_ms
            .checked_add(duration_ms(self.config.lease_duration)?)
            .context("Workspace Plan delivery lease deadline overflowed")?;
        let service = PublicWorkspacePlanDeliveryService::new(self.db.as_ref(), self.sql_flavor);
        let claims = service
            .claim_deliveries(
                self.config.worker_id.as_str(),
                now_ms,
                lease_expires_at_ms,
                self.config.batch_size,
            )
            .await
            .context("claim Workspace Plan deliveries")?;
        let mut outcome = WorkspacePlanDeliveryBatchOutcome {
            claimed: claims.len(),
            ..WorkspacePlanDeliveryBatchOutcome::default()
        };
        let retry_base_ms = duration_ms(self.config.retry_base)?;
        let retry_max_ms = duration_ms(self.config.retry_max)?;
        let mut deliveries = JoinSet::new();
        for claim in claims {
            let db = Arc::clone(&self.db);
            let dispatcher = Arc::clone(&self.dispatcher);
            let sql_flavor = self.sql_flavor;
            deliveries.spawn(async move {
                dispatch_claim(
                    db,
                    sql_flavor,
                    dispatcher,
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
    dispatcher: Arc<dyn WorkspacePlanDispatchPort>,
    claim: PublicWorkspacePlanDeliveryClaim,
    now_ms: i64,
    retry_base_ms: i64,
    retry_max_ms: i64,
) -> Result<ClaimDispatchOutcome> {
    let service = PublicWorkspacePlanDeliveryService::new(db.as_ref(), sql_flavor);
    match dispatcher.dispatch(&claim.request).await {
        Ok(receipt) => {
            service
                .complete_delivery(&claim, &receipt, now_ms)
                .await
                .context("complete fenced Workspace Plan delivery")?;
            Ok(ClaimDispatchOutcome::Completed)
        }
        Err(error) => {
            let next_attempt_at_ms = now_ms
                .checked_add(retry_backoff_ms(
                    retry_base_ms,
                    retry_max_ms,
                    claim.attempt_count,
                ))
                .context("Workspace Plan delivery retry deadline overflowed")?;
            let failure = service
                .fail_delivery(&claim, now_ms, next_attempt_at_ms, error.code())
                .await
                .context("release fenced Workspace Plan delivery")?;
            tracing::warn!(
                workspace_id = %claim.request.workspace_id(),
                plan_id = %claim.request.plan_id(),
                plan_node_id = claim.request.plan_node_id(),
                outbox_id = %claim.request.outbox_id(),
                action = claim.request.action().as_str(),
                attempt_count = claim.attempt_count,
                error_code = error.code(),
                dead_lettered = failure.dead_lettered,
                "Workspace Plan Provider delivery failed"
            );
            Ok(if failure.dead_lettered {
                ClaimDispatchOutcome::DeadLettered
            } else {
                ClaimDispatchOutcome::RetryScheduled
            })
        }
    }
}

fn retry_backoff_ms(base_ms: i64, maximum_ms: i64, attempt_count: u32) -> i64 {
    let exponent = attempt_count.saturating_sub(1).min(20);
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
