use std::collections::HashSet;

use serde::Serialize;
use serde_json::Value;

use agistack_adapters_postgres::{
    SkillEvolutionJobRecord, SkillEvolutionOverviewStatsRecord, SkillEvolutionSessionRecord,
    SkillEvolutionSkillSummaryRecord, SkillRecord, SkillVersionRecord,
};

use super::{iso8601, present, SkillEvolutionConfig, SkillEvolutionScheduleResult};

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

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SkillEvolutionScheduleResultView {
    pub(in crate::skill_api) scheduled: bool,
    pub(in crate::skill_api) reason: String,
    pub(in crate::skill_api) status: String,
}

impl From<SkillEvolutionScheduleResult> for SkillEvolutionScheduleResultView {
    fn from(result: SkillEvolutionScheduleResult) -> Self {
        Self {
            scheduled: result.scheduled,
            reason: result.reason,
            status: result.status,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SkillEvolutionRunView {
    pub(in crate::skill_api) skill_id: String,
    pub(in crate::skill_api) skill_name: String,
    pub(in crate::skill_api) result: SkillEvolutionScheduleResultView,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SkillEvolutionTenantRunView {
    pub(in crate::skill_api) tenant_id: String,
    pub(in crate::skill_api) result: SkillEvolutionScheduleResultView,
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

pub(super) fn filter_disabled_system_skills(
    view: &mut SkillListView,
    disabled_names: &HashSet<String>,
) {
    if disabled_names.is_empty() {
        return;
    }
    view.skills
        .retain(|skill| !disabled_names.contains(&skill.name));
    view.total = view.skills.len();
}

pub(super) fn empty_evolution_overview(config: SkillEvolutionConfig) -> SkillEvolutionOverviewView {
    evolution_overview_from_records(
        config,
        SkillEvolutionOverviewStatsRecord::default(),
        Vec::new(),
        Vec::new(),
        Vec::new(),
    )
}

pub(super) fn evolution_detail_from_records(
    skill: &SkillRecord,
    config: SkillEvolutionConfig,
    versions: Vec<SkillVersionRecord>,
    jobs: Vec<SkillEvolutionJobRecord>,
    captured_session_count: i64,
) -> SkillEvolutionDetailView {
    let route = skill_evolution_route(&versions, &jobs);
    let jobs = jobs.into_iter().map(SkillEvolutionJobView::from).collect();
    let trigger = skill_evolution_trigger_view(&skill.id, &config);
    SkillEvolutionDetailView {
        skill_id: skill.id.clone(),
        skill_name: skill.name.clone(),
        captured_session_count,
        jobs,
        route,
        trigger,
    }
}

fn skill_evolution_route(
    versions: &[SkillVersionRecord],
    jobs: &[SkillEvolutionJobRecord],
) -> Vec<SkillEvolutionRouteEntryView> {
    let mut route = Vec::with_capacity(versions.len() + jobs.len());
    route.extend(versions.iter().map(skill_version_route_entry));
    route.extend(jobs.iter().map(skill_evolution_job_route_entry));
    route.sort_by(|left, right| right.created_at.cmp(&left.created_at));
    route
}

fn skill_version_route_entry(version: &SkillVersionRecord) -> SkillEvolutionRouteEntryView {
    let label = present(version.version_label.as_deref())
        .map(ToString::to_string)
        .unwrap_or_else(|| format!("v{}", version.version_number));
    SkillEvolutionRouteEntryView {
        kind: "version".to_string(),
        id: version.id.clone(),
        label,
        project_id: None,
        status: None,
        action: None,
        version_number: Some(version.version_number),
        version_label: version.version_label.clone(),
        skill_version_id: None,
        change_summary: version.change_summary.clone(),
        rationale: None,
        candidate_preview: None,
        created_by: Some(version.created_by.clone()),
        created_at: iso8601(version.created_at),
    }
}

fn skill_evolution_job_route_entry(job: &SkillEvolutionJobRecord) -> SkillEvolutionRouteEntryView {
    SkillEvolutionRouteEntryView {
        kind: "evolution_job".to_string(),
        id: job.id.clone(),
        label: format!("{}:{}", job.action, job.status),
        project_id: job.project_id.clone(),
        status: Some(job.status.clone()),
        action: Some(job.action.clone()),
        version_number: None,
        version_label: None,
        skill_version_id: job.skill_version_id.clone(),
        change_summary: None,
        rationale: job.rationale.clone(),
        candidate_preview: candidate_content_preview(job.candidate_content.as_deref()),
        created_by: Some("skill-evolution".to_string()),
        created_at: iso8601(job.created_at),
    }
}

fn candidate_content_preview(value: Option<&str>) -> Option<String> {
    value
        .filter(|value| !value.is_empty())
        .map(|value| value.chars().take(500).collect())
}

pub(super) fn evolution_overview_from_records(
    config: SkillEvolutionConfig,
    stats: SkillEvolutionOverviewStatsRecord,
    skill_summaries: Vec<SkillEvolutionSkillSummaryRecord>,
    recent_sessions: Vec<SkillEvolutionSessionRecord>,
    recent_jobs: Vec<SkillEvolutionJobRecord>,
) -> SkillEvolutionOverviewView {
    let stats = SkillEvolutionOverviewStatsView::from(stats);
    let skills: Vec<SkillEvolutionSkillSummaryView> = skill_summaries
        .into_iter()
        .map(SkillEvolutionSkillSummaryView::from)
        .collect();
    let recent_sessions: Vec<SkillEvolutionSessionView> = recent_sessions
        .into_iter()
        .map(SkillEvolutionSessionView::from)
        .collect();
    let recent_jobs: Vec<SkillEvolutionJobView> = recent_jobs
        .into_iter()
        .map(SkillEvolutionJobView::from)
        .collect();
    let trigger = skill_evolution_trigger_view("", &config);
    let monitor =
        skill_evolution_monitor_view(&stats, &skills, &recent_sessions, &recent_jobs, &trigger);
    let stages = skill_evolution_stage_views(&stats, &monitor);
    SkillEvolutionOverviewView {
        stats,
        monitor,
        stages,
        skills,
        recent_sessions,
        recent_jobs,
        trigger,
    }
}

fn skill_evolution_trigger_view(
    skill_id: &str,
    config: &SkillEvolutionConfig,
) -> SkillEvolutionTriggerView {
    SkillEvolutionTriggerView {
        capture_hook: "after_turn_complete".to_string(),
        capture_timing: "After every agent turn completes, the plugin records matched skills, dynamically loaded skill_loader usage, conversation trajectory, tool calls, success, and latency.".to_string(),
        scheduled_timing: format!(
            "Every {} minute(s), the scheduler summarizes, judges, aggregates, and evolves qualifying skill sessions.",
            config.evolution_interval_minutes
        ),
        manual_trigger: if skill_id.is_empty() {
            "/api/v1/skills/{skill_id}/evolution/run".to_string()
        } else {
            format!("/api/v1/skills/{skill_id}/evolution/run")
        },
        min_sessions_per_skill: config.min_sessions_per_skill,
        scoring_min_sessions_per_skill: config.scoring_min_sessions_per_skill,
        min_avg_score: config.min_avg_score,
        max_sessions_per_batch: config.max_sessions_per_batch,
        publish_mode: config.publish_mode.as_str().to_string(),
        auto_apply: config.auto_apply,
        enabled: config.enabled,
    }
}

fn skill_evolution_monitor_view(
    stats: &SkillEvolutionOverviewStatsView,
    skills: &[SkillEvolutionSkillSummaryView],
    recent_sessions: &[SkillEvolutionSessionView],
    recent_jobs: &[SkillEvolutionJobView],
    trigger: &SkillEvolutionTriggerView,
) -> SkillEvolutionMonitorView {
    let backlog_count: i64 = skills
        .iter()
        .filter(|summary| {
            summary.skill_name != "__no_skill__"
                && summary.session_count >= trigger.scoring_min_sessions_per_skill
        })
        .map(|summary| summary.unprocessed_count)
        .sum();
    let unscored_count = (stats.processed_sessions - stats.scored_sessions).max(0);
    let eligible_skill_count = skills
        .iter()
        .filter(|summary| {
            summary.skill_name != "__no_skill__"
                && summary.session_count >= trigger.min_sessions_per_skill
                && summary
                    .avg_score
                    .is_some_and(|score| score >= trigger.min_avg_score)
        })
        .count() as i64;
    let blocked_by_review_count = stats.pending_jobs;
    SkillEvolutionMonitorView {
        refresh_interval_seconds: 15,
        latest_session_at: recent_sessions
            .first()
            .map(|session| session.created_at.clone()),
        latest_job_at: recent_jobs.first().map(|job| job.created_at.clone()),
        backlog_count,
        unscored_count,
        blocked_by_review_count,
        eligible_skill_count,
        needs_attention: backlog_count > 0 || unscored_count > 0 || blocked_by_review_count > 0,
    }
}

fn skill_evolution_stage_views(
    stats: &SkillEvolutionOverviewStatsView,
    monitor: &SkillEvolutionMonitorView,
) -> Vec<SkillEvolutionStageView> {
    vec![
        SkillEvolutionStageView {
            id: "capture".to_string(),
            label: "capture".to_string(),
            status: if stats.total_sessions > 0 {
                "active".to_string()
            } else {
                "waiting".to_string()
            },
            count: stats.total_sessions,
            backlog_count: 0,
            detail: "Captured agent turns available for evolution.".to_string(),
        },
        SkillEvolutionStageView {
            id: "summarize".to_string(),
            label: "summarize".to_string(),
            status: if monitor.backlog_count > 0 {
                "waiting".to_string()
            } else {
                "complete".to_string()
            },
            count: stats.processed_sessions,
            backlog_count: monitor.backlog_count,
            detail: "Captured turns are summarized into comparable trajectories.".to_string(),
        },
        SkillEvolutionStageView {
            id: "judge".to_string(),
            label: "judge".to_string(),
            status: if monitor.unscored_count > 0 {
                "waiting".to_string()
            } else {
                "complete".to_string()
            },
            count: stats.scored_sessions,
            backlog_count: monitor.unscored_count,
            detail: "Summaries are judged and scored for evolution readiness.".to_string(),
        },
        SkillEvolutionStageView {
            id: "review".to_string(),
            label: "review".to_string(),
            status: if stats.pending_jobs > 0 {
                "blocked".to_string()
            } else {
                "complete".to_string()
            },
            count: stats.pending_jobs,
            backlog_count: stats.pending_jobs,
            detail: "Pending jobs require apply or reject before duplicate batches advance."
                .to_string(),
        },
        SkillEvolutionStageView {
            id: "apply".to_string(),
            label: "apply".to_string(),
            status: if stats.applied_jobs > 0 {
                "active".to_string()
            } else {
                "waiting".to_string()
            },
            count: stats.applied_jobs,
            backlog_count: 0,
            detail: "Applied jobs create skill versions attributed to evolution.".to_string(),
        },
    ]
}
