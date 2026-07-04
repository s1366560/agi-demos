use serde::Serialize;
use serde_json::Value;

use agistack_adapters_postgres::{
    SkillEvolutionJobRecord, SkillEvolutionOverviewStatsRecord, SkillEvolutionSessionRecord,
    SkillEvolutionSkillSummaryRecord, SkillRecord, SkillVersionRecord,
};

use super::{candidate_content_preview, iso8601, SkillEvolutionConfig};

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillView {
    pub(in crate::skill_api) id: String,
    pub(in crate::skill_api) tenant_id: String,
    pub(in crate::skill_api) project_id: Option<String>,
    pub(in crate::skill_api) name: String,
    pub(in crate::skill_api) description: String,
    pub(in crate::skill_api) tools: Vec<String>,
    pub(in crate::skill_api) full_content: Option<String>,
    pub(in crate::skill_api) status: String,
    pub(in crate::skill_api) scope: String,
    pub(in crate::skill_api) is_system_skill: bool,
    pub(in crate::skill_api) source: String,
    pub(in crate::skill_api) file_path: Option<String>,
    pub(in crate::skill_api) created_at: String,
    pub(in crate::skill_api) updated_at: String,
    pub(in crate::skill_api) metadata: Option<Value>,
    pub(in crate::skill_api) resource_files: Value,
    pub(in crate::skill_api) agent_modes: Vec<String>,
    pub(in crate::skill_api) license: Option<String>,
    pub(in crate::skill_api) compatibility: Option<String>,
    pub(in crate::skill_api) allowed_tools_raw: Option<String>,
    pub(in crate::skill_api) spec_version: String,
    pub(in crate::skill_api) current_version: i32,
    pub(in crate::skill_api) version_label: Option<String>,
}

