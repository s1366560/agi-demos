use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use agistack_adapters_postgres::{
    SkillEvolutionJobInsertRecord, SkillEvolutionJobRecord, SkillEvolutionPipelineSessionRecord,
    SkillEvolutionRunRecord, SkillEvolutionSessionGroupRecord,
};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};

use super::super::evolution_pipeline::{
    PgSkillEvolutionPipelineExecutor, SkillEvolutionDecision, SkillEvolutionDecisionAction,
    SkillEvolutionEvidenceGroup, SkillEvolutionPipelineConfig, SkillEvolutionPipelineStore,
    SkillEvolutionSessionScore, SkillEvolutionSessionSummary, SkillEvolutionStageEngine,
};
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

#[derive(Default)]
struct FakePipelineStore {
    unprocessed: Mutex<Vec<SkillEvolutionPipelineSessionRecord>>,
    unscored: Mutex<Vec<SkillEvolutionPipelineSessionRecord>>,
    groups: Mutex<Vec<SkillEvolutionSessionGroupRecord>>,
    scored: Mutex<Vec<SkillEvolutionPipelineSessionRecord>>,
    existing_job: Mutex<Option<SkillEvolutionJobRecord>>,
    summaries: Mutex<Vec<(String, Value, String)>>,
    scores: Mutex<Vec<(String, Value, f64)>>,
    inserted_jobs: Mutex<Vec<SkillEvolutionJobInsertRecord>>,
    cleanup_count: i64,
}

