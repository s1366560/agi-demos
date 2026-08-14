//! Bounded fenced worker that materializes Agent-judged Autonomy continuations as Tasks.

use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service::{
    PublicWorkspaceAutonomyProgressionClaim, PublicWorkspaceAutonomyProgressionService,
    StructuredTaskActor, StructuredTaskContext, StructuredTaskErrorKind,
    StructuredTaskMutationFields, StructuredTaskService, StructuredWorkspaceTask,
};
use serde_json::json;
use tokio_util::sync::CancellationToken;

const MAX_PROGRESSION_BATCH_SIZE: i64 = 100;
const PROGRESSION_ERROR_CODE: &str = "autonomy_progression_execution_failed";

/// Bounded lease, polling, and retry controls for Autonomy continuation recovery.
#[derive(Debug, Clone)]
pub struct WorkspaceAutonomyProgressionWorkerConfig {
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_duration: Duration,
    pub poll_interval: Duration,
    pub retry_base: Duration,
    pub retry_max: Duration,
}

impl WorkspaceAutonomyProgressionWorkerConfig {
    /// Validate deterministic worker controls before spawning the task.
    pub fn validate(&self) -> Result<()> {
        if self.worker_id.trim().is_empty() || self.worker_id.chars().count() > 191 {
            bail!("Workspace Autonomy progression worker id is invalid");
        }
        if !(1..=MAX_PROGRESSION_BATCH_SIZE).contains(&self.batch_size) {
            bail!("Workspace Autonomy progression batch size must be between 1 and 100");
        }
        for (name, duration) in [
            ("lease", self.lease_duration),
            ("poll", self.poll_interval),
            ("retry base", self.retry_base),
            ("retry maximum", self.retry_max),
        ] {
            if duration.is_zero() {
                bail!("Workspace Autonomy progression {name} duration must be positive");
            }
            duration_ms(duration)
                .with_context(|| format!("Workspace Autonomy progression {name} duration"))?;
        }
        if self.retry_base > self.retry_max {
            bail!("Workspace Autonomy progression retry base exceeds retry maximum");
        }
        Ok(())
    }
}

impl Default for WorkspaceAutonomyProgressionWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: format!("workspace-autonomy-progression:{}", std::process::id()),
            batch_size: 25,
            lease_duration: Duration::from_secs(120),
            poll_interval: Duration::from_millis(250),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(300),
        }
    }
}

/// Result counters from one bounded Autonomy progression pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WorkspaceAutonomyProgressionBatchOutcome {
    pub claimed: usize,
    pub completed: usize,
    pub retry_scheduled: usize,
    pub dead_lettered: usize,
    pub failed: usize,
}

/// Polls fenced progression claims and queues the selected execution Task.
pub struct WorkspaceAutonomyProgressionWorker {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    config: WorkspaceAutonomyProgressionWorkerConfig,
}

impl WorkspaceAutonomyProgressionWorker {
    /// Construct a worker after validating bounded controls.
    pub fn new(
        db: Arc<dyn DbPlugin>,
        sql_flavor: DbSqlFlavor,
        config: WorkspaceAutonomyProgressionWorkerConfig,
    ) -> Result<Self> {
        config.validate()?;
        Ok(Self {
            db,
            sql_flavor,
            config,
        })
    }

    /// Run until the owning task is cancelled.
    pub async fn run(&self) {
        self.run_until_cancelled(CancellationToken::new()).await;
    }

    /// Stop polling cooperatively without abandoning an in-flight fenced batch.
    pub async fn run_until_cancelled(&self, shutdown: CancellationToken) {
        loop {
            let batch = tokio::select! {
                () = shutdown.cancelled() => break,
                result = self.advance_once() => result,
            };
            match batch {
                Ok(outcome) if outcome.claimed > 0 => {
                    tracing::debug!(
                        claimed = outcome.claimed,
                        completed = outcome.completed,
                        retry_scheduled = outcome.retry_scheduled,
                        dead_lettered = outcome.dead_lettered,
                        "Workspace Autonomy progression batch completed"
                    );
                }
                Ok(_) => {
                    tokio::select! {
                        () = shutdown.cancelled() => break,
                        () = tokio::time::sleep(self.config.poll_interval) => {}
                    }
                }
                Err(error) => {
                    tracing::error!(error = %error, "Workspace Autonomy progression polling failed");
                    tokio::select! {
                        () = shutdown.cancelled() => break,
                        () = tokio::time::sleep(self.config.poll_interval) => {}
                    }
                }
            }
        }
    }

