//! Structural scheduler that triggers Agent-judged autonomous Workspace ticks.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{DateTime, Duration as ChronoDuration, SecondsFormat, Utc};
use memstack_workspace_service::{
    PublicWorkspaceAutonomyContext, PublicWorkspaceAutonomyJudgePort,
    PublicWorkspaceAutonomyScheduleCandidate, PublicWorkspaceAutonomyScheduleService,
    PublicWorkspaceAutonomyService, WORKSPACE_AUTONOMY_COOLDOWN_SECONDS,
};
use tokio::sync::Mutex;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;

const MAX_SCHEDULE_BATCH_SIZE: i64 = 100;

/// Bounded polling and circuit-breaker controls for autonomous Workspace scheduling.
#[derive(Debug, Clone)]
pub struct WorkspaceAutonomySchedulerConfig {
    pub batch_size: i64,
    pub poll_interval: Duration,
    pub cooldown: Duration,
    pub failure_backoff: Duration,
}

impl WorkspaceAutonomySchedulerConfig {
    pub fn validate(&self) -> Result<()> {
        if !(1..=MAX_SCHEDULE_BATCH_SIZE).contains(&self.batch_size) {
            bail!("Workspace Autonomy schedule batch size must be between 1 and 100");
        }
        for (name, duration) in [
            ("poll", self.poll_interval),
            ("cooldown", self.cooldown),
            ("failure backoff", self.failure_backoff),
        ] {
            if duration.is_zero() {
                bail!("Workspace Autonomy scheduler {name} duration must be positive");
            }
            duration_ms(duration)
                .with_context(|| format!("Workspace Autonomy scheduler {name} duration"))?;
        }
        let service_cooldown = u64::try_from(WORKSPACE_AUTONOMY_COOLDOWN_SECONDS)
            .context("Workspace Autonomy service cooldown is invalid")?;
        if self.cooldown < Duration::from_secs(service_cooldown) {
            bail!("Workspace Autonomy scheduler cooldown is below the service cooldown");
        }
        Ok(())
    }
}

impl Default for WorkspaceAutonomySchedulerConfig {
    fn default() -> Self {
        Self {
            batch_size: 25,
            poll_interval: Duration::from_secs(5),
            cooldown: Duration::from_secs(60),
            failure_backoff: Duration::from_secs(60),
        }
    }
}

/// Result counters from one bounded structural scheduling pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WorkspaceAutonomyScheduleBatchOutcome {
    pub due: usize,
    pub triggered: usize,
    pub not_triggered: usize,
    pub failed: usize,
    pub locally_suppressed: usize,
}

/// Polls objective structural state and delegates every semantic verdict to the Judge port.
pub struct WorkspaceAutonomyScheduler {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    judge: Arc<dyn PublicWorkspaceAutonomyJudgePort>,
    config: WorkspaceAutonomySchedulerConfig,
    failure_suppressed_until_ms: Mutex<BTreeMap<String, i64>>,
}

impl WorkspaceAutonomyScheduler {
    pub fn new(
        db: Arc<dyn DbPlugin>,
        sql_flavor: DbSqlFlavor,
        judge: Arc<dyn PublicWorkspaceAutonomyJudgePort>,
        config: WorkspaceAutonomySchedulerConfig,
    ) -> Result<Self> {
        config.validate()?;
        Ok(Self {
            db,
            sql_flavor,
            judge,
            config,
            failure_suppressed_until_ms: Mutex::new(BTreeMap::new()),
        })
    }

    /// Run until the owning task is cancelled.
    pub async fn run(&self) {
        self.run_until_cancelled(CancellationToken::new()).await;
    }

    /// Run until an explicit producer-stop signal is observed.
    pub async fn run_until_cancelled(&self, shutdown: CancellationToken) {
        loop {
            let tick = tokio::select! {
                () = shutdown.cancelled() => break,
                result = self.tick_once() => result,
            };
            match tick {
                Ok(outcome) if outcome.due > 0 => {
                    tracing::debug!(
                        due = outcome.due,
                        triggered = outcome.triggered,
                        not_triggered = outcome.not_triggered,
                        failed = outcome.failed,
                        locally_suppressed = outcome.locally_suppressed,
                        "Workspace Autonomy schedule batch completed"
                    );
                }
                Ok(_) => {}
                Err(error) => {
                    tracing::error!(error = %error, "Workspace Autonomy schedule scan failed");
                }
            }
            tokio::select! {
                () = shutdown.cancelled() => break,
                () = tokio::time::sleep(self.config.poll_interval) => {}
            }
        }
    }