#[async_trait]
impl SkillEvolutionPipelineStore for FakePipelineStore {
    async fn list_unprocessed_sessions(
        &self,
        _tenant_id: &str,
        _skill_name: Option<&str>,
        _project_id: Option<&str>,
        _filter_project_id: bool,
        _min_skill_sessions: i64,
        _limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError> {
        self.unprocessed
            .lock()
            .map_err(SkillApiError::internal)
            .map(|sessions| sessions.clone())
    }

    async fn update_session_summary(
        &self,
        session_id: &str,
        trajectory: &Value,
        summary: &str,
    ) -> Result<bool, SkillApiError> {
        self.summaries
            .lock()
            .map_err(SkillApiError::internal)?
            .push((
                session_id.to_string(),
                trajectory.clone(),
                summary.to_string(),
            ));
        Ok(true)
    }

    async fn list_unscored_sessions(
        &self,
        _tenant_id: &str,
        _skill_name: Option<&str>,
        _project_id: Option<&str>,
        _filter_project_id: bool,
        _min_skill_sessions: i64,
        _limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError> {
        self.unscored
            .lock()
            .map_err(SkillApiError::internal)
            .map(|sessions| sessions.clone())
    }

    async fn update_session_scores(
        &self,
        session_id: &str,
        judge_scores: &Value,
        overall_score: f64,
    ) -> Result<bool, SkillApiError> {
        self.scores.lock().map_err(SkillApiError::internal)?.push((
            session_id.to_string(),
            judge_scores.clone(),
            overall_score,
        ));
        Ok(true)
    }

    async fn scored_session_groups(
        &self,
        _tenant_id: &str,
        _project_id: Option<&str>,
        _filter_project_id: bool,
        _min_sessions: i64,
        _min_avg_score: f64,
    ) -> Result<Vec<SkillEvolutionSessionGroupRecord>, SkillApiError> {
        self.groups
            .lock()
            .map_err(SkillApiError::internal)
            .map(|groups| groups.clone())
    }

    async fn list_scored_sessions_by_skill(
        &self,
        _tenant_id: &str,
        _skill_name: &str,
        _project_id: Option<&str>,
        _filter_project_id: bool,
        _min_score: Option<f64>,
        _limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError> {
        self.scored
            .lock()
            .map_err(SkillApiError::internal)
            .map(|sessions| sessions.clone())
    }

    async fn get_job_for_sessions(
        &self,
        _tenant_id: &str,
        _skill_name: &str,
        _project_id: Option<&str>,
        _filter_project_id: bool,
        _session_ids: &[String],
        _excluded_statuses: &[&str],
    ) -> Result<Option<SkillEvolutionJobRecord>, SkillApiError> {
        self.existing_job
            .lock()
            .map_err(SkillApiError::internal)
            .map(|job| job.clone())
    }

    async fn insert_job(
        &self,
        job: &SkillEvolutionJobInsertRecord,
    ) -> Result<SkillEvolutionJobRecord, SkillApiError> {
        self.inserted_jobs
            .lock()
            .map_err(SkillApiError::internal)?
            .push(job.clone());
        Ok(job_record_from_insert(job))
    }

    async fn cleanup_old_sessions(&self, _retention_days: i64) -> Result<i64, SkillApiError> {
        Ok(self.cleanup_count)
    }
}

struct ScriptedStageEngine;

#[async_trait]
impl SkillEvolutionStageEngine for ScriptedStageEngine {
    async fn summarize(
        &self,
        session: &SkillEvolutionPipelineSessionRecord,
    ) -> Result<SkillEvolutionSessionSummary, SkillApiError> {
        Ok(SkillEvolutionSessionSummary {
            trajectory: json!({
                "steps": [{"step": 1, "action": "reviewed", "outcome": "success"}],
                "source_session_id": session.id
            }),
            summary: format!("summary for {}", session.id),
        })
    }

    async fn judge(
        &self,
        session: &SkillEvolutionPipelineSessionRecord,
    ) -> Result<SkillEvolutionSessionScore, SkillApiError> {
        SkillEvolutionSessionScore::new(
            json!({
                "task_completion": 0.9,
                "response_quality": 0.8,
                "efficiency": 0.7,
                "tool_usage": 0.8,
                "rationale": format!("{} is useful", session.id)
            }),
            0.82,
        )
    }

    async fn evolve(
        &self,
        group: &SkillEvolutionEvidenceGroup,
    ) -> Result<Option<SkillEvolutionDecision>, SkillApiError> {
        Ok(Some(SkillEvolutionDecision {
            action: SkillEvolutionDecisionAction::ImproveSkill,
            rationale: Some(format!(
                "{} sessions support an improvement",
                group.session_count
            )),
            candidate_content: Some(format!("# {}\nImprove review guidance.", group.skill_name)),
        }))
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

#[test]
fn skill_evolution_pipeline_config_from_env_has_safe_defaults() {
    let config = SkillEvolutionPipelineConfig::from_env();

    assert!(config.min_sessions_per_skill >= 1);
    assert!(config.scoring_min_sessions_per_skill >= 1);
    assert!((0.0..=1.0).contains(&config.min_avg_score));
    assert!(config.max_sessions_per_batch >= 1);
    assert!(config.session_retention_days >= 1);
}

#[test]
fn skill_evolution_decision_actions_preserve_python_wire_values() {
    assert_eq!(
        SkillEvolutionDecisionAction::CreateSkill.as_str(),
        "create_skill"
    );
    assert_eq!(
        SkillEvolutionDecisionAction::ImproveSkill.as_str(),
        "improve_skill"
    );
    assert_eq!(
        SkillEvolutionDecisionAction::OptimizeDescription.as_str(),
        "optimize_description"
    );
    assert_eq!(SkillEvolutionDecisionAction::Skip.as_str(), "skip");
}

#[tokio::test]
async fn skill_evolution_pipeline_executor_runs_all_data_plane_stages() {
    let session = sample_pipeline_session("sess-pipeline-1");
    let store = Arc::new(FakePipelineStore {
        unprocessed: Mutex::new(vec![session.clone()]),
        unscored: Mutex::new(vec![session.clone()]),
        groups: Mutex::new(vec![sample_session_group()]),
        scored: Mutex::new(vec![session]),
        cleanup_count: 3,
        ..Default::default()
    });
    let executor = PgSkillEvolutionPipelineExecutor::with_parts(
        Arc::clone(&store) as Arc<dyn SkillEvolutionPipelineStore>,
        Arc::new(ScriptedStageEngine),
        SkillEvolutionPipelineConfig {
            min_sessions_per_skill: 1,
            scoring_min_sessions_per_skill: 1,
            max_sessions_per_batch: 10,
            ..Default::default()
        },
    );

    let summary = executor
        .execute(&sample_run_record("run-pipeline-1"))
        .await
        .unwrap();

    assert_eq!(summary.summarized, 1);
    assert_eq!(summary.judged, 1);
    assert_eq!(summary.groups, 1);
    assert_eq!(summary.jobs, 1);
    assert_eq!(summary.cleaned, 3);
    let summaries = store.summaries.lock().unwrap();
    assert_eq!(summaries[0].0, "sess-pipeline-1");
    assert_eq!(summaries[0].2, "summary for sess-pipeline-1");
    let scores = store.scores.lock().unwrap();
    assert_eq!(scores[0].0, "sess-pipeline-1");
    assert!((scores[0].2 - 0.82).abs() < 0.000_001);
    let jobs = store.inserted_jobs.lock().unwrap();
    assert_eq!(jobs.len(), 1);
    assert!(jobs[0].id.starts_with("evj-"));
    assert_eq!(jobs[0].tenant_id, "tenant-1");
    assert_eq!(jobs[0].project_id.as_deref(), Some("project-1"));
    assert_eq!(jobs[0].skill_name, "code-review");
    assert_eq!(jobs[0].action, "improve_skill");
    assert_eq!(jobs[0].status, "pending_review");
    assert_eq!(jobs[0].session_ids, vec!["sess-pipeline-1".to_string()]);
}

#[tokio::test]
async fn skill_evolution_pipeline_executor_blocks_duplicate_pending_review_job() {
    let session = sample_pipeline_session("sess-duplicate-1");
    let store = Arc::new(FakePipelineStore {
        groups: Mutex::new(vec![sample_session_group()]),
        scored: Mutex::new(vec![session]),
        existing_job: Mutex::new(Some(SkillEvolutionJobRecord {
            id: "job-existing".to_string(),
            tenant_id: "tenant-1".to_string(),
            project_id: Some("project-1".to_string()),
            skill_name: "code-review".to_string(),
            action: "improve_skill".to_string(),
            status: "pending_review".to_string(),
            rationale: Some("already waiting".to_string()),
            candidate_content: Some("candidate".to_string()),
            session_ids: vec!["sess-duplicate-1".to_string()],
            skill_version_id: None,
            created_at: test_time(),
            applied_at: None,
        })),
        ..Default::default()
    });
    let executor = PgSkillEvolutionPipelineExecutor::with_parts(
        Arc::clone(&store) as Arc<dyn SkillEvolutionPipelineStore>,
        Arc::new(ScriptedStageEngine),
        SkillEvolutionPipelineConfig {
            min_sessions_per_skill: 1,
            scoring_min_sessions_per_skill: 1,
            max_sessions_per_batch: 10,
            ..Default::default()
        },
    );

    let summary = executor
        .execute(&sample_run_record("run-pipeline-duplicate"))
        .await
        .unwrap();

    assert_eq!(summary.groups, 1);
    assert_eq!(summary.jobs, 0);
    assert_eq!(summary.blocked_by_review, 1);
    assert!(store.inserted_jobs.lock().unwrap().is_empty());
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
        created_at: test_time(),
        updated_at: None,
    }
}

fn sample_pipeline_session(id: &str) -> SkillEvolutionPipelineSessionRecord {
    SkillEvolutionPipelineSessionRecord {
        id: id.to_string(),
        skill_name: "code-review".to_string(),
        conversation_id: format!("conv-{id}"),
        project_id: Some("project-1".to_string()),
        user_query: "review this patch".to_string(),
        trajectory: Some(json!({"steps": []})),
        summary: None,
        judge_scores: None,
        overall_score: None,
        success: true,
        execution_time_ms: 100,
        tool_call_count: 2,
        processed: false,
        created_at: test_time(),
    }
}

fn sample_session_group() -> SkillEvolutionSessionGroupRecord {
    SkillEvolutionSessionGroupRecord {
        skill_name: "code-review".to_string(),
        project_id: Some("project-1".to_string()),
        session_count: 1,
        avg_score: 0.82,
        success_count: 1,
    }
}

fn job_record_from_insert(job: &SkillEvolutionJobInsertRecord) -> SkillEvolutionJobRecord {
    SkillEvolutionJobRecord {
        id: job.id.clone(),
        tenant_id: job.tenant_id.clone(),
        project_id: job.project_id.clone(),
        skill_name: job.skill_name.clone(),
        action: job.action.clone(),
        status: job.status.clone(),
        rationale: job.rationale.clone(),
        candidate_content: job.candidate_content.clone(),
        session_ids: job.session_ids.clone(),
        skill_version_id: None,
        created_at: test_time(),
        applied_at: None,
    }
}

fn test_time() -> DateTime<Utc> {
    DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap()
}
