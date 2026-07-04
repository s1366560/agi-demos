use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use agistack_adapters_postgres::SkillEvolutionRunRecord;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};

use super::super::evolution_worker::{
    PgSkillEvolutionWorker, SkillEvolutionExecutionSummary, SkillEvolutionRunExecutor,
    SkillEvolutionRunQueue, SkillEvolutionWorkerConfig, SkillEvolutionWorkerRunReport,
};
use super::super::SkillApiError;

#[derive(Default)]
struct FakeRunQueue {
    pending: Mutex<VecDeque<SkillEvolutionRunRecord>>,
    completed: Mutex<Vec<(String, Value)>>,
    failed: Mutex<Vec<(String, String)>>,
}

impl FakeRunQueue {
    fn with_run(run: SkillEvolutionRunRecord) -> Self {
        Self {
            pending: Mutex::new(VecDeque::from([run])),
            completed: Mutex::new(Vec::new()),
            failed: Mutex::new(Vec::new()),
        }
    }
}

#[async_trait]
impl SkillEvolutionRunQueue for FakeRunQueue {
    async fn claim_next(
        &self,
        worker_id: &str,
    ) -> Result<Option<SkillEvolutionRunRecord>, SkillApiError> {
        let mut pending = self.pending.lock().map_err(SkillApiError::internal)?;
        let Some(mut run) = pending.pop_front() else {
            return Ok(None);
        };
        run.status = "running".to_string();
        run.worker_id = Some(worker_id.to_string());
        run.attempts += 1;
        Ok(Some(run))
    }

    async fn complete(
        &self,
        run_id: &str,
        _worker_id: Option<&str>,
        result_json: &Value,
    ) -> Result<bool, SkillApiError> {
        self.completed
            .lock()
            .map_err(SkillApiError::internal)?
            .push((run_id.to_string(), result_json.clone()));
        Ok(true)
    }

    async fn fail(
        &self,
        run_id: &str,
        _worker_id: Option<&str>,
        error: &str,
    ) -> Result<bool, SkillApiError> {
        self.failed
            .lock()
            .map_err(SkillApiError::internal)?
            .push((run_id.to_string(), error.to_string()));
        Ok(true)
    }
}

struct SummaryExecutor;

#[async_trait]
impl SkillEvolutionRunExecutor for SummaryExecutor {
    async fn execute(
        &self,
        run: &SkillEvolutionRunRecord,
    ) -> Result<SkillEvolutionExecutionSummary, SkillApiError> {
        assert_eq!(run.status, "running");
        assert_eq!(run.attempts, 1);
        Ok(SkillEvolutionExecutionSummary {
            skipped: false,
            reason: None,
            summarized: 2,
            judged: 2,
            groups: 1,
            jobs: 1,
            blocked_by_review: 0,
            cleaned: 0,
        })
    }
}

struct FailingExecutor;

#[async_trait]
impl SkillEvolutionRunExecutor for FailingExecutor {
    async fn execute(
        &self,
        _run: &SkillEvolutionRunRecord,
    ) -> Result<SkillEvolutionExecutionSummary, SkillApiError> {
        Err(SkillApiError::internal("llm provider unavailable"))
    }
}

#[tokio::test]
async fn skill_evolution_worker_completes_claimed_run_with_summary() {
    let queue = Arc::new(FakeRunQueue::with_run(sample_run_record("run-1")));
    let worker = PgSkillEvolutionWorker::with_parts(
        Arc::clone(&queue) as Arc<dyn SkillEvolutionRunQueue>,
        Arc::new(SummaryExecutor),
        SkillEvolutionWorkerConfig::default(),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(report.claimed, 1);
    assert_eq!(report.completed, 1);
    assert_eq!(report.failed, 0);
    let completed = queue.completed.lock().unwrap();
    assert_eq!(completed[0].0, "run-1");
    assert_eq!(completed[0].1["summarized"], json!(2));
    assert_eq!(completed[0].1["jobs"], json!(1));
}

#[tokio::test]
async fn skill_evolution_worker_marks_claimed_run_failed_on_executor_error() {
    let queue = Arc::new(FakeRunQueue::with_run(sample_run_record("run-2")));
    let worker = PgSkillEvolutionWorker::with_parts(
        Arc::clone(&queue) as Arc<dyn SkillEvolutionRunQueue>,
        Arc::new(FailingExecutor),
        SkillEvolutionWorkerConfig::default(),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(report.claimed, 1);
    assert_eq!(report.completed, 0);
    assert_eq!(report.failed, 1);
    let failed = queue.failed.lock().unwrap();
    assert_eq!(
        failed[0],
        ("run-2".to_string(), "llm provider unavailable".to_string())
    );
}

#[tokio::test]
async fn skill_evolution_worker_reports_empty_queue_without_side_effects() {
    let queue = Arc::new(FakeRunQueue::default());
    let worker = PgSkillEvolutionWorker::with_parts(
        Arc::clone(&queue) as Arc<dyn SkillEvolutionRunQueue>,
        Arc::new(SummaryExecutor),
        SkillEvolutionWorkerConfig::default(),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(report, SkillEvolutionWorkerRunReport::default());
    assert!(queue.completed.lock().unwrap().is_empty());
    assert!(queue.failed.lock().unwrap().is_empty());
}

fn sample_run_record(id: &str) -> SkillEvolutionRunRecord {
    SkillEvolutionRunRecord {
        id: id.to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: Some("project-1".to_string()),
        skill_name: Some("code-review".to_string()),
        reason: "manual".to_string(),
        status: "queued".to_string(),
        attempts: 0,
        worker_id: None,
        started_at: None,
        completed_at: None,
        last_error: None,
        result_json: None,
        created_at: DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap(),
        updated_at: None,
    }
}