impl From<SkillRecord> for SkillView {
    fn from(record: SkillRecord) -> Self {
        let updated_at = record.updated_at.unwrap_or(record.created_at);
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            project_id: record.project_id,
            name: record.name,
            description: record.description,
            tools: record.tools,
            full_content: record.full_content,
            status: record.status,
            scope: record.scope,
            is_system_skill: record.is_system_skill,
            source: "database".to_string(),
            file_path: None,
            created_at: iso8601(record.created_at),
            updated_at: iso8601(updated_at),
            metadata: record.metadata_json,
            resource_files: record.resource_files,
            agent_modes: vec!["*".to_string()],
            license: record.license,
            compatibility: record.compatibility,
            allowed_tools_raw: record.allowed_tools_raw,
            spec_version: record.spec_version,
            current_version: record.current_version,
            version_label: record.version_label,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillListView {
    pub(in crate::skill_api) skills: Vec<SkillView>,
    pub(in crate::skill_api) total: usize,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillContentView {
    pub(in crate::skill_api) skill_id: String,
    pub(in crate::skill_api) name: String,
    pub(in crate::skill_api) full_content: Option<String>,
    pub(in crate::skill_api) scope: String,
    pub(in crate::skill_api) is_system_skill: bool,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillVersionView {
    pub(in crate::skill_api) id: String,
    pub(in crate::skill_api) skill_id: String,
    pub(in crate::skill_api) version_number: i32,
    pub(in crate::skill_api) version_label: Option<String>,
    pub(in crate::skill_api) change_summary: Option<String>,
    pub(in crate::skill_api) created_by: String,
    pub(in crate::skill_api) created_at: String,
}

impl From<SkillVersionRecord> for SkillVersionView {
    fn from(record: SkillVersionRecord) -> Self {
        Self {
            id: record.id,
            skill_id: record.skill_id,
            version_number: record.version_number,
            version_label: record.version_label,
            change_summary: record.change_summary,
            created_by: record.created_by,
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillVersionDetailView {
    pub(in crate::skill_api) id: String,
    pub(in crate::skill_api) skill_id: String,
    pub(in crate::skill_api) version_number: i32,
    pub(in crate::skill_api) version_label: Option<String>,
    pub(in crate::skill_api) skill_md_content: String,
    pub(in crate::skill_api) resource_files: Value,
    pub(in crate::skill_api) change_summary: Option<String>,
    pub(in crate::skill_api) created_by: String,
    pub(in crate::skill_api) created_at: String,
}

impl From<SkillVersionRecord> for SkillVersionDetailView {
    fn from(record: SkillVersionRecord) -> Self {
        Self {
            id: record.id,
            skill_id: record.skill_id,
            version_number: record.version_number,
            version_label: record.version_label,
            skill_md_content: record.skill_md_content,
            resource_files: record.resource_files,
            change_summary: record.change_summary,
            created_by: record.created_by,
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillVersionListView {
    pub(in crate::skill_api) versions: Vec<SkillVersionView>,
    pub(in crate::skill_api) total: i64,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillPackageView {
    pub(in crate::skill_api) format: String,
    pub(in crate::skill_api) skill: SkillView,
    pub(in crate::skill_api) skill_md_content: String,
    pub(in crate::skill_api) resource_files: Value,
    pub(in crate::skill_api) version_number: Option<i32>,
    pub(in crate::skill_api) version_label: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillLifecycleView {
    pub(in crate::skill_api) action: String,
    pub(in crate::skill_api) skill: SkillView,
    pub(in crate::skill_api) version_number: Option<i32>,
    pub(in crate::skill_api) version_label: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionConfigView {
    pub(in crate::skill_api) enabled: bool,
    pub(in crate::skill_api) min_sessions_per_skill: i64,
    pub(in crate::skill_api) scoring_min_sessions_per_skill: i64,
    pub(in crate::skill_api) min_avg_score: f64,
    pub(in crate::skill_api) max_sessions_per_batch: i64,
    pub(in crate::skill_api) evolution_interval_minutes: i64,
    pub(in crate::skill_api) publish_mode: String,
    pub(in crate::skill_api) auto_apply: bool,
}

impl From<SkillEvolutionConfig> for SkillEvolutionConfigView {
    fn from(config: SkillEvolutionConfig) -> Self {
        Self {
            enabled: config.enabled,
            min_sessions_per_skill: config.min_sessions_per_skill,
            scoring_min_sessions_per_skill: config.scoring_min_sessions_per_skill,
            min_avg_score: config.min_avg_score,
            max_sessions_per_batch: config.max_sessions_per_batch,
            evolution_interval_minutes: config.evolution_interval_minutes,
            publish_mode: config.publish_mode.as_str().to_string(),
            auto_apply: config.auto_apply,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionOverviewStatsView {
    pub(in crate::skill_api) total_sessions: i64,
    pub(in crate::skill_api) skill_sessions: i64,
    pub(in crate::skill_api) no_skill_sessions: i64,
    pub(in crate::skill_api) unprocessed_sessions: i64,
    pub(in crate::skill_api) processed_sessions: i64,
    pub(in crate::skill_api) scored_sessions: i64,
    pub(in crate::skill_api) successful_sessions: i64,
    pub(in crate::skill_api) avg_score: Option<f64>,
    pub(in crate::skill_api) total_jobs: i64,
    pub(in crate::skill_api) pending_jobs: i64,
    pub(in crate::skill_api) applied_jobs: i64,
    pub(in crate::skill_api) skipped_jobs: i64,
    pub(in crate::skill_api) rejected_jobs: i64,
}

impl From<SkillEvolutionOverviewStatsRecord> for SkillEvolutionOverviewStatsView {
    fn from(record: SkillEvolutionOverviewStatsRecord) -> Self {
        Self {
            total_sessions: record.total_sessions,
            skill_sessions: record.skill_sessions,
            no_skill_sessions: record.no_skill_sessions,
            unprocessed_sessions: record.unprocessed_sessions,
            processed_sessions: record.processed_sessions,
            scored_sessions: record.scored_sessions,
            successful_sessions: record.successful_sessions,
            avg_score: record.avg_score,
            total_jobs: record.total_jobs,
            pending_jobs: record.pending_jobs,
            applied_jobs: record.applied_jobs,
            skipped_jobs: record.skipped_jobs,
            rejected_jobs: record.rejected_jobs,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionSkillSummaryView {
    pub(in crate::skill_api) skill_id: Option<String>,
    pub(in crate::skill_api) project_id: Option<String>,
    pub(in crate::skill_api) skill_name: String,
    pub(in crate::skill_api) session_count: i64,
    pub(in crate::skill_api) success_count: i64,
    pub(in crate::skill_api) unprocessed_count: i64,
    pub(in crate::skill_api) scored_count: i64,
    pub(in crate::skill_api) avg_score: Option<f64>,
    pub(in crate::skill_api) latest_session_at: Option<String>,
    pub(in crate::skill_api) job_count: i64,
    pub(in crate::skill_api) pending_job_count: i64,
    pub(in crate::skill_api) latest_job_at: Option<String>,
}

impl From<SkillEvolutionSkillSummaryRecord> for SkillEvolutionSkillSummaryView {
    fn from(record: SkillEvolutionSkillSummaryRecord) -> Self {
        Self {
            skill_id: record.skill_id,
            project_id: record.project_id,
            skill_name: record.skill_name,
            session_count: record.session_count,
            success_count: record.success_count,
            unprocessed_count: record.unprocessed_count,
            scored_count: record.scored_count,
            avg_score: record.avg_score,
            latest_session_at: record.latest_session_at.map(iso8601),
            job_count: record.job_count,
            pending_job_count: record.pending_job_count,
            latest_job_at: record.latest_job_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionSessionView {
    pub(in crate::skill_api) id: String,
    pub(in crate::skill_api) skill_name: String,
    pub(in crate::skill_api) conversation_id: String,
    pub(in crate::skill_api) project_id: Option<String>,
    pub(in crate::skill_api) user_query: String,
    pub(in crate::skill_api) summary: Option<String>,
    pub(in crate::skill_api) judge_scores: Option<Value>,
    pub(in crate::skill_api) overall_score: Option<f64>,
    pub(in crate::skill_api) success: bool,
    pub(in crate::skill_api) execution_time_ms: i64,
    pub(in crate::skill_api) tool_call_count: i64,
    pub(in crate::skill_api) processed: bool,
    pub(in crate::skill_api) created_at: String,
}

impl From<SkillEvolutionSessionRecord> for SkillEvolutionSessionView {
    fn from(record: SkillEvolutionSessionRecord) -> Self {
        Self {
            id: record.id,
            skill_name: record.skill_name,
            conversation_id: record.conversation_id,
            project_id: record.project_id,
            user_query: record.user_query,
            summary: record.summary,
            judge_scores: record.judge_scores,
            overall_score: record.overall_score,
            success: record.success,
            execution_time_ms: record.execution_time_ms,
            tool_call_count: record.tool_call_count,
            processed: record.processed,
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionJobView {
    pub(in crate::skill_api) id: String,
    pub(in crate::skill_api) project_id: Option<String>,
    pub(in crate::skill_api) skill_name: String,
    pub(in crate::skill_api) action: String,
    pub(in crate::skill_api) status: String,
    pub(in crate::skill_api) rationale: Option<String>,
    pub(in crate::skill_api) candidate_preview: Option<String>,
    pub(in crate::skill_api) candidate_content: Option<String>,
    pub(in crate::skill_api) blocked_by_review: bool,
    pub(in crate::skill_api) session_ids: Vec<String>,
    pub(in crate::skill_api) skill_version_id: Option<String>,
    pub(in crate::skill_api) created_at: String,
    pub(in crate::skill_api) applied_at: Option<String>,
}

impl From<SkillEvolutionJobRecord> for SkillEvolutionJobView {
    fn from(record: SkillEvolutionJobRecord) -> Self {
        let candidate_preview = candidate_content_preview(record.candidate_content.as_deref());
        Self {
            id: record.id,
            project_id: record.project_id,
            skill_name: record.skill_name,
            action: record.action,
            blocked_by_review: record.status == "pending_review",
            status: record.status,
            rationale: record.rationale,
            candidate_preview,
            candidate_content: record.candidate_content,
            session_ids: record.session_ids,
            skill_version_id: record.skill_version_id,
            created_at: iso8601(record.created_at),
            applied_at: record.applied_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionRouteEntryView {
    pub(in crate::skill_api) kind: String,
    pub(in crate::skill_api) id: String,
    pub(in crate::skill_api) label: String,
    pub(in crate::skill_api) project_id: Option<String>,
    pub(in crate::skill_api) status: Option<String>,
    pub(in crate::skill_api) action: Option<String>,
    pub(in crate::skill_api) version_number: Option<i32>,
    pub(in crate::skill_api) version_label: Option<String>,
    pub(in crate::skill_api) skill_version_id: Option<String>,
    pub(in crate::skill_api) change_summary: Option<String>,
    pub(in crate::skill_api) rationale: Option<String>,
    pub(in crate::skill_api) candidate_preview: Option<String>,
    pub(in crate::skill_api) created_by: Option<String>,
    pub(in crate::skill_api) created_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionDetailView {
    pub(in crate::skill_api) skill_id: String,
    pub(in crate::skill_api) skill_name: String,
    pub(in crate::skill_api) captured_session_count: i64,
    pub(in crate::skill_api) jobs: Vec<SkillEvolutionJobView>,
    pub(in crate::skill_api) route: Vec<SkillEvolutionRouteEntryView>,
    pub(in crate::skill_api) trigger: SkillEvolutionTriggerView,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionTriggerView {
    pub(in crate::skill_api) capture_hook: String,
    pub(in crate::skill_api) capture_timing: String,
    pub(in crate::skill_api) scheduled_timing: String,
    pub(in crate::skill_api) manual_trigger: String,
    pub(in crate::skill_api) min_sessions_per_skill: i64,
    pub(in crate::skill_api) scoring_min_sessions_per_skill: i64,
    pub(in crate::skill_api) min_avg_score: f64,
    pub(in crate::skill_api) max_sessions_per_batch: i64,
    pub(in crate::skill_api) publish_mode: String,
    pub(in crate::skill_api) auto_apply: bool,
    pub(in crate::skill_api) enabled: bool,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionMonitorView {
    pub(in crate::skill_api) refresh_interval_seconds: i64,
    pub(in crate::skill_api) latest_session_at: Option<String>,
    pub(in crate::skill_api) latest_job_at: Option<String>,
    pub(in crate::skill_api) backlog_count: i64,
    pub(in crate::skill_api) unscored_count: i64,
    pub(in crate::skill_api) blocked_by_review_count: i64,
    pub(in crate::skill_api) eligible_skill_count: i64,
    pub(in crate::skill_api) needs_attention: bool,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionStageView {
    pub(in crate::skill_api) id: String,
    pub(in crate::skill_api) label: String,
    pub(in crate::skill_api) status: String,
    pub(in crate::skill_api) count: i64,
    pub(in crate::skill_api) backlog_count: i64,
    pub(in crate::skill_api) detail: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillEvolutionOverviewView {
    pub(in crate::skill_api) stats: SkillEvolutionOverviewStatsView,
    pub(in crate::skill_api) monitor: SkillEvolutionMonitorView,
    pub(in crate::skill_api) stages: Vec<SkillEvolutionStageView>,
    pub(in crate::skill_api) skills: Vec<SkillEvolutionSkillSummaryView>,
    pub(in crate::skill_api) recent_sessions: Vec<SkillEvolutionSessionView>,
    pub(in crate::skill_api) recent_jobs: Vec<SkillEvolutionJobView>,
    pub(in crate::skill_api) trigger: SkillEvolutionTriggerView,
}