    /// Process one bounded claim batch.
    pub async fn advance_once(&self) -> Result<WorkspaceAutonomyProgressionBatchOutcome> {
        let mut outcome = WorkspaceAutonomyProgressionBatchOutcome::default();
        let retry_base_ms = duration_ms(self.config.retry_base)?;
        let retry_max_ms = duration_ms(self.config.retry_max)?;
        for _ in 0..self.config.batch_size {
            let claim_now_ms = now_ms()?;
            let lease_expires_at_ms = claim_now_ms
                .checked_add(duration_ms(self.config.lease_duration)?)
                .context("Workspace Autonomy progression lease deadline overflowed")?;
            let progression =
                PublicWorkspaceAutonomyProgressionService::new(self.db.as_ref(), self.sql_flavor);
            let mut claims = progression
                .claim_progressions(
                    self.config.worker_id.as_str(),
                    claim_now_ms,
                    lease_expires_at_ms,
                    1,
                )
                .await
                .context("claim Workspace Autonomy progression")?;
            let Some(claim) = claims.pop() else {
                break;
            };
            outcome.claimed += 1;
            match materialize_execution_task(self.db.as_ref(), self.sql_flavor, &claim).await {
                Ok(execution_task_id) => {
                    let completed_at_ms =
                        now_ms().map_or(claim_now_ms, |now| now.max(claim_now_ms));
                    if let Err(error) = progression
                        .complete_progression(&claim, execution_task_id.as_str(), completed_at_ms)
                        .await
                    {
                        outcome.failed += 1;
                        tracing::error!(
                            workspace_id = %claim.workspace_id,
                            root_task_id = %claim.root_task_id,
                            progression_id = %claim.progression_id,
                            attempt_count = claim.attempt_count,
                            error = %error,
                            "Workspace Autonomy progression ACK failed"
                        );
                    } else {
                        outcome.completed += 1;
                    }
                }
                Err(error) => {
                    let failure_now_ms = now_ms().map_or(claim_now_ms, |now| now.max(claim_now_ms));
                    let next_attempt_at_ms = failure_now_ms
                        .checked_add(retry_backoff_ms(
                            retry_base_ms,
                            retry_max_ms,
                            claim.attempt_count,
                        ))
                        .context("Workspace Autonomy progression retry deadline overflowed")?;
                    let failure = progression
                        .fail_progression(&claim, next_attempt_at_ms, PROGRESSION_ERROR_CODE)
                        .await;
                    match failure {
                        Ok(failure) => {
                            tracing::warn!(
                                workspace_id = %claim.workspace_id,
                                root_task_id = %claim.root_task_id,
                                progression_id = %claim.progression_id,
                                attempt_count = claim.attempt_count,
                                dead_lettered = failure.dead_lettered,
                                error = %error,
                                "Workspace Autonomy progression materialization failed"
                            );
                            if failure.dead_lettered {
                                outcome.dead_lettered += 1;
                            } else {
                                outcome.retry_scheduled += 1;
                            }
                        }
                        Err(release_error) => {
                            outcome.failed += 1;
                            tracing::error!(
                                workspace_id = %claim.workspace_id,
                                root_task_id = %claim.root_task_id,
                                progression_id = %claim.progression_id,
                                attempt_count = claim.attempt_count,
                                materialization_error = %error,
                                error = %release_error,
                                "Workspace Autonomy progression failure release failed"
                            );
                        }
                    }
                }
            }
        }
        Ok(outcome)
    }
}