    /// Execute one bounded structural scan and Agent-judged tick batch.
    pub async fn tick_once(&self) -> Result<WorkspaceAutonomyScheduleBatchOutcome> {
        self.tick_once_at(Utc::now()).await
    }

    pub(crate) async fn tick_once_at(
        &self,
        now: DateTime<Utc>,
    ) -> Result<WorkspaceAutonomyScheduleBatchOutcome> {
        let cooldown = ChronoDuration::from_std(self.config.cooldown)
            .context("Workspace Autonomy scheduler cooldown is invalid")?;
        let cutoff = (now - cooldown).to_rfc3339_opts(SecondsFormat::Micros, false);
        let candidates =
            PublicWorkspaceAutonomyScheduleService::new(self.db.as_ref(), self.sql_flavor)
                .list_due(cutoff.as_str(), self.config.batch_size)
                .await
                .context("list structurally due autonomous Workspaces")?;
        let now_ms = now.timestamp_millis();
        let mut outcome = WorkspaceAutonomyScheduleBatchOutcome {
            due: candidates.len(),
            ..WorkspaceAutonomyScheduleBatchOutcome::default()
        };
        let mut suppressed = self.failure_suppressed_until_ms.lock().await;
        suppressed.retain(|_, deadline| *deadline > now_ms);
        let (ready, locally_suppressed): (Vec<_>, Vec<_>) = candidates
            .into_iter()
            .partition(|candidate| !suppressed.contains_key(schedule_key(candidate).as_str()));
        outcome.locally_suppressed = locally_suppressed.len();
        drop(suppressed);

        let mut ticks = JoinSet::new();
        for candidate in ready {
            let db = Arc::clone(&self.db);
            let judge = Arc::clone(&self.judge);
            let sql_flavor = self.sql_flavor;
            ticks.spawn(async move {
                let result =
                    tick_candidate(db.as_ref(), sql_flavor, judge.as_ref(), &candidate).await;
                (candidate, result)
            });
        }
        let failure_backoff_ms = duration_ms(self.config.failure_backoff)?;
        while let Some(result) = ticks.join_next().await {
            let (candidate, result) = result.context("Workspace Autonomy scheduler task failed")?;
            match result {
                Ok(true) => outcome.triggered += 1,
                Ok(false) => outcome.not_triggered += 1,
                Err(error) => {
                    outcome.failed += 1;
                    let deadline = now_ms
                        .checked_add(failure_backoff_ms)
                        .context("Workspace Autonomy scheduler failure deadline overflowed")?;
                    self.failure_suppressed_until_ms
                        .lock()
                        .await
                        .insert(schedule_key(&candidate), deadline);
                    tracing::warn!(
                        workspace_id = %candidate.workspace_id,
                        workspace_revision = candidate.workspace_revision,
                        error = %error,
                        "Workspace Autonomy scheduled judgment failed"
                    );
                }
            }
        }
        Ok(outcome)
    }
}

async fn tick_candidate(
    db: &dyn DbPlugin,
    sql_flavor: DbSqlFlavor,
    judge: &dyn PublicWorkspaceAutonomyJudgePort,
    candidate: &PublicWorkspaceAutonomyScheduleCandidate,
) -> Result<bool> {
    let context = PublicWorkspaceAutonomyContext {
        tenant_id: candidate.tenant_id.clone(),
        project_id: candidate.project_id.clone(),
        workspace_id: candidate.workspace_id.clone(),
        user_id: candidate.actor_id.clone(),
        is_superuser: false,
        expected_revision: Some(candidate.workspace_revision),
        idempotency_key: Some(format!(
            "autonomy-scheduler:{}:revision:{}",
            candidate.workspace_id, candidate.workspace_revision
        )),
    };
    Ok(PublicWorkspaceAutonomyService::new(db, sql_flavor, judge)
        .tick(&context, false)
        .await
        .context("execute scheduled Workspace Autonomy judgment")?
        .response
        .triggered)
}

fn schedule_key(candidate: &PublicWorkspaceAutonomyScheduleCandidate) -> String {
    format!(
        "{}\0{}\0{}",
        candidate.tenant_id, candidate.project_id, candidate.workspace_id
    )
}

fn duration_ms(duration: Duration) -> Result<i64> {
    i64::try_from(duration.as_millis()).context("duration milliseconds exceed i64")
}
