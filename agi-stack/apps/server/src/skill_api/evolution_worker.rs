use std::sync::Arc;
use std::time::Duration;

use agistack_adapters_postgres::{PgSkillEvolutionRepository, SkillEvolutionRunRecord};
use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::task::JoinHandle;
use tokio::time::sleep;

use super::*;

pub(crate) type SharedSkillEvolutionWorker = Arc<PgSkillEvolutionWorker>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SkillEvolutionWorkerConfig {
    pub(crate) worker_id: String,
    pub(crate) poll_interval_millis: u64,
    pub(crate) autostart: bool,
    pub(crate) production_ready: bool,
}

impl SkillEvolutionWorkerConfig {
    pub(crate) fn from_env() -> Self {
        Self {
            worker_id: std::env::var("AGISTACK_SKILL_EVOLUTION_WORKER_ID")
                .ok()
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| "agistack-rust-skill-evolution".to_string()),
            poll_interval_millis: positive_millis_env(
                "AGISTACK_SKILL_EVOLUTION_POLL_SECONDS",
                2000,
            ),
            autostart: bool_env("AGISTACK_SKILL_EVOLUTION_WORKER_AUTOSTART", false),
            production_ready: bool_env("AGISTACK_SKILL_EVOLUTION_ENGINE_READY", false),
        }
    }
}

impl Default for SkillEvolutionWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: "agistack-rust-skill-evolution".to_string(),
            poll_interval_millis: 2000,
            autostart: false,
            production_ready: false,
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct SkillEvolutionWorkerRunReport {
    pub(crate) claimed: usize,
    pub(crate) completed: usize,
    pub(crate) failed: usize,
    pub(crate) skipped: usize,
}

pub(crate) struct SkillEvolutionWorkerRuntime {
    join: Option<JoinHandle<()>>,
}