async fn materialize_execution_task(
    db: &dyn DbPlugin,
    sql_flavor: DbSqlFlavor,
    claim: &PublicWorkspaceAutonomyProgressionClaim,
) -> Result<String> {
    let service = StructuredTaskService::new(db, sql_flavor);
    let create_context = progression_context(claim, "create");
    let execution_task_id = StructuredTaskService::execution_task_id(&create_context)
        .context("derive Autonomy execution Task id")?;
    let task = match service
        .get(&create_context, execution_task_id.as_str())
        .await
    {
        Ok(task) => task,
        Err(error) if error.kind() == StructuredTaskErrorKind::NotFound => {
            service
                .create_execution_task(
                    &create_context,
                    &StructuredTaskMutationFields {
                        title: Some(claim.task_title.clone()),
                        description: Some(claim.task_description.clone()),
                        metadata: Some(json!({
                            "autonomy_progression_id": &claim.progression_id,
                            "autonomy_tick_id": &claim.tick_id,
                            "autonomy_judge_agent_id": &claim.judge_agent_id,
                        })),
                        ..StructuredTaskMutationFields::default()
                    },
                    claim.root_task_id.as_str(),
                )
                .await
                .context("create Autonomy execution Task")?
                .task
        }
        Err(error) => return Err(error).context("read Autonomy execution Task"),
    };
    validate_execution_task(claim, &task)?;
    match task.status.as_str() {
        "todo" => {
            let assigned = service
                .assign_and_start(
                    &progression_context(claim, "assign"),
                    execution_task_id.as_str(),
                    claim.workspace_agent_binding_id.as_str(),
                )
                .await
                .context("assign and start Autonomy execution Task")?
                .task;
            validate_started_task(claim, &assigned)?;
        }
        "in_progress" | "blocked" | "done" => validate_started_task(claim, &task)?,
        _ => bail!("Autonomy execution Task has an unsupported status"),
    }
    Ok(execution_task_id)
}

fn progression_context(
    claim: &PublicWorkspaceAutonomyProgressionClaim,
    action: &str,
) -> StructuredTaskContext {
    StructuredTaskContext {
        tenant_id: claim.tenant_id.clone(),
        project_id: claim.project_id.clone(),
        workspace_id: claim.workspace_id.clone(),
        actor: StructuredTaskActor {
            user_id: claim.actor_id.clone(),
            leader_agent_id: claim.judge_agent_id.clone(),
        },
        expected_revision: None,
        idempotency_key: Some(format!(
            "autonomy-progression:{}:{action}",
            claim.progression_id
        )),
    }
}

fn validate_execution_task(
    claim: &PublicWorkspaceAutonomyProgressionClaim,
    task: &StructuredWorkspaceTask,
) -> Result<()> {
    if task.workspace_id != claim.workspace_id
        || task.title != claim.task_title
        || task.description.as_deref() != Some(claim.task_description.as_str())
        || task.created_by != claim.actor_id
        || task
            .metadata
            .get("task_role")
            .and_then(|value| value.as_str())
            != Some("execution_task")
        || task
            .metadata
            .get("root_goal_task_id")
            .and_then(|value| value.as_str())
            != Some(claim.root_task_id.as_str())
        || task
            .metadata
            .get("autonomy_progression_id")
            .and_then(|value| value.as_str())
            != Some(claim.progression_id.as_str())
    {
        bail!("Autonomy execution Task identity conflicted with its progression snapshot");
    }
    Ok(())
}

fn validate_started_task(
    claim: &PublicWorkspaceAutonomyProgressionClaim,
    task: &StructuredWorkspaceTask,
) -> Result<()> {
    validate_execution_task(claim, task)?;
    if task.workspace_agent_id.as_deref() != Some(claim.workspace_agent_binding_id.as_str())
        || !matches!(task.status.as_str(), "in_progress" | "blocked" | "done")
    {
        bail!("Autonomy execution Task was not started with the Judge-selected Agent binding");
    }
    Ok(())
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
