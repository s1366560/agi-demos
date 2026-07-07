use std::collections::BTreeMap;
use std::sync::Arc;

use agistack_adapters_postgres::{
    PgSkillEvolutionRepository, PgSkillRepository, SkillEvolutionJobAuditEventInsertRecord,
    SkillEvolutionJobInsertRecord, SkillEvolutionJobRecord, SkillEvolutionPipelineSessionRecord,
    SkillEvolutionRunRecord, SkillEvolutionSessionGroupRecord, SkillRecord, SkillUpdateRecord,
    SkillVersionRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use async_trait::async_trait;
use chrono::Utc;
use serde_json::{json, Value};

use super::evolution_worker::{SkillEvolutionExecutionSummary, SkillEvolutionRunExecutor};
use super::{
    evolution_change_summary, evolution_job_scope, replace_frontmatter_description,
    ParsedImportPackage, SkillApiError, SkillImportPayload,
};

#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) struct SkillEvolutionPipelineConfig {
    pub(crate) enabled: bool,
    pub(crate) min_sessions_per_skill: i64,
    pub(crate) scoring_min_sessions_per_skill: i64,
    pub(crate) min_avg_score: f64,
    pub(crate) max_sessions_per_batch: i64,
    pub(crate) session_retention_days: i64,
    pub(crate) auto_apply: bool,
    pub(crate) auto_apply_production_ready: bool,
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
            auto_apply: bool_env("SKILL_EVOLUTION_AUTO_APPLY", false),
            auto_apply_production_ready: bool_env(
                "AGISTACK_SKILL_EVOLUTION_AUTO_APPLY_PRODUCTION_READY",
                false,
            ),
        }
    }

    fn auto_apply_enabled(&self) -> bool {
        self.auto_apply && self.auto_apply_production_ready
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
            auto_apply: false,
            auto_apply_production_ready: false,
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
    pub(crate) current_skill_content: Option<String>,
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

    async fn current_skill_content(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
    ) -> Result<Option<String>, SkillApiError>;

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

    async fn apply_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError>;

    async fn update_job_status(
        &self,
        tenant_id: &str,
        job_id: &str,
        status: &str,
        skill_version_id: Option<&str>,
    ) -> Result<Option<SkillEvolutionJobRecord>, SkillApiError>;

    async fn record_job_audit_event(
        &self,
        event: &SkillEvolutionJobAuditEventInsertRecord,
    ) -> Result<(), SkillApiError>;

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

    async fn current_skill_content(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
    ) -> Result<Option<String>, SkillApiError> {
        PgSkillEvolutionRepository::current_skill_content(self, tenant_id, skill_name, project_id)
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

    async fn apply_job(
        &self,
        _tenant_id: &str,
        _job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        Ok(None)
    }

    async fn update_job_status(
        &self,
        tenant_id: &str,
        job_id: &str,
        status: &str,
        skill_version_id: Option<&str>,
    ) -> Result<Option<SkillEvolutionJobRecord>, SkillApiError> {
        PgSkillEvolutionRepository::update_job_status(
            self,
            tenant_id,
            job_id,
            status,
            skill_version_id,
        )
        .await
        .map_err(SkillApiError::internal)
    }

    async fn record_job_audit_event(
        &self,
        event: &SkillEvolutionJobAuditEventInsertRecord,
    ) -> Result<(), SkillApiError> {
        PgSkillEvolutionRepository::insert_job_audit_event(self, event)
            .await
            .map(|_| ())
            .map_err(SkillApiError::internal)
    }

    async fn cleanup_old_sessions(&self, retention_days: i64) -> Result<i64, SkillApiError> {
        PgSkillEvolutionRepository::cleanup_old_sessions(self, retention_days)
            .await
            .map_err(SkillApiError::internal)
    }
}

pub(crate) struct PgSkillEvolutionPipelineStore {
    evolution_repo: PgSkillEvolutionRepository,
    skill_repo: PgSkillRepository,
}

impl PgSkillEvolutionPipelineStore {
    pub(crate) fn new(
        evolution_repo: PgSkillEvolutionRepository,
        skill_repo: PgSkillRepository,
    ) -> Self {
        Self {
            evolution_repo,
            skill_repo,
        }
    }

    async fn create_skill_from_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        let Some(candidate_content) = job
            .candidate_content
            .as_deref()
            .filter(|content| !content.is_empty())
        else {
            return Ok(None);
        };
        let payload = SkillImportPayload {
            skill_md_content: candidate_content.to_string(),
            resource_files: BTreeMap::new(),
            scope: evolution_job_scope(job).to_string(),
            project_id: job.project_id.clone(),
            overwrite: false,
            change_summary: None,
        };
        let Ok(parsed) = ParsedImportPackage::from_payload(&payload) else {
            return Ok(None);
        };
        if parsed.name != job.skill_name {
            return Ok(None);
        }
        if self
            .skill_repo
            .find_skill(
                tenant_id,
                &parsed.name,
                evolution_job_scope(job),
                job.project_id.as_deref(),
            )
            .await
            .map_err(SkillApiError::internal)?
            .is_some()
        {
            return Ok(None);
        }

        let now = Utc::now();
        let version_label = parsed
            .version_label
            .clone()
            .or_else(|| Some("1".to_string()));
        let skill = SkillRecord {
            id: generate_uuid_v4(),
            tenant_id: tenant_id.to_string(),
            project_id: job.project_id.clone(),
            name: parsed.name,
            description: parsed.description,
            tools: parsed.tools,
            status: "active".to_string(),
            metadata_json: parsed.metadata,
            created_at: now,
            updated_at: Some(now),
            scope: evolution_job_scope(job).to_string(),
            is_system_skill: false,
            full_content: Some(candidate_content.to_string()),
            resource_files: json!({}),
            license: parsed.license,
            compatibility: parsed.compatibility,
            allowed_tools_raw: parsed.allowed_tools_raw,
            spec_version: parsed.spec_version,
            current_version: 0,
            version_label: parsed.version_label,
        };
        let created = self
            .skill_repo
            .create_skill(&skill)
            .await
            .map_err(SkillApiError::internal)?;
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: created.id.clone(),
            version_number: 1,
            version_label: version_label.clone(),
            skill_md_content: candidate_content.to_string(),
            resource_files: json!({}),
            change_summary: evolution_change_summary(job, "create_skill"),
            created_by: "evolution".to_string(),
            created_at: now,
        };
        let version_id = version.id.clone();
        self.skill_repo
            .create_version(&version)
            .await
            .map_err(SkillApiError::internal)?;
        let updated = SkillUpdateRecord {
            current_version: Some(1),
            version_label: Some(version_label),
            ..Default::default()
        }
        .apply_to(created, now);
        self.skill_repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(Some(version_id))
    }

    async fn update_skill_from_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        let Some(candidate_content) = job
            .candidate_content
            .as_deref()
            .filter(|content| !content.is_empty())
        else {
            return Ok(None);
        };
        let Some(skill) = self.skill_for_job(tenant_id, job).await? else {
            return Ok(None);
        };
        let updated_content = if job.action == "optimize_description" {
            replace_frontmatter_description(
                skill.full_content.as_deref().unwrap_or_default(),
                candidate_content,
            )
        } else {
            candidate_content.to_string()
        };
        let next_version = self
            .skill_repo
            .max_version_number(&skill.id)
            .await
            .map_err(SkillApiError::internal)?
            + 1;
        let now = Utc::now();
        let version_label = Some(next_version.to_string());
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: skill.id.clone(),
            version_number: next_version,
            version_label: version_label.clone(),
            skill_md_content: updated_content.clone(),
            resource_files: json!({}),
            change_summary: evolution_change_summary(job, &job.action),
            created_by: "evolution".to_string(),
            created_at: now,
        };
        let version_id = version.id.clone();
        self.skill_repo
            .create_version(&version)
            .await
            .map_err(SkillApiError::internal)?;
        let updated = SkillUpdateRecord {
            full_content: Some(Some(updated_content)),
            current_version: Some(next_version),
            version_label: Some(version_label),
            ..Default::default()
        }
        .apply_to(skill, now);
        self.skill_repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(Some(version_id))
    }

    async fn skill_for_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<SkillRecord>, SkillApiError> {
        if let Some(project_id) = job.project_id.as_deref() {
            if let Some(skill) = self
                .skill_repo
                .find_skill(tenant_id, &job.skill_name, "project", Some(project_id))
                .await
                .map_err(SkillApiError::internal)?
            {
                return Ok(Some(skill));
            }
        }
        self.skill_repo
            .find_skill(tenant_id, &job.skill_name, "tenant", None)
            .await
            .map_err(SkillApiError::internal)
    }
}