impl Drop for SkillEvolutionWorkerRuntime {
    fn drop(&mut self) {
        if let Some(join) = &self.join {
            join.abort();
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SkillEvolutionExecutionSummary {
    pub(crate) skipped: bool,
    pub(crate) reason: Option<String>,
    pub(crate) summarized: i64,
    pub(crate) judged: i64,
    pub(crate) groups: i64,
    pub(crate) jobs: i64,
    pub(crate) blocked_by_review: i64,
    pub(crate) cleaned: i64,
}

impl SkillEvolutionExecutionSummary {
    pub(crate) fn skipped(reason: impl Into<String>) -> Self {
        Self {
            skipped: true,
            reason: Some(reason.into()),
            summarized: 0,
            judged: 0,
            groups: 0,
            jobs: 0,
            blocked_by_review: 0,
            cleaned: 0,
        }
    }

    fn to_json(&self) -> Value {
        json!({
            "skipped": self.skipped,
            "reason": self.reason,
            "summarized": self.summarized,
            "judged": self.judged,
            "groups": self.groups,
            "jobs": self.jobs,
            "blocked_by_review": self.blocked_by_review,
            "cleaned": self.cleaned,
        })
    }
}

#[async_trait]
pub(crate) trait SkillEvolutionRunExecutor: Send + Sync {
    async fn execute(
        &self,
        run: &SkillEvolutionRunRecord,
    ) -> Result<SkillEvolutionExecutionSummary, SkillApiError>;
}

#[derive(Debug, Default)]
pub(crate) struct EngineUnavailableSkillEvolutionExecutor;

#[async_trait]
impl SkillEvolutionRunExecutor for EngineUnavailableSkillEvolutionExecutor {
    async fn execute(
        &self,
        _run: &SkillEvolutionRunRecord,
    ) -> Result<SkillEvolutionExecutionSummary, SkillApiError> {
        Ok(SkillEvolutionExecutionSummary::skipped(
            "engine_unavailable",
        ))
    }
}

#[async_trait]
pub(crate) trait SkillEvolutionRunQueue: Send + Sync {
    async fn claim_next(
        &self,
        worker_id: &str,
    ) -> Result<Option<SkillEvolutionRunRecord>, SkillApiError>;

    async fn complete(
        &self,
        run_id: &str,
        worker_id: Option<&str>,
        result_json: &Value,
    ) -> Result<bool, SkillApiError>;

    async fn fail(
        &self,
        run_id: &str,
        worker_id: Option<&str>,
        error: &str,
    ) -> Result<bool, SkillApiError>;
}

#[async_trait]
impl SkillEvolutionRunQueue for PgSkillEvolutionRepository {
    async fn claim_next(
        &self,
        worker_id: &str,
    ) -> Result<Option<SkillEvolutionRunRecord>, SkillApiError> {
        self.claim_next_evolution_run(worker_id)
            .await
            .map_err(SkillApiError::internal)
    }

    async fn complete(
        &self,
        run_id: &str,
        worker_id: Option<&str>,
        result_json: &Value,
    ) -> Result<bool, SkillApiError> {
        self.complete_evolution_run(run_id, worker_id, result_json)
            .await
            .map_err(SkillApiError::internal)
    }

    async fn fail(
        &self,
        run_id: &str,
        worker_id: Option<&str>,
        error: &str,
    ) -> Result<bool, SkillApiError> {
        self.fail_evolution_run(run_id, worker_id, error)
            .await
            .map_err(SkillApiError::internal)
    }
}

pub(crate) struct PgSkillEvolutionWorker {
    queue: Arc<dyn SkillEvolutionRunQueue>,
    executor: Arc<dyn SkillEvolutionRunExecutor>,
    config: SkillEvolutionWorkerConfig,
}

impl PgSkillEvolutionWorker {
    pub(crate) fn new(
        repo: PgSkillEvolutionRepository,
        executor: Arc<dyn SkillEvolutionRunExecutor>,
    ) -> Self {
        Self {
            queue: Arc::new(repo),
            executor,
            config: SkillEvolutionWorkerConfig::from_env(),
        }
    }

    #[cfg(test)]
    pub(crate) fn with_parts(
        queue: Arc<dyn SkillEvolutionRunQueue>,
        executor: Arc<dyn SkillEvolutionRunExecutor>,
        config: SkillEvolutionWorkerConfig,
    ) -> Self {
        Self {
            queue,
            executor,
            config,
        }
    }

    pub(crate) fn spawn_if_enabled(self: Arc<Self>) -> Option<SkillEvolutionWorkerRuntime> {
        if !self.config.autostart {
            return None;
        }
        if !self.config.production_ready {
            eprintln!(
                "[agistack] skill evolution worker: autostart requested but engine readiness gate is disabled (set AGISTACK_SKILL_EVOLUTION_ENGINE_READY=true after full engine parity); not consuming queue"
            );
            return None;
        }
        let worker = Arc::clone(&self);
        let join = tokio::spawn(async move {
            worker.run_loop().await;
        });
        Some(SkillEvolutionWorkerRuntime { join: Some(join) })
    }

    pub(crate) async fn run_once(&self) -> Result<SkillEvolutionWorkerRunReport, SkillApiError> {
        let Some(run) = self.queue.claim_next(&self.config.worker_id).await? else {
            return Ok(SkillEvolutionWorkerRunReport::default());
        };
        let mut report = SkillEvolutionWorkerRunReport {
            claimed: 1,
            ..Default::default()
        };
        let run_id = run.id.clone();
        match self.executor.execute(&run).await {
            Ok(summary) => {
                if self
                    .queue
                    .complete(&run_id, Some(&self.config.worker_id), &summary.to_json())
                    .await?
                {
                    report.completed = 1;
                } else {
                    report.skipped = 1;
                }
            }
            Err(err) => {
                if self
                    .queue
                    .fail(&run_id, Some(&self.config.worker_id), &err.detail)
                    .await?
                {
                    report.failed = 1;
                } else {
                    report.skipped = 1;
                }
            }
        }
        Ok(report)
    }

    async fn run_loop(self: Arc<Self>) {
        loop {
            if let Err(err) = self.run_once().await {
                eprintln!(
                    "[agistack] skill evolution worker poll failed: {}",
                    err.detail
                );
            }
            sleep(Duration::from_millis(
                self.config.poll_interval_millis.max(1),
            ))
            .await;
        }
    }
}

fn bool_env(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<bool>().ok())
        .unwrap_or(default)
}

fn positive_millis_env(name: &str, default: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}
