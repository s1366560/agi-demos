//! Bounded fenced worker that bootstraps autonomous root Objectives and Tasks.

use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service::{
    PublicCreateWorkspaceObjectiveInput, PublicObjectiveTaskOutcome,
    PublicWorkspaceAutonomyBootstrapClaim, PublicWorkspaceAutonomyBootstrapService,
    PublicWorkspaceObjective, PublicWorkspaceObjectiveContext, PublicWorkspaceObjectiveService,
};
use tokio_util::sync::CancellationToken;

const MAX_BOOTSTRAP_BATCH_SIZE: i64 = 100;
const BOOTSTRAP_ERROR_CODE: &str = "autonomy_bootstrap_materialization_failed";

/// Bounded lease, polling, and retry controls for autonomous bootstrap recovery.
#[derive(Debug, Clone)]
pub struct WorkspaceAutonomyBootstrapWorkerConfig {
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_duration: Duration,
    pub poll_interval: Duration,
    pub retry_base: Duration,
    pub retry_max: Duration,
}

impl WorkspaceAutonomyBootstrapWorkerConfig {
    /// Validate deterministic worker controls before spawning the task.
    pub fn validate(&self) -> Result<()> {
        if self.worker_id.trim().is_empty() || self.worker_id.chars().count() > 191 {
            bail!("Workspace Autonomy bootstrap worker id is invalid");
        }
        if !(1..=MAX_BOOTSTRAP_BATCH_SIZE).contains(&self.batch_size) {
            bail!("Workspace Autonomy bootstrap batch size must be between 1 and 100");
        }
        for (name, duration) in [
            ("lease", self.lease_duration),
            ("poll", self.poll_interval),
            ("retry base", self.retry_base),
            ("retry maximum", self.retry_max),
        ] {
            if duration.is_zero() {
                bail!("Workspace Autonomy bootstrap {name} duration must be positive");
            }
            duration_ms(duration)
                .with_context(|| format!("Workspace Autonomy bootstrap {name} duration"))?;
        }
        if self.retry_base > self.retry_max {
            bail!("Workspace Autonomy bootstrap retry base exceeds retry maximum");
        }
        Ok(())
    }
}

impl Default for WorkspaceAutonomyBootstrapWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: format!("workspace-autonomy-bootstrap:{}", std::process::id()),
            batch_size: 25,
            lease_duration: Duration::from_secs(120),
            poll_interval: Duration::from_millis(250),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(300),
        }
    }
}

/// Result counters from one bounded autonomous bootstrap pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WorkspaceAutonomyBootstrapBatchOutcome {
    pub claimed: usize,
    pub completed: usize,
    pub retry_scheduled: usize,
    pub dead_lettered: usize,
    pub failed: usize,
}

/// Polls fenced bootstrap claims and materializes the Objective-to-root projection.
pub struct WorkspaceAutonomyBootstrapWorker {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    config: WorkspaceAutonomyBootstrapWorkerConfig,
}

