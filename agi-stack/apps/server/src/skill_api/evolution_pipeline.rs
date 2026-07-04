use std::sync::Arc;

use agistack_adapters_postgres::{
    PgSkillEvolutionRepository, SkillEvolutionJobInsertRecord, SkillEvolutionJobRecord,
    SkillEvolutionPipelineSessionRecord, SkillEvolutionRunRecord, SkillEvolutionSessionGroupRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use async_trait::async_trait;
use serde_json::Value;

use super::evolution_worker::{SkillEvolutionExecutionSummary, SkillEvolutionRunExecutor};
use super::SkillApiError;

#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) struct SkillEvolutionPipelineConfig {
    pub(crate) enabled: bool,
    pub(crate) min_sessions_per_skill: i64,
    pub(crate) scoring_min_sessions_per_skill: i64,
    pub(crate) min_avg_score: f64,
    pub(crate) max_sessions_per_batch: i64,
    pub(crate) session_retention_days: i64,
}

impl SkillEvolutionPipelineConfig {
    pub(crate) fn from_env() -> Self {
        Self {
            enabled: bool_env("SKILL_EVOLUTION_ENABLED", true),
            min_sessions_per_skill: positive_i64_env("SKILL_EVOLUTION_MIN_SESSIONS", 5),
            scoring_min_sessions_per_skill: positive_i64_env(
                "SKILL_EVOLUTION_SCORING_MIN_SESSIONS",
                5,
            ),
            min_avg_score: f64_env("SKILL_EVOLUTION_MIN_AVG_SCORE", 0.6).clamp(0.0, 1.0),
            max_sessions_per_batch: positive_i64_env("SKILL_EVOLUTION_MAX_SESSIONS_PER_BATCH", 50),
            session_retention_days: positive_i64_env("SKILL_EVOLUTION_SESSION_RETENTION_DAYS", 30),
        }
    }
}

impl Default for SkillEvolutionPipelineConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            min_sessions_per_skill: 5,
            scoring_min_sessions_per_skill: 5,
            min_avg_score: 0.6,
            max_sessions_per_batch: 50,
            session_retention_days: 30,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct SkillEvolutionSessionSummary {
    pub(crate) trajectory: Value,
    pub(crate) summary: String,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct SkillEvolutionSessionScore {
    pub(crate) judge_scores: Value,
    pub(crate) overall_score: f64,
}

impl SkillEvolutionSessionScore {
    #[allow(dead_code)]
    pub(crate) fn new(judge_scores: Value, overall_score: f64) -> Result<Self, SkillApiError> {
        if !(0.0..=1.0).contains(&overall_score) {
            return Err(SkillApiError::internal(
                "skill evolution judge score out of range",
            ));
        }
        Ok(Self {
            judge_scores,
            overall_score,
        })
    }
}

#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SkillEvolutionDecisionAction {
    CreateSkill,
    ImproveSkill,
    OptimizeDescription,
    Skip,
}