#[async_trait]
impl SkillEvolutionPipelineStore for PgSkillEvolutionPipelineStore {
    async fn list_unprocessed_sessions(
        &self,
        tenant_id: &str,
        skill_name: Option<&str>,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_skill_sessions: i64,
        limit: i64,
    ) -> Result<Vec<SkillEvolutionPipelineSessionRecord>, SkillApiError> {
        self.evolution_repo
            .list_unprocessed_sessions(
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
        self.evolution_repo
            .update_session_summary(session_id, trajectory, summary)
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
        self.evolution_repo
            .list_unscored_sessions(
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
        self.evolution_repo
            .update_session_scores(session_id, judge_scores, overall_score)
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
        self.evolution_repo
            .scored_session_groups(
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
        self.evolution_repo
            .list_scored_sessions_by_skill(
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

    async fn current_skill_content(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
    ) -> Result<Option<String>, SkillApiError> {
        self.evolution_repo
            .current_skill_content(tenant_id, skill_name, project_id)
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
        self.evolution_repo
            .get_job_for_sessions(
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
        self.evolution_repo
            .insert_job(job)
            .await
            .map_err(SkillApiError::internal)
    }

    async fn apply_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        match job.action.as_str() {
            "create_skill" => self.create_skill_from_job(tenant_id, job).await,
            "improve_skill" | "optimize_description" => {
                self.update_skill_from_job(tenant_id, job).await
            }
            _ => Ok(None),
        }
    }

    async fn update_job_status(
        &self,
        tenant_id: &str,
        job_id: &str,
        status: &str,
        skill_version_id: Option<&str>,
    ) -> Result<Option<SkillEvolutionJobRecord>, SkillApiError> {
        self.evolution_repo
            .update_job_status(tenant_id, job_id, status, skill_version_id)
            .await
            .map_err(SkillApiError::internal)
    }

    async fn record_job_audit_event(
        &self,
        event: &SkillEvolutionJobAuditEventInsertRecord,
    ) -> Result<(), SkillApiError> {
        self.evolution_repo
            .insert_job_audit_event(event)
            .await
            .map(|_| ())
            .map_err(SkillApiError::internal)
    }

    async fn cleanup_old_sessions(&self, retention_days: i64) -> Result<i64, SkillApiError> {
        self.evolution_repo
            .cleanup_old_sessions(retention_days)
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

    pub(crate) fn with_store(
        store: Arc<dyn SkillEvolutionPipelineStore>,
        engine: Arc<dyn SkillEvolutionStageEngine>,
    ) -> Self {
        Self {
            store,
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
            auto_applied: 0,
            auto_apply_blocked: 0,
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
            let current_skill_content = self
                .store
                .current_skill_content(tenant_id, &group.skill_name, group.project_id.as_deref())
                .await?;
            let evidence = SkillEvolutionEvidenceGroup {
                skill_name: group.skill_name,
                project_id: group.project_id,
                current_skill_content,
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
            let inserted = self.store.insert_job(&job).await?;
            summary.jobs += 1;
            if self.config.auto_apply_enabled() && inserted.status == "pending_review" {
                let Some(version_id) = self.store.apply_job(tenant_id, &inserted).await? else {
                    summary.auto_apply_blocked += 1;
                    continue;
                };
                if self
                    .store
                    .update_job_status(tenant_id, &inserted.id, "applied", Some(&version_id))
                    .await?
                    .is_some()
                {
                    self.store
                        .record_job_audit_event(&SkillEvolutionJobAuditEventInsertRecord {
                            id: evolution_job_audit_event_id(),
                            tenant_id: tenant_id.to_string(),
                            project_id: inserted.project_id.clone(),
                            skill_name: inserted.skill_name.clone(),
                            job_id: inserted.id.clone(),
                            event_type: "auto_applied".to_string(),
                            actor_user_id: None,
                            skill_version_id: Some(version_id.clone()),
                            details_json: json!({
                                "run_id": run.id,
                                "job_action": inserted.action,
                                "skill_version_id": version_id,
                                "source": "skill_evolution_pipeline",
                            }),
                        })
                        .await?;
                    summary.auto_applied += 1;
                } else {
                    summary.auto_apply_blocked += 1;
                }
            }
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

fn evolution_job_audit_event_id() -> String {
    let hex: String = generate_uuid_v4()
        .chars()
        .filter(|ch| *ch != '-')
        .take(16)
        .collect();
    format!("evja-{hex}")
}