impl WorkspaceAutonomyBootstrapWorker {
    /// Construct a worker after validating bounded controls.
    pub fn new(
        db: Arc<dyn DbPlugin>,
        sql_flavor: DbSqlFlavor,
        config: WorkspaceAutonomyBootstrapWorkerConfig,
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
                        "Workspace Autonomy bootstrap batch completed"
                    );
                }
                Ok(_) => {
                    tokio::select! {
                        () = shutdown.cancelled() => break,
                        () = tokio::time::sleep(self.config.poll_interval) => {}
                    }
                }
                Err(error) => {
                    tracing::error!(error = %error, "Workspace Autonomy bootstrap polling failed");
                    tokio::select! {
                        () = shutdown.cancelled() => break,
                        () = tokio::time::sleep(self.config.poll_interval) => {}
                    }
                }
            }
        }
    }

    /// Process one bounded claim batch.
    pub async fn advance_once(&self) -> Result<WorkspaceAutonomyBootstrapBatchOutcome> {
        let mut outcome = WorkspaceAutonomyBootstrapBatchOutcome::default();
        let retry_base_ms = duration_ms(self.config.retry_base)?;
        let retry_max_ms = duration_ms(self.config.retry_max)?;
        for _ in 0..self.config.batch_size {
            let claim_now_ms = now_ms()?;
            let lease_expires_at_ms = claim_now_ms
                .checked_add(duration_ms(self.config.lease_duration)?)
                .context("Workspace Autonomy bootstrap lease deadline overflowed")?;
            let bootstrap =
                PublicWorkspaceAutonomyBootstrapService::new(self.db.as_ref(), self.sql_flavor);
            let mut claims = bootstrap
                .claim_bootstraps(
                    self.config.worker_id.as_str(),
                    claim_now_ms,
                    lease_expires_at_ms,
                    1,
                )
                .await
                .context("claim Workspace Autonomy bootstrap")?;
            let Some(claim) = claims.pop() else {
                break;
            };
            outcome.claimed += 1;
            match materialize_root(self.db.as_ref(), self.sql_flavor, &claim).await {
                Ok((objective_id, root_task_id)) => {
                    let completed_at_ms =
                        now_ms().map_or(claim_now_ms, |now| now.max(claim_now_ms));
                    if let Err(error) = bootstrap
                        .complete_bootstrap(
                            &claim,
                            objective_id.as_str(),
                            root_task_id.as_str(),
                            completed_at_ms,
                        )
                        .await
                    {
                        outcome.failed += 1;
                        tracing::error!(
                            workspace_id = %claim.workspace_id,
                            bootstrap_id = %claim.bootstrap_id,
                            attempt_count = claim.attempt_count,
                            error = %error,
                            "Workspace Autonomy bootstrap ACK failed"
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
                        .context("Workspace Autonomy bootstrap retry deadline overflowed")?;
                    match bootstrap
                        .fail_bootstrap(&claim, next_attempt_at_ms, BOOTSTRAP_ERROR_CODE)
                        .await
                    {
                        Ok(failure) => {
                            if failure.dead_lettered {
                                outcome.dead_lettered += 1;
                            } else {
                                outcome.retry_scheduled += 1;
                            }
                            tracing::warn!(
                                workspace_id = %claim.workspace_id,
                                bootstrap_id = %claim.bootstrap_id,
                                attempt_count = failure.attempt_count,
                                dead_lettered = failure.dead_lettered,
                                error = %error,
                                "Workspace Autonomy bootstrap attempt failed"
                            );
                        }
                        Err(release_error) => {
                            outcome.failed += 1;
                            tracing::error!(
                                workspace_id = %claim.workspace_id,
                                bootstrap_id = %claim.bootstrap_id,
                                attempt_count = claim.attempt_count,
                                materialization_error = %error,
                                error = %release_error,
                                "Workspace Autonomy bootstrap failure release failed"
                            );
                        }
                    }
                }
            }
        }
        Ok(outcome)
    }
}

async fn materialize_root(
    db: &dyn DbPlugin,
    sql_flavor: DbSqlFlavor,
    claim: &PublicWorkspaceAutonomyBootstrapClaim,
) -> Result<(String, String)> {
    let objectives = PublicWorkspaceObjectiveService::new(db, sql_flavor);
    let objective = objectives
        .create(&PublicCreateWorkspaceObjectiveInput {
            context: bootstrap_context(claim, "objective"),
            title: claim.objective_title.clone(),
            description: claim.objective_description.clone(),
            objective_type: "objective".to_string(),
            parent_objective_id: None,
            progress: 0.0,
        })
        .await
        .context("create autonomous root Objective")?
        .objective;
    validate_objective(claim, &objective)?;

    let projection = objectives
        .project_to_task(
            &bootstrap_context(claim, "projection"),
            objective.id.as_str(),
            None,
        )
        .await
        .context("project autonomous root Objective")?;
    validate_projection(claim, &objective, &projection)?;
    Ok((objective.id, projection.task.id))
}

fn bootstrap_context(
    claim: &PublicWorkspaceAutonomyBootstrapClaim,
    action: &str,
) -> PublicWorkspaceObjectiveContext {
    PublicWorkspaceObjectiveContext {
        tenant_id: claim.tenant_id.clone(),
        project_id: claim.project_id.clone(),
        workspace_id: claim.workspace_id.clone(),
        user_id: claim.actor_id.clone(),
        is_superuser: false,
        // Read the current revision immediately before each idempotent mutation.
        // A concurrent revision advance therefore becomes a bounded retry, not
        // a permanently stale projection request.
        expected_revision: None,
        idempotency_key: Some(format!(
            "workspace-autonomy-bootstrap-{action}:{}",
            claim.workspace_id
        )),
    }
}

fn validate_objective(
    claim: &PublicWorkspaceAutonomyBootstrapClaim,
    objective: &PublicWorkspaceObjective,
) -> Result<()> {
    if objective.workspace_id != claim.workspace_id
        || objective.title != claim.objective_title
        || objective.description != claim.objective_description
        || objective.obj_type != "objective"
        || objective.parent_id.is_some()
        || objective.progress != 0.0
        || objective.created_by != claim.actor_id
    {
        bail!("autonomous root Objective identity conflicted with its bootstrap snapshot");
    }
    Ok(())
}

fn validate_projection(
    claim: &PublicWorkspaceAutonomyBootstrapClaim,
    objective: &PublicWorkspaceObjective,
    projection: &PublicObjectiveTaskOutcome,
) -> Result<()> {
    let task = &projection.task;
    if task.workspace_id != claim.workspace_id
        || task.title != claim.objective_title
        || task.description != claim.objective_description
        || task.created_by != claim.actor_id
        || task
            .metadata
            .get("task_role")
            .and_then(|value| value.as_str())
            != Some("goal_root")
        || task
            .metadata
            .get("objective_id")
            .and_then(|value| value.as_str())
            != Some(objective.id.as_str())
    {
        bail!("autonomous root Task identity conflicted with its bootstrap snapshot");
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