impl SkillEvolutionDecisionAction {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::CreateSkill => "create_skill",
            Self::ImproveSkill => "improve_skill",
            Self::OptimizeDescription => "optimize_description",
            Self::Skip => "skip",
        }
    }

    fn status(self) -> &'static str {
        match self {
            Self::Skip => "skipped",
            Self::CreateSkill | Self::ImproveSkill | Self::OptimizeDescription => "pending_review",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct SkillEvolutionDecision {
    pub(crate) action: SkillEvolutionDecisionAction,
    pub(crate) rationale: Option<String>,
    pub(crate) candidate_content: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct SkillEvolutionEvidenceGroup {
    pub(crate) skill_name: String,
    pub(crate) project_id: Option<String>,
    pub(crate) session_count: i64,
    pub(crate) avg_score: f64,
    pub(crate) success_count: i64,
    pub(crate) sessions: Vec<SkillEvolutionPipelineSessionRecord>,
}

#[async_trait]
pub(crate) trait SkillEvolutionPipelineStore: Send + Sync {
    async fn list_unprocessed_sessions(
        &self,
        tenant_id: &str,
        skill_name: Option<&str>,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_skill_sessions: i64,
        limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError>;

    async fn update_session_summary(
        &self,
        session_id: &str,
        trajectory: &Value,
        summary: &str,
    ) -> Result<bool, SkillApiError>;

    async fn list_unscored_sessions(
        &self,
        tenant_id: &str,
        skill_name: Option<&str>,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_skill_sessions: i64,
        limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError>;

    async fn update_session_scores(
        &self,
        session_id: &str,
        judge_scores: &Value,
        overall_score: f64,
    ) -> Result<bool, SkillApiError>;

    async fn scored_session_groups(
        &self,
        tenant_id: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_sessions: i64,
        min_avg_score: f64,
    ) -> Result<Vec<SkillEvolutionSessionGroupRecord>, SkillApiError>;

    async fn list_scored_sessions_by_skill(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_score: Option<f64>,
        limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError>;

    async fn get_job_for_sessions(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        session_ids: &[String],
        excluded_statuses: &[&str],
    ) -> Result<Option<SkillEvolutionJobRecord>, SkillApiError>;

    async fn insert_job(
        &self,
        job: &SkillEvolutionJobInsertRecord,
    ) -> Result<SkillEvolutionJobRecord, SkillApiError>;

    async fn cleanup_old_sessions(&self, retention_days: i64) -> Result<i64, SkillApiError>;
}

#[async_trait]
impl SkillEvolutionPipelineStore for PgSkillEvolutionRepository {
    async fn list_unprocessed_sessions(
        &self,
        tenant_id: &str,
        skill_name: Option<&str>,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_skill_sessions: i64,
        limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError> {
        PgSkillEvolutionRepository::list_unprocessed_sessions(
            self,
            tenant_id,
            skill_name,
            project_id,
            filter_project_id,
            min_skill_sessions,
            limit,
        )
        .await
        .map_err(SkillApiError::internal)
    }

    async fn update_session_summary(
        &self,
        session_id: &str,
        trajectory: &Value,
        summary: &str,
    ) -> Result<bool, SkillApiError> {
        PgSkillEvolutionRepository::update_session_summary(self, session_id, trajectory, summary)
            .await
            .map_err(SkillApiError::internal)
    }

    async fn list_unscored_sessions(
        &self,
        tenant_id: &str,
        skill_name: Option<&str>,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_skill_sessions: i64,
        limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError> {
        PgSkillEvolutionRepository::list_unscored_sessions(
            self,
            tenant_id,
            skill_name,
            project_id,
            filter_project_id,
            min_skill_sessions,
            limit,
        )
        .await
        .map_err(SkillApiError::internal)
    }

    async fn update_session_scores(
        &self,
        session_id: &str,
        judge_scores: &Value,
        overall_score: f64,
    ) -> Result<bool, SkillApiError> {
        PgSkillEvolutionRepository::update_session_scores(
            self,
            session_id,
            judge_scores,
            overall_score,
        )
        .await
        .map_err(SkillApiError::internal)
    }

    async fn scored_session_groups(
        &self,
        tenant_id: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_sessions: i64,
        min_avg_score: f64,
    ) -> Result<Vec<SkillEvolutionSessionGroupRecord>, SkillApiError> {
        PgSkillEvolutionRepository::scored_session_groups(
            self,
            tenant_id,
            project_id,
            filter_project_id,
            min_sessions,
            min_avg_score,
        )
        .await
        .map_err(SkillApiError::internal)
    }

    async fn list_scored_sessions_by_skill(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_score: Option<f64>,
        limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError> {
        PgSkillEvolutionRepository::list_scored_sessions_by_skill(
            self,
            tenant_id,
            skill_name,
            project_id,
            filter_project_id,
            min_score,
            limit,
        )
        .await
        .map_err(SkillApiError::internal)
    }

    async fn get_job_for_sessions(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        session_ids: &[String],
        excluded_statuses: &[&str],
    ) -> Result<Option<SkillEvolutionJobRecord>, SkillApiError> {
        PgSkillEvolutionRepository::get_job_for_sessions(
            self,
            tenant_id,
            skill_name,
            project_id,
            filter_project_id,
            session_ids,
            excluded_statuses,
        )
        .await
        .map_err(SkillApiError::internal)
    }

    async fn insert_job(
        &self,
        job: &SkillEvolutionJobInsertRecord,
    ) -> Result<SkillEvolutionJobRecord, SkillApiError> {
        PgSkillEvolutionRepository::insert_job(self, job)
            .await
            .map_err(SkillApiError::internal)
    }

    async fn cleanup_old_sessions(&self, retention_days: i64) -> Result<i64, SkillApiError> {
        PgSkillEvolutionRepository::cleanup_old_sessions(self, retention_days)
            .await
            .map_err(SkillApiError::internal)
    }
}

#[async_trait]
pub(crate) trait SkillEvolutionStageEngine: Send + Sync {
    async fn summarize(
        &self,
        session: &SkillEvolutionPipelineSessionRecord,
    ) -> Result<SkillEvolutionSessionSummary, SkillApiError>;

    async fn judge(
        &self,
        session: &SkillEvolutionPipelineSessionRecord,
    ) -> Result<SkillEvolutionSessionScore, SkillApiError>;

    async fn evolve(
        &self,
        group: &SkillEvolutionEvidenceGroup,
    ) -> Result<Option<SkillEvolutionDecision>, SkillApiError>;
}

pub(crate) struct PgSkillEvolutionPipelineExecutor {
    store: Arc<dyn SkillEvolutionPipelineStore>,
    engine: Arc<dyn SkillEvolutionStageEngine>,
    config: SkillEvolutionPipelineConfig,
}

impl PgSkillEvolutionPipelineExecutor {
    #[allow(dead_code)]
    pub(crate) fn new(
        repo: PgSkillEvolutionRepository,
        engine: Arc<dyn SkillEvolutionStageEngine>,
    ) -> Self {
        Self {
            store: Arc::new(repo),
            engine,
            config: SkillEvolutionPipelineConfig::from_env(),
        }
    }

    #[cfg(test)]
    pub(crate) fn with_parts(
        store: Arc<dyn SkillEvolutionPipelineStore>,
        engine: Arc<dyn SkillEvolutionStageEngine>,
        config: SkillEvolutionPipelineConfig,
    ) -> Self {
        Self {
            store,
            engine,
            config,
        }
    }
}

#[async_trait]
impl SkillEvolutionRunExecutor for PgSkillEvolutionPipelineExecutor {
    async fn execute(
        &self,
        run: &SkillEvolutionRunRecord,
    ) -> Result<SkillEvolutionExecutionSummary, SkillApiError> {
        if !self.config.enabled {
            return Ok(SkillEvolutionExecutionSummary::skipped("disabled"));
        }

        let tenant_id = run.tenant_id.as_str();
        let skill_name = run
            .skill_name
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty());
        let project_id = run
            .project_id
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty());
        let filter_project_id = skill_name.is_some() || project_id.is_some();
        let mut summary = SkillEvolutionExecutionSummary {
            skipped: false,
            reason: None,
            summarized: 0,
            judged: 0,
            groups: 0,
            jobs: 0,
            blocked_by_review: 0,
            cleaned: 0,
        };

        let unprocessed = self
            .store
            .list_unprocessed_sessions(
                tenant_id,
                skill_name,
                project_id,
                filter_project_id,
                self.config.scoring_min_sessions_per_skill,
                self.config.max_sessions_per_batch,
            )
            .await?;
        for session in &unprocessed {
            let session_summary = self.engine.summarize(session).await?;
            if self
                .store
                .update_session_summary(
                    &session.id,
                    &session_summary.trajectory,
                    &session_summary.summary,
                )
                .await?
            {
                summary.summarized += 1;
            }
        }

        let unscored = self
            .store
            .list_unscored_sessions(
                tenant_id,
                skill_name,
                project_id,
                filter_project_id,
                self.config.scoring_min_sessions_per_skill,
                self.config.max_sessions_per_batch,
            )
            .await?;
        for session in &unscored {
            let score = self.engine.judge(session).await?;
            if self
                .store
                .update_session_scores(&session.id, &score.judge_scores, score.overall_score)
                .await?
            {
                summary.judged += 1;
            }
        }

        let groups = self
            .store
            .scored_session_groups(
                tenant_id,
                project_id,
                filter_project_id,
                self.config.min_sessions_per_skill,
                self.config.min_avg_score,
            )
            .await?;
        for group in groups {
            if skill_name.is_some_and(|name| name != group.skill_name) {
                continue;
            }
            let sessions = self
                .store
                .list_scored_sessions_by_skill(
                    tenant_id,
                    &group.skill_name,
                    group.project_id.as_deref(),
                    true,
                    Some(self.config.min_avg_score),
                    self.config.max_sessions_per_batch,
                )
                .await?;
            if sessions.is_empty() {
                continue;
            }
            summary.groups += 1;
            let session_ids: Vec<String> =
                sessions.iter().map(|session| session.id.clone()).collect();
            if let Some(existing) = self
                .store
                .get_job_for_sessions(
                    tenant_id,
                    &group.skill_name,
                    group.project_id.as_deref(),
                    true,
                    &session_ids,
                    &["rejected"],
                )
                .await?
            {
                if existing.status == "pending_review" {
                    summary.blocked_by_review += 1;
                }
                continue;
            }
            let evidence = SkillEvolutionEvidenceGroup {
                skill_name: group.skill_name,
                project_id: group.project_id,
                session_count: group.session_count,
                avg_score: group.avg_score,
                success_count: group.success_count,
                sessions,
            };
            let Some(decision) = self.engine.evolve(&evidence).await? else {
                continue;
            };
            let job = SkillEvolutionJobInsertRecord {
                id: evolution_job_id(),
                tenant_id: tenant_id.to_string(),
                project_id: evidence.project_id.clone(),
                skill_name: evidence.skill_name.clone(),
                action: decision.action.as_str().to_string(),
                status: decision.action.status().to_string(),
                rationale: decision.rationale,
                candidate_content: decision.candidate_content,
                session_ids,
            };
            self.store.insert_job(&job).await?;
            summary.jobs += 1;
        }

        summary.cleaned = self
            .store
            .cleanup_old_sessions(self.config.session_retention_days)
            .await?;
        Ok(summary)
    }
}

fn bool_env(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<bool>().ok())
        .unwrap_or(default)
}

fn positive_i64_env(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<i64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn f64_env(name: &str, default: f64) -> f64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .unwrap_or(default)
}

fn evolution_job_id() -> String {
    let hex: String = generate_uuid_v4()
        .chars()
        .filter(|ch| *ch != '-')
        .take(16)
        .collect();
    format!("evj-{hex}")
}
