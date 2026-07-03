//! Server-only Workspace Plan outbox worker foundation.
//!
//! The portable core stays out of this module: it owns no Tokio, SQLx, or
//! Postgres contracts. This file is the strangler-side host shell that can claim
//! Python-shaped `workspace_plan_outbox` rows and dispatch them to event
//! handlers once each P6 runtime slice is migrated.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::time::Instant;

use agistack_adapters_postgres::{
    PgWorkspaceRepository, WorkspacePipelineRunRecord, WorkspacePipelineStageRunRecord,
    WorkspacePlanEventRecord, WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord,
    WorkspacePlanRecord, WorkspaceRecord, WorkspaceTaskRecord, WorkspaceTaskSessionAttemptRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::ports::{CoreError, CoreResult, EventStream, StreamEntry};
use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use serde_json::{json, Map, Value};
use serde_yaml_ng::Value as YamlValue;
use sha2::{Digest, Sha256};
use tokio::io::AsyncWriteExt;
use tokio::task::JoinHandle;
use tokio::time::{sleep, Duration};
use uuid::Uuid;

use crate::sandbox_api::{ExecuteToolResponse, ProjectSandboxService};

pub(crate) type SharedWorkspacePlanOutboxWorker = Arc<WorkspacePlanOutboxWorker>;
pub(crate) type WorkspacePlanOutboxHandlers = HashMap<String, Arc<dyn WorkspacePlanOutboxHandler>>;

const SUPERVISOR_TICK_EVENT: &str = "supervisor_tick";
const WORKER_LAUNCH_EVENT: &str = "worker_launch";
const HANDOFF_RESUME_EVENT: &str = "handoff_resume";
const ATTEMPT_RETRY_EVENT: &str = "attempt_retry";
const PIPELINE_RUN_REQUESTED_EVENT: &str = "pipeline_run_requested";
const SANDBOX_NATIVE_PROVIDER: &str = "sandbox_native";
const DRONE_PROVIDER: &str = "drone";
const DRONE_SERVER_ENV: &str = "DRONE_SERVER";
const DRONE_SERVER_URL_ENV: &str = "DRONE_SERVER_URL";
const DRONE_TOKEN_ENV: &str = "DRONE_TOKEN";
const DRONE_CLI_JSON_TEMPLATE: &str = "{{ json . }}";
const DRONE_DOCKER_DEPLOY_VALIDATION: &str = "explicit_deploy_step_v1";
const DRONE_YAML_PREFLIGHT_VALIDATION: &str = "drone_yml_preflight_v1";
const DEFAULT_DRONE_DEPLOY_MODE: &str = "cli";
const DEFAULT_DRONE_DEPLOY_STAGE: &str = "deploy";
const PLANNING_CONTRACT_SOURCE: &str = "planner_agent_code_analysis";
const DEFAULT_PIPELINE_TIMEOUT_SECONDS: i32 = 600;
const DEFAULT_PREVIEW_PORT: i32 = 3000;
const PIPELINE_EXIT_MARKER: &str = "__MEMSTACK_PIPELINE_EXIT_CODE__=";
const WORKSPACE_PLAN_SYSTEM_ACTOR_ID: &str = "workspace-plan:system";
const ROOT_GOAL_TASK_ID: &str = "root_goal_task_id";
const WORKSPACE_PLAN_ID: &str = "workspace_plan_id";
const WORKSPACE_PLAN_NODE_ID: &str = "workspace_plan_node_id";
const CURRENT_ATTEMPT_ID: &str = "current_attempt_id";
const CURRENT_ATTEMPT_WORKER_BINDING_ID: &str = "current_attempt_worker_binding_id";
const CURRENT_ATTEMPT_CONVERSATION_ID: &str = "current_attempt_conversation_id";
const PENDING_LEADER_ADJUDICATION: &str = "pending_leader_adjudication";
const LAST_WORKER_REPORT_ATTEMPT_ID: &str = "last_worker_report_attempt_id";
const LAST_WORKER_REPORT_SUMMARY: &str = "last_worker_report_summary";
const TASK_ROLE: &str = "task_role";
const GOAL_ROOT_TASK_ROLE: &str = "goal_root";
const REMEDIATION_STATUS: &str = "remediation_status";
const REMEDIATION_SUMMARY: &str = "remediation_summary";
const WORKER_LAUNCH_MAX_ACTIVE_ENV: &str = "WORKSPACE_WORKER_LAUNCH_MAX_ACTIVE";
const WORKER_LAUNCH_DEFER_SECONDS_ENV: &str = "WORKSPACE_WORKER_LAUNCH_DEFER_SECONDS";
const WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS_ENV: &str =
    "WORKSPACE_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS";
const WORKER_STREAM_POLL_INTERVAL_SECONDS_ENV: &str =
    "WORKSPACE_WORKER_STREAM_POLL_INTERVAL_SECONDS";
const WORKER_LAUNCH_CONVERSATION_SOURCE: &str = "workspace_worker_launch";
const WORKER_LAUNCH_CONVERSATION_STAGE: &str = "worker_launch";
const WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY_ENV: &str =
    "AGISTACK_WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY";
const PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV: &str = "WORKSPACE_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES";
const AWAITING_LEADER_ADJUDICATION_STATUS: &str = "awaiting_leader_adjudication";
const DEFAULT_WORKER_LAUNCH_MAX_ACTIVE: i64 = 4;
const DEFAULT_WORKER_LAUNCH_DEFER_SECONDS: i64 = 20;
const DEFAULT_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS: i64 = 300;
const DEFAULT_WORKER_STREAM_POLL_INTERVAL_SECONDS: i64 = 5;
const WORKER_LAUNCH_COOLDOWN_SECONDS: u64 = 300;
#[allow(dead_code)]
const WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS: usize = 700;
#[allow(dead_code)]
const WORKER_STREAM_COMPLETION_SUMMARY_CHARS: usize = 2000;
#[allow(dead_code)]
const DEFAULT_WORKER_STREAM_ORPHAN_GRACE_SECONDS: i64 = 900;
const DEFAULT_WORKER_STREAM_IDLE_PROGRESS_INTERVAL_SECONDS: i64 = 60;
const DEFAULT_WORKER_STREAM_REPLAY_BATCH_LIMIT: usize = 100;
const DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES: i64 = 3;
const WORKER_LAUNCHABLE_ATTEMPT_STATUSES: [&str; 2] = ["pending", "running"];
const ACCEPTED_ATTEMPT_STATUS: &str = "accepted";
const DISPOSED_ATTEMPT_STATUS: &str = "disposed";
const REJECTED_ATTEMPT_STATUS: &str = "rejected";
const SUPERVISOR_DECISION_DISPOSE_NODE_ACTION: &str = "dispose_node";
const SUPERVISOR_DISPOSED_NODE_DISPOSITION: &str = "supervisor_agent_disposed_node";
const SUPERVISOR_DECISION_RETRY_SAME_NODE_ACTION: &str = "retry_same_node";
const SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON: &str = "supervisor_decision_retry_same_node";
const TERMINAL_RETRY_ATTEMPT_STATUSES: [&str; 3] = ["rejected", "blocked", "cancelled"];
const WORKTREE_INTEGRATION_DONE_STATUSES: [&str; 5] = [
    "merged",
    "already_merged",
    "skipped",
    "blocked_dirty_main",
    "failed",
];
const NO_COMMIT_ACCEPTED_ATTEMPT_STALE_METADATA_KEYS: [&str; 27] = [
    "candidate_artifacts",
    "candidate_verifications",
    "execution_verifications",
    "last_worker_report_artifacts",
    "last_worker_report_verifications",
    "pipeline_evidence_refs",
    "pipeline_gate_status",
    "pipeline_last_summary",
    "pipeline_run_id",
    "pipeline_status",
    "source_publish_branch",
    "source_publish_commit_ref",
    "source_publish_provider",
    "source_publish_reason",
    "source_publish_source_commit_ref",
    "source_publish_status",
    "verification_evidence_refs",
    "verified_commit_ref",
    "verified_git_diff_summary",
    "verified_test_commands",
    "worktree_integration_attempt_id",
    "worktree_integration_commit_ref",
    "worktree_integration_dirty_signature",
    "worktree_integration_ran_at",
    "worktree_integration_status",
    "worktree_integration_summary",
    "worktree_integration_worktree_path",
];
const ATTEMPT_RETRY_STALE_WORKER_STREAM_METADATA_KEYS: &[&str] = &[
    "current_attempt_conversation_id",
    "evidence_refs",
    "execution_verifications",
    "last_worker_report_artifacts",
    "last_worker_report_attempt_id",
    "last_worker_report_fingerprint",
    "last_worker_report_summary",
    "last_worker_report_type",
    "last_worker_report_verifications",
    "last_worker_reported_at",
    "pending_leader_adjudication",
    "worker_launch_admitted_at",
    "worker_launch_bound_at",
    "worker_stream_idle_finished_message_id",
    "worker_stream_idle_progress_published_at",
    "worker_stream_idle_progress_published_at_us",
    "worker_stream_idle_progress_summary",
    "worker_stream_idle_running_exists",
    "worker_stream_idle_seconds",
    "worker_stream_last_entry_id",
    "worker_stream_last_event_time_us",
    "worker_stream_last_event_type",
    "worker_stream_last_replayed_at",
    "worker_stream_message_id",
    "worker_stream_replay_attempt_id",
    "worker_stream_replay_status",
    "worker_stream_terminal_launch_state",
    "worker_stream_terminal_outcome",
    "worker_stream_terminal_replayed_at",
    "worker_stream_terminal_should_report",
];
const FAILED_WORKTREE_RETRY_STALE_METADATA_KEYS: &[&str] = &[
    "candidate_artifacts",
    "candidate_verifications",
    "deploy_mode",
    "deployment_status",
    "evidence_refs",
    "execution_verifications",
    "external_id",
    "external_provider",
    "external_url",
    "last_verification_summary",
    "last_verification_passed",
    "last_verification_hard_fail",
    "last_verification_attempt_id",
    "last_verification_ran_at",
    "last_verification_judge_confidence",
    "last_verification_judge_failed_criteria",
    "last_verification_judge_next_action_kind",
    "last_verification_judge_rationale",
    "last_verification_judge_repair_brief",
    "last_verification_judge_required_next_action",
    "last_verification_judge_verdict",
    "last_verification_feedback_items",
    "last_worker_report_attempt_id",
    "last_worker_report_artifacts",
    "last_worker_report_summary",
    "last_worker_report_type",
    "last_worker_report_verifications",
    "verification_feedback_disposition",
    "obsolete_by_verifier_feedback",
    "obsolete_feedback_items",
    "current_repair_turn",
    "dependency_invalidated_at",
    "dependency_invalidated_missing_ids",
    "dependency_invalidated_reason",
    "dependency_invalidated_previous_attempt_id",
    "dependency_invalidated_previous_intent",
    "dependency_invalidated_previous_execution",
    "pipeline_finished_at",
    "pipeline_request_count",
    "pipeline_requested_at",
    "verification_evidence_refs",
    "verified_commit_ref",
    "verified_git_diff_summary",
    "verified_test_commands",
    "reported_attempt_reconciled_at",
    "reported_attempt_status",
    "retry_last_reason",
    "source_publish_branch",
    "source_publish_commit_ref",
    "source_publish_provider",
    "source_publish_reason",
    "source_publish_source_commit_ref",
    "source_publish_status",
    "source_publish_token_env",
    "terminal_attempt_status",
    "terminal_attempt_reconciled_at",
    "terminal_attempt_superseded_attempt_id",
    "terminal_attempt_superseded_reason",
    "terminal_attempt_superseded_status",
    "pipeline_status",
    "pipeline_gate_status",
    "pipeline_run_id",
    "pipeline_evidence_refs",
    "pipeline_last_summary",
    "worktree_integration_attempt_id",
    "worktree_integration_commit_ref",
    "worktree_integration_dirty_signature",
    "worktree_integration_ran_at",
    "worktree_integration_status",
    "worktree_integration_summary",
    "worktree_integration_worktree_path",
];

#[allow(dead_code)]
mod worker_stream_watchdog {
    use super::{
        DEFAULT_WORKER_STREAM_IDLE_PROGRESS_INTERVAL_SECONDS,
        DEFAULT_WORKER_STREAM_ORPHAN_GRACE_SECONDS, WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS,
        WORKER_STREAM_COMPLETION_SUMMARY_CHARS,
    };
    use serde_json::Value;

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub(super) enum StopReason {
        AgentFinishedWithoutTerminalEvent,
        AgentNotRunningStreamIdle,
    }

    impl StopReason {
        pub(super) fn as_str(self) -> &'static str {
            match self {
                Self::AgentFinishedWithoutTerminalEvent => "agent_finished_without_terminal_event",
                Self::AgentNotRunningStreamIdle => "agent_not_running_stream_idle",
            }
        }
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub(super) struct Decision {
        pub(super) should_stop: bool,
        pub(super) reason: Option<StopReason>,
    }

    pub(super) fn should_stop(
        finished_message_id: Option<&str>,
        stream_message_id: Option<&str>,
        running_exists: bool,
        idle_seconds: f64,
        orphan_grace_seconds: Option<i64>,
    ) -> Decision {
        if let Some(finished_message_id) = finished_message_id.filter(|value| !value.is_empty()) {
            if stream_message_id.is_none() || stream_message_id == Some(finished_message_id) {
                return Decision {
                    should_stop: true,
                    reason: Some(StopReason::AgentFinishedWithoutTerminalEvent),
                };
            }
        }

        let grace_seconds = orphan_grace_seconds
            .unwrap_or(DEFAULT_WORKER_STREAM_ORPHAN_GRACE_SECONDS)
            .max(1) as f64;
        if !running_exists && idle_seconds >= grace_seconds {
            return Decision {
                should_stop: true,
                reason: Some(StopReason::AgentNotRunningStreamIdle),
            };
        }

        Decision {
            should_stop: false,
            reason: None,
        }
    }

    pub(super) fn message_id_from_event(event: &Value) -> Option<&str> {
        if event.get("type").and_then(Value::as_str) != Some("message") {
            return None;
        }
        let data = event.get("data")?.as_object()?;
        data.get("id")
            .or_else(|| data.get("message_id"))
            .and_then(Value::as_str)
            .filter(|message_id| !message_id.is_empty())
    }

    pub(super) fn should_publish_idle_progress(
        idle_seconds: f64,
        last_published_at: f64,
        now: f64,
        interval_seconds: Option<i64>,
    ) -> bool {
        let interval = interval_seconds
            .unwrap_or(DEFAULT_WORKER_STREAM_IDLE_PROGRESS_INTERVAL_SECONDS)
            .max(1) as f64;
        if idle_seconds < interval {
            return false;
        }
        last_published_at <= 0.0 || now - last_published_at >= interval
    }

    pub(super) fn idle_progress_summary(
        idle_seconds: f64,
        last_stream_event_type: Option<&str>,
        running_exists: bool,
        finished_message_id: Option<&str>,
    ) -> String {
        let marker_state = if running_exists {
            "agent:running present"
        } else {
            "agent:running missing"
        };
        let mut parts = vec![
            format!(
                "Worker stream still active; no new visible stream event for {}s",
                idle_seconds as i64
            ),
            marker_state.to_string(),
        ];
        if let Some(event_type) = last_stream_event_type.filter(|value| !value.is_empty()) {
            parts.push(format!("last_event={event_type}"));
        }
        if let Some(finished_message_id) = finished_message_id.filter(|value| !value.is_empty()) {
            parts.push(format!("agent:finished={finished_message_id}"));
        }
        parts.join("; ")
    }

    pub(super) fn worker_launch_started_summary(
        attempt_number: Option<&str>,
        repair_brief_prompt: Option<&str>,
    ) -> String {
        let attempt_label = attempt_number
            .filter(|value| !value.is_empty())
            .map(|value| format!("attempt #{value}"))
            .unwrap_or_else(|| "attempt".to_string());
        let repair_summary = compact_progress_text(repair_brief_prompt);
        if repair_summary.is_empty() {
            return format!("Worker {attempt_label} started; session is bound and streaming.");
        }
        format!("Worker {attempt_label} started from verifier feedback: {repair_summary}")
    }

    pub(super) fn compact_progress_text(value: Option<&str>) -> String {
        let Some(value) = value else {
            return String::new();
        };
        let collapsed = value.split_whitespace().collect::<Vec<_>>().join(" ");
        if collapsed.is_empty() {
            return collapsed;
        }
        if collapsed.chars().count() <= WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS {
            return collapsed;
        }
        let end = char_prefix_boundary(&collapsed, WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS - 1);
        format!("{}...", collapsed[..end].trim_end())
    }

    pub(super) fn stream_completion_summary(final_content: &str, accumulated_text: &str) -> String {
        let mut summary = if final_content.is_empty() {
            accumulated_text.trim().to_string()
        } else {
            final_content.trim().to_string()
        };
        if summary.is_empty() {
            summary = "Worker stream completed without an explicit workspace terminal report."
                .to_string();
        }
        if summary.chars().count() > WORKER_STREAM_COMPLETION_SUMMARY_CHARS {
            let end = char_prefix_boundary(&summary, WORKER_STREAM_COMPLETION_SUMMARY_CHARS - 3);
            summary = format!("{}...", &summary[..end]);
        }
        summary
    }

    pub(super) fn should_synthesize_stream_completion_report(
        terminal_report_tool_observed: bool,
    ) -> bool {
        !terminal_report_tool_observed
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub(super) enum TerminalReportToolStatus {
        Denied,
        Applied,
        Attempted,
    }

    impl TerminalReportToolStatus {
        pub(super) fn as_str(self) -> &'static str {
            match self {
                Self::Denied => "denied",
                Self::Applied => "applied",
                Self::Attempted => "attempted",
            }
        }
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub(super) enum TerminalReportType {
        Completed,
        Blocked,
    }

    impl TerminalReportType {
        pub(super) fn as_str(self) -> &'static str {
            match self {
                Self::Completed => "completed",
                Self::Blocked => "blocked",
            }
        }
    }

    pub(super) fn terminal_report_tool_observation_status(
        event: &Value,
    ) -> Option<TerminalReportToolStatus> {
        if event.get("type").and_then(Value::as_str) != Some("observe") {
            return None;
        }
        let data = event.get("data")?.as_object()?;
        let _report_type = terminal_report_type_for_tool(data.get("tool_name")?)?;
        if data.get("error").is_some_and(json_truthy) {
            return Some(TerminalReportToolStatus::Denied);
        }
        Some(terminal_report_tool_result_status(data.get("result")))
    }

    pub(super) fn terminal_report_tool_report_type(event: &Value) -> Option<TerminalReportType> {
        if event.get("type").and_then(Value::as_str) != Some("observe") {
            return None;
        }
        let data = event.get("data")?.as_object()?;
        terminal_report_type_for_tool(data.get("tool_name")?)
    }

    pub(super) fn terminal_report_metadata_matches_attempt(
        metadata: Option<&Value>,
        attempt_id: Option<&str>,
        report_type: Option<&str>,
    ) -> bool {
        let Some(attempt_id) = attempt_id.filter(|value| !value.is_empty()) else {
            return false;
        };
        let Some(metadata) = metadata.and_then(Value::as_object) else {
            return false;
        };
        if metadata
            .get("last_worker_report_attempt_id")
            .and_then(Value::as_str)
            != Some(attempt_id)
        {
            return false;
        }
        match report_type.filter(|value| !value.is_empty()) {
            Some(report_type) => {
                metadata
                    .get("last_worker_report_type")
                    .and_then(Value::as_str)
                    == Some(report_type)
            }
            None => true,
        }
    }

    pub(super) fn should_reconcile_terminal_report_tool(
        terminal_report_tool_applied: bool,
        report_recorded_for_attempt: bool,
    ) -> bool {
        terminal_report_tool_applied && !report_recorded_for_attempt
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub(super) enum StreamTerminalEvent {
        Complete,
        Error,
    }

    #[derive(Debug, Clone, PartialEq, Eq, Default)]
    pub(super) struct StreamState {
        pub(super) final_content: String,
        pub(super) accumulated_text: String,
        pub(super) terminal_event: Option<StreamTerminalEvent>,
        pub(super) stream_message_id: Option<String>,
        pub(super) terminal_report_tool_observed: bool,
        pub(super) terminal_report_tool_denied: bool,
        pub(super) terminal_report_tool_applied: bool,
        pub(super) terminal_report_tool_report_type: Option<TerminalReportType>,
        pub(super) last_stream_event_type: Option<String>,
    }

    impl StreamState {
        pub(super) fn observe_event(&mut self, event: &Value) -> Option<StreamTerminalEvent> {
            if self.stream_message_id.is_none() {
                self.stream_message_id = message_id_from_event(event).map(ToOwned::to_owned);
            }
            let event_type = event
                .get("type")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            self.last_stream_event_type = Some(event_type.to_string());
            match event_type {
                "text_delta" => {
                    if let Some(text) = event
                        .get("data")
                        .and_then(Value::as_object)
                        .and_then(|data| data.get("text"))
                        .and_then(Value::as_str)
                    {
                        self.accumulated_text.push_str(text);
                    }
                    None
                }
                "observe" => {
                    if let Some(status) = terminal_report_tool_observation_status(event) {
                        self.terminal_report_tool_observed = true;
                        if let Some(report_type) = terminal_report_tool_report_type(event) {
                            self.terminal_report_tool_report_type = Some(report_type);
                        }
                        match status {
                            TerminalReportToolStatus::Denied => {
                                self.terminal_report_tool_denied = true;
                            }
                            TerminalReportToolStatus::Applied => {
                                self.terminal_report_tool_applied = true;
                            }
                            TerminalReportToolStatus::Attempted => {}
                        }
                    }
                    None
                }
                "complete" => {
                    self.terminal_event = Some(StreamTerminalEvent::Complete);
                    self.final_content = event
                        .get("data")
                        .and_then(Value::as_object)
                        .and_then(|data| data.get("content"))
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string();
                    if self.final_content.is_empty() && !self.accumulated_text.is_empty() {
                        self.final_content = self.accumulated_text.clone();
                    }
                    self.terminal_event
                }
                "error" => {
                    self.terminal_event = Some(StreamTerminalEvent::Error);
                    self.final_content = event
                        .get("data")
                        .and_then(Value::as_object)
                        .and_then(|data| data.get("message"))
                        .and_then(Value::as_str)
                        .unwrap_or("Worker stream reported an error")
                        .to_string();
                    self.terminal_event
                }
                _ => None,
            }
        }

        pub(super) fn mark_stream_ended_without_terminal(&mut self) {
            self.final_content =
                "Worker stream ended without a terminal complete/error event.".to_string();
            self.terminal_event = None;
        }

        pub(super) fn mark_orphaned_stream_stop(&mut self, reason: Option<&str>) {
            let reason = reason.unwrap_or("unknown");
            self.final_content = format!(
                "Worker stream stopped without a terminal complete/error event ({reason})."
            );
            self.terminal_event = None;
        }

        pub(super) fn terminal_outcome(
            &self,
            report_recorded_for_attempt: bool,
        ) -> TerminalOutcome {
            match self.terminal_event {
                Some(StreamTerminalEvent::Complete) => {
                    let summary =
                        stream_completion_summary(&self.final_content, &self.accumulated_text);
                    if should_synthesize_stream_completion_report(
                        self.terminal_report_tool_observed,
                    ) {
                        return TerminalOutcome {
                            outcome_reason: "completed",
                            launch_state: "completed_via_stream",
                            report_type: Some(TerminalReportType::Completed),
                            summary,
                            should_report: true,
                            should_reconcile: false,
                        };
                    }
                    if should_reconcile_terminal_report_tool(
                        self.terminal_report_tool_applied,
                        report_recorded_for_attempt,
                    ) {
                        return TerminalOutcome {
                            outcome_reason: "terminal_report_tool_reconciled",
                            launch_state: "terminal_report_tool_reconciled",
                            report_type: Some(
                                self.terminal_report_tool_report_type
                                    .unwrap_or(TerminalReportType::Completed),
                            ),
                            summary,
                            should_report: true,
                            should_reconcile: true,
                        };
                    }
                    let outcome_reason = if self.terminal_report_tool_applied {
                        "terminal_report_tool_applied"
                    } else if self.terminal_report_tool_denied {
                        "terminal_report_tool_denied"
                    } else {
                        "terminal_report_tool_observed"
                    };
                    TerminalOutcome {
                        outcome_reason,
                        launch_state: outcome_reason,
                        report_type: None,
                        summary,
                        should_report: false,
                        should_reconcile: false,
                    }
                }
                Some(StreamTerminalEvent::Error) => TerminalOutcome {
                    outcome_reason: "blocked",
                    launch_state: "blocked",
                    report_type: Some(TerminalReportType::Blocked),
                    summary: bounded_terminal_summary(
                        &self.final_content,
                        "Worker stream errored.",
                    ),
                    should_report: true,
                    should_reconcile: false,
                },
                None => {
                    if self.terminal_report_tool_applied {
                        TerminalOutcome {
                            outcome_reason: "terminal_report_tool_applied",
                            launch_state: "terminal_report_tool_applied",
                            report_type: None,
                            summary: bounded_terminal_summary(&self.final_content, ""),
                            should_report: false,
                            should_reconcile: false,
                        }
                    } else {
                        TerminalOutcome {
                            outcome_reason: "no_terminal_event",
                            launch_state: "no_terminal_event",
                            report_type: Some(TerminalReportType::Blocked),
                            summary: bounded_terminal_summary(
                                &self.final_content,
                                "Worker stream ended without a terminal complete/error event and without a workspace_report_complete/workspace_report_blocked tool call.",
                            ),
                            should_report: true,
                            should_reconcile: false,
                        }
                    }
                }
            }
        }
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    pub(super) struct TerminalOutcome {
        pub(super) outcome_reason: &'static str,
        pub(super) launch_state: &'static str,
        pub(super) report_type: Option<TerminalReportType>,
        pub(super) summary: String,
        pub(super) should_report: bool,
        pub(super) should_reconcile: bool,
    }

    fn terminal_report_type_for_tool(value: &Value) -> Option<TerminalReportType> {
        match value.as_str()?.trim() {
            "workspace_report_complete" => Some(TerminalReportType::Completed),
            "workspace_report_blocked" => Some(TerminalReportType::Blocked),
            _ => None,
        }
    }

    fn terminal_report_tool_result_status(result: Option<&Value>) -> TerminalReportToolStatus {
        let result_text = result.and_then(Value::as_str).unwrap_or("");
        if let Ok(Value::Object(parsed)) = serde_json::from_str::<Value>(result_text) {
            if let Some(status) = parsed_terminal_report_tool_status(&parsed) {
                return status;
            }
        }
        let lowered = result_text.to_lowercase();
        if lowered.contains("completion denied:")
            || lowered.contains("terminal_report_apply_failed")
            || lowered.contains("\"error\"")
        {
            TerminalReportToolStatus::Denied
        } else {
            TerminalReportToolStatus::Attempted
        }
    }

    fn parsed_terminal_report_tool_status(
        parsed: &serde_json::Map<String, Value>,
    ) -> Option<TerminalReportToolStatus> {
        if let Some(applied_report) = parsed.get("applied_report").and_then(Value::as_object) {
            if applied_report
                .get("skipped_supervisor_only")
                .and_then(Value::as_bool)
                == Some(true)
            {
                return Some(TerminalReportToolStatus::Attempted);
            }
            if applied_report.get("applied").and_then(Value::as_bool) == Some(true) {
                return Some(TerminalReportToolStatus::Applied);
            }
        }
        if parsed.get("ok").and_then(Value::as_bool) == Some(true) {
            return Some(TerminalReportToolStatus::Applied);
        }
        if parsed.get("error").is_some_and(json_truthy) {
            return Some(TerminalReportToolStatus::Denied);
        }
        None
    }

    fn bounded_terminal_summary(value: &str, default: &str) -> String {
        let trimmed = value.trim();
        let summary = if trimmed.is_empty() { default } else { trimmed };
        if summary.chars().count() > WORKER_STREAM_COMPLETION_SUMMARY_CHARS {
            let end = char_prefix_boundary(summary, WORKER_STREAM_COMPLETION_SUMMARY_CHARS);
            summary[..end].to_string()
        } else {
            summary.to_string()
        }
    }

    fn json_truthy(value: &Value) -> bool {
        match value {
            Value::Null => false,
            Value::Bool(value) => *value,
            Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
            Value::String(value) => !value.is_empty(),
            Value::Array(value) => !value.is_empty(),
            Value::Object(value) => !value.is_empty(),
        }
    }

    fn char_prefix_boundary(value: &str, max_chars: usize) -> usize {
        value
            .char_indices()
            .nth(max_chars)
            .map(|(index, _)| index)
            .unwrap_or(value.len())
    }
}

#[async_trait]
pub(crate) trait WorkerLaunchRuntimeStateStore: Send + Sync {
    async fn claim_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn refresh_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn agent_finished_message_id(&self, conversation_id: &str) -> CoreResult<Option<String>>;

    async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool>;

    async fn refresh_agent_running_marker(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()>;
}

#[derive(Debug, Default)]
struct NoopWorkerLaunchRuntimeStateStore;

#[async_trait]
impl WorkerLaunchRuntimeStateStore for NoopWorkerLaunchRuntimeStateStore {
    async fn claim_launch_cooldown(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(true)
    }

    async fn refresh_launch_cooldown(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(false)
    }

    async fn agent_finished_message_id(
        &self,
        _conversation_id: &str,
    ) -> CoreResult<Option<String>> {
        Ok(None)
    }

    async fn agent_running_exists(&self, _conversation_id: &str) -> CoreResult<bool> {
        Ok(false)
    }

    async fn refresh_agent_running_marker(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(false)
    }

    async fn clear_reused_session_markers(&self, _conversation_id: &str) -> CoreResult<()> {
        Ok(())
    }
}

#[async_trait]
impl WorkerLaunchRuntimeStateStore for agistack_adapters_redis::RedisWorkerLaunchStateStore {
    async fn claim_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.claim_worker_launch_cooldown(conversation_id, ttl_seconds)
            .await
    }

    async fn refresh_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.refresh_worker_launch_cooldown(conversation_id, ttl_seconds)
            .await
    }

    async fn agent_finished_message_id(&self, conversation_id: &str) -> CoreResult<Option<String>> {
        self.agent_finished_message_id(conversation_id).await
    }

    async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool> {
        self.agent_running_exists(conversation_id).await
    }

    async fn refresh_agent_running_marker(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.refresh_existing_agent_running_marker(conversation_id, ttl_seconds)
            .await
    }

    async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()> {
        self.clear_reused_worker_session_markers(conversation_id)
            .await
    }
}

#[async_trait]
pub(crate) trait WorkerLaunchEventStream: Send + Sync {
    async fn read_after(
        &self,
        conversation_id: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>>;
}

#[derive(Debug, Default)]
struct NoopWorkerLaunchEventStream;

#[async_trait]
impl WorkerLaunchEventStream for NoopWorkerLaunchEventStream {
    async fn read_after(
        &self,
        _conversation_id: &str,
        _after_id: &str,
        _limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        Ok(Vec::new())
    }
}

struct EventStreamWorkerLaunchEventSource {
    events: Arc<dyn EventStream>,
}

#[async_trait]
impl WorkerLaunchEventStream for EventStreamWorkerLaunchEventSource {
    async fn read_after(
        &self,
        conversation_id: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        self.events
            .read_after(&worker_stream_topic(conversation_id), after_id, limit)
            .await
    }
}

pub(crate) fn worker_launch_event_stream_source(
    events: Arc<dyn EventStream>,
) -> Arc<dyn WorkerLaunchEventStream> {
    Arc::new(EventStreamWorkerLaunchEventSource { events })
}

#[cfg(test)]
pub(crate) fn workspace_plan_outbox_handlers(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
) -> WorkspacePlanOutboxHandlers {
    workspace_plan_outbox_handlers_with_stage_runner(dispatch_store, None)
}

#[allow(dead_code)]
pub(crate) fn workspace_plan_outbox_handlers_with_stage_runner(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
) -> WorkspacePlanOutboxHandlers {
    workspace_plan_outbox_handlers_with_runtime_state(dispatch_store, stage_runner, None)
}

#[allow(dead_code)]
pub(crate) fn workspace_plan_outbox_handlers_with_runtime_state(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
    worker_launch_state: Option<Arc<dyn WorkerLaunchRuntimeStateStore>>,
) -> WorkspacePlanOutboxHandlers {
    workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
        dispatch_store,
        stage_runner,
        worker_launch_state,
        None,
    )
}

pub(crate) fn workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
    worker_launch_state: Option<Arc<dyn WorkerLaunchRuntimeStateStore>>,
    worker_stream_events: Option<Arc<dyn WorkerLaunchEventStream>>,
) -> WorkspacePlanOutboxHandlers {
    let handoff = Arc::new(DurableHandoffResumeHandler::new(Arc::clone(
        &dispatch_store,
    )));
    let stream_events =
        worker_stream_events.unwrap_or_else(|| Arc::new(NoopWorkerLaunchEventStream));
    let worker_launch = Arc::new(match worker_launch_state {
        Some(runtime_state) => WorkerLaunchAdmissionHandler::with_runtime_state_and_event_stream(
            Arc::clone(&dispatch_store),
            runtime_state,
            stream_events,
        ),
        None => WorkerLaunchAdmissionHandler::with_event_stream(
            Arc::clone(&dispatch_store),
            stream_events,
        ),
    });
    let supervisor_tick = Arc::new(SupervisorTickAdmissionHandler::new(Arc::clone(
        &dispatch_store,
    )));
    let pipeline_run = Arc::new(PipelineRunAdmissionHandler::new(
        dispatch_store,
        stage_runner,
    ));
    HashMap::from([
        (
            SUPERVISOR_TICK_EVENT.to_string(),
            supervisor_tick as Arc<dyn WorkspacePlanOutboxHandler>,
        ),
        (
            HANDOFF_RESUME_EVENT.to_string(),
            Arc::clone(&handoff) as Arc<dyn WorkspacePlanOutboxHandler>,
        ),
        (
            ATTEMPT_RETRY_EVENT.to_string(),
            handoff as Arc<dyn WorkspacePlanOutboxHandler>,
        ),
        (
            WORKER_LAUNCH_EVENT.to_string(),
            worker_launch as Arc<dyn WorkspacePlanOutboxHandler>,
        ),
        (
            PIPELINE_RUN_REQUESTED_EVENT.to_string(),
            pipeline_run as Arc<dyn WorkspacePlanOutboxHandler>,
        ),
    ])
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct WorkspacePlanOutboxWorkerConfig {
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_seconds: i64,
    pub poll_interval_millis: u64,
    pub autostart: bool,
    pub production_ready: bool,
}

impl WorkspacePlanOutboxWorkerConfig {
    pub(crate) fn from_env() -> Self {
        let rust_autostart = bool_env("AGISTACK_WORKSPACE_PLAN_OUTBOX_AUTOSTART", false);
        let python_worker_enabled = bool_env("WORKSPACE_PLAN_OUTBOX_ENABLED", true);
        Self {
            worker_id: std::env::var("WORKSPACE_PLAN_OUTBOX_WORKER_ID")
                .ok()
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| "agistack-rust-workspace-plan-outbox".to_string()),
            batch_size: positive_i64_env("WORKSPACE_PLAN_OUTBOX_BATCH_SIZE", 10),
            lease_seconds: positive_i64_env("WORKSPACE_PLAN_OUTBOX_LEASE_SECONDS", 60),
            poll_interval_millis: positive_millis_env("WORKSPACE_PLAN_OUTBOX_POLL_SECONDS", 2000),
            autostart: rust_autostart && python_worker_enabled,
            production_ready: bool_env(WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY_ENV, false),
        }
    }
}

impl Default for WorkspacePlanOutboxWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: "agistack-rust-workspace-plan-outbox".to_string(),
            batch_size: 10,
            lease_seconds: 60,
            poll_interval_millis: 2000,
            autostart: false,
            production_ready: false,
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct WorkspacePlanOutboxRunReport {
    pub claimed: usize,
    pub completed: usize,
    pub failed: usize,
    pub released: usize,
    pub missing_handler: usize,
    pub skipped: usize,
}

pub(crate) struct WorkspacePlanOutboxWorkerRuntime {
    join: Option<JoinHandle<()>>,
}

impl WorkspacePlanOutboxWorkerRuntime {
    #[cfg(test)]
    async fn shutdown(mut self) {
        if let Some(join) = self.join.take() {
            join.abort();
            let _ = join.await;
        }
    }
}

impl Drop for WorkspacePlanOutboxWorkerRuntime {
    fn drop(&mut self) {
        if let Some(join) = &self.join {
            join.abort();
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
#[allow(dead_code)]
pub(crate) enum WorkspacePlanOutboxHandlerOutcome {
    Complete,
    Release { reason: Option<String> },
}

#[async_trait]
pub(crate) trait WorkspacePlanOutboxHandler: Send + Sync {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome>;
}

#[async_trait]
pub(crate) trait WorkspacePipelineStageRunner: Send + Sync {
    async fn run_stage(
        &self,
        project_id: &str,
        contract: &PipelineContractFoundation,
        stage: &PipelineStageSpec,
    ) -> PipelineStageResult;
}

pub(crate) struct ProjectSandboxPipelineStageRunner {
    sandboxes: Arc<ProjectSandboxService>,
}

impl ProjectSandboxPipelineStageRunner {
    pub(crate) fn new(sandboxes: Arc<ProjectSandboxService>) -> Self {
        Self { sandboxes }
    }
}

#[async_trait]
impl WorkspacePipelineStageRunner for ProjectSandboxPipelineStageRunner {
    async fn run_stage(
        &self,
        project_id: &str,
        contract: &PipelineContractFoundation,
        stage: &PipelineStageSpec,
    ) -> PipelineStageResult {
        let command = wrapped_pipeline_command(
            &stage.command,
            contract.code_root.as_deref(),
            &contract.env_json,
        );
        let started = Instant::now();
        let raw = self
            .sandboxes
            .execute_pipeline_tool(
                project_id,
                "bash",
                &json!({
                    "command": command,
                    "timeout": stage.timeout_seconds
                }),
                f64::from(stage.timeout_seconds.saturating_add(5).max(1)),
            )
            .await;
        let duration_ms = saturating_duration_ms(started.elapsed().as_millis());
        match raw {
            Ok(response) => pipeline_stage_result_from_tool_response(stage, response, duration_ms),
            Err(err) => PipelineStageResult {
                stage: stage.stage.clone(),
                status: "failed".to_string(),
                command: stage.command.clone(),
                exit_code: Some(1),
                stdout_preview: String::new(),
                stderr_preview: compact_text(&format!("{err:?}"), 4_000),
                duration_ms,
                log_ref: None,
                artifact_refs: Vec::new(),
                service_id: stage.service_id.clone(),
                required: stage.required,
            },
        }
    }
}

#[async_trait]
pub(crate) trait WorkspacePlanOutboxStore: Send + Sync {
    async fn claim_due(
        &self,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>>;

    async fn mark_completed(
        &self,
        outbox_id: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool>;

    async fn mark_failed(
        &self,
        outbox_id: &str,
        error_message: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool>;

    async fn release_processing(
        &self,
        outbox_id: &str,
        error_message: Option<&str>,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool>;
}

#[async_trait]
pub(crate) trait WorkspacePlanDispatchStore: Send + Sync {
    async fn get_workspace(&self, workspace_id: &str) -> CoreResult<Option<WorkspaceRecord>>;

    async fn get_task(
        &self,
        workspace_id: &str,
        task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskRecord>>;

    async fn list_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>>;

    async fn list_current_plan_child_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>>;

    async fn save_task(&self, task: WorkspaceTaskRecord) -> CoreResult<WorkspaceTaskRecord>;

    async fn get_plan(&self, plan_id: &str) -> CoreResult<Option<WorkspacePlanRecord>>;

    async fn list_plan_nodes(&self, plan_id: &str) -> CoreResult<Vec<WorkspacePlanNodeRecord>>;

    async fn save_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord>;

    async fn find_active_task_session_attempt(
        &self,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>>;

    async fn find_latest_accepted_task_session_attempt(
        &self,
        workspace_id: &str,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>>;

    async fn get_task_session_attempt(
        &self,
        attempt_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>>;

    async fn latest_pipeline_run_for_node(
        &self,
        plan_id: &str,
        node_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>>;

    #[allow(clippy::too_many_arguments)]
    async fn ensure_pipeline_contract(
        &self,
        contract_id: &str,
        workspace_id: &str,
        plan_id: &str,
        provider: &str,
        code_root: Option<&str>,
        commands_json: &Value,
        env_json: &Value,
        trigger_policy_json: &Value,
        timeout_seconds: i32,
        auto_deploy: bool,
        preview_port: Option<i32>,
        health_url: Option<&str>,
        metadata_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<String>;

    async fn create_pipeline_run(
        &self,
        run: WorkspacePipelineRunRecord,
    ) -> CoreResult<WorkspacePipelineRunRecord>;

    async fn finish_pipeline_run(
        &self,
        run_id: &str,
        status: &str,
        reason: Option<&str>,
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>>;

    #[allow(dead_code)]
    async fn create_pipeline_stage_run(
        &self,
        stage_run: WorkspacePipelineStageRunRecord,
    ) -> CoreResult<WorkspacePipelineStageRunRecord>;

    #[allow(clippy::too_many_arguments, dead_code)]
    async fn finish_pipeline_stage_run(
        &self,
        stage_run_id: &str,
        status: &str,
        exit_code: Option<i32>,
        stdout_preview: Option<&str>,
        stderr_preview: Option<&str>,
        log_ref: Option<&str>,
        artifact_refs: &[String],
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineStageRunRecord>>;

    async fn latest_task_session_attempt_number(&self, workspace_task_id: &str) -> CoreResult<i32>;

    async fn create_task_session_attempt(
        &self,
        attempt: WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<WorkspaceTaskSessionAttemptRecord>;

    async fn mark_task_session_attempt_running(
        &self,
        attempt_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>>;

    #[allow(clippy::too_many_arguments)]
    async fn ensure_worker_launch_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        user_id: &str,
        title: &str,
        agent_config_json: &Value,
        metadata_json: &Value,
        participant_agents_json: &[String],
        focused_agent_id: &str,
        workspace_id: &str,
        linked_workspace_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()>;

    async fn bind_task_session_attempt_conversation(
        &self,
        attempt_id: &str,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>>;

    async fn finish_task_session_attempt(
        &self,
        attempt_id: &str,
        status: &str,
        leader_feedback: Option<&str>,
        adjudication_reason: Option<&str>,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>>;

    async fn record_task_session_attempt_candidate_output(
        &self,
        attempt_id: &str,
        summary: Option<&str>,
        artifacts_json: &[String],
        verifications_json: &[String],
        conversation_id: Option<&str>,
        updated_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>>;

    async fn count_recent_running_task_session_attempts_with_conversation(
        &self,
        workspace_id: &str,
        active_after: DateTime<Utc>,
    ) -> CoreResult<i64>;

    async fn has_supervisor_dispose_decision_for_node(
        &self,
        workspace_id: &str,
        plan_id: &str,
        node_id: &str,
    ) -> CoreResult<bool>;

    async fn create_plan_event(
        &self,
        event: WorkspacePlanEventRecord,
    ) -> CoreResult<WorkspacePlanEventRecord>;

    async fn enqueue_plan_outbox(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxRecord>;
}

pub(crate) struct PgWorkspacePlanOutboxStore {
    repo: PgWorkspaceRepository,
}

impl PgWorkspacePlanOutboxStore {
    pub(crate) fn new(repo: PgWorkspaceRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl WorkspacePlanOutboxStore for PgWorkspacePlanOutboxStore {
    async fn claim_due(
        &self,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
        self.repo
            .claim_due_plan_outbox(limit, lease_owner, lease_seconds, now)
            .await
    }

    async fn mark_completed(
        &self,
        outbox_id: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        self.repo
            .mark_plan_outbox_completed(outbox_id, lease_owner, now)
            .await
    }

    async fn mark_failed(
        &self,
        outbox_id: &str,
        error_message: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        self.repo
            .mark_plan_outbox_failed(outbox_id, error_message, lease_owner, now)
            .await
    }

    async fn release_processing(
        &self,
        outbox_id: &str,
        error_message: Option<&str>,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        self.repo
            .release_plan_outbox_processing(outbox_id, error_message, lease_owner, now)
            .await
    }
}

#[async_trait]
impl WorkspacePlanDispatchStore for PgWorkspaceRepository {
    async fn get_workspace(&self, workspace_id: &str) -> CoreResult<Option<WorkspaceRecord>> {
        PgWorkspaceRepository::get_workspace(self, workspace_id).await
    }

    async fn get_task(
        &self,
        workspace_id: &str,
        task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskRecord>> {
        PgWorkspaceRepository::get_task(self, workspace_id, task_id).await
    }

    async fn list_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        PgWorkspaceRepository::list_tasks_by_root_goal_task_id(
            self,
            workspace_id,
            root_goal_task_id,
        )
        .await
    }

    async fn list_current_plan_child_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        PgWorkspaceRepository::list_current_plan_child_tasks_by_root_goal_task_id(
            self,
            workspace_id,
            root_goal_task_id,
        )
        .await
    }

    async fn save_task(&self, task: WorkspaceTaskRecord) -> CoreResult<WorkspaceTaskRecord> {
        PgWorkspaceRepository::save_task(self, task).await
    }

    async fn get_plan(&self, plan_id: &str) -> CoreResult<Option<WorkspacePlanRecord>> {
        PgWorkspaceRepository::get_plan(self, plan_id).await
    }

    async fn list_plan_nodes(&self, plan_id: &str) -> CoreResult<Vec<WorkspacePlanNodeRecord>> {
        PgWorkspaceRepository::list_plan_nodes(self, plan_id).await
    }

    async fn save_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        PgWorkspaceRepository::save_plan_node(self, node).await
    }

    async fn find_active_task_session_attempt(
        &self,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        PgWorkspaceRepository::find_active_task_session_attempt(self, workspace_task_id).await
    }

    async fn find_latest_accepted_task_session_attempt(
        &self,
        workspace_id: &str,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        PgWorkspaceRepository::find_latest_accepted_task_session_attempt(
            self,
            workspace_id,
            workspace_task_id,
        )
        .await
    }

    async fn get_task_session_attempt(
        &self,
        attempt_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        PgWorkspaceRepository::get_task_session_attempt(self, attempt_id).await
    }

    async fn latest_pipeline_run_for_node(
        &self,
        plan_id: &str,
        node_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        PgWorkspaceRepository::latest_pipeline_run_for_node(self, plan_id, node_id, attempt_id)
            .await
    }

    async fn ensure_pipeline_contract(
        &self,
        contract_id: &str,
        workspace_id: &str,
        plan_id: &str,
        provider: &str,
        code_root: Option<&str>,
        commands_json: &Value,
        env_json: &Value,
        trigger_policy_json: &Value,
        timeout_seconds: i32,
        auto_deploy: bool,
        preview_port: Option<i32>,
        health_url: Option<&str>,
        metadata_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<String> {
        PgWorkspaceRepository::ensure_pipeline_contract(
            self,
            contract_id,
            workspace_id,
            plan_id,
            provider,
            code_root,
            commands_json,
            env_json,
            trigger_policy_json,
            timeout_seconds,
            auto_deploy,
            preview_port,
            health_url,
            metadata_json,
            now,
        )
        .await
    }

    async fn create_pipeline_run(
        &self,
        run: WorkspacePipelineRunRecord,
    ) -> CoreResult<WorkspacePipelineRunRecord> {
        PgWorkspaceRepository::create_pipeline_run(self, run).await
    }

    async fn finish_pipeline_run(
        &self,
        run_id: &str,
        status: &str,
        reason: Option<&str>,
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        PgWorkspaceRepository::finish_pipeline_run(
            self,
            run_id,
            status,
            reason,
            metadata_patch,
            completed_at,
        )
        .await
    }

    async fn create_pipeline_stage_run(
        &self,
        stage_run: WorkspacePipelineStageRunRecord,
    ) -> CoreResult<WorkspacePipelineStageRunRecord> {
        PgWorkspaceRepository::create_pipeline_stage_run(self, stage_run).await
    }

    async fn finish_pipeline_stage_run(
        &self,
        stage_run_id: &str,
        status: &str,
        exit_code: Option<i32>,
        stdout_preview: Option<&str>,
        stderr_preview: Option<&str>,
        log_ref: Option<&str>,
        artifact_refs: &[String],
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineStageRunRecord>> {
        PgWorkspaceRepository::finish_pipeline_stage_run(
            self,
            stage_run_id,
            status,
            exit_code,
            stdout_preview,
            stderr_preview,
            log_ref,
            artifact_refs,
            metadata_patch,
            completed_at,
        )
        .await
    }

    async fn latest_task_session_attempt_number(&self, workspace_task_id: &str) -> CoreResult<i32> {
        PgWorkspaceRepository::latest_task_session_attempt_number(self, workspace_task_id).await
    }

    async fn create_task_session_attempt(
        &self,
        attempt: WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
        PgWorkspaceRepository::create_task_session_attempt(self, attempt).await
    }

    async fn mark_task_session_attempt_running(
        &self,
        attempt_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        PgWorkspaceRepository::mark_task_session_attempt_running(self, attempt_id, now).await
    }

    async fn ensure_worker_launch_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        user_id: &str,
        title: &str,
        agent_config_json: &Value,
        metadata_json: &Value,
        participant_agents_json: &[String],
        focused_agent_id: &str,
        workspace_id: &str,
        linked_workspace_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        PgWorkspaceRepository::ensure_worker_launch_conversation(
            self,
            conversation_id,
            project_id,
            tenant_id,
            user_id,
            title,
            agent_config_json,
            metadata_json,
            participant_agents_json,
            focused_agent_id,
            workspace_id,
            linked_workspace_task_id,
            now,
        )
        .await
    }

    async fn bind_task_session_attempt_conversation(
        &self,
        attempt_id: &str,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        PgWorkspaceRepository::bind_task_session_attempt_conversation(
            self,
            attempt_id,
            conversation_id,
            now,
        )
        .await
    }

    async fn finish_task_session_attempt(
        &self,
        attempt_id: &str,
        status: &str,
        leader_feedback: Option<&str>,
        adjudication_reason: Option<&str>,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        PgWorkspaceRepository::finish_task_session_attempt(
            self,
            attempt_id,
            status,
            leader_feedback,
            adjudication_reason,
            completed_at,
        )
        .await
    }

    async fn record_task_session_attempt_candidate_output(
        &self,
        attempt_id: &str,
        summary: Option<&str>,
        artifacts_json: &[String],
        verifications_json: &[String],
        conversation_id: Option<&str>,
        updated_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        PgWorkspaceRepository::record_task_session_attempt_candidate_output(
            self,
            attempt_id,
            summary,
            artifacts_json,
            verifications_json,
            conversation_id,
            updated_at,
        )
        .await
    }

    async fn count_recent_running_task_session_attempts_with_conversation(
        &self,
        workspace_id: &str,
        active_after: DateTime<Utc>,
    ) -> CoreResult<i64> {
        PgWorkspaceRepository::count_recent_running_task_session_attempts_with_conversation(
            self,
            workspace_id,
            active_after,
        )
        .await
    }

    async fn has_supervisor_dispose_decision_for_node(
        &self,
        workspace_id: &str,
        plan_id: &str,
        node_id: &str,
    ) -> CoreResult<bool> {
        PgWorkspaceRepository::has_supervisor_dispose_decision_for_node(
            self,
            workspace_id,
            plan_id,
            node_id,
        )
        .await
    }

    async fn create_plan_event(
        &self,
        event: WorkspacePlanEventRecord,
    ) -> CoreResult<WorkspacePlanEventRecord> {
        PgWorkspaceRepository::create_plan_event(self, event).await
    }

    async fn enqueue_plan_outbox(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxRecord> {
        PgWorkspaceRepository::enqueue_plan_outbox(self, item).await
    }
}

pub(crate) struct DurableHandoffResumeHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
}

impl DurableHandoffResumeHandler {
    pub(crate) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self { store }
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for DurableHandoffResumeHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_or_empty(item.payload_json.clone());
        let workspace_id =
            string_from_map(&payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let task_id = required_string(&payload, "task_id")?;
        let mut task = self
            .store
            .get_task(&workspace_id, &task_id)
            .await?
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "workspace task {task_id} not found for workspace {workspace_id}"
                ))
            })?;
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        let actor_user_id =
            string_from_map(&payload, "actor_user_id").unwrap_or_else(|| task.created_by.clone());
        let leader_agent_id = string_from_map(&payload, "leader_agent_id")
            .or_else(|| string_from_map(&task_metadata, "leader_agent_id"))
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let worker_agent_id = string_from_map(&payload, "worker_agent_id")
            .or_else(|| task.assignee_agent_id.clone())
            .ok_or_else(|| {
                CoreError::Storage(format!("workspace task {task_id} has no worker agent"))
            })?;
        let root_goal_task_id = string_from_map(&payload, ROOT_GOAL_TASK_ID)
            .or_else(|| string_from_map(&payload, "root_task_id"))
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID))
            .ok_or_else(|| {
                CoreError::Storage(format!("workspace task {task_id} has no root goal task"))
            })?;
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(&payload, "plan_id"))
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_ID));
        let node_id = string_from_map(&payload, "node_id")
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_NODE_ID));
        let previous_attempt_id = string_from_map(&payload, "previous_attempt_id");
        let force_schedule = bool_from_map(&payload, "force_schedule");

        let mut should_schedule = force_schedule;
        let mut attempt = self
            .store
            .find_active_task_session_attempt(&task.id)
            .await?;
        if let Some(active) = attempt.as_ref() {
            if !force_schedule
                && previous_attempt_id.as_deref() == Some(active.id.as_str())
                && active.status == "running"
                && active.conversation_id.is_some()
            {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
        }

        let now = Utc::now();
        if attempt.is_none() {
            let next_attempt_number = self
                .store
                .latest_task_session_attempt_number(&task.id)
                .await?
                + 1;
            let created = self
                .store
                .create_task_session_attempt(WorkspaceTaskSessionAttemptRecord {
                    id: generate_uuid_v4(),
                    workspace_task_id: task.id.clone(),
                    root_goal_task_id: root_goal_task_id.clone(),
                    workspace_id: workspace_id.clone(),
                    attempt_number: next_attempt_number,
                    status: "pending".to_string(),
                    conversation_id: None,
                    worker_agent_id: Some(worker_agent_id.clone()),
                    leader_agent_id: persisted_attempt_leader_agent_id(&leader_agent_id),
                    candidate_summary: None,
                    candidate_artifacts_json: Vec::new(),
                    candidate_verifications_json: Vec::new(),
                    leader_feedback: None,
                    adjudication_reason: None,
                    created_at: now,
                    updated_at: Some(now),
                    completed_at: None,
                })
                .await?;
            attempt = Some(created);
            should_schedule = true;
        }
        let mut attempt = attempt.expect("attempt must exist after creation branch");
        if attempt.status == "pending" {
            attempt = self
                .store
                .mark_task_session_attempt_running(&attempt.id, now)
                .await?
                .ok_or_else(|| {
                    CoreError::Storage(format!(
                        "workspace task session attempt {} not found",
                        attempt.id
                    ))
                })?;
            should_schedule = true;
        } else if attempt.conversation_id.is_none() {
            should_schedule = true;
        }

        if let (Some(plan_id), Some(node_id)) = (plan_id.as_deref(), node_id.as_deref()) {
            self.project_attempt_to_plan_node(
                &workspace_id,
                plan_id,
                node_id,
                &item,
                &payload,
                &attempt,
                &worker_agent_id,
            )
            .await?;
        }

        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
        task_metadata.insert(
            "current_attempt_number".to_string(),
            json!(attempt.attempt_number),
        );
        task_metadata.insert(
            "current_attempt_worker_agent_id".to_string(),
            json!(worker_agent_id.clone()),
        );
        task_metadata.insert(CURRENT_ATTEMPT_WORKER_BINDING_ID.to_string(), Value::Null);
        task_metadata.insert("last_attempt_status".to_string(), json!("running"));
        task_metadata.insert("launch_state".to_string(), json!("scheduled"));
        if should_reset_attempt_retry_worker_state(&item.event_type, &payload) {
            clear_attempt_retry_worker_stream_state(&mut task_metadata);
            task.blocker_reason = None;
        }
        apply_attempt_retry_context(&mut task_metadata, &payload, now);
        task_metadata.insert(
            "execution_state".to_string(),
            json!({
                "phase": "in_progress",
                "last_agent_reason": "workspace_plan.dispatch.project_attempt",
                "last_agent_action": "start",
                "updated_by_actor_type": "agent",
                "updated_by_actor_id": leader_agent_id,
                "updated_at": now.to_rfc3339()
            }),
        );
        task.metadata_json = Value::Object(task_metadata);
        if task.status != "done" {
            task.status = "in_progress".to_string();
            task.completed_at = None;
        }
        task.updated_at = Some(now);
        self.store.save_task(task).await?;

        if should_schedule {
            self.store
                .enqueue_plan_outbox(worker_launch_outbox(
                    plan_id.as_deref(),
                    &workspace_id,
                    &item.event_type,
                    &payload,
                    &task_id,
                    &worker_agent_id,
                    &actor_user_id,
                    &leader_agent_id,
                    &attempt.id,
                    node_id.as_deref(),
                    now,
                ))
                .await?;
        }

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

impl DurableHandoffResumeHandler {
    async fn project_attempt_to_plan_node(
        &self,
        workspace_id: &str,
        plan_id: &str,
        node_id: &str,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        worker_agent_id: &str,
    ) -> CoreResult<()> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let mut node = nodes
            .drain(..)
            .find(|candidate| candidate.id == node_id)
            .ok_or_else(|| {
                CoreError::Storage(format!("workspace plan node {node_id} not found"))
            })?;
        let now = Utc::now();
        let handoff = json!({
            "event_type": item.event_type,
            "outbox_id": item.id,
            "previous_attempt_id": string_from_map(payload, "previous_attempt_id"),
            "attempt_id": attempt.id,
            "worker_agent_id": worker_agent_id,
        });
        let mut handoff = handoff;
        if let Some(handoff) = handoff.as_object_mut() {
            copy_retry_context_payload_fields(payload, handoff);
        }
        node.handoff_package_json = Some(handoff.clone());
        node.current_attempt_id = Some(attempt.id.clone());
        node.assignee_agent_id = Some(worker_agent_id.to_string());
        apply_attempt_worktree_checkpoint(&mut node, &attempt.id);
        if node.intent != "done" {
            node.intent = "in_progress".to_string();
            node.execution = "dispatched".to_string();
            node.completed_at = None;
        }
        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert("handoff_package".to_string(), handoff);
        metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
        metadata.insert(
            "current_attempt_number".to_string(),
            json!(attempt.attempt_number),
        );
        metadata.insert(
            "current_attempt_worker_agent_id".to_string(),
            json!(worker_agent_id),
        );
        metadata.insert("last_attempt_status".to_string(), json!("running"));
        metadata.insert("launch_state".to_string(), json!("scheduled"));
        if should_reset_attempt_retry_worker_state(&item.event_type, payload) {
            clear_attempt_retry_worker_stream_state(&mut metadata);
        }
        apply_attempt_retry_context(&mut metadata, payload, now);
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct WorkerLaunchAdmissionConfig {
    pub max_active_worker_conversations: i64,
    pub defer_seconds: i64,
    pub active_event_grace_seconds: i64,
    pub stream_poll_interval_seconds: i64,
}

impl WorkerLaunchAdmissionConfig {
    fn from_env() -> Self {
        Self {
            max_active_worker_conversations: i64_env(
                WORKER_LAUNCH_MAX_ACTIVE_ENV,
                DEFAULT_WORKER_LAUNCH_MAX_ACTIVE,
            ),
            defer_seconds: positive_i64_env(
                WORKER_LAUNCH_DEFER_SECONDS_ENV,
                DEFAULT_WORKER_LAUNCH_DEFER_SECONDS,
            ),
            active_event_grace_seconds: positive_i64_env(
                WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS_ENV,
                DEFAULT_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS,
            ),
            stream_poll_interval_seconds: positive_i64_env(
                WORKER_STREAM_POLL_INTERVAL_SECONDS_ENV,
                DEFAULT_WORKER_STREAM_POLL_INTERVAL_SECONDS,
            ),
        }
    }
}

fn worker_conversation_scope_for_task(task_id: &str, attempt_id: Option<&str>) -> String {
    attempt_id
        .map(|attempt_id| format!("task:{task_id}:attempt:{attempt_id}"))
        .unwrap_or_else(|| format!("task:{task_id}"))
}

fn worker_conversation_id(
    workspace_id: &str,
    worker_agent_id: &str,
    task_id: &str,
    attempt_id: Option<&str>,
) -> String {
    let scope = worker_conversation_scope_for_task(task_id, attempt_id);
    let name = format!("workspace:{workspace_id}:agent:{worker_agent_id}:scope:{scope}");
    Uuid::new_v5(&Uuid::NAMESPACE_DNS, name.as_bytes()).to_string()
}

fn worker_stream_topic(conversation_id: &str) -> String {
    format!("agent:events:{conversation_id}")
}

fn worker_stream_event_time_us(event: &Value) -> Option<i64> {
    event
        .get("event_time_us")
        .and_then(Value::as_i64)
        .or_else(|| {
            event
                .get("event_time_us")
                .and_then(Value::as_u64)
                .and_then(|value| i64::try_from(value).ok())
        })
}

fn worker_conversation_title(task: &WorkspaceTaskRecord) -> String {
    let title_prefix = task.title.chars().take(80).collect::<String>();
    format!("Workspace Worker - {title_prefix}")
}

fn worker_conversation_metadata(
    workspace_id: &str,
    task: &WorkspaceTaskRecord,
    task_metadata: &Map<String, Value>,
    worker_agent_id: &str,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    now: DateTime<Utc>,
) -> Value {
    let mut metadata = json!({
        "workspace_id": workspace_id,
        "agent_id": worker_agent_id,
        "workspace_agent_binding_id": Value::Null,
        "workspace_task_id": task.id,
        "linked_workspace_task_id": task.id,
        ROOT_GOAL_TASK_ID: attempt.root_goal_task_id,
        "attempt_id": attempt.id,
        "conversation_scope": worker_conversation_scope_for_task(&task.id, Some(&attempt.id)),
        "source": WORKER_LAUNCH_CONVERSATION_SOURCE,
        "workspace_llm_stage": WORKER_LAUNCH_CONVERSATION_STAGE,
        "created_at": now.to_rfc3339(),
    });
    if let Some(preferred_language) = string_from_map(task_metadata, "preferred_language") {
        if let Some(map) = metadata.as_object_mut() {
            map.insert("preferred_language".to_string(), json!(preferred_language));
        }
    }
    if let Some(map) = metadata.as_object_mut() {
        for key in [
            "last_retry_reason",
            "last_retry_previous_attempt_id",
            "retry_origin",
            "worker_stream_orphan_retry_reason",
            "worker_stream_orphan_summary",
        ] {
            copy_metadata_string_field(task_metadata, map, key);
        }
    }
    metadata
}

pub(crate) struct WorkerLaunchAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
    runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
    stream_events: Arc<dyn WorkerLaunchEventStream>,
    config: WorkerLaunchAdmissionConfig,
}

impl WorkerLaunchAdmissionHandler {
    #[allow(dead_code)]
    pub(crate) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self::with_runtime_state_and_event_stream(
            store,
            Arc::new(NoopWorkerLaunchRuntimeStateStore),
            Arc::new(NoopWorkerLaunchEventStream),
        )
    }

    #[allow(dead_code)]
    pub(crate) fn with_runtime_state(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
    ) -> Self {
        Self::with_runtime_state_and_event_stream(
            store,
            runtime_state,
            Arc::new(NoopWorkerLaunchEventStream),
        )
    }

    pub(crate) fn with_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
    ) -> Self {
        Self::with_runtime_state_and_event_stream(
            store,
            Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events,
        )
    }

    pub(crate) fn with_runtime_state_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events,
            config: WorkerLaunchAdmissionConfig::from_env(),
        }
    }

    #[cfg(test)]
    fn with_config(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state: Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events: Arc::new(NoopWorkerLaunchEventStream),
            config,
        }
    }

    #[cfg(test)]
    fn with_config_and_runtime_state(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events: Arc::new(NoopWorkerLaunchEventStream),
            config,
        }
    }

    #[cfg(test)]
    fn with_config_and_runtime_state_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events,
            config,
        }
    }

    #[cfg(test)]
    fn with_config_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state: Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events,
            config,
        }
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for WorkerLaunchAdmissionHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_or_empty(item.payload_json.clone());
        let workspace_id =
            string_from_map(&payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let task_id = required_string(&payload, "task_id")?;
        let actor_user_id = required_string(&payload, "actor_user_id")?;
        let leader_agent_id = string_from_map(&payload, "leader_agent_id")
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let mut task = self
            .store
            .get_task(&workspace_id, &task_id)
            .await?
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "workspace task {task_id} not found for workspace {workspace_id}"
                ))
            })?;
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        let worker_agent_id = string_from_map(&payload, "worker_agent_id")
            .or_else(|| task.assignee_agent_id.clone())
            .ok_or_else(|| {
                CoreError::Storage(format!("workspace task {task_id} has no worker agent"))
            })?;
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(&payload, "plan_id"))
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_ID));
        let node_id = string_from_map(&payload, "node_id")
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_NODE_ID));
        let attempt_id = string_from_map(&payload, "attempt_id");
        let is_stream_poll = bool_from_map(&payload, "worker_stream_poll");

        if self
            .stale_worker_launch_reason(
                &task,
                plan_id.as_deref(),
                node_id.as_deref(),
                attempt_id.as_deref(),
            )
            .await?
            .is_some()
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        if !is_stream_poll {
            if let Some(active_count) = self
                .defer_active_capacity_count(&workspace_id, attempt_id.as_deref())
                .await?
            {
                self.store
                    .enqueue_plan_outbox(deferred_worker_launch_outbox(
                        &item,
                        &payload,
                        active_count,
                        self.config.max_active_worker_conversations,
                        self.config.defer_seconds,
                        Utc::now(),
                    ))
                    .await?;
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
        }

        let workspace = self
            .store
            .get_workspace(&workspace_id)
            .await?
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "workspace {workspace_id} not found for worker launch"
                ))
            })?;
        let launch_node = self
            .load_launch_node(plan_id.as_deref(), node_id.as_deref())
            .await?;
        let worktree_context = if is_stream_poll {
            None
        } else {
            worker_launch_worktree_context(
                Some(&workspace),
                &task,
                launch_node.as_ref(),
                attempt_id.as_deref(),
            )
            .await?
        };
        let now = Utc::now();
        if let Some(context) = worktree_context.as_ref() {
            merge_metadata_patch(&mut task_metadata, &context.metadata_patch);
            if context.setup_failed {
                self.block_task_for_worktree_setup_failure(
                    task,
                    task_metadata,
                    launch_node,
                    attempt_id.as_deref(),
                    context,
                    now,
                )
                .await?;
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
        }

        let mut bound_attempt = None;
        let mut current_attempt_conversation_id = None;
        if let Some(attempt_id) = attempt_id.as_deref() {
            let attempt = self
                .store
                .get_task_session_attempt(attempt_id)
                .await?
                .ok_or_else(|| {
                    CoreError::Storage(format!(
                        "workspace task session attempt {attempt_id} not found"
                    ))
                })?;
            let reuse_conversation_id = string_from_map(&payload, "reuse_conversation_id");
            let conversation_id = reuse_conversation_id
                .clone()
                .or_else(|| attempt.conversation_id.clone())
                .unwrap_or_else(|| {
                    worker_conversation_id(
                        &workspace_id,
                        &worker_agent_id,
                        &task.id,
                        Some(attempt_id),
                    )
                });
            if reuse_conversation_id.is_some()
                && self.runtime_agent_running_exists(&conversation_id).await
            {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
            if reuse_conversation_id.is_some() {
                self.runtime_clear_reused_session_markers(&conversation_id)
                    .await;
            }
            if !is_stream_poll && !self.runtime_claim_launch_cooldown(&conversation_id).await {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
            apply_attempt_retry_context(&mut task_metadata, &payload, now);
            let agent_config = json!({
                "selected_agent_id": worker_agent_id,
                "agent_definition_id": worker_agent_id,
            });
            let conversation_metadata = worker_conversation_metadata(
                &workspace_id,
                &task,
                &task_metadata,
                &worker_agent_id,
                &attempt,
                now,
            );
            let participant_agents = vec![worker_agent_id.clone()];
            self.store
                .ensure_worker_launch_conversation(
                    &conversation_id,
                    &workspace.project_id,
                    &workspace.tenant_id,
                    &actor_user_id,
                    &worker_conversation_title(&task),
                    &agent_config,
                    &conversation_metadata,
                    &participant_agents,
                    &worker_agent_id,
                    &workspace_id,
                    &task.id,
                    now,
                )
                .await?;
            let attempt = self
                .store
                .bind_task_session_attempt_conversation(attempt_id, &conversation_id, now)
                .await?
                .ok_or_else(|| {
                    CoreError::Storage(format!(
                        "workspace task session attempt {attempt_id} not found"
                    ))
                })?;
            self.runtime_refresh_bound_session_markers(&conversation_id)
                .await;
            current_attempt_conversation_id = Some(conversation_id);
            bound_attempt = Some(attempt);
        }

        let launch_state = if is_stream_poll && current_attempt_conversation_id.is_some() {
            "stream_polling"
        } else if current_attempt_conversation_id.is_some() {
            "bound"
        } else {
            "runtime_admitted"
        };
        task_metadata.insert("launch_state".to_string(), json!(launch_state));
        task_metadata.insert(
            "worker_launch_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        if current_attempt_conversation_id.is_some() {
            task_metadata.insert(
                "worker_launch_bound_at".to_string(),
                json!(now.to_rfc3339()),
            );
        }
        task_metadata.insert(
            "worker_launch_admitted_by".to_string(),
            json!(leader_agent_id.clone()),
        );
        task_metadata.insert(
            "current_attempt_worker_agent_id".to_string(),
            json!(worker_agent_id),
        );
        task_metadata.insert(CURRENT_ATTEMPT_WORKER_BINDING_ID.to_string(), Value::Null);
        if let Some(attempt) = bound_attempt.as_ref() {
            task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
            task_metadata.insert(
                "current_attempt_number".to_string(),
                json!(attempt.attempt_number),
            );
            if let Some(conversation_id) = current_attempt_conversation_id.as_deref() {
                task_metadata.insert(
                    CURRENT_ATTEMPT_CONVERSATION_ID.to_string(),
                    json!(conversation_id),
                );
            }
        } else if let Some(attempt_id) = attempt_id.as_deref() {
            task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        task_metadata.insert(
            "execution_state".to_string(),
            json!({
                "phase": "in_progress",
                "last_agent_reason": if current_attempt_conversation_id.is_some() {
                    "workspace_worker_launch.bind_conversation"
                } else {
                    "workspace_plan.worker_launch.admitted"
                },
                "last_agent_action": "schedule",
                "updated_by_actor_type": "agent",
                "updated_by_actor_id": task_metadata
                    .get("worker_launch_admitted_by")
                    .and_then(Value::as_str)
                    .unwrap_or(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
                "actor_user_id": actor_user_id,
                "updated_at": now.to_rfc3339()
            }),
        );
        task.metadata_json = Value::Object(task_metadata);
        if task.status != "done" {
            task.status = "in_progress".to_string();
            task.completed_at = None;
        }
        task.updated_at = Some(now);
        self.store.save_task(task).await?;

        self.mark_plan_node_running_after_launch_schedule(
            plan_id.as_deref(),
            node_id.as_deref(),
            attempt_id.as_deref(),
            current_attempt_conversation_id.as_deref(),
            launch_state,
            now,
        )
        .await?;

        if let (Some(conversation_id), Some(attempt_id)) = (
            current_attempt_conversation_id.as_deref(),
            attempt_id.as_deref(),
        ) {
            let stream_after_id = string_from_map(&payload, "stream_after_id")
                .or_else(|| string_from_map(&payload, "worker_stream_after_id"));
            let root_goal_task_id = string_from_map(&payload, ROOT_GOAL_TASK_ID);
            let replay = self
                .replay_bound_worker_stream_once(WorkerStreamReplayInput {
                    workspace_id: &workspace_id,
                    task_id: &task_id,
                    root_goal_task_id: root_goal_task_id.as_deref(),
                    attempt_id,
                    conversation_id,
                    actor_user_id: &actor_user_id,
                    worker_agent_id: &worker_agent_id,
                    leader_agent_id: Some(&leader_agent_id),
                    plan_id: plan_id.as_deref(),
                    node_id: node_id.as_deref(),
                    stream_after_id: stream_after_id.as_deref(),
                    now,
                })
                .await?;
            self.enqueue_worker_stream_poll_if_needed(
                &item,
                &payload,
                &replay,
                conversation_id,
                now,
            )
            .await?;
        }

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

#[allow(dead_code)]
struct WorkerStreamTerminalPersistence<'a> {
    workspace_id: &'a str,
    task_id: &'a str,
    root_goal_task_id: Option<&'a str>,
    attempt_id: Option<&'a str>,
    conversation_id: Option<&'a str>,
    actor_user_id: &'a str,
    worker_agent_id: &'a str,
    leader_agent_id: Option<&'a str>,
    plan_id: Option<&'a str>,
    node_id: Option<&'a str>,
    outcome: &'a worker_stream_watchdog::TerminalOutcome,
    now: DateTime<Utc>,
}

struct WorkerStreamReplayInput<'a> {
    workspace_id: &'a str,
    task_id: &'a str,
    root_goal_task_id: Option<&'a str>,
    attempt_id: &'a str,
    conversation_id: &'a str,
    actor_user_id: &'a str,
    worker_agent_id: &'a str,
    leader_agent_id: Option<&'a str>,
    plan_id: Option<&'a str>,
    node_id: Option<&'a str>,
    stream_after_id: Option<&'a str>,
    now: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct WorkerStreamReplayResult {
    replay_after_id: String,
    last_entry_id: Option<String>,
    entries_read: usize,
    terminal_seen: bool,
}

impl WorkerStreamReplayResult {
    fn empty(replay_after_id: String) -> Self {
        Self {
            replay_after_id,
            last_entry_id: None,
            entries_read: 0,
            terminal_seen: false,
        }
    }

    fn next_after_id(&self) -> &str {
        self.last_entry_id
            .as_deref()
            .unwrap_or(&self.replay_after_id)
    }

    fn is_nonterminal(&self) -> bool {
        !self.terminal_seen
    }
}

struct WorkerStreamIdleProgress {
    summary: String,
    idle_seconds: i64,
    running_exists: bool,
    finished_message_id: Option<String>,
}

#[allow(dead_code)]
#[derive(Debug, Clone)]
struct WorkerReportPayload {
    normalized_summary: String,
    report_artifacts: Vec<String>,
    merged_artifacts: Vec<String>,
    report_verifications: Vec<String>,
    merged_verifications: Vec<String>,
    fingerprint: String,
}

impl WorkerLaunchAdmissionHandler {
    async fn replay_bound_worker_stream_once(
        &self,
        input: WorkerStreamReplayInput<'_>,
    ) -> CoreResult<WorkerStreamReplayResult> {
        let stream_after_id = self.worker_stream_replay_after_id(&input).await?;
        let (mut state, mut last_event_time_us) = self
            .worker_stream_state_from_replay_metadata(&input)
            .await?;
        let entries = self
            .stream_events
            .read_after(
                input.conversation_id,
                &stream_after_id,
                DEFAULT_WORKER_STREAM_REPLAY_BATCH_LIMIT,
            )
            .await?;
        if entries.is_empty() {
            if self
                .stop_orphaned_worker_stream_if_needed(&input, &mut state, None, last_event_time_us)
                .await?
            {
                return Ok(WorkerStreamReplayResult {
                    replay_after_id: stream_after_id,
                    last_entry_id: None,
                    entries_read: 0,
                    terminal_seen: true,
                });
            }
            return Ok(WorkerStreamReplayResult::empty(stream_after_id));
        }

        let mut last_entry_id = None;
        let mut terminal_seen = false;
        let mut entries_read = 0;
        for entry in entries {
            entries_read += 1;
            last_entry_id = Some(entry.id.clone());
            let event = match serde_json::from_str::<Value>(&entry.payload) {
                Ok(event) => event,
                Err(err) => json!({
                    "type": "error",
                    "data": {
                        "message": format!(
                            "Malformed worker stream payload at {}: {err}",
                            entry.id
                        )
                    }
                }),
            };
            if let Some(event_time_us) = worker_stream_event_time_us(&event) {
                last_event_time_us = Some(event_time_us);
            }
            if state.observe_event(&event).is_some() {
                terminal_seen = true;
                break;
            }
        }

        let last_entry_id = last_entry_id.as_deref();
        if !terminal_seen {
            if self
                .stop_orphaned_worker_stream_if_needed(
                    &input,
                    &mut state,
                    last_entry_id,
                    last_event_time_us,
                )
                .await?
            {
                return Ok(WorkerStreamReplayResult {
                    replay_after_id: stream_after_id,
                    last_entry_id: last_entry_id.map(ToOwned::to_owned),
                    entries_read,
                    terminal_seen: true,
                });
            }
            self.patch_worker_stream_replay_metadata(
                &input,
                last_entry_id,
                last_event_time_us,
                &state,
                None,
            )
            .await?;
            return Ok(WorkerStreamReplayResult {
                replay_after_id: stream_after_id,
                last_entry_id: last_entry_id.map(ToOwned::to_owned),
                entries_read,
                terminal_seen: false,
            });
        }

        self.persist_worker_stream_replay_terminal_outcome(
            &input,
            &state,
            last_entry_id,
            last_event_time_us,
        )
        .await?;
        Ok(WorkerStreamReplayResult {
            replay_after_id: stream_after_id,
            last_entry_id: last_entry_id.map(ToOwned::to_owned),
            entries_read,
            terminal_seen: true,
        })
    }

    async fn worker_stream_state_from_replay_metadata(
        &self,
        input: &WorkerStreamReplayInput<'_>,
    ) -> CoreResult<(worker_stream_watchdog::StreamState, Option<i64>)> {
        let Some(task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok((worker_stream_watchdog::StreamState::default(), None));
        };
        let metadata = object_or_empty(task.metadata_json);
        if !worker_stream_replay_metadata_matches_attempt(&metadata, input.attempt_id) {
            return Ok((worker_stream_watchdog::StreamState::default(), None));
        }
        let mut state = worker_stream_watchdog::StreamState::default();
        state.stream_message_id = string_from_map(&metadata, "worker_stream_message_id");
        state.last_stream_event_type = string_from_map(&metadata, "worker_stream_last_event_type");
        let last_event_time_us = metadata
            .get("worker_stream_last_event_time_us")
            .and_then(Value::as_i64);
        Ok((state, last_event_time_us))
    }

    async fn stop_orphaned_worker_stream_if_needed(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &mut worker_stream_watchdog::StreamState,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
    ) -> CoreResult<bool> {
        let finished_message_id = self
            .runtime_agent_finished_message_id(input.conversation_id)
            .await;
        let running_exists = self
            .runtime_agent_running_exists(input.conversation_id)
            .await;
        let idle_seconds = last_event_time_us
            .filter(|event_time_us| input.now.timestamp_micros() > *event_time_us)
            .map(|event_time_us| {
                (input.now.timestamp_micros() - event_time_us) as f64 / 1_000_000.0
            })
            .unwrap_or_default();
        let decision = worker_stream_watchdog::should_stop(
            finished_message_id.as_deref(),
            state.stream_message_id.as_deref(),
            running_exists,
            idle_seconds,
            None,
        );
        if !decision.should_stop {
            return Ok(false);
        }
        state.mark_orphaned_stream_stop(
            decision
                .reason
                .map(worker_stream_watchdog::StopReason::as_str),
        );
        self.persist_worker_stream_replay_terminal_outcome(
            input,
            state,
            last_entry_id,
            last_event_time_us,
        )
        .await?;
        Ok(true)
    }

    async fn persist_worker_stream_replay_terminal_outcome(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &worker_stream_watchdog::StreamState,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
    ) -> CoreResult<()> {
        let report_recorded_for_attempt = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
            .map(|task| {
                worker_stream_watchdog::terminal_report_metadata_matches_attempt(
                    Some(&task.metadata_json),
                    Some(input.attempt_id),
                    None,
                )
            })
            .unwrap_or(false);
        let outcome = state.terminal_outcome(report_recorded_for_attempt);
        self.persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: input.workspace_id,
            task_id: input.task_id,
            root_goal_task_id: input.root_goal_task_id,
            attempt_id: Some(input.attempt_id),
            conversation_id: Some(input.conversation_id),
            actor_user_id: input.actor_user_id,
            worker_agent_id: input.worker_agent_id,
            leader_agent_id: input.leader_agent_id,
            plan_id: input.plan_id,
            node_id: input.node_id,
            outcome: &outcome,
            now: input.now,
        })
        .await?;
        self.patch_worker_stream_replay_metadata(
            &input,
            last_entry_id,
            last_event_time_us,
            &state,
            Some(&outcome),
        )
        .await?;
        Ok(())
    }

    async fn enqueue_worker_stream_poll_if_needed(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        replay: &WorkerStreamReplayResult,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        if !replay.is_nonterminal() {
            return Ok(());
        }
        if self
            .runtime_agent_finished_message_id(conversation_id)
            .await
            .is_some()
        {
            return Ok(());
        }
        let running_exists = self.runtime_agent_running_exists(conversation_id).await;
        if !running_exists && replay.entries_read == 0 {
            return Ok(());
        }
        self.store
            .enqueue_plan_outbox(worker_stream_poll_outbox(
                item,
                payload,
                conversation_id,
                replay,
                self.config.stream_poll_interval_seconds,
                now,
            ))
            .await?;
        Ok(())
    }

    async fn worker_stream_replay_after_id(
        &self,
        input: &WorkerStreamReplayInput<'_>,
    ) -> CoreResult<String> {
        if let Some(after_id) = input
            .stream_after_id
            .filter(|value| !value.trim().is_empty())
        {
            return Ok(after_id.to_string());
        }
        let after_id = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
            .and_then(|task| {
                let metadata = object_or_empty(task.metadata_json);
                if !worker_stream_replay_metadata_matches_attempt(&metadata, input.attempt_id) {
                    return None;
                }
                metadata
                    .get("worker_stream_last_entry_id")
                    .and_then(Value::as_str)
                    .filter(|value| !value.trim().is_empty())
                    .map(ToOwned::to_owned)
            })
            .unwrap_or_default();
        Ok(after_id)
    }

    async fn patch_worker_stream_replay_metadata(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
        state: &worker_stream_watchdog::StreamState,
        outcome: Option<&worker_stream_watchdog::TerminalOutcome>,
    ) -> CoreResult<()> {
        let Some(mut task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok(());
        };
        let mut metadata = object_or_empty(task.metadata_json.clone());
        let idle_progress = if outcome.is_none() {
            self.worker_stream_idle_progress(input, state, last_event_time_us, &metadata)
                .await
        } else {
            None
        };
        if let Some(last_entry_id) = last_entry_id {
            metadata.insert(
                "worker_stream_last_entry_id".to_string(),
                json!(last_entry_id),
            );
        }
        if let Some(last_event_time_us) = last_event_time_us {
            metadata.insert(
                "worker_stream_last_event_time_us".to_string(),
                json!(last_event_time_us),
            );
        }
        metadata.insert(
            "worker_stream_last_replayed_at".to_string(),
            json!(input.now.to_rfc3339()),
        );
        metadata.insert(
            "worker_stream_replay_status".to_string(),
            json!(if outcome.is_some() {
                "terminal"
            } else if idle_progress.is_some() {
                "stream_idle"
            } else {
                "observed"
            }),
        );
        metadata.insert(
            "worker_stream_replay_attempt_id".to_string(),
            json!(input.attempt_id),
        );
        if let Some(last_event_type) = state
            .last_stream_event_type
            .as_deref()
            .filter(|value| !value.trim().is_empty())
        {
            metadata.insert(
                "worker_stream_last_event_type".to_string(),
                json!(last_event_type),
            );
        }
        if let Some(message_id) = state
            .stream_message_id
            .as_deref()
            .filter(|value| !value.trim().is_empty())
        {
            metadata.insert("worker_stream_message_id".to_string(), json!(message_id));
        }
        if let Some(outcome) = outcome {
            metadata.insert(
                "worker_stream_terminal_outcome".to_string(),
                json!(outcome.outcome_reason),
            );
            metadata.insert(
                "worker_stream_terminal_launch_state".to_string(),
                json!(outcome.launch_state),
            );
            metadata.insert(
                "worker_stream_terminal_should_report".to_string(),
                json!(outcome.should_report),
            );
            metadata.insert(
                "worker_stream_terminal_replayed_at".to_string(),
                json!(input.now.to_rfc3339()),
            );
        }
        if let Some(progress) = idle_progress.as_ref() {
            metadata.insert(
                "worker_stream_idle_progress_summary".to_string(),
                json!(progress.summary.clone()),
            );
            metadata.insert(
                "worker_stream_idle_seconds".to_string(),
                json!(progress.idle_seconds),
            );
            metadata.insert(
                "worker_stream_idle_progress_published_at".to_string(),
                json!(input.now.to_rfc3339()),
            );
            metadata.insert(
                "worker_stream_idle_progress_published_at_us".to_string(),
                json!(input.now.timestamp_micros()),
            );
            metadata.insert(
                "worker_stream_idle_running_exists".to_string(),
                json!(progress.running_exists),
            );
            if let Some(finished_message_id) = progress.finished_message_id.as_deref() {
                metadata.insert(
                    "worker_stream_idle_finished_message_id".to_string(),
                    json!(finished_message_id),
                );
            }
            metadata.insert(
                "execution_state".to_string(),
                worker_execution_state(
                    "in_progress",
                    &progress.summary,
                    "observe_stream_idle",
                    input.leader_agent_id.unwrap_or(input.actor_user_id),
                    input.now,
                ),
            );
        }
        task.metadata_json = Value::Object(metadata);
        task.updated_at = Some(input.now);
        self.store.save_task(task).await?;
        if let Some(progress) = idle_progress.as_ref() {
            self.mark_workspace_plan_node_stream_idle(input, progress)
                .await?;
        }
        Ok(())
    }

    async fn worker_stream_idle_progress(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &worker_stream_watchdog::StreamState,
        last_event_time_us: Option<i64>,
        metadata: &Map<String, Value>,
    ) -> Option<WorkerStreamIdleProgress> {
        let last_event_time_us = last_event_time_us?;
        let now_us = input.now.timestamp_micros();
        if now_us <= last_event_time_us {
            return None;
        }
        let idle_seconds = (now_us - last_event_time_us) as f64 / 1_000_000.0;
        let last_published_at = metadata
            .get("worker_stream_idle_progress_published_at_us")
            .and_then(Value::as_i64)
            .map(|value| value as f64 / 1_000_000.0)
            .unwrap_or_default();
        let now_seconds = now_us as f64 / 1_000_000.0;
        if !worker_stream_watchdog::should_publish_idle_progress(
            idle_seconds,
            last_published_at,
            now_seconds,
            None,
        ) {
            return None;
        }
        let finished_message_id = self
            .runtime_agent_finished_message_id(input.conversation_id)
            .await;
        let running_exists = self
            .runtime_agent_running_exists(input.conversation_id)
            .await;
        let summary = worker_stream_watchdog::idle_progress_summary(
            idle_seconds,
            state.last_stream_event_type.as_deref(),
            running_exists,
            finished_message_id.as_deref(),
        );
        Some(WorkerStreamIdleProgress {
            summary,
            idle_seconds: idle_seconds as i64,
            running_exists,
            finished_message_id,
        })
    }

    async fn mark_workspace_plan_node_stream_idle(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        progress: &WorkerStreamIdleProgress,
    ) -> CoreResult<()> {
        let (Some(plan_id), Some(node_id)) = (input.plan_id, input.node_id) else {
            return Ok(());
        };
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if node.current_attempt_id.as_deref() != Some(input.attempt_id) {
            return Ok(());
        }
        if node.execution != "running" {
            return Ok(());
        }

        let mut progress_json = object_or_empty(node.progress_json.clone());
        progress_json
            .entry("percent".to_string())
            .or_insert_with(|| json!(0.0));
        progress_json
            .entry("confidence".to_string())
            .or_insert_with(|| json!(1.0));
        progress_json.insert("note".to_string(), json!(progress.summary.clone()));

        let mut metadata = object_or_empty(node.metadata_json.clone());
        let reported_at = input.now.to_rfc3339();
        let progress_event = json!({
            "event_type": "worker_stream_idle",
            "source_event_type": "worker_stream_idle",
            "summary": progress.summary.clone(),
            "attempt_id": input.attempt_id,
            "worker_agent_id": input.worker_agent_id,
            "idle_seconds": progress.idle_seconds,
            "running_exists": progress.running_exists,
            "reported_at": reported_at.clone()
        });
        let mut progress_events = metadata
            .get("progress_events")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        progress_events.push(progress_event.clone());
        if progress_events.len() > 25 {
            progress_events = progress_events.split_off(progress_events.len() - 25);
        }
        metadata.insert("progress_events".to_string(), Value::Array(progress_events));
        metadata.insert("latest_worker_progress".to_string(), progress_event);
        metadata.insert("launch_state".to_string(), json!("stream_idle"));
        metadata.insert(
            "worker_stream_idle_progress_summary".to_string(),
            json!(progress.summary.clone()),
        );
        metadata.insert(
            "worker_stream_idle_progress_published_at".to_string(),
            json!(reported_at),
        );

        node.intent = "in_progress".to_string();
        node.progress_json = Value::Object(progress_json);
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(input.now);
        self.store.save_plan_node(node).await?;
        Ok(())
    }

    #[allow(dead_code)]
    async fn persist_worker_stream_terminal_outcome(
        &self,
        input: WorkerStreamTerminalPersistence<'_>,
    ) -> CoreResult<bool> {
        let Some(mut task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok(false);
        };
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        let root_goal_task_id = input
            .root_goal_task_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID));
        if let (Some(expected), Some(actual)) = (
            input.root_goal_task_id,
            string_from_map(&task_metadata, ROOT_GOAL_TASK_ID),
        ) {
            if actual != expected {
                return Err(CoreError::Storage(
                    "worker stream terminal report task does not belong to root goal".into(),
                ));
            }
        }
        let plan_id = input
            .plan_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_ID));
        let node_id = input
            .node_id
            .map(ToOwned::to_owned)
            .or_else(|| string_from_map(&task_metadata, WORKSPACE_PLAN_NODE_ID));
        let v2_plan_linked = plan_id
            .as_deref()
            .is_some_and(|value| !value.trim().is_empty())
            && node_id
                .as_deref()
                .is_some_and(|value| !value.trim().is_empty());

        task_metadata.insert(
            "launch_state".to_string(),
            json!(input.outcome.launch_state),
        );

        let mut reported = false;
        if input.outcome.should_report {
            if let (Some(attempt_id), Some(report_type)) =
                (input.attempt_id, input.outcome.report_type.as_ref())
            {
                if !is_stale_terminal_worker_report(&task_metadata, attempt_id) {
                    let report_type = report_type.as_str();
                    let report = build_worker_report_payload(
                        &task_metadata,
                        report_type,
                        &input.outcome.summary,
                        &[],
                        None,
                    );
                    let pending_leader = !v2_plan_linked;
                    let last_attempt_status = if v2_plan_linked {
                        "awaiting_plan_verification"
                    } else {
                        AWAITING_LEADER_ADJUDICATION_STATUS
                    };
                    task_metadata
                        .insert("evidence_refs".to_string(), json!(report.merged_artifacts));
                    task_metadata.insert(
                        "execution_verifications".to_string(),
                        json!(report.merged_verifications),
                    );
                    task_metadata.insert("last_worker_report_type".to_string(), json!(report_type));
                    task_metadata.insert(
                        LAST_WORKER_REPORT_SUMMARY.to_string(),
                        json!(report.normalized_summary.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_report_artifacts".to_string(),
                        json!(report.merged_artifacts.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_report_verifications".to_string(),
                        json!(report.report_verifications.clone()),
                    );
                    task_metadata.insert(
                        "last_worker_reported_at".to_string(),
                        json!(input.now.to_rfc3339()),
                    );
                    task_metadata.insert(
                        "last_worker_report_fingerprint".to_string(),
                        json!(report.fingerprint.clone()),
                    );
                    task_metadata
                        .insert(LAST_WORKER_REPORT_ATTEMPT_ID.to_string(), json!(attempt_id));
                    task_metadata.insert(
                        PENDING_LEADER_ADJUDICATION.to_string(),
                        json!(pending_leader),
                    );
                    task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
                    task_metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
                    if let Some(conversation_id) = input.conversation_id {
                        task_metadata.insert(
                            CURRENT_ATTEMPT_CONVERSATION_ID.to_string(),
                            json!(conversation_id),
                        );
                    }
                    task_metadata.insert(
                        "current_attempt_worker_agent_id".to_string(),
                        json!(input.worker_agent_id),
                    );
                    if let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? {
                        task_metadata.insert(
                            "current_attempt_number".to_string(),
                            json!(attempt.attempt_number),
                        );
                    }
                    task_metadata.insert(
                        "last_attempt_status".to_string(),
                        json!(last_attempt_status),
                    );
                    task_metadata.insert(
                        "execution_state".to_string(),
                        worker_execution_state(
                            "in_progress",
                            &format!(
                                "workspace_goal_runtime.worker_report.{report_type}:{}",
                                report.normalized_summary
                            ),
                            if v2_plan_linked {
                                "await_plan_verification"
                            } else {
                                "await_leader_adjudication"
                            },
                            input.worker_agent_id,
                            input.now,
                        ),
                    );

                    let recorded = self
                        .store
                        .record_task_session_attempt_candidate_output(
                            attempt_id,
                            Some(&report.normalized_summary),
                            &report.report_artifacts,
                            &report.report_verifications,
                            input.conversation_id,
                            input.now,
                        )
                        .await?
                        .is_some();
                    if recorded {
                        reported = true;
                        if let (Some(plan_id), Some(node_id), Some(root_goal_task_id)) = (
                            plan_id.as_deref(),
                            node_id.as_deref(),
                            root_goal_task_id.as_deref(),
                        ) {
                            self.mark_workspace_plan_node_reported(
                                &input,
                                plan_id,
                                node_id,
                                root_goal_task_id,
                                report_type,
                                &report,
                            )
                            .await?;
                        }
                    }
                }
            }
        } else {
            task_metadata.insert(
                "execution_state".to_string(),
                worker_execution_state(
                    "in_progress",
                    &format!("workspace_worker_launch.{}", input.outcome.launch_state),
                    "observe",
                    input.leader_agent_id.unwrap_or(input.actor_user_id),
                    input.now,
                ),
            );
        }

        task.metadata_json = Value::Object(task_metadata);
        if task.status == "todo" {
            task.status = "in_progress".to_string();
            task.completed_at = None;
        }
        if input
            .outcome
            .report_type
            .as_ref()
            .is_some_and(|report_type| {
                report_type.as_str() == "blocked" && input.outcome.should_report
            })
        {
            task.blocker_reason = Some(input.outcome.summary.clone());
        }
        task.updated_at = Some(input.now);
        self.store.save_task(task).await?;
        Ok(reported)
    }

    async fn mark_workspace_plan_node_reported(
        &self,
        input: &WorkerStreamTerminalPersistence<'_>,
        plan_id: &str,
        node_id: &str,
        root_goal_task_id: &str,
        report_type: &str,
        report: &WorkerReportPayload,
    ) -> CoreResult<()> {
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if input
            .attempt_id
            .is_some_and(|attempt_id| node.current_attempt_id.as_deref() != Some(attempt_id))
        {
            return Ok(());
        }
        let Some(attempt_id) = input.attempt_id else {
            return Ok(());
        };
        let mut progress = object_or_empty(node.progress_json.clone());
        progress
            .entry("percent".to_string())
            .or_insert_with(|| json!(0.0));
        progress
            .entry("confidence".to_string())
            .or_insert_with(|| json!(1.0));
        progress.insert("note".to_string(), json!(report.normalized_summary.clone()));

        let mut metadata = object_or_empty(node.metadata_json.clone());
        let reported_at = input.now.to_rfc3339();
        let report_event = json!({
            "event_type": "worker_report_terminal",
            "source_event_type": "worker_report_terminal",
            "summary": report.normalized_summary,
            "attempt_id": attempt_id,
            "worker_agent_id": input.worker_agent_id,
            "reported_at": reported_at
        });
        let mut progress_events = metadata
            .get("progress_events")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        progress_events.push(report_event.clone());
        if progress_events.len() > 25 {
            progress_events = progress_events.split_off(progress_events.len() - 25);
        }
        metadata.insert("progress_events".to_string(), Value::Array(progress_events));
        metadata.insert("latest_worker_progress".to_string(), report_event);
        metadata.insert(
            "launch_state".to_string(),
            json!(input.outcome.launch_state),
        );
        metadata.insert("last_worker_report_type".to_string(), json!(report_type));
        metadata.insert(
            LAST_WORKER_REPORT_SUMMARY.to_string(),
            json!(report.normalized_summary.clone()),
        );
        metadata.insert(LAST_WORKER_REPORT_ATTEMPT_ID.to_string(), json!(attempt_id));
        metadata.insert("last_worker_reported_at".to_string(), json!(reported_at));

        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some(attempt_id.to_string());
        node.progress_json = Value::Object(progress);
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(input.now);
        self.store.save_plan_node(node).await?;
        self.store
            .create_plan_event(WorkspacePlanEventRecord {
                id: generate_uuid_v4(),
                plan_id: plan_id.to_string(),
                workspace_id: input.workspace_id.to_string(),
                node_id: Some(node_id.to_string()),
                attempt_id: Some(attempt_id.to_string()),
                event_type: "worker_report_terminal".to_string(),
                source: "worker_report".to_string(),
                actor_id: Some(input.worker_agent_id.to_string()),
                payload_json: json!({
                    "report_type": report_type,
                    "summary": report.normalized_summary,
                    "artifacts": report.report_artifacts,
                    "verifications": report.report_verifications,
                    "reported_at": input.now.to_rfc3339()
                }),
                created_at: input.now,
            })
            .await?;
        self.store
            .enqueue_plan_outbox(worker_report_supervisor_tick(
                input.workspace_id,
                plan_id,
                node_id,
                attempt_id,
                root_goal_task_id,
                input.actor_user_id,
                input.leader_agent_id,
                input.now,
            ))
            .await?;
        Ok(())
    }

    async fn runtime_agent_running_exists(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .agent_running_exists(conversation_id)
            .await
        {
            Ok(exists) => exists,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:running check failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    async fn runtime_clear_reused_session_markers(&self, conversation_id: &str) {
        if let Err(err) = self
            .runtime_state
            .clear_reused_session_markers(conversation_id)
            .await
        {
            eprintln!(
                "[agistack] worker launch state: clear reused markers failed for {conversation_id}: {err}"
            );
        }
    }

    async fn runtime_refresh_bound_session_markers(&self, conversation_id: &str) {
        self.runtime_refresh_launch_cooldown(conversation_id).await;
        if self
            .runtime_agent_finished_message_id(conversation_id)
            .await
            .is_some()
        {
            return;
        }
        self.runtime_refresh_agent_running_marker(conversation_id)
            .await;
    }

    async fn runtime_refresh_launch_cooldown(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .refresh_launch_cooldown(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(refreshed) => refreshed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: cooldown refresh failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    async fn runtime_agent_finished_message_id(&self, conversation_id: &str) -> Option<String> {
        match self
            .runtime_state
            .agent_finished_message_id(conversation_id)
            .await
        {
            Ok(message_id) => message_id,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:finished read failed for {conversation_id}: {err}"
                );
                None
            }
        }
    }

    async fn runtime_refresh_agent_running_marker(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .refresh_agent_running_marker(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(refreshed) => refreshed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: agent:running refresh failed for {conversation_id}: {err}"
                );
                false
            }
        }
    }

    async fn runtime_claim_launch_cooldown(&self, conversation_id: &str) -> bool {
        match self
            .runtime_state
            .claim_launch_cooldown(conversation_id, WORKER_LAUNCH_COOLDOWN_SECONDS)
            .await
        {
            Ok(claimed) => claimed,
            Err(err) => {
                eprintln!(
                    "[agistack] worker launch state: cooldown claim failed for {conversation_id}: {err}"
                );
                true
            }
        }
    }

    async fn stale_worker_launch_reason(
        &self,
        task: &WorkspaceTaskRecord,
        plan_id: Option<&str>,
        node_id: Option<&str>,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<String>> {
        let mut reason = None;
        if let Some(attempt_id) = attempt_id {
            match self.store.get_task_session_attempt(attempt_id).await? {
                None => reason = Some("attempt_missing".to_string()),
                Some(attempt) => {
                    if attempt.workspace_task_id != task.id
                        || attempt.workspace_id != task.workspace_id
                    {
                        reason = Some("attempt_task_mismatch".to_string());
                    } else if !WORKER_LAUNCHABLE_ATTEMPT_STATUSES.contains(&attempt.status.as_str())
                    {
                        reason = Some(format!("attempt_{}", attempt.status));
                    }
                }
            }
        }

        let task_metadata = object_or_empty(task.metadata_json.clone());
        let current_task_attempt_id = string_from_map(&task_metadata, CURRENT_ATTEMPT_ID);
        if reason.is_none()
            && current_task_attempt_id.is_some()
            && current_task_attempt_id.as_deref() != attempt_id
        {
            reason = Some("task_current_attempt_changed".to_string());
        }

        if reason.is_none() {
            if let (Some(plan_id), Some(node_id)) = (plan_id, node_id) {
                if self
                    .store
                    .has_supervisor_dispose_decision_for_node(&task.workspace_id, plan_id, node_id)
                    .await?
                {
                    return Ok(Some("supervisor_disposed_node".to_string()));
                }
                if let Some(plan) = self.store.get_plan(plan_id).await? {
                    if plan.workspace_id == task.workspace_id {
                        let nodes = self.store.list_plan_nodes(plan_id).await?;
                        if let Some(node) =
                            nodes.into_iter().find(|candidate| candidate.id == node_id)
                        {
                            if node.workspace_task_id.as_deref().is_some()
                                && node.workspace_task_id.as_deref() != Some(task.id.as_str())
                            {
                                reason = Some("node_task_mismatch".to_string());
                            } else if node.current_attempt_id.as_deref().is_some()
                                && node.current_attempt_id.as_deref() != attempt_id
                            {
                                reason = Some("node_current_attempt_changed".to_string());
                            } else if node.intent == "done" || node.execution == "idle" {
                                reason = Some("node_not_launchable".to_string());
                            }
                        }
                    }
                }
            }
        }
        Ok(reason)
    }

    async fn defer_active_capacity_count(
        &self,
        workspace_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<i64>> {
        let max_active = self.config.max_active_worker_conversations;
        if max_active <= 0 {
            return Ok(None);
        }
        if let Some(attempt_id) = attempt_id {
            if self
                .store
                .get_task_session_attempt(attempt_id)
                .await?
                .and_then(|attempt| attempt.conversation_id)
                .is_some()
            {
                return Ok(None);
            }
        }
        let active_after =
            Utc::now() - ChronoDuration::seconds(self.config.active_event_grace_seconds.max(1));
        let active_count = self
            .store
            .count_recent_running_task_session_attempts_with_conversation(
                workspace_id,
                active_after,
            )
            .await?;
        Ok((active_count >= max_active).then_some(active_count))
    }

    async fn mark_plan_node_running_after_launch_schedule(
        &self,
        plan_id: Option<&str>,
        node_id: Option<&str>,
        attempt_id: Option<&str>,
        conversation_id: Option<&str>,
        launch_state: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let (Some(plan_id), Some(node_id)) = (plan_id, node_id) else {
            return Ok(());
        };
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if attempt_id.is_some()
            && node.current_attempt_id.as_deref().is_some()
            && node.current_attempt_id.as_deref() != attempt_id
        {
            return Ok(());
        }
        if !matches!(node.execution.as_str(), "dispatched" | "running") {
            return Ok(());
        }
        node.execution = "running".to_string();
        if let Some(attempt_id) = attempt_id {
            node.current_attempt_id = Some(attempt_id.to_string());
        }
        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert("launch_state".to_string(), json!(launch_state));
        metadata.insert(
            "worker_launch_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        if let Some(conversation_id) = conversation_id {
            metadata.insert(
                CURRENT_ATTEMPT_CONVERSATION_ID.to_string(),
                json!(conversation_id),
            );
            metadata.insert(
                "worker_launch_bound_at".to_string(),
                json!(now.to_rfc3339()),
            );
        }
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;
        Ok(())
    }

    async fn load_launch_node(
        &self,
        plan_id: Option<&str>,
        node_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePlanNodeRecord>> {
        let (Some(plan_id), Some(node_id)) = (plan_id, node_id) else {
            return Ok(None);
        };
        Ok(self
            .store
            .list_plan_nodes(plan_id)
            .await?
            .into_iter()
            .find(|candidate| candidate.id == node_id))
    }

    async fn block_task_for_worktree_setup_failure(
        &self,
        mut task: WorkspaceTaskRecord,
        mut task_metadata: Map<String, Value>,
        launch_node: Option<WorkspacePlanNodeRecord>,
        attempt_id: Option<&str>,
        context: &WorkerLaunchWorktreeContext,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let reason = context
            .setup_reason
            .as_deref()
            .unwrap_or("attempt worktree setup failed");
        let summary = format!("worktree_setup_failed: {reason}");
        merge_metadata_patch(&mut task_metadata, &context.metadata_patch);
        task_metadata.insert("launch_state".to_string(), json!("worktree_setup_failed"));
        task_metadata.insert("last_attempt_status".to_string(), json!("blocked"));
        if let Some(attempt_id) = attempt_id {
            task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        task.metadata_json = Value::Object(task_metadata);
        task.status = "blocked".to_string();
        task.blocker_reason = Some(summary.clone());
        task.completed_at = None;
        task.updated_at = Some(now);
        self.store.save_task(task).await?;

        if let Some(attempt_id) = attempt_id {
            let _ = self
                .store
                .finish_task_session_attempt(
                    attempt_id,
                    "blocked",
                    Some(&summary),
                    Some("worktree_setup_failed"),
                    now,
                )
                .await?;
        }

        if let Some(mut node) = launch_node {
            let mut node_metadata = object_or_empty(node.metadata_json);
            merge_metadata_patch(&mut node_metadata, &context.metadata_patch);
            node_metadata.insert("worktree_setup_failure_summary".to_string(), json!(summary));
            node_metadata.insert("last_attempt_status".to_string(), json!("blocked"));
            if let Some(attempt_id) = attempt_id {
                node_metadata.insert("terminal_attempt_status".to_string(), json!("blocked"));
                node_metadata.insert(
                    "terminal_attempt_reconciled_at".to_string(),
                    json!(now.to_rfc3339()),
                );
                node_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
            }
            node.intent = "blocked".to_string();
            node.execution = "idle".to_string();
            node.current_attempt_id = None;
            node.metadata_json = Value::Object(node_metadata);
            node.completed_at = None;
            node.updated_at = Some(now);
            self.store.save_plan_node(node).await?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
struct WorkerLaunchWorktreeContext {
    metadata_patch: Map<String, Value>,
    setup_failed: bool,
    setup_reason: Option<String>,
}

async fn worker_launch_worktree_context(
    workspace: Option<&WorkspaceRecord>,
    task: &WorkspaceTaskRecord,
    node: Option<&WorkspacePlanNodeRecord>,
    attempt_id: Option<&str>,
) -> CoreResult<Option<WorkerLaunchWorktreeContext>> {
    let feature = node
        .and_then(|node| node.feature_checkpoint_json.as_ref())
        .filter(|value| value.is_object())
        .or_else(|| {
            task.metadata_json
                .get("feature_checkpoint")
                .filter(|value| value.is_object())
        });
    if feature.is_none() && attempt_id.is_none() {
        return Ok(None);
    }

    let task_metadata = task.metadata_json.clone();
    let workspace_metadata = workspace
        .map(|workspace| workspace.metadata_json.clone())
        .unwrap_or(Value::Null);
    let base_ref = feature
        .and_then(|value| metadata_string_from_path(value, &["base_ref"]))
        .or_else(|| feature.and_then(|value| metadata_string_from_path(value, &["commit_ref"])))
        .unwrap_or_else(|| "HEAD".to_string());
    let sandbox_code_root = sandbox_code_root_for_integration(&task_metadata, &workspace_metadata);
    let Some(sandbox_code_root) = sandbox_code_root else {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some("sandbox_code_root is not available for this workspace"),
                workspace_root: None,
                sandbox_code_root: None,
                active_root: None,
                worktree_path: None,
                branch_name: None,
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    };

    let worktree_path_template =
        feature.and_then(|value| metadata_string_from_path(value, &["worktree_path"]));
    let branch_name = feature
        .and_then(|value| metadata_string_from_path(value, &["branch_name"]))
        .or_else(|| {
            let attempt_id = attempt_id?;
            let node_id = node
                .map(|node| node.id.as_str())
                .unwrap_or(task.id.as_str());
            Some(worktree_branch_name(node_id, attempt_id))
        });

    if (worktree_path_template.is_none() || branch_name.is_none()) && attempt_id.is_none() {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some(
                    "feature checkpoint does not include worktree_path and branch_name",
                ),
                workspace_root: None,
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: None,
                branch_name: branch_name.as_deref(),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let worktree_path = match (worktree_path_template, attempt_id) {
        (Some(template), _) => template.replace("${sandbox_code_root}", &sandbox_code_root),
        (None, Some(attempt_id)) => default_attempt_worktree_path(&sandbox_code_root, attempt_id),
        (None, None) => String::new(),
    };
    let branch_name = branch_name.unwrap_or_else(|| {
        worktree_branch_name(
            node.map(|node| node.id.as_str())
                .unwrap_or(task.id.as_str()),
            attempt_id.unwrap_or("attempt"),
        )
    });

    if worktree_path.contains("${sandbox_code_root}") {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some(
                    "worktree_path still contains an unresolved sandbox_code_root placeholder",
                ),
                workspace_root: None,
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: None,
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let worktree_path = normalize_posix_path(&worktree_path);
    if let Some(reason) = worker_launch_worktree_path_failure(&sandbox_code_root, &worktree_path) {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "failed",
                setup_reason: Some(&reason),
                workspace_root: workspace_root_for_code_root(&sandbox_code_root).as_deref(),
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: Some(&base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    let code_root = Path::new(&sandbox_code_root);
    if !code_root.exists() {
        return Ok(Some(worker_launch_worktree_context_value(
            WorktreeContextInput {
                setup_status: "skipped",
                setup_reason: Some("sandbox_code_root is not a local path on the Rust worker host"),
                workspace_root: workspace_root_for_code_root(&sandbox_code_root).as_deref(),
                sandbox_code_root: Some(&sandbox_code_root),
                active_root: None,
                worktree_path: Some(&worktree_path),
                branch_name: Some(&branch_name),
                base_ref: Some(&base_ref),
                attempt_id,
                setup_output: None,
                original_base_ref: Some(&base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            },
        )));
    }

    Ok(Some(
        prepare_worker_launch_worktree_with_git(
            code_root,
            Path::new(&worktree_path),
            &branch_name,
            &base_ref,
            attempt_id,
        )
        .await?,
    ))
}

struct WorktreeContextInput<'a> {
    setup_status: &'a str,
    setup_reason: Option<&'a str>,
    workspace_root: Option<&'a str>,
    sandbox_code_root: Option<&'a str>,
    active_root: Option<&'a str>,
    worktree_path: Option<&'a str>,
    branch_name: Option<&'a str>,
    base_ref: Option<&'a str>,
    attempt_id: Option<&'a str>,
    setup_output: Option<&'a str>,
    original_base_ref: Option<&'a str>,
    resolved_base_ref: Option<&'a str>,
    fallback_reason: Option<&'a str>,
    git_fsck_summary: Option<&'a str>,
    pruned_worktrees_count: Option<i64>,
}

fn worker_launch_worktree_context_value(
    input: WorktreeContextInput<'_>,
) -> WorkerLaunchWorktreeContext {
    let active_root = input.active_root.map(ToOwned::to_owned);
    let is_isolated = active_root.is_some();
    let attempt_worktree = json!({
        "workspace_root": input.workspace_root,
        "sandbox_code_root": input.sandbox_code_root,
        "active_root": active_root,
        "worktree_path": input.worktree_path,
        "branch_name": input.branch_name,
        "base_ref": input.base_ref,
        "attempt_id": input.attempt_id,
        "is_isolated": is_isolated,
        "setup_status": input.setup_status,
        "setup_reason": input.setup_reason,
        "setup_output": input.setup_output,
        "original_base_ref": input.original_base_ref,
        "resolved_base_ref": input.resolved_base_ref,
        "fallback_reason": input.fallback_reason,
        "git_fsck_summary": input.git_fsck_summary,
        "pruned_worktrees_count": input.pruned_worktrees_count
    });
    let setup = json!({
        "status": input.setup_status,
        "reason": input.setup_reason,
        "output": input.setup_output,
        "worktree_path": input.worktree_path,
        "branch_name": input.branch_name,
        "base_ref": input.base_ref,
        "attempt_id": input.attempt_id,
        "original_base_ref": input.original_base_ref,
        "resolved_base_ref": input.resolved_base_ref,
        "fallback_reason": input.fallback_reason,
        "git_fsck_summary": input.git_fsck_summary,
        "pruned_worktrees_count": input.pruned_worktrees_count
    });
    let mut metadata_patch = Map::new();
    metadata_patch.insert("attempt_worktree".to_string(), attempt_worktree);
    metadata_patch.insert("worktree_setup".to_string(), setup);
    if let Some(active_root) = input.active_root {
        metadata_patch.insert("active_execution_root".to_string(), json!(active_root));
    }
    WorkerLaunchWorktreeContext {
        metadata_patch,
        setup_failed: input.setup_status == "failed",
        setup_reason: input.setup_reason.map(ToOwned::to_owned),
    }
}

async fn prepare_worker_launch_worktree_with_git(
    sandbox_code_root: &Path,
    worktree_path: &Path,
    branch_name: &str,
    base_ref: &str,
    attempt_id: Option<&str>,
) -> CoreResult<WorkerLaunchWorktreeContext> {
    let env: Vec<(String, String)> = Vec::new();
    let sandbox_code_root_text = sandbox_code_root.to_string_lossy().to_string();
    let worktree_path_text = worktree_path.to_string_lossy().to_string();
    let workspace_root = workspace_root_for_code_root(&sandbox_code_root.to_string_lossy());
    let git_root = run_git_command(
        sandbox_code_root,
        &["rev-parse", "--show-toplevel"],
        &env,
        30,
    )
    .await?;
    if git_root.exit_code != 0 {
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "skipped",
            setup_reason: Some("sandbox_code_root is not a git checkout"),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: None,
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some(&compact_git_error(&git_root)),
            original_base_ref: Some(base_ref),
            resolved_base_ref: None,
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }

    if worktree_path.exists() {
        let existing = run_git_command(
            worktree_path,
            &["rev-parse", "--is-inside-work-tree"],
            &env,
            30,
        )
        .await?;
        if existing.exit_code != 0 {
            let reason = format!(
                "worktree_path exists but is not a git worktree: {}",
                worktree_path.display()
            );
            return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
                setup_status: "failed",
                setup_reason: Some(&reason),
                workspace_root: workspace_root.as_deref(),
                sandbox_code_root: Some(&sandbox_code_root_text),
                active_root: None,
                worktree_path: Some(&worktree_path_text),
                branch_name: Some(branch_name),
                base_ref: Some(base_ref),
                attempt_id,
                setup_output: Some(&compact_git_error(&existing)),
                original_base_ref: Some(base_ref),
                resolved_base_ref: None,
                fallback_reason: None,
                git_fsck_summary: None,
                pruned_worktrees_count: None,
            }));
        }
        let head = short_git_head(worktree_path, &env).await?;
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "prepared",
            setup_reason: Some("attempt worktree already exists"),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: Some(&worktree_path_text),
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some("existing git worktree reused"),
            original_base_ref: Some(base_ref),
            resolved_base_ref: Some(&head),
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }

    if let Some(parent) = worktree_path.parent() {
        std::fs::create_dir_all(parent).map_err(|err| {
            CoreError::Storage(format!(
                "create attempt worktree parent {}: {err}",
                parent.display()
            ))
        })?;
    }
    let _ = run_git_command(sandbox_code_root, &["worktree", "prune"], &env, 60).await?;
    let worktree_arg = worktree_path.to_string_lossy().to_string();
    let add = run_git_command(
        sandbox_code_root,
        &[
            "worktree",
            "add",
            "-B",
            branch_name,
            &worktree_arg,
            base_ref,
        ],
        &env,
        120,
    )
    .await?;
    if add.exit_code != 0 {
        let reason = compact_git_error(&add);
        return Ok(worker_launch_worktree_context_value(WorktreeContextInput {
            setup_status: "failed",
            setup_reason: Some(&reason),
            workspace_root: workspace_root.as_deref(),
            sandbox_code_root: Some(&sandbox_code_root_text),
            active_root: None,
            worktree_path: Some(&worktree_path_text),
            branch_name: Some(branch_name),
            base_ref: Some(base_ref),
            attempt_id,
            setup_output: Some(&compact_text(&add.stdout, 1200)),
            original_base_ref: Some(base_ref),
            resolved_base_ref: None,
            fallback_reason: None,
            git_fsck_summary: None,
            pruned_worktrees_count: None,
        }));
    }
    let head = short_git_head(worktree_path, &env).await?;
    Ok(worker_launch_worktree_context_value(WorktreeContextInput {
        setup_status: "prepared",
        setup_reason: None,
        workspace_root: workspace_root.as_deref(),
        sandbox_code_root: Some(&sandbox_code_root_text),
        active_root: Some(&worktree_path_text),
        worktree_path: Some(&worktree_path_text),
        branch_name: Some(branch_name),
        base_ref: Some(base_ref),
        attempt_id,
        setup_output: Some(&compact_text(&add.stdout, 1200)),
        original_base_ref: Some(base_ref),
        resolved_base_ref: Some(&head),
        fallback_reason: None,
        git_fsck_summary: None,
        pruned_worktrees_count: None,
    }))
}

fn worker_launch_worktree_path_failure(
    sandbox_code_root: &str,
    worktree_path: &str,
) -> Option<String> {
    let code_root = normalize_posix_path(sandbox_code_root);
    let worktree_path = normalize_posix_path(worktree_path);
    if !worktree_path.starts_with('/') {
        return Some(format!("worktree_path is not absolute: {worktree_path}"));
    }
    if worktree_path == code_root || worktree_path.starts_with(&format!("{code_root}/")) {
        return Some(format!(
            "workspace run contract rejected worker launch path: worktree_path must not be inside sandbox_code_root; code_root={code_root}; worktree_path={worktree_path}"
        ));
    }
    None
}

fn workspace_root_for_code_root(sandbox_code_root: &str) -> Option<String> {
    let normalized = normalize_posix_path(sandbox_code_root);
    normalized
        .rsplit_once('/')
        .map(|(parent, _)| if parent.is_empty() { "/" } else { parent })
        .map(ToOwned::to_owned)
}

fn merge_metadata_patch(target: &mut Map<String, Value>, patch: &Map<String, Value>) {
    for (key, value) in patch {
        target.insert(key.clone(), value.clone());
    }
}

pub(crate) struct PipelineRunAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
}

impl PipelineRunAdmissionHandler {
    pub(crate) fn new(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
    ) -> Self {
        Self {
            store,
            stage_runner,
        }
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for PipelineRunAdmissionHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_or_empty(item.payload_json.clone());
        let workspace_id =
            string_from_map(&payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(&payload, "plan_id"))
            .ok_or_else(|| {
                CoreError::Storage(
                    "pipeline_run_requested requires plan_id and node_id".to_string(),
                )
            })?;
        let node_id = required_string(&payload, "node_id")?;
        let attempt_id = string_from_map(&payload, "attempt_id");
        let reason = string_from_map(&payload, "reason")
            .unwrap_or_else(|| "pipeline_gate_required".to_string());

        let plan = self.store.get_plan(&plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }
        let nodes = self.store.list_plan_nodes(&plan_id).await?;
        let Some(mut node) = nodes.into_iter().find(|candidate| candidate.id == node_id) else {
            return Err(CoreError::Storage(format!(
                "workspace plan node {node_id} not found"
            )));
        };
        if node.intent == "done" {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }
        if attempt_id.is_some()
            && node.current_attempt_id.as_deref().is_some()
            && node.current_attempt_id.as_deref() != attempt_id.as_deref()
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let now = Utc::now();
        if let Some(run) = self
            .store
            .latest_pipeline_run_for_node(&plan_id, &node_id, attempt_id.as_deref())
            .await?
        {
            if run.status == "running" {
                if pipeline_run_matches_node_expected_commit(&run, &node) {
                    mark_existing_pipeline_run_running(&mut node, &run, now);
                    self.store.save_plan_node(node).await?;
                    return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
                }
                let (reason, metadata_patch) = stale_pipeline_run_failure_metadata(&run, &node);
                let _ = self
                    .store
                    .finish_pipeline_run(&run.id, "failed", Some(&reason), &metadata_patch, now)
                    .await?;
            }
            if can_reflect_existing_pipeline_run(&run, &node) {
                reflect_existing_pipeline_run_to_node(&mut node, &run, now);
                self.store.save_plan_node(node).await?;
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
        }

        let workspace = self
            .store
            .get_workspace(&workspace_id)
            .await?
            .ok_or_else(|| CoreError::Storage(format!("workspace {workspace_id} not found")))?;
        let mut contract = pipeline_contract_foundation(&workspace);
        let source_publish_outcome =
            prepare_drone_source_publish(&mut contract, &workspace, &node, attempt_id.as_deref())
                .await?;
        if !contract.can_create_sandbox_native_run() && source_publish_outcome.is_none() {
            mark_pipeline_requested(
                &mut node,
                &item,
                &reason,
                attempt_id.as_deref(),
                now,
                "runtime_admitted",
            );
            self.store.save_plan_node(node).await?;
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let trigger_policy_json = json!({
            "trigger": "verification_gate",
            "node_id": node_id,
            "attempt_id": attempt_id
        });
        let contract_id = self
            .store
            .ensure_pipeline_contract(
                &generate_uuid_v4(),
                &workspace_id,
                &plan_id,
                &contract.provider,
                contract.code_root.as_deref(),
                &contract.commands_json,
                &contract.env_json,
                &trigger_policy_json,
                contract.timeout_seconds,
                contract.auto_deploy,
                contract.preview_port,
                contract.health_url.as_deref(),
                &pipeline_contract_metadata(&contract, source_publish_outcome.as_ref()),
                now,
            )
            .await?;
        let run_metadata = pipeline_run_metadata(&reason, source_publish_outcome.as_ref());
        let run = WorkspacePipelineRunRecord {
            id: generate_uuid_v4(),
            contract_id,
            workspace_id: workspace_id.clone(),
            plan_id: Some(plan_id.clone()),
            node_id: Some(node_id.clone()),
            attempt_id: attempt_id.clone(),
            commit_ref: source_publish_source_commit_ref(source_publish_outcome.as_ref())
                .or_else(|| node_expected_commit_ref(&node)),
            provider: contract.provider.clone(),
            status: "running".to_string(),
            reason: None,
            started_at: Some(now),
            completed_at: None,
            metadata_json: run_metadata,
            created_at: now,
            updated_at: None,
        };
        let run = self.store.create_pipeline_run(run).await?;
        mark_existing_pipeline_run_running(&mut node, &run, now);
        self.store.save_plan_node(node.clone()).await?;

        if let Some(source_publish_failure) = source_publish_outcome
            .as_ref()
            .and_then(DroneSourcePublishOutcome::failure)
        {
            let completed_at = Utc::now();
            let run = finish_drone_source_publish_failure(
                self.store.as_ref(),
                &workspace,
                &contract,
                &run,
                &source_publish_failure,
                completed_at,
            )
            .await?;
            finish_pipeline_on_node(
                &mut node,
                &run,
                "failed",
                Some(&source_publish_failure.reason),
                &source_publish_failure.evidence_refs(&run.id),
                None,
                contract.health_url.as_deref(),
                completed_at,
            );
            self.store.save_plan_node(node).await?;
            self.store
                .enqueue_plan_outbox(pipeline_completed_supervisor_tick_with_source(
                    &workspace_id,
                    &plan_id,
                    &node_id,
                    &run.id,
                    "failed",
                    "workspace_plan.drone_pipeline_run_completed",
                    completed_at,
                ))
                .await?;
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        if contract.provider == DRONE_PROVIDER {
            let completed_at = Utc::now();
            if let Some(result) = run_drone_pipeline_if_configured(&contract).await? {
                let (run, evidence_refs) = finish_drone_pipeline_result(
                    self.store.as_ref(),
                    &workspace,
                    &contract,
                    &run,
                    &result,
                    completed_at,
                )
                .await?;
                finish_pipeline_on_node(
                    &mut node,
                    &run,
                    &result.status,
                    run.reason.as_deref(),
                    &evidence_refs,
                    None,
                    contract.health_url.as_deref(),
                    completed_at,
                );
                self.store.save_plan_node(node).await?;
                self.store
                    .enqueue_plan_outbox(pipeline_completed_supervisor_tick_with_source(
                        &workspace_id,
                        &plan_id,
                        &node_id,
                        &run.id,
                        &result.status,
                        "workspace_plan.drone_pipeline_run_completed",
                        completed_at,
                    ))
                    .await?;
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
            let run = finish_drone_provider_unavailable(
                self.store.as_ref(),
                &workspace,
                &contract,
                &run,
                source_publish_outcome.as_ref(),
                completed_at,
            )
            .await?;
            let evidence_refs = vec![
                "ci_pipeline:failed".to_string(),
                "drone:plugin_unavailable".to_string(),
                format!("pipeline_run:failed:{}", run.id),
            ];
            finish_pipeline_on_node(
                &mut node,
                &run,
                "failed",
                run.reason.as_deref(),
                &evidence_refs,
                None,
                contract.health_url.as_deref(),
                completed_at,
            );
            self.store.save_plan_node(node).await?;
            self.store
                .enqueue_plan_outbox(pipeline_completed_supervisor_tick_with_source(
                    &workspace_id,
                    &plan_id,
                    &node_id,
                    &run.id,
                    "failed",
                    "workspace_plan.drone_pipeline_run_completed",
                    completed_at,
                ))
                .await?;
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        if contract.can_execute_inline_stages() {
            if let Some(stage_runner) = &self.stage_runner {
                let outcome = execute_sandbox_native_pipeline_stages(
                    self.store.as_ref(),
                    stage_runner.as_ref(),
                    &workspace,
                    &contract,
                    &run,
                )
                .await?;
                let completed_at = Utc::now();
                let run = self
                    .store
                    .finish_pipeline_run(
                        &run.id,
                        &outcome.status,
                        outcome.reason.as_deref(),
                        &json!({
                            "stage_count": outcome.stage_results.len(),
                            "service_count": 0,
                            "preview_urls": {}
                        }),
                        completed_at,
                    )
                    .await?
                    .unwrap_or_else(|| {
                        let mut fallback = run.clone();
                        fallback.status = outcome.status.clone();
                        fallback.reason = outcome.reason.clone();
                        fallback.completed_at = Some(completed_at);
                        fallback.updated_at = Some(completed_at);
                        fallback
                    });
                finish_pipeline_on_node(
                    &mut node,
                    &run,
                    &outcome.status,
                    outcome.reason.as_deref(),
                    &outcome.evidence_refs,
                    None,
                    contract.health_url.as_deref(),
                    completed_at,
                );
                self.store.save_plan_node(node).await?;
                self.store
                    .enqueue_plan_outbox(pipeline_completed_supervisor_tick(
                        &workspace_id,
                        &plan_id,
                        &node_id,
                        &run.id,
                        &outcome.status,
                        completed_at,
                    ))
                    .await?;
            }
        }

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

pub(crate) struct PipelineContractFoundation {
    provider: String,
    host_code_root: Option<String>,
    code_root: Option<String>,
    commands_json: Value,
    env_json: Value,
    timeout_seconds: i32,
    auto_deploy: bool,
    preview_port: Option<i32>,
    health_url: Option<String>,
    services_json: Value,
    deploy_command: Option<String>,
    agent_managed: bool,
    contract_source: String,
    provider_config_json: Value,
    metadata_json: Value,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PipelineStageSpec {
    stage: String,
    command: String,
    required: bool,
    timeout_seconds: i32,
    service_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PipelineStageResult {
    stage: String,
    status: String,
    command: String,
    exit_code: Option<i32>,
    stdout_preview: String,
    stderr_preview: String,
    duration_ms: i32,
    log_ref: Option<String>,
    artifact_refs: Vec<String>,
    service_id: Option<String>,
    required: bool,
}

impl PipelineStageResult {
    fn passed(&self) -> bool {
        matches!(self.status.as_str(), "success" | "skipped")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PipelineStageExecutionOutcome {
    status: String,
    reason: Option<String>,
    stage_results: Vec<PipelineStageResult>,
    evidence_refs: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DroneSourcePublishFailure {
    reason: String,
    metadata: Map<String, Value>,
}

impl DroneSourcePublishFailure {
    fn evidence_refs(&self, run_id: &str) -> Vec<String> {
        vec![
            "ci_pipeline:failed".to_string(),
            "source_publish:failed".to_string(),
            format!("pipeline_run:failed:{run_id}"),
        ]
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DroneSourcePublishSuccess {
    metadata: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DroneSourcePublishSkipped {
    metadata: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum DroneSourcePublishOutcome {
    Failed(DroneSourcePublishFailure),
    Published(DroneSourcePublishSuccess),
    Skipped(DroneSourcePublishSkipped),
}

impl DroneSourcePublishOutcome {
    fn metadata(&self) -> &Map<String, Value> {
        match self {
            Self::Failed(failure) => &failure.metadata,
            Self::Published(success) => &success.metadata,
            Self::Skipped(skipped) => &skipped.metadata,
        }
    }

    fn failure(&self) -> Option<&DroneSourcePublishFailure> {
        match self {
            Self::Failed(failure) => Some(failure),
            Self::Published(_) | Self::Skipped(_) => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct GitPublishResult {
    status: String,
    reason: Option<String>,
    published_commit: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct GitRemoteMergeResult {
    status: String,
    reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct AcceptedWorktreeIntegrationResult {
    status: String,
    summary: String,
    commit_ref: String,
    dirty_signature: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct GitCommandOutput {
    exit_code: i32,
    stdout: String,
    stderr: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DronePipelineConfig {
    owner: String,
    repo: String,
    server_url: String,
    token: String,
    client: String,
    cli_command: String,
    host_code_root: Option<PathBuf>,
    branch: Option<String>,
    commit: Option<String>,
    params: Vec<(String, String)>,
    deploy: Option<DroneDeployConfig>,
    timeout_seconds: u64,
    poll_interval_seconds: u64,
}

impl DronePipelineConfig {
    fn repo_slug(&self) -> String {
        format!("{}/{}", self.owner, self.repo)
    }

    fn build_url(&self, build_number: i64) -> String {
        format!(
            "{}/{}/{}/{}",
            self.server_url.trim_end_matches('/'),
            drone_path_segment(&self.owner),
            drone_path_segment(&self.repo),
            build_number
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DroneDeployConfig {
    mode: String,
    stage: String,
    required: bool,
    target: Option<String>,
    docker: Map<String, Value>,
    kubernetes: Map<String, Value>,
    cli: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DronePipelineResult {
    status: String,
    reason: Option<String>,
    stage_results: Vec<DronePipelineStageResult>,
    evidence_refs: Vec<String>,
    external_id: Option<String>,
    external_url: Option<String>,
    metadata: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DronePipelineStageResult {
    stage: String,
    status: String,
    command: String,
    exit_code: Option<i32>,
    stdout_preview: String,
    stderr_preview: String,
    duration_ms: i32,
    log_ref: Option<String>,
    artifact_refs: Vec<String>,
    metadata: Map<String, Value>,
}

impl PipelineContractFoundation {
    fn can_create_sandbox_native_run(&self) -> bool {
        if self.provider != SANDBOX_NATIVE_PROVIDER {
            return false;
        }
        if !self.auto_deploy {
            return true;
        }
        let service_count = self.services_json.as_array().map_or(0, Vec::len);
        if self.agent_managed {
            if self.contract_source != PLANNING_CONTRACT_SOURCE {
                return false;
            }
            if service_count == 0 && self.deploy_command.is_none() && self.health_url.is_none() {
                return false;
            }
        }
        service_count > 0
    }

    fn can_execute_inline_stages(&self) -> bool {
        self.provider == SANDBOX_NATIVE_PROVIDER
            && !self.auto_deploy
            && self.services_json.as_array().map_or(0, Vec::len) == 0
    }
}

async fn execute_sandbox_native_pipeline_stages(
    store: &dyn WorkspacePlanDispatchStore,
    runner: &dyn WorkspacePipelineStageRunner,
    workspace: &WorkspaceRecord,
    contract: &PipelineContractFoundation,
    run: &WorkspacePipelineRunRecord,
) -> CoreResult<PipelineStageExecutionOutcome> {
    let stages = pipeline_stage_specs_from_json(&contract.commands_json, contract.timeout_seconds);
    let mut stage_results = Vec::new();
    let mut evidence_refs = Vec::new();
    let mut failure_reason = None;

    for stage in stages {
        let started_at = Utc::now();
        let stage_row = store
            .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
                id: generate_uuid_v4(),
                run_id: run.id.clone(),
                workspace_id: workspace.id.clone(),
                stage: stage.stage.clone(),
                status: "running".to_string(),
                command: Some(stage.command.clone()),
                exit_code: None,
                stdout_preview: None,
                stderr_preview: None,
                log_ref: None,
                artifact_refs_json: Vec::new(),
                started_at: Some(started_at),
                completed_at: None,
                duration_ms: None,
                metadata_json: json!({
                    "required": stage.required,
                    "service_id": stage.service_id
                }),
                created_at: started_at,
                updated_at: None,
            })
            .await?;
        let stage_result = runner
            .run_stage(&workspace.project_id, contract, &stage)
            .await;
        let completed_at = Utc::now();
        let _ = store
            .finish_pipeline_stage_run(
                &stage_row.id,
                &stage_result.status,
                stage_result.exit_code,
                Some(&stage_result.stdout_preview),
                Some(&stage_result.stderr_preview),
                stage_result.log_ref.as_deref(),
                &stage_result.artifact_refs,
                &json!({
                    "duration_ms_observed": stage_result.duration_ms,
                    "service_id": stage_result.service_id
                }),
                completed_at,
            )
            .await?;

        let passed = stage_result.passed();
        let status_label = if passed { "passed" } else { "failed" };
        evidence_refs.push(format!(
            "pipeline_stage:{}:{status_label}",
            stage_result.stage
        ));
        if let Some(service_id) = &stage_result.service_id {
            evidence_refs.push(format!(
                "pipeline_stage:{}:{status_label}:{service_id}",
                stage_result.stage
            ));
        }
        if !passed && stage_result.required {
            failure_reason = Some(format!(
                "stage {} failed with exit {}",
                stage_result.stage,
                stage_result.exit_code.unwrap_or(1)
            ));
            stage_results.push(stage_result);
            break;
        }
        stage_results.push(stage_result);
    }

    let status = if failure_reason.is_none() {
        "success"
    } else {
        "failed"
    }
    .to_string();
    evidence_refs.insert(
        0,
        format!(
            "ci_pipeline:{}",
            if status == "success" {
                "passed"
            } else {
                "failed"
            }
        ),
    );
    evidence_refs.push(format!("pipeline_run:{status}:{}", run.id));
    dedup_strings(&mut evidence_refs);

    Ok(PipelineStageExecutionOutcome {
        status,
        reason: failure_reason,
        stage_results,
        evidence_refs,
    })
}

async fn finish_drone_source_publish_failure(
    store: &dyn WorkspacePlanDispatchStore,
    workspace: &WorkspaceRecord,
    contract: &PipelineContractFoundation,
    run: &WorkspacePipelineRunRecord,
    failure: &DroneSourcePublishFailure,
    completed_at: DateTime<Utc>,
) -> CoreResult<WorkspacePipelineRunRecord> {
    let stage_row = store
        .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
            id: generate_uuid_v4(),
            run_id: run.id.clone(),
            workspace_id: workspace.id.clone(),
            stage: "source_publish".to_string(),
            status: "running".to_string(),
            command: Some("git:publish".to_string()),
            exit_code: None,
            stdout_preview: None,
            stderr_preview: None,
            log_ref: None,
            artifact_refs_json: Vec::new(),
            started_at: Some(completed_at),
            completed_at: None,
            duration_ms: None,
            metadata_json: Value::Object(source_publish_stage_metadata(failure)),
            created_at: completed_at,
            updated_at: None,
        })
        .await?;
    let _ = store
        .finish_pipeline_stage_run(
            &stage_row.id,
            "failed",
            Some(1),
            Some(""),
            Some(&failure.reason),
            None,
            &[],
            &Value::Object(source_publish_stage_metadata(failure)),
            completed_at,
        )
        .await?;

    let run_metadata = Value::Object(drone_source_publish_run_metadata(
        contract,
        failure,
        completed_at,
    ));
    let finished = store
        .finish_pipeline_run(
            &run.id,
            "failed",
            Some(&failure.reason),
            &run_metadata,
            completed_at,
        )
        .await?;
    Ok(finished.unwrap_or_else(|| {
        let mut fallback = run.clone();
        fallback.status = "failed".to_string();
        fallback.reason = Some(failure.reason.clone());
        fallback.metadata_json = merge_object_values(&fallback.metadata_json, &run_metadata);
        fallback.completed_at = Some(completed_at);
        fallback.updated_at = Some(completed_at);
        fallback
    }))
}

async fn finish_drone_provider_unavailable(
    store: &dyn WorkspacePlanDispatchStore,
    workspace: &WorkspaceRecord,
    contract: &PipelineContractFoundation,
    run: &WorkspacePipelineRunRecord,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
    completed_at: DateTime<Utc>,
) -> CoreResult<WorkspacePipelineRunRecord> {
    let message = format!("pipeline provider plugin is not enabled: {DRONE_PROVIDER}");
    let stage_metadata = drone_provider_unavailable_stage_metadata(contract);
    let stage_row = store
        .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
            id: generate_uuid_v4(),
            run_id: run.id.clone(),
            workspace_id: workspace.id.clone(),
            stage: "drone_plugin".to_string(),
            status: "running".to_string(),
            command: Some("plugin:resolve".to_string()),
            exit_code: None,
            stdout_preview: None,
            stderr_preview: None,
            log_ref: None,
            artifact_refs_json: Vec::new(),
            started_at: Some(completed_at),
            completed_at: None,
            duration_ms: None,
            metadata_json: Value::Object(stage_metadata.clone()),
            created_at: completed_at,
            updated_at: None,
        })
        .await?;
    let _ = store
        .finish_pipeline_stage_run(
            &stage_row.id,
            "failed",
            Some(1),
            Some(""),
            Some(&message),
            None,
            &[],
            &Value::Object(stage_metadata),
            completed_at,
        )
        .await?;

    let run_metadata = Value::Object(drone_provider_unavailable_run_metadata(
        contract,
        source_publish_outcome,
        &message,
    ));
    let finished = store
        .finish_pipeline_run(
            &run.id,
            "failed",
            Some(&message),
            &run_metadata,
            completed_at,
        )
        .await?;
    Ok(finished.unwrap_or_else(|| {
        let mut fallback = run.clone();
        fallback.status = "failed".to_string();
        fallback.reason = Some(message);
        fallback.metadata_json = merge_object_values(&fallback.metadata_json, &run_metadata);
        fallback.completed_at = Some(completed_at);
        fallback.updated_at = Some(completed_at);
        fallback
    }))
}

fn drone_provider_unavailable_stage_metadata(
    contract: &PipelineContractFoundation,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("plugin_unavailable".to_string(), json!(true));
    metadata.insert("provider".to_string(), json!(contract.provider));
    metadata
}

fn drone_provider_unavailable_run_metadata(
    contract: &PipelineContractFoundation,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
    message: &str,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("stage_count".to_string(), json!(1));
    metadata.insert(
        "service_count".to_string(),
        json!(contract.services_json.as_array().map_or(0, Vec::len)),
    );
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("plugin_unavailable".to_string(), json!(true));
    metadata.insert("provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("provider_error".to_string(), json!(message));
    metadata.insert("pipeline_failed_stage".to_string(), json!("drone_plugin"));
    metadata.insert("pipeline_failure_summary".to_string(), json!(message));
    metadata.insert("pipeline_last_summary".to_string(), json!(message));
    if let Some(outcome) = source_publish_outcome {
        metadata.extend(outcome.metadata().clone());
    }
    metadata
}

async fn run_drone_pipeline_if_configured(
    contract: &PipelineContractFoundation,
) -> CoreResult<Option<DronePipelineResult>> {
    let Some(config) = drone_pipeline_config(contract)? else {
        return Ok(None);
    };
    let result = match run_drone_pipeline(&config).await {
        Ok(result) => result,
        Err(err) => drone_api_failure_result(&err.to_string()),
    };
    Ok(Some(result))
}

fn drone_pipeline_config(
    contract: &PipelineContractFoundation,
) -> CoreResult<Option<DronePipelineConfig>> {
    let provider_config = object_or_empty(contract.provider_config_json.clone());
    let Some(repo_slug) = string_from_map(&provider_config, "repo")
        .or_else(|| string_from_map(&provider_config, "repository"))
    else {
        return Ok(None);
    };
    let Some((owner, repo)) = repo_slug.split_once('/') else {
        return Ok(Some(drone_config_failure_config(
            "delivery_cicd.drone.repo must be '<owner>/<repo>'",
        )));
    };
    let owner = owner.trim();
    let repo = repo.trim();
    if owner.is_empty() || repo.is_empty() || repo.contains('/') {
        return Ok(Some(drone_config_failure_config(
            "delivery_cicd.drone.repo must be '<owner>/<repo>'",
        )));
    }

    let server_env = string_from_map(&provider_config, "drone_server_env")
        .or_else(|| string_from_map(&provider_config, "server_env"))
        .or_else(|| string_from_map(&provider_config, "server_url_env"))
        .unwrap_or_else(|| DRONE_SERVER_ENV.to_string());
    let server_url = string_from_map(&provider_config, "server_url")
        .or_else(|| drone_config_value_env(&server_env))
        .or_else(|| {
            if server_env == DRONE_SERVER_URL_ENV {
                None
            } else {
                drone_config_value_env(DRONE_SERVER_URL_ENV)
            }
        });
    let Some(server_url) = server_url else {
        return Ok(None);
    };

    let token_env = string_from_map(&provider_config, "drone_token_env")
        .or_else(|| string_from_map(&provider_config, "token_env"))
        .unwrap_or_else(|| DRONE_TOKEN_ENV.to_string());
    let Some(token) = drone_config_value_env(&token_env) else {
        return Ok(None);
    };

    let deploy = drone_deploy_config(provider_config.get("deploy"));
    let mut params = string_pairs_from_map(
        provider_config
            .get("params")
            .or_else(|| provider_config.get("build_params")),
    );
    let target = string_from_map(&provider_config, "target")
        .or_else(|| deploy.as_ref().and_then(|deploy| deploy.target.clone()));
    if let Some(target) = target {
        insert_default_param(&mut params, "target", target);
    }
    add_drone_deploy_params(&mut params, deploy.as_ref());
    params.sort_by(|left, right| left.0.cmp(&right.0));

    Ok(Some(DronePipelineConfig {
        owner: owner.to_string(),
        repo: repo.to_string(),
        server_url: server_url.trim_end_matches('/').to_string(),
        token,
        client: drone_client_from_config(&provider_config),
        cli_command: drone_cli_command_from_config(&provider_config),
        host_code_root: contract.host_code_root.as_deref().map(PathBuf::from),
        branch: string_from_map(&provider_config, "branch"),
        commit: string_from_map(&provider_config, "commit"),
        params,
        deploy,
        timeout_seconds: positive_u64_from_map(
            &provider_config,
            "timeout_seconds",
            contract.timeout_seconds.max(1) as u64,
        ),
        poll_interval_seconds: positive_u64_from_map(&provider_config, "poll_interval_seconds", 5),
    }))
}

fn drone_client_from_config(provider_config: &Map<String, Value>) -> String {
    if bool_from_map_default(provider_config, "use_cli", false) {
        return "cli".to_string();
    }
    let raw = string_from_map(provider_config, "drone_client")
        .or_else(|| string_from_map(provider_config, "client"))
        .or_else(|| string_from_map(provider_config, "transport"))
        .unwrap_or_else(|| "http".to_string());
    let normalized = raw.trim().to_ascii_lowercase().replace('-', "_");
    if matches!(normalized.as_str(), "cli" | "drone_cli") {
        "cli".to_string()
    } else {
        "http".to_string()
    }
}

fn drone_cli_command_from_config(provider_config: &Map<String, Value>) -> String {
    string_from_map(provider_config, "drone_command")
        .or_else(|| string_from_map(provider_config, "cli_command"))
        .or_else(|| string_from_map(provider_config, "command"))
        .or_else(|| drone_config_value_env("DRONE_CLI"))
        .unwrap_or_else(|| "drone".to_string())
}

fn drone_deploy_config(value: Option<&Value>) -> Option<DroneDeployConfig> {
    let map = value.and_then(Value::as_object)?;
    if !bool_from_map_default(map, "enabled", false) {
        return None;
    }
    let mode = string_from_map(map, "mode")
        .unwrap_or_else(|| DEFAULT_DRONE_DEPLOY_MODE.to_string())
        .to_ascii_lowercase();
    let stage =
        string_from_map(map, "stage").unwrap_or_else(|| DEFAULT_DRONE_DEPLOY_STAGE.to_string());
    Some(DroneDeployConfig {
        mode,
        stage,
        required: bool_from_map_default(map, "required", true),
        target: string_from_map(map, "target"),
        docker: map
            .get("docker")
            .cloned()
            .map(object_or_empty)
            .unwrap_or_default(),
        kubernetes: map
            .get("kubernetes")
            .cloned()
            .map(object_or_empty)
            .unwrap_or_default(),
        cli: map
            .get("cli")
            .cloned()
            .map(object_or_empty)
            .unwrap_or_default(),
    })
}

fn add_drone_deploy_params(params: &mut Vec<(String, String)>, deploy: Option<&DroneDeployConfig>) {
    let Some(deploy) = deploy else {
        return;
    };
    insert_default_param(params, "MEMSTACK_DEPLOY_ENABLED", "true");
    insert_default_param(params, "MEMSTACK_DEPLOY_MODE", deploy.mode.clone());
    insert_default_param(params, "MEMSTACK_DEPLOY_STAGE", deploy.stage.clone());
    if let Some(target) = &deploy.target {
        insert_default_param(params, "MEMSTACK_DEPLOY_TARGET", target.clone());
    }
    match deploy.mode.as_str() {
        "docker" => {
            add_prefixed_drone_deploy_params(params, "MEMSTACK_DEPLOY_DOCKER", &deploy.docker)
        }
        "kubernetes" => add_prefixed_drone_deploy_params(
            params,
            "MEMSTACK_DEPLOY_KUBERNETES",
            &deploy.kubernetes,
        ),
        "cli" => add_prefixed_drone_deploy_params(params, "MEMSTACK_DEPLOY_CLI", &deploy.cli),
        _ => {}
    }
}

fn add_prefixed_drone_deploy_params(
    params: &mut Vec<(String, String)>,
    prefix: &str,
    values: &Map<String, Value>,
) {
    for (key, value) in values {
        let Some(param_value) = drone_deploy_param_value(value) else {
            continue;
        };
        let safe_key = drone_deploy_safe_param_key(key);
        if !safe_key.is_empty() {
            insert_default_param(params, format!("{prefix}_{safe_key}"), param_value);
        }
    }
}

fn insert_default_param(
    params: &mut Vec<(String, String)>,
    key: impl Into<String>,
    value: impl Into<String>,
) {
    let key = key.into();
    if params.iter().any(|(existing, _)| existing == &key) {
        return;
    }
    params.push((key, value.into()));
}

fn drone_deploy_safe_param_key(key: &str) -> String {
    key.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_uppercase()
            } else {
                '_'
            }
        })
        .collect::<String>()
        .trim_matches('_')
        .to_string()
}

fn drone_deploy_param_value(value: &Value) -> Option<String> {
    if value.is_null() {
        None
    } else if let Some(value) = value.as_bool() {
        Some(if value { "true" } else { "false" }.to_string())
    } else if value.is_i64() || value.is_u64() || value.is_f64() {
        Some(value.to_string())
    } else if let Some(value) = value.as_str() {
        metadata_string(Some(&Value::String(value.to_string())))
    } else if let Some(items) = value.as_array() {
        let joined = items
            .iter()
            .filter_map(|item| metadata_string(Some(&Value::String(scalar_to_string(item)))))
            .collect::<Vec<_>>()
            .join(",");
        if joined.is_empty() {
            None
        } else {
            Some(joined)
        }
    } else {
        None
    }
}

fn drone_config_failure_config(message: &str) -> DronePipelineConfig {
    DronePipelineConfig {
        owner: String::new(),
        repo: String::new(),
        server_url: String::new(),
        token: String::new(),
        client: "http".to_string(),
        cli_command: "drone".to_string(),
        host_code_root: None,
        branch: None,
        commit: None,
        params: vec![("__configuration_error__".to_string(), message.to_string())],
        deploy: None,
        timeout_seconds: 1,
        poll_interval_seconds: 1,
    }
}

fn drone_yaml_preflight_failure_result(
    config: &DronePipelineConfig,
) -> Option<DronePipelineResult> {
    let host_code_root = config.host_code_root.as_ref()?;
    let path = host_code_root.join(".drone.yml");
    let content = match std::fs::read_to_string(&path) {
        Ok(content) => content,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            return Some(drone_preflight_failure_result(
                "Drone build .drone.yml preflight failed: .drone.yml is missing",
                &[".drone.yml is missing".to_string()],
                &["drone_error:missing_config".to_string()],
                config.deploy.as_ref(),
            ));
        }
        Err(err) => {
            return Some(drone_preflight_failure_result(
                &format!("Drone build .drone.yml preflight failed: {err}"),
                &[format!("could not read .drone.yml: {err}")],
                &["drone_error:config_read_failed".to_string()],
                config.deploy.as_ref(),
            ));
        }
    };
    let yaml = match serde_yaml_ng::from_str::<YamlValue>(&content) {
        Ok(value) => value,
        Err(err) => {
            return Some(drone_preflight_failure_result(
                &format!("Drone build .drone.yml preflight failed: {err}"),
                &[format!(".drone.yml parse error: {err}")],
                &[
                    "drone_error:yaml_parse_failed".to_string(),
                    "drone_config:.drone.yml".to_string(),
                ],
                config.deploy.as_ref(),
            ));
        }
    };
    let mut issues = drone_yaml_command_type_issues(&yaml);
    if let Some(deploy) = config
        .deploy
        .as_ref()
        .filter(|deploy| deploy.mode == "docker")
    {
        issues.extend(drone_yaml_docker_deploy_issues(&yaml, deploy));
    }
    dedup_strings(&mut issues);
    if issues.is_empty() {
        return None;
    }
    let mut evidence_refs = vec![
        "drone:preflight_failed".to_string(),
        "drone_config:.drone.yml".to_string(),
    ];
    if issues
        .iter()
        .any(|issue| issue.contains("commands") && issue.contains("string"))
    {
        evidence_refs.push("drone_error:yaml_unmarshal_into_string".to_string());
    }
    if issues
        .iter()
        .any(|issue| issue.contains("required services"))
    {
        evidence_refs.push("drone_error:docker_deploy_missing_required_service".to_string());
    }
    if issues
        .iter()
        .any(|issue| issue.contains("host.docker.internal") || issue.contains("localhost"))
    {
        evidence_refs.push("drone_error:docker_deploy_local_registry".to_string());
    }
    dedup_strings(&mut evidence_refs);
    Some(drone_preflight_failure_result(
        &format!(
            "Drone build .drone.yml preflight failed: {}",
            issues
                .iter()
                .take(4)
                .cloned()
                .collect::<Vec<_>>()
                .join("; ")
        ),
        &issues,
        &evidence_refs,
        config.deploy.as_ref(),
    ))
}

fn drone_preflight_failure_result(
    reason: &str,
    issues: &[String],
    evidence_refs: &[String],
    deploy: Option<&DroneDeployConfig>,
) -> DronePipelineResult {
    let preview = compact_text(reason, 4_000);
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert(
        "drone_preflight".to_string(),
        json!(DRONE_YAML_PREFLIGHT_VALIDATION),
    );
    metadata.insert("drone_preflight_status".to_string(), json!("failed"));
    metadata.insert("drone_config_path".to_string(), json!(".drone.yml"));
    metadata.insert(
        "drone_preflight_issues".to_string(),
        json!(issues.iter().take(8).cloned().collect::<Vec<_>>()),
    );
    if let Some(deploy) = deploy {
        metadata.extend(drone_deploy_metadata(Some(deploy), Some("invalid"), issues));
        metadata.insert(
            "deploy_preflight_validation".to_string(),
            json!(DRONE_YAML_PREFLIGHT_VALIDATION),
        );
    }

    let mut stage_metadata = Map::new();
    stage_metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    stage_metadata.insert(
        "drone_preflight".to_string(),
        json!(DRONE_YAML_PREFLIGHT_VALIDATION),
    );
    stage_metadata.insert("drone_config_path".to_string(), json!(".drone.yml"));
    stage_metadata.insert(
        "drone_preflight_issues".to_string(),
        json!(issues.iter().take(8).cloned().collect::<Vec<_>>()),
    );

    let mut refs = vec!["ci_pipeline:failed".to_string()];
    refs.extend(evidence_refs.iter().cloned());
    if deploy.is_some() {
        refs.push("deployment:invalid:docker".to_string());
    }
    dedup_strings(&mut refs);

    DronePipelineResult {
        status: "failed".to_string(),
        reason: Some(preview.clone()),
        stage_results: vec![DronePipelineStageResult {
            stage: "drone_preflight".to_string(),
            status: "failed".to_string(),
            command: "drone:preflight .drone.yml".to_string(),
            exit_code: Some(1),
            stdout_preview: String::new(),
            stderr_preview: preview,
            duration_ms: 0,
            log_ref: Some("drone://preflight/.drone.yml".to_string()),
            artifact_refs: vec!["drone_config:.drone.yml".to_string()],
            metadata: stage_metadata,
        }],
        evidence_refs: refs,
        external_id: None,
        external_url: None,
        metadata,
    }
}

fn drone_yaml_command_type_issues(yaml: &YamlValue) -> Vec<String> {
    let mut issues = Vec::new();
    for (index, step) in drone_yaml_steps(yaml).iter().enumerate() {
        let step_name = drone_yaml_step_name(step, index);
        let Some(commands) = yaml_get(step, "commands") else {
            continue;
        };
        let Some(commands) = yaml_sequence(commands) else {
            issues.push(format!(
                "steps[{step_name}].commands must be a list of strings"
            ));
            continue;
        };
        for (command_index, command) in commands.iter().enumerate() {
            if yaml_string(command).is_none() {
                issues.push(format!(
                    "steps[{step_name}].commands[{command_index}] must be a string"
                ));
            }
        }
    }
    issues
}

fn drone_yaml_docker_deploy_issues(yaml: &YamlValue, deploy: &DroneDeployConfig) -> Vec<String> {
    let deploy_commands = drone_yaml_deploy_commands(yaml, deploy);
    if deploy_commands.is_empty() {
        return vec![format!("docker deploy stage {} is missing", deploy.stage)];
    }
    let output = deploy_commands.join("\n").to_ascii_lowercase();
    let mut issues = Vec::new();
    if drone_docker_deploy_uses_forbidden_local_registry_pull(&output) {
        issues.push(
            "deploy step pulls or runs host.docker.internal/localhost local-registry images through the mounted host Docker daemon".to_string(),
        );
    }
    let missing_services = drone_missing_docker_deploy_required_services(&output, deploy);
    if !missing_services.is_empty() {
        issues.push(format!(
            "docker deploy stage {} does not cover required services: {}",
            deploy.stage,
            missing_services.join(", ")
        ));
    }
    if !drone_docker_deploy_has_run_marker(&output) {
        issues.push(format!(
            "docker deploy stage {} missing docker run/compose/stack/service deploy command",
            deploy.stage
        ));
    }
    issues
}

fn drone_yaml_deploy_commands(yaml: &YamlValue, deploy: &DroneDeployConfig) -> Vec<String> {
    drone_yaml_steps(yaml)
        .into_iter()
        .filter(|step| {
            yaml_get(step, "name")
                .and_then(yaml_string)
                .is_some_and(|name| drone_is_deploy_label(name, deploy))
        })
        .filter_map(|step| yaml_get(step, "commands"))
        .filter_map(yaml_sequence)
        .flat_map(|commands| commands.iter().filter_map(yaml_string))
        .map(ToOwned::to_owned)
        .collect()
}

fn drone_yaml_steps(yaml: &YamlValue) -> Vec<&YamlValue> {
    yaml_get(yaml, "steps")
        .and_then(yaml_sequence)
        .map(|steps| steps.iter().collect())
        .unwrap_or_default()
}

fn drone_yaml_step_name(step: &YamlValue, index: usize) -> String {
    yaml_get(step, "name")
        .and_then(yaml_string)
        .filter(|value| !value.trim().is_empty())
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| index.to_string())
}

fn yaml_get<'a>(value: &'a YamlValue, key: &str) -> Option<&'a YamlValue> {
    let YamlValue::Mapping(map) = value else {
        return None;
    };
    map.get(YamlValue::String(key.to_string()))
}

fn yaml_sequence(value: &YamlValue) -> Option<&Vec<YamlValue>> {
    match value {
        YamlValue::Sequence(items) => Some(items),
        _ => None,
    }
}

fn yaml_string(value: &YamlValue) -> Option<&str> {
    match value {
        YamlValue::String(text) => Some(text),
        _ => None,
    }
}

async fn run_drone_pipeline(config: &DronePipelineConfig) -> CoreResult<DronePipelineResult> {
    if let Some((_, message)) = config
        .params
        .iter()
        .find(|(key, _)| key == "__configuration_error__")
    {
        return Ok(drone_configuration_failure_result(message));
    }
    if let Some(result) = drone_yaml_preflight_failure_result(config) {
        return Ok(result);
    }

    if config.client == "cli" {
        match run_drone_pipeline_cli(config).await {
            Ok(mut result) => {
                result
                    .metadata
                    .insert("drone_client".to_string(), json!("cli"));
                return Ok(result);
            }
            Err(err) if is_drone_cli_unavailable_error(&err) => {
                let mut result = run_drone_pipeline_http(config).await?;
                result
                    .metadata
                    .insert("drone_client".to_string(), json!("http_fallback"));
                return Ok(result);
            }
            Err(err) => return Err(err),
        }
    }

    run_drone_pipeline_http(config).await
}

async fn run_drone_pipeline_http(config: &DronePipelineConfig) -> CoreResult<DronePipelineResult> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|err| CoreError::Storage(format!("Drone HTTP client error: {err}")))?;
    ensure_drone_repo_enabled(&client, config).await?;
    ensure_drone_docker_deploy_repo_trusted(&client, config).await?;
    let running = running_drone_build_for_commit(&client, config).await?;
    let build_number = if let Some(build) = running {
        required_i64(build.get("number"), "Drone build number")?
    } else {
        let created = create_drone_build(&client, config).await?;
        required_i64(created.get("number"), "Drone build number")?
    };
    let build = poll_drone_build(&client, config, build_number).await?;
    drone_result_from_build(&client, config, &build).await
}

async fn run_drone_pipeline_cli(config: &DronePipelineConfig) -> CoreResult<DronePipelineResult> {
    ensure_drone_repo_enabled_cli(config).await?;
    ensure_drone_docker_deploy_repo_trusted_cli(config).await?;
    let running = running_drone_build_for_commit_cli(config).await?;
    let build_number = if let Some(build) = running {
        required_i64(build.get("number"), "Drone build number")?
    } else {
        let created = create_drone_build_cli(config).await?;
        required_i64(created.get("number"), "Drone build number")?
    };
    let build = poll_drone_build_cli(config, build_number).await?;
    drone_result_from_build_cli(config, &build).await
}

async fn ensure_drone_repo_enabled_cli(config: &DronePipelineConfig) -> CoreResult<()> {
    match drone_cli_json_object(config, &["repo", "info", &config.repo_slug()]).await {
        Ok(repo) => {
            if repo.get("active").and_then(Value::as_bool) == Some(false) {
                let _ = drone_cli_text(config, &["repo", "enable", &config.repo_slug()]).await?;
            }
            Ok(())
        }
        Err(err) if looks_like_drone_not_found(&err.to_string()) => {
            let _ = drone_cli_text(config, &["repo", "enable", &config.repo_slug()]).await?;
            Ok(())
        }
        Err(err) => Err(err),
    }
}

async fn ensure_drone_docker_deploy_repo_trusted_cli(
    config: &DronePipelineConfig,
) -> CoreResult<()> {
    if !drone_docker_deploy_requires_trusted_repo(config.deploy.as_ref()) {
        return Ok(());
    }
    let repo = drone_cli_json_object(config, &["repo", "info", &config.repo_slug()]).await?;
    if repo.get("trusted").and_then(Value::as_bool) == Some(true) {
        return Ok(());
    }
    let _ = drone_cli_text(
        config,
        &["repo", "update", &config.repo_slug(), "--trusted"],
    )
    .await?;
    let updated = drone_cli_json_object(config, &["repo", "info", &config.repo_slug()])
        .await
        .unwrap_or_else(|_| {
            let mut updated = Map::new();
            updated.insert("trusted".to_string(), json!(true));
            updated
        });
    if updated.get("trusted").and_then(Value::as_bool) != Some(true) {
        return Err(CoreError::Storage(format!(
            "Drone repo {} must be trusted for docker deploy host volumes",
            config.repo_slug()
        )));
    }
    Ok(())
}

async fn running_drone_build_for_commit_cli(
    config: &DronePipelineConfig,
) -> CoreResult<Option<Value>> {
    let Some(commit) = config.commit.as_deref() else {
        return Ok(None);
    };
    let builds = drone_cli_build_list(config, 25).await;
    let Ok(builds) = builds else {
        return Ok(None);
    };
    Ok(builds.into_iter().find(|build| {
        let status = drone_status(build.get("status"));
        is_drone_running_status(&status) && drone_build_matches_commit(build, commit)
    }))
}

async fn create_drone_build_cli(config: &DronePipelineConfig) -> CoreResult<Value> {
    let mut args = vec![
        "build".to_string(),
        "create".to_string(),
        config.repo_slug(),
    ];
    if let Some(branch) = &config.branch {
        args.push(format!("--branch={branch}"));
    }
    if let Some(commit) = &config.commit {
        args.push(format!("--commit={commit}"));
    }
    for (key, value) in &config.params {
        args.push(format!("--param={key}={value}"));
    }
    drone_cli_json_value_owned(config, args).await
}

async fn poll_drone_build_cli(
    config: &DronePipelineConfig,
    build_number: i64,
) -> CoreResult<Value> {
    let started = Instant::now();
    let mut latest: Option<Value> = None;
    loop {
        let build = drone_cli_json_value_owned(
            config,
            vec![
                "build".to_string(),
                "info".to_string(),
                config.repo_slug(),
                build_number.to_string(),
            ],
        )
        .await?;
        let status = drone_status(build.get("status"));
        if is_drone_terminal_status(&status) {
            return Ok(build);
        }
        if started.elapsed() >= Duration::from_secs(config.timeout_seconds.max(1)) {
            let _ = drone_cli_text_owned(
                config,
                vec![
                    "build".to_string(),
                    "stop".to_string(),
                    config.repo_slug(),
                    build_number.to_string(),
                ],
            )
            .await;
            let mut timeout_build = object_or_empty(latest.unwrap_or(build));
            timeout_build.insert("number".to_string(), json!(build_number));
            timeout_build.insert("status".to_string(), json!("timeout"));
            return Ok(Value::Object(timeout_build));
        }
        latest = Some(build);
        sleep(Duration::from_secs(config.poll_interval_seconds.max(1))).await;
    }
}

async fn drone_result_from_build_cli(
    config: &DronePipelineConfig,
    build: &Value,
) -> CoreResult<DronePipelineResult> {
    let build_number = required_i64(build.get("number"), "Drone build number")?;
    let external_url = config.build_url(build_number);
    let stage_results = drone_stage_results_cli(config, build_number, build, &external_url).await;
    drone_result_from_build_and_stages(config, build, stage_results)
}

async fn drone_stage_results_cli(
    config: &DronePipelineConfig,
    build_number: i64,
    build: &Value,
    external_url: &str,
) -> Vec<DronePipelineStageResult> {
    let Some(stages) = build.get("stages").and_then(Value::as_array) else {
        return vec![drone_pipeline_stage_result(
            config,
            build_number,
            "drone",
            "build",
            drone_status(build.get("status")),
            optional_i32(build.get("exit_code")),
            String::new(),
            build.get("error").and_then(Value::as_str).unwrap_or(""),
            external_url,
            config.deploy.as_ref(),
        )];
    };
    let mut output = Vec::new();
    for stage in stages {
        let stage_name = stage
            .get("name")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or("stage");
        let stage_log_ref = log_part(stage.get("number")).unwrap_or_else(|| stage_name.to_string());
        if let Some(steps) = stage.get("steps").and_then(Value::as_array) {
            for step in steps {
                let step_name = step
                    .get("name")
                    .and_then(Value::as_str)
                    .filter(|value| !value.trim().is_empty())
                    .unwrap_or("step");
                let step_log_ref =
                    log_part(step.get("number")).unwrap_or_else(|| step_name.to_string());
                let log_text = drone_cli_text_owned(
                    config,
                    vec![
                        "log".to_string(),
                        "view".to_string(),
                        config.repo_slug(),
                        build_number.to_string(),
                        stage_log_ref.clone(),
                        step_log_ref,
                    ],
                )
                .await
                .unwrap_or_default();
                output.push(drone_pipeline_stage_result(
                    config,
                    build_number,
                    stage_name,
                    step_name,
                    drone_status(step.get("status")),
                    optional_i32(step.get("exit_code")),
                    log_text,
                    step.get("error").and_then(Value::as_str).unwrap_or(""),
                    external_url,
                    config.deploy.as_ref(),
                ));
            }
        } else {
            output.push(drone_pipeline_stage_result(
                config,
                build_number,
                stage_name,
                stage_name,
                drone_status(stage.get("status")),
                optional_i32(stage.get("exit_code")),
                String::new(),
                stage.get("error").and_then(Value::as_str).unwrap_or(""),
                external_url,
                config.deploy.as_ref(),
            ));
        }
    }
    if output.is_empty() {
        output.push(drone_pipeline_stage_result(
            config,
            build_number,
            "drone",
            "build",
            drone_status(build.get("status")),
            optional_i32(build.get("exit_code")),
            String::new(),
            build.get("error").and_then(Value::as_str).unwrap_or(""),
            external_url,
            config.deploy.as_ref(),
        ));
    }
    output
}

async fn drone_cli_build_list(
    config: &DronePipelineConfig,
    per_page: usize,
) -> CoreResult<Vec<Value>> {
    let text = drone_cli_text_owned(
        config,
        vec![
            "build".to_string(),
            "ls".to_string(),
            config.repo_slug(),
            format!("--limit={}", per_page.max(1)),
            "--format".to_string(),
            DRONE_CLI_JSON_TEMPLATE.to_string(),
        ],
    )
    .await?;
    Ok(text
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .filter(|value| value.is_object())
        .collect())
}

async fn drone_cli_json_object(
    config: &DronePipelineConfig,
    args: &[&str],
) -> CoreResult<Map<String, Value>> {
    let value = drone_cli_json_value(config, args).await?;
    match value {
        Value::Object(map) => Ok(map),
        _ => Err(CoreError::Storage(
            "Drone CLI JSON response was not an object".to_string(),
        )),
    }
}

async fn drone_cli_json_value(config: &DronePipelineConfig, args: &[&str]) -> CoreResult<Value> {
    drone_cli_json_value_owned(config, args.iter().map(|arg| (*arg).to_string()).collect()).await
}

async fn drone_cli_json_value_owned(
    config: &DronePipelineConfig,
    mut args: Vec<String>,
) -> CoreResult<Value> {
    args.push("--format".to_string());
    args.push(DRONE_CLI_JSON_TEMPLATE.to_string());
    let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    let text = drone_cli_text(config, &arg_refs).await?;
    serde_json::from_str(&text)
        .map_err(|err| CoreError::Storage(format!("Drone CLI returned invalid JSON: {err}")))
}

async fn drone_cli_text(config: &DronePipelineConfig, args: &[&str]) -> CoreResult<String> {
    let output = run_drone_cli_command(config, args).await?;
    if output.exit_code != 0 {
        let text = if output.stderr.trim().is_empty() {
            output.stdout.trim()
        } else {
            output.stderr.trim()
        };
        return Err(CoreError::Storage(format!(
            "Drone CLI command failed: {}",
            compact_text(text, 600)
        )));
    }
    Ok(output.stdout)
}

async fn drone_cli_text_owned(
    config: &DronePipelineConfig,
    args: Vec<String>,
) -> CoreResult<String> {
    let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    drone_cli_text(config, &arg_refs).await
}

async fn run_drone_cli_command(
    config: &DronePipelineConfig,
    args: &[&str],
) -> CoreResult<GitCommandOutput> {
    let mut command = tokio::process::Command::new(&config.cli_command);
    command
        .args(args)
        .env(DRONE_SERVER_ENV, &config.server_url)
        .env(DRONE_TOKEN_ENV, &config.token)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let output = tokio::time::timeout(Duration::from_secs(30), command.output())
        .await
        .map_err(|_| {
            CoreError::Storage(format!(
                "Drone CLI {} timed out after 30s",
                config.cli_command
            ))
        })?
        .map_err(|err| {
            if err.kind() == std::io::ErrorKind::NotFound {
                CoreError::Storage(format!(
                    "Drone CLI executable not found: {}",
                    config.cli_command
                ))
            } else {
                CoreError::Storage(format!(
                    "Drone CLI {} failed to start: {err}",
                    config.cli_command
                ))
            }
        })?;
    Ok(GitCommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

fn is_drone_cli_unavailable_error(err: &CoreError) -> bool {
    err.to_string()
        .to_ascii_lowercase()
        .contains("drone cli executable not found")
}

async fn ensure_drone_repo_enabled(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
) -> CoreResult<()> {
    match drone_api_request(
        client,
        config,
        reqwest::Method::GET,
        &drone_repo_path(config),
        &[],
    )
    .await
    {
        Ok(repo) => {
            if repo.get("active").and_then(Value::as_bool) == Some(false) {
                let _ = drone_api_request(
                    client,
                    config,
                    reqwest::Method::POST,
                    &drone_repo_path(config),
                    &[],
                )
                .await
                .map_err(CoreError::Storage)?;
            }
            Ok(())
        }
        Err(err) if looks_like_drone_not_found(&err) => {
            let _ = drone_api_request(
                client,
                config,
                reqwest::Method::POST,
                &drone_repo_path(config),
                &[],
            )
            .await
            .map_err(CoreError::Storage)?;
            Ok(())
        }
        Err(err) => Err(CoreError::Storage(err)),
    }
}

async fn ensure_drone_docker_deploy_repo_trusted(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
) -> CoreResult<()> {
    if !drone_docker_deploy_requires_trusted_repo(config.deploy.as_ref()) {
        return Ok(());
    }
    let repo = drone_api_request(
        client,
        config,
        reqwest::Method::GET,
        &drone_repo_path(config),
        &[],
    )
    .await
    .map_err(CoreError::Storage)?;
    if repo.get("trusted").and_then(Value::as_bool) == Some(true) {
        return Ok(());
    }
    let updated = drone_api_json_request(
        client,
        config,
        reqwest::Method::PATCH,
        &drone_repo_path(config),
        &[],
        Some(&json!({"trusted": true})),
    )
    .await
    .map_err(CoreError::Storage)?;
    if updated.get("trusted").and_then(Value::as_bool) != Some(true) {
        return Err(CoreError::Storage(format!(
            "Drone repo {} must be trusted for docker deploy host volumes",
            config.repo_slug()
        )));
    }
    Ok(())
}

fn drone_docker_deploy_requires_trusted_repo(deploy: Option<&DroneDeployConfig>) -> bool {
    let Some(deploy) = deploy else {
        return false;
    };
    if deploy.mode != "docker" {
        return false;
    }
    deploy
        .docker
        .get("trusted")
        .and_then(Value::as_bool)
        .unwrap_or(true)
}

async fn running_drone_build_for_commit(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
) -> CoreResult<Option<Value>> {
    let Some(commit) = config.commit.as_deref() else {
        return Ok(None);
    };
    let builds = drone_api_request(
        client,
        config,
        reqwest::Method::GET,
        &drone_repo_child_path(config, &["builds"]),
        &[("per_page", "25".to_string())],
    )
    .await;
    let Ok(Value::Array(builds)) = builds else {
        return Ok(None);
    };
    Ok(builds.into_iter().find(|build| {
        let status = drone_status(build.get("status"));
        is_drone_running_status(&status) && drone_build_matches_commit(build, commit)
    }))
}

async fn create_drone_build(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
) -> CoreResult<Value> {
    let mut query = config
        .params
        .iter()
        .map(|(key, value)| (key.as_str(), value.clone()))
        .collect::<Vec<_>>();
    if let Some(branch) = &config.branch {
        query.push(("branch", branch.clone()));
    }
    if let Some(commit) = &config.commit {
        query.push(("commit", commit.clone()));
    }
    drone_api_request(
        client,
        config,
        reqwest::Method::POST,
        &drone_repo_child_path(config, &["builds"]),
        &query,
    )
    .await
    .map_err(CoreError::Storage)
}

async fn poll_drone_build(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    build_number: i64,
) -> CoreResult<Value> {
    let started = Instant::now();
    let path = drone_repo_child_path(config, &["builds", &build_number.to_string()]);
    let mut latest: Option<Value> = None;
    loop {
        let build = drone_api_request(client, config, reqwest::Method::GET, &path, &[])
            .await
            .map_err(CoreError::Storage)?;
        let status = drone_status(build.get("status"));
        if is_drone_terminal_status(&status) {
            return Ok(build);
        }
        if started.elapsed() >= Duration::from_secs(config.timeout_seconds.max(1)) {
            let _ = drone_api_request(client, config, reqwest::Method::DELETE, &path, &[]).await;
            let mut timeout_build = object_or_empty(latest.unwrap_or(build));
            timeout_build.insert("number".to_string(), json!(build_number));
            timeout_build.insert("status".to_string(), json!("timeout"));
            return Ok(Value::Object(timeout_build));
        }
        latest = Some(build);
        sleep(Duration::from_secs(config.poll_interval_seconds.max(1))).await;
    }
}

async fn drone_result_from_build(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    build: &Value,
) -> CoreResult<DronePipelineResult> {
    let build_number = required_i64(build.get("number"), "Drone build number")?;
    let external_url = config.build_url(build_number);
    let stage_results =
        drone_stage_results(client, config, build_number, build, &external_url).await;
    drone_result_from_build_and_stages(config, build, stage_results)
}

fn drone_result_from_build_and_stages(
    config: &DronePipelineConfig,
    build: &Value,
    stage_results: Vec<DronePipelineStageResult>,
) -> CoreResult<DronePipelineResult> {
    let build_number = required_i64(build.get("number"), "Drone build number")?;
    let external_id = format!("{}#{build_number}", config.repo_slug());
    let external_url = config.build_url(build_number);
    let drone_status = drone_status(build.get("status"));
    let mut status = drone_internal_status(&drone_status);
    let mut reason = drone_failure_reason(&drone_status, &external_id);
    let deploy_state = drone_deploy_state(&stage_results, config.deploy.as_ref());
    let deploy_validation_issues = if deploy_state.as_deref() == Some("invalid") {
        drone_deploy_validation_issues(&stage_results, config.deploy.as_ref())
    } else {
        Vec::new()
    };
    if let Some(deploy) = config.deploy.as_ref() {
        if deploy.required
            && matches!(
                deploy_state.as_deref(),
                Some("failed" | "missing" | "invalid")
            )
            && status == "success"
        {
            status = "failed".to_string();
            reason = Some(drone_deploy_failure_reason(
                deploy,
                &external_id,
                deploy_state.as_deref().unwrap_or("failed"),
                &deploy_validation_issues,
            ));
        }
    }
    let mut evidence_refs = vec![
        format!(
            "ci_pipeline:{}",
            if status == "success" {
                "passed"
            } else {
                "failed"
            }
        ),
        format!("drone_build:{drone_status}:{external_id}"),
        format!("pipeline_external:{DRONE_PROVIDER}:{external_id}"),
    ];
    for stage in &stage_results {
        evidence_refs.push(format!("pipeline_stage:{}:{}", stage.stage, stage.status));
    }
    if let Some(deploy) = config.deploy.as_ref() {
        if let Some(deploy_state) = deploy_state.as_deref() {
            evidence_refs.push(format!(
                "deployment:{}:{}",
                if deploy_state == "passed" {
                    "passed"
                } else {
                    deploy_state
                },
                deploy.mode
            ));
            if let Some(target) = &deploy.target {
                evidence_refs.push(format!("deployment_target:{target}"));
            }
        }
    }
    dedup_strings(&mut evidence_refs);

    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("external_id".to_string(), json!(external_id));
    metadata.insert("external_url".to_string(), json!(external_url));
    metadata.insert("drone_build_number".to_string(), json!(build_number));
    metadata.insert("drone_repo".to_string(), json!(config.repo_slug()));
    metadata.insert("drone_status".to_string(), json!(drone_status));
    metadata.insert(
        "drone_link".to_string(),
        build
            .get("link")
            .and_then(Value::as_str)
            .map_or(Value::Null, |value| json!(value)),
    );
    metadata.extend(drone_deploy_metadata(
        config.deploy.as_ref(),
        deploy_state.as_deref(),
        &deploy_validation_issues,
    ));

    Ok(DronePipelineResult {
        status,
        reason,
        stage_results,
        evidence_refs,
        external_id: Some(external_id),
        external_url: Some(external_url),
        metadata,
    })
}

async fn drone_stage_results(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    build_number: i64,
    build: &Value,
    external_url: &str,
) -> Vec<DronePipelineStageResult> {
    let Some(stages) = build.get("stages").and_then(Value::as_array) else {
        return vec![drone_pipeline_stage_result(
            config,
            build_number,
            "drone",
            "build",
            drone_status(build.get("status")),
            optional_i32(build.get("exit_code")),
            String::new(),
            build.get("error").and_then(Value::as_str).unwrap_or(""),
            external_url,
            config.deploy.as_ref(),
        )];
    };
    let mut output = Vec::new();
    for stage in stages {
        let stage_name = stage
            .get("name")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or("stage");
        let stage_log_ref = log_part(stage.get("number")).unwrap_or_else(|| stage_name.to_string());
        if let Some(steps) = stage.get("steps").and_then(Value::as_array) {
            for step in steps {
                let step_name = step
                    .get("name")
                    .and_then(Value::as_str)
                    .filter(|value| !value.trim().is_empty())
                    .unwrap_or("step");
                let step_log_ref =
                    log_part(step.get("number")).unwrap_or_else(|| step_name.to_string());
                let log_text = drone_logs_text(
                    drone_api_request(
                        client,
                        config,
                        reqwest::Method::GET,
                        &drone_repo_child_path(
                            config,
                            &[
                                "builds",
                                &build_number.to_string(),
                                "logs",
                                &stage_log_ref,
                                &step_log_ref,
                            ],
                        ),
                        &[],
                    )
                    .await
                    .ok()
                    .as_ref(),
                );
                output.push(drone_pipeline_stage_result(
                    config,
                    build_number,
                    stage_name,
                    step_name,
                    drone_status(step.get("status")),
                    optional_i32(step.get("exit_code")),
                    log_text,
                    step.get("error").and_then(Value::as_str).unwrap_or(""),
                    external_url,
                    config.deploy.as_ref(),
                ));
            }
        } else {
            output.push(drone_pipeline_stage_result(
                config,
                build_number,
                stage_name,
                stage_name,
                drone_status(stage.get("status")),
                optional_i32(stage.get("exit_code")),
                String::new(),
                stage.get("error").and_then(Value::as_str).unwrap_or(""),
                external_url,
                config.deploy.as_ref(),
            ));
        }
    }
    if output.is_empty() {
        output.push(drone_pipeline_stage_result(
            config,
            build_number,
            "drone",
            "build",
            drone_status(build.get("status")),
            optional_i32(build.get("exit_code")),
            String::new(),
            build.get("error").and_then(Value::as_str).unwrap_or(""),
            external_url,
            config.deploy.as_ref(),
        ));
    }
    output
}

fn drone_pipeline_stage_result(
    config: &DronePipelineConfig,
    build_number: i64,
    stage_name: &str,
    step_name: &str,
    drone_status: String,
    exit_code: Option<i32>,
    log_text: String,
    error_text: &str,
    external_url: &str,
    deploy: Option<&DroneDeployConfig>,
) -> DronePipelineStageResult {
    let status = drone_internal_status(&drone_status);
    let stage = drone_stage_label(stage_name, step_name);
    let compact_log = compact_text(log_text.trim(), 4_000);
    let compact_error = compact_text(error_text.trim(), 4_000);
    let stderr_preview = if status == "failed" {
        combine_failure_preview(&compact_error, &compact_log)
    } else {
        String::new()
    };
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("external_url".to_string(), json!(external_url));
    metadata.insert("drone_stage".to_string(), json!(stage_name));
    metadata.insert("drone_step".to_string(), json!(step_name));
    metadata.insert("drone_status".to_string(), json!(drone_status));
    if !compact_error.is_empty() {
        metadata.insert("drone_error".to_string(), json!(compact_error));
    }
    if drone_is_deploy_stage(stage_name, step_name, deploy) {
        metadata.insert("drone_step_kind".to_string(), json!("deploy"));
        if let Some(deploy) = deploy {
            metadata.insert("deploy_mode".to_string(), json!(deploy.mode));
            metadata.insert("deploy_stage".to_string(), json!(deploy.stage));
            if let Some(target) = &deploy.target {
                metadata.insert("deploy_target".to_string(), json!(target));
            }
        }
    }
    DronePipelineStageResult {
        stage,
        status: status.clone(),
        command: format!("drone:{stage_name}/{step_name}"),
        exit_code,
        stdout_preview: if status == "success" {
            compact_log
        } else {
            String::new()
        },
        stderr_preview,
        duration_ms: 0,
        log_ref: Some(format!(
            "drone://{}/{build_number}/{stage_name}/{step_name}",
            config.repo_slug()
        )),
        artifact_refs: vec![format!("drone_build:{external_url}")],
        metadata,
    }
}

async fn finish_drone_pipeline_result(
    store: &dyn WorkspacePlanDispatchStore,
    workspace: &WorkspaceRecord,
    contract: &PipelineContractFoundation,
    run: &WorkspacePipelineRunRecord,
    result: &DronePipelineResult,
    completed_at: DateTime<Utc>,
) -> CoreResult<(WorkspacePipelineRunRecord, Vec<String>)> {
    for stage_result in &result.stage_results {
        let mut stage_metadata = Map::new();
        stage_metadata.insert("provider".to_string(), json!(contract.provider));
        stage_metadata.extend(stage_result.metadata.clone());
        let stage_row = store
            .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
                id: generate_uuid_v4(),
                run_id: run.id.clone(),
                workspace_id: workspace.id.clone(),
                stage: stage_result.stage.clone(),
                status: "running".to_string(),
                command: Some(stage_result.command.clone()),
                exit_code: None,
                stdout_preview: None,
                stderr_preview: None,
                log_ref: None,
                artifact_refs_json: Vec::new(),
                started_at: Some(completed_at),
                completed_at: None,
                duration_ms: None,
                metadata_json: Value::Object(stage_metadata.clone()),
                created_at: completed_at,
                updated_at: None,
            })
            .await?;
        let mut finish_metadata = stage_metadata;
        finish_metadata.insert(
            "duration_ms_observed".to_string(),
            json!(stage_result.duration_ms),
        );
        let _ = store
            .finish_pipeline_stage_run(
                &stage_row.id,
                &stage_result.status,
                stage_result.exit_code,
                Some(&stage_result.stdout_preview),
                Some(&stage_result.stderr_preview),
                stage_result.log_ref.as_deref(),
                &stage_result.artifact_refs,
                &Value::Object(finish_metadata),
                completed_at,
            )
            .await?;
    }

    let mut run_metadata = Map::new();
    run_metadata.insert("stage_count".to_string(), json!(result.stage_results.len()));
    run_metadata.insert(
        "service_count".to_string(),
        json!(contract.services_json.as_array().map_or(0, Vec::len)),
    );
    run_metadata.extend(result.metadata.clone());
    if let Some(reason) = result.reason.as_deref() {
        run_metadata.insert("pipeline_failure_summary".to_string(), json!(reason));
        run_metadata.insert("pipeline_last_summary".to_string(), json!(reason));
        if let Some(stage) = first_failed_drone_stage(&result.stage_results) {
            run_metadata.insert("pipeline_failed_stage".to_string(), json!(stage.stage));
        }
    }
    let run_metadata = Value::Object(run_metadata);
    let finished = store
        .finish_pipeline_run(
            &run.id,
            &result.status,
            result.reason.as_deref(),
            &run_metadata,
            completed_at,
        )
        .await?;
    let mut evidence_refs = result.evidence_refs.clone();
    evidence_refs.push(format!("pipeline_run:{}:{}", result.status, run.id));
    if let Some(external_id) = &result.external_id {
        evidence_refs.push(format!(
            "pipeline_run_external:{DRONE_PROVIDER}:{external_id}"
        ));
    }
    dedup_strings(&mut evidence_refs);
    Ok((
        finished.unwrap_or_else(|| {
            let mut fallback = run.clone();
            fallback.status = result.status.clone();
            fallback.reason = result.reason.clone();
            fallback.metadata_json = merge_object_values(&fallback.metadata_json, &run_metadata);
            fallback.completed_at = Some(completed_at);
            fallback.updated_at = Some(completed_at);
            fallback
        }),
        evidence_refs,
    ))
}

fn drone_configuration_failure_result(message: &str) -> DronePipelineResult {
    let preview = compact_text(message, 4_000);
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("configuration_error".to_string(), json!(preview));
    let mut stage_metadata = Map::new();
    stage_metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    DronePipelineResult {
        status: "failed".to_string(),
        reason: Some(preview.clone()),
        stage_results: vec![DronePipelineStageResult {
            stage: "drone_config".to_string(),
            status: "failed".to_string(),
            command: "drone:configure".to_string(),
            exit_code: Some(1),
            stdout_preview: String::new(),
            stderr_preview: preview.clone(),
            duration_ms: 0,
            log_ref: None,
            artifact_refs: Vec::new(),
            metadata: stage_metadata,
        }],
        evidence_refs: vec![
            "ci_pipeline:failed".to_string(),
            "drone:configuration_failed".to_string(),
        ],
        external_id: None,
        external_url: None,
        metadata,
    }
}

fn drone_api_failure_result(message: &str) -> DronePipelineResult {
    let preview = compact_text(message, 4_000);
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("provider_error".to_string(), json!(preview));
    let mut stage_metadata = Map::new();
    stage_metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    DronePipelineResult {
        status: "failed".to_string(),
        reason: Some(preview.clone()),
        stage_results: vec![DronePipelineStageResult {
            stage: "drone_api".to_string(),
            status: "failed".to_string(),
            command: "drone:api".to_string(),
            exit_code: Some(1),
            stdout_preview: String::new(),
            stderr_preview: preview.clone(),
            duration_ms: 0,
            log_ref: None,
            artifact_refs: Vec::new(),
            metadata: stage_metadata,
        }],
        evidence_refs: vec![
            "ci_pipeline:failed".to_string(),
            "drone:api_failed".to_string(),
        ],
        external_id: None,
        external_url: None,
        metadata,
    }
}

async fn drone_api_request(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    method: reqwest::Method,
    path: &str,
    query: &[(&str, String)],
) -> Result<Value, String> {
    drone_api_json_request(client, config, method, path, query, None).await
}

async fn drone_api_json_request(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    method: reqwest::Method,
    path: &str,
    query: &[(&str, String)],
    json_body: Option<&Value>,
) -> Result<Value, String> {
    let url = format!("{}{}", config.server_url.trim_end_matches('/'), path);
    let mut request = client
        .request(method.clone(), &url)
        .bearer_auth(&config.token)
        .query(query);
    if let Some(json_body) = json_body {
        request = request.json(json_body);
    }
    let response = request
        .send()
        .await
        .map_err(|err| format!("Drone API {method} {path} failed: {err}"))?;
    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|err| format!("Drone API {method} {path} body failed: {err}"))?;
    if !status.is_success() {
        return Err(format!(
            "Drone API {method} {path} returned {}: {}",
            status.as_u16(),
            compact_text(&body, 600)
        ));
    }
    serde_json::from_str(&body)
        .map_err(|err| format!("Drone API {method} {path} returned invalid JSON: {err}"))
}

fn drone_repo_path(config: &DronePipelineConfig) -> String {
    drone_repo_child_path(config, &[])
}

fn drone_repo_child_path(config: &DronePipelineConfig, parts: &[&str]) -> String {
    let mut path = format!(
        "/api/repos/{}/{}",
        drone_path_segment(&config.owner),
        drone_path_segment(&config.repo)
    );
    for part in parts {
        path.push('/');
        path.push_str(&drone_path_segment(part));
    }
    path
}

fn drone_path_segment(value: &str) -> String {
    url::form_urlencoded::byte_serialize(value.as_bytes()).collect()
}

fn looks_like_drone_not_found(message: &str) -> bool {
    let lower = message.to_ascii_lowercase();
    lower.contains(" 404") || lower.contains("not found") || lower.contains("not enabled")
}

fn drone_config_value_env(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .and_then(|value| metadata_string(Some(&Value::String(value))))
        .or_else(|| source_publish_dotenv_value(name))
}

fn string_pairs_from_map(value: Option<&Value>) -> Vec<(String, String)> {
    value
        .and_then(Value::as_object)
        .map(|map| {
            map.iter()
                .filter_map(|(key, value)| {
                    if value.is_null() {
                        None
                    } else {
                        Some((key.clone(), scalar_to_string(value)))
                    }
                })
                .collect()
        })
        .unwrap_or_default()
}

fn scalar_to_string(value: &Value) -> String {
    value
        .as_str()
        .map_or_else(|| value.to_string(), ToOwned::to_owned)
}

fn positive_u64_from_map(map: &Map<String, Value>, key: &str, fallback: u64) -> u64 {
    map.get(key)
        .and_then(|value| {
            value
                .as_u64()
                .or_else(|| value.as_str()?.trim().parse::<u64>().ok())
        })
        .filter(|value| *value > 0)
        .unwrap_or(fallback.max(1))
}

fn required_i64(value: Option<&Value>, label: &str) -> CoreResult<i64> {
    optional_i64(value)
        .ok_or_else(|| CoreError::Storage(format!("{label} missing from Drone API response")))
}

fn optional_i64(value: Option<&Value>) -> Option<i64> {
    value.and_then(|value| {
        value
            .as_i64()
            .or_else(|| value.as_str()?.trim().parse::<i64>().ok())
    })
}

fn optional_i32(value: Option<&Value>) -> Option<i32> {
    optional_i64(value).and_then(|value| i32::try_from(value).ok())
}

fn drone_status(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_str)
        .and_then(|value| metadata_string(Some(&Value::String(value.to_string()))))
        .unwrap_or_else(|| "unknown".to_string())
        .to_ascii_lowercase()
}

fn drone_internal_status(status: &str) -> String {
    if status == "success" {
        "success".to_string()
    } else if status == "skipped" {
        "skipped".to_string()
    } else if is_drone_running_status(status) {
        "running".to_string()
    } else {
        "failed".to_string()
    }
}

fn is_drone_terminal_status(status: &str) -> bool {
    matches!(
        status,
        "success" | "failure" | "error" | "killed" | "declined" | "skipped"
    )
}

fn is_drone_running_status(status: &str) -> bool {
    matches!(status, "pending" | "running" | "blocked" | "waiting")
}

fn drone_failure_reason(status: &str, external_id: &str) -> Option<String> {
    if status == "success" {
        None
    } else if status == "timeout" {
        Some(format!("Drone build {external_id} timed out"))
    } else if matches!(status, "failure" | "error" | "killed" | "declined") {
        Some(format!(
            "Drone build {external_id} finished with status {status}"
        ))
    } else {
        Some(format!(
            "Drone build {external_id} did not complete successfully: {status}"
        ))
    }
}

fn drone_build_matches_commit(build: &Value, commit: &str) -> bool {
    ["after", "commit", "sha"].iter().any(|key| {
        build
            .get(*key)
            .and_then(Value::as_str)
            .is_some_and(|value| {
                value == commit || value.starts_with(commit) || commit.starts_with(value)
            })
    })
}

fn log_part(value: Option<&Value>) -> Option<String> {
    if let Some(number) = optional_i64(value).filter(|number| *number > 0) {
        return Some(number.to_string());
    }
    value
        .and_then(Value::as_str)
        .and_then(|value| metadata_string(Some(&Value::String(value.to_string()))))
}

fn drone_logs_text(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.get("out").and_then(Value::as_str))
                .collect::<String>()
        })
        .unwrap_or_default()
}

fn drone_stage_label(stage_name: &str, step_name: &str) -> String {
    let label = if stage_name == step_name {
        step_name.to_string()
    } else {
        format!("{stage_name}/{step_name}")
    };
    label.chars().take(40).collect()
}

fn drone_is_deploy_stage(
    stage_name: &str,
    step_name: &str,
    deploy: Option<&DroneDeployConfig>,
) -> bool {
    let Some(deploy) = deploy else {
        return false;
    };
    drone_is_deploy_label(stage_name, deploy) || drone_is_deploy_label(step_name, deploy)
}

fn drone_is_deploy_label(value: &str, deploy: &DroneDeployConfig) -> bool {
    let normalized = value.trim().to_ascii_lowercase();
    let configured = deploy.stage.trim().to_ascii_lowercase();
    normalized == configured
        || normalized.ends_with(&format!("/{configured}"))
        || normalized.starts_with("deploy-")
        || normalized.ends_with("-deploy")
        || normalized == "deployment"
}

fn drone_deploy_state(
    stages: &[DronePipelineStageResult],
    deploy: Option<&DroneDeployConfig>,
) -> Option<String> {
    let deploy = deploy?;
    let deploy_results = stages
        .iter()
        .filter(|stage| {
            stage
                .metadata
                .get("drone_step_kind")
                .and_then(Value::as_str)
                == Some("deploy")
                || drone_is_deploy_label(&stage.stage, deploy)
        })
        .collect::<Vec<_>>();
    if deploy_results.is_empty() {
        return Some("missing".to_string());
    }
    if !deploy_results
        .iter()
        .all(|stage| matches!(stage.status.as_str(), "success" | "skipped"))
    {
        return Some("failed".to_string());
    }
    if !deploy_results
        .iter()
        .any(|stage| drone_deploy_result_matches_mode(stage, deploy, stages))
    {
        return Some("invalid".to_string());
    }
    Some("passed".to_string())
}

fn drone_deploy_result_matches_mode(
    stage: &DronePipelineStageResult,
    deploy: &DroneDeployConfig,
    stages: &[DronePipelineStageResult],
) -> bool {
    match deploy.mode.as_str() {
        "docker" => drone_docker_deploy_validation_issues(stage, deploy, stages).is_empty(),
        "kubernetes" => {
            let image = stage
                .metadata
                .get("drone_image")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_ascii_lowercase();
            let output = drone_stage_output(stage).to_ascii_lowercase();
            image.contains("kubectl")
                || output.contains("kubectl apply")
                || output.contains("helm upgrade")
        }
        "cli" => true,
        _ => false,
    }
}

fn drone_deploy_validation_issues(
    stages: &[DronePipelineStageResult],
    deploy: Option<&DroneDeployConfig>,
) -> Vec<String> {
    let Some(deploy) = deploy else {
        return Vec::new();
    };
    if deploy.mode != "docker" {
        return Vec::new();
    }
    let mut issues = Vec::new();
    for stage in stages.iter().filter(|stage| {
        stage
            .metadata
            .get("drone_step_kind")
            .and_then(Value::as_str)
            == Some("deploy")
            || drone_is_deploy_label(&stage.stage, deploy)
    }) {
        let stage_issues = drone_docker_deploy_validation_issues(stage, deploy, stages);
        if stage_issues.is_empty() {
            return Vec::new();
        }
        issues.extend(stage_issues);
    }
    dedup_strings(&mut issues);
    issues
}

fn drone_docker_deploy_validation_issues(
    stage: &DronePipelineStageResult,
    deploy: &DroneDeployConfig,
    stages: &[DronePipelineStageResult],
) -> Vec<String> {
    let output = drone_stage_output(stage).to_ascii_lowercase();
    let mut issues = Vec::new();
    if drone_docker_deploy_output_masks_failure(&output) {
        issues.push(
            "deploy output contains failure markers despite a successful Drone step".to_string(),
        );
    }
    if drone_docker_deploy_uses_forbidden_local_registry_pull(&output) {
        issues.push(
            "deploy step pulls or runs host.docker.internal/localhost local-registry images through the mounted host Docker daemon".to_string(),
        );
    }
    let missing_services = drone_missing_docker_deploy_required_services(&output, deploy);
    if !missing_services.is_empty() {
        issues.push(format!(
            "missing required deploy services: {}",
            missing_services.join(", ")
        ));
    }
    let missing_images = drone_missing_docker_deploy_built_images(&output, deploy, stages);
    if !missing_images.is_empty() {
        issues.push(format!(
            "missing built image deploy references: {}",
            missing_images.join(", ")
        ));
    }
    if !drone_docker_deploy_has_run_marker(&output) {
        issues.push("missing docker run/compose/stack/service deploy command".to_string());
    }
    dedup_strings(&mut issues);
    issues
}

fn drone_deploy_failure_reason(
    deploy: &DroneDeployConfig,
    external_id: &str,
    deploy_state: &str,
    validation_issues: &[String],
) -> String {
    match deploy_state {
        "missing" => format!(
            "Drone build {external_id} did not report deploy stage {}",
            deploy.stage
        ),
        "invalid" => {
            if validation_issues.is_empty() {
                format!(
                    "Drone build {external_id} deploy stage {} did not implement {} deployment semantics",
                    deploy.stage, deploy.mode
                )
            } else {
                format!(
                    "Drone build {external_id} deploy stage {} did not implement {} deployment semantics: {}",
                    deploy.stage,
                    deploy.mode,
                    validation_issues
                        .iter()
                        .take(4)
                        .cloned()
                        .collect::<Vec<_>>()
                        .join("; ")
                )
            }
        }
        _ => format!(
            "Drone build {external_id} deploy stage {} failed",
            deploy.stage
        ),
    }
}

fn drone_deploy_metadata(
    deploy: Option<&DroneDeployConfig>,
    deploy_state: Option<&str>,
    validation_issues: &[String],
) -> Map<String, Value> {
    let mut metadata = Map::new();
    let Some(deploy) = deploy else {
        return metadata;
    };
    metadata.insert("deploy_enabled".to_string(), json!(true));
    metadata.insert("deploy_mode".to_string(), json!(deploy.mode));
    metadata.insert("deploy_stage".to_string(), json!(deploy.stage));
    metadata.insert(
        "deployment_status".to_string(),
        match deploy_state {
            Some("passed") => json!("deployed"),
            Some("failed" | "missing" | "invalid") => json!(deploy_state.unwrap()),
            _ => Value::Null,
        },
    );
    if let Some(target) = &deploy.target {
        metadata.insert("deploy_target".to_string(), json!(target));
    }
    if deploy.mode == "docker" && deploy_state == Some("passed") {
        metadata.insert(
            "deploy_validation".to_string(),
            json!(DRONE_DOCKER_DEPLOY_VALIDATION),
        );
    }
    if !validation_issues.is_empty() {
        metadata.insert(
            "deploy_validation_failure".to_string(),
            json!(validation_issues
                .iter()
                .take(4)
                .cloned()
                .collect::<Vec<_>>()
                .join("; ")),
        );
        metadata.insert(
            "deploy_validation_issues".to_string(),
            json!(validation_issues
                .iter()
                .take(8)
                .cloned()
                .collect::<Vec<_>>()),
        );
    }
    metadata
}

fn drone_stage_output(stage: &DronePipelineStageResult) -> String {
    [stage.stdout_preview.as_str(), stage.stderr_preview.as_str()]
        .into_iter()
        .filter(|value| !value.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

fn drone_docker_deploy_output_masks_failure(output: &str) -> bool {
    if [
        "|| echo",
        "container start skipped",
        "health check skipped",
        "image may not exist yet",
        "deployment skipped",
        "deploy skipped",
    ]
    .iter()
    .any(|marker| output.contains(marker))
    {
        return true;
    }
    output.lines().any(|line| {
        line.contains("|| true")
            && !line.contains("docker rm")
            && !line.contains("docker container rm")
            && [
                "docker pull",
                "docker run",
                "docker container run",
                "docker compose up",
                "docker-compose up",
                "docker stack deploy",
                "docker service create",
                "docker service update",
                "wget ",
                "curl ",
            ]
            .iter()
            .any(|marker| line.contains(marker))
    })
}

fn drone_docker_deploy_uses_forbidden_local_registry_pull(output: &str) -> bool {
    output.lines().any(|line| {
        (line.contains("docker pull")
            || line.contains("docker run")
            || line.contains("docker container run"))
            && (line.contains("host.docker.internal/")
                || line.contains("localhost:")
                || line.contains("127.0.0.1:")
                || line.contains("[::1]:"))
    })
}

fn drone_docker_deploy_has_run_marker(output: &str) -> bool {
    [
        "docker run",
        "docker container run",
        "docker compose up",
        "docker-compose up",
        "docker stack deploy",
        "docker service create",
        "docker service update",
    ]
    .iter()
    .any(|marker| output.contains(marker))
        || (output.contains("container id") && output.contains("names") && output.contains(" up "))
}

fn drone_missing_docker_deploy_required_services(
    output: &str,
    deploy: &DroneDeployConfig,
) -> Vec<String> {
    drone_docker_deploy_service_requirements(deploy)
        .into_iter()
        .filter(|markers| !markers.iter().any(|marker| output.contains(marker)))
        .map(|markers| {
            markers
                .first()
                .cloned()
                .unwrap_or_else(|| "unknown".to_string())
        })
        .collect()
}

fn drone_missing_docker_deploy_built_images(
    output: &str,
    deploy: &DroneDeployConfig,
    stages: &[DronePipelineStageResult],
) -> Vec<String> {
    drone_docker_build_service_requirements(stages, deploy)
        .into_iter()
        .filter(|markers| !markers.iter().any(|marker| output.contains(marker)))
        .map(|markers| {
            markers
                .first()
                .cloned()
                .unwrap_or_else(|| "unknown".to_string())
        })
        .collect()
}

fn drone_docker_deploy_service_requirements(deploy: &DroneDeployConfig) -> Vec<Vec<String>> {
    let raw = deploy
        .docker
        .get("deploy_services")
        .or_else(|| deploy.docker.get("services"));
    raw.and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| {
                    let item = item.as_object()?;
                    if item.get("required").and_then(Value::as_bool) == Some(false) {
                        return None;
                    }
                    let mut markers = [
                        "container_name",
                        "image_deploy_local",
                        "image_host_docker",
                        "image",
                        "service_id",
                        "id",
                    ]
                    .iter()
                    .filter_map(|key| string_from_map(item, key))
                    .map(|value| value.to_ascii_lowercase())
                    .collect::<Vec<_>>();
                    dedup_strings(&mut markers);
                    if markers.is_empty() {
                        None
                    } else {
                        Some(markers)
                    }
                })
                .collect()
        })
        .unwrap_or_default()
}

fn drone_docker_build_service_requirements(
    stages: &[DronePipelineStageResult],
    deploy: &DroneDeployConfig,
) -> Vec<Vec<String>> {
    let mut requirements = Vec::new();
    for stage in stages {
        if stage
            .metadata
            .get("drone_step_kind")
            .and_then(Value::as_str)
            == Some("deploy")
            || drone_is_deploy_label(&stage.stage, deploy)
        {
            continue;
        }
        let output = drone_stage_output(stage).to_ascii_lowercase();
        if !output.contains("docker build") && !output.contains("docker buildx build") {
            continue;
        }
        let identity = format!(
            "{}\n{}\n{}\n{}",
            stage.stage,
            stage.command,
            stage
                .metadata
                .get("drone_stage")
                .and_then(Value::as_str)
                .unwrap_or(""),
            stage
                .metadata
                .get("drone_step")
                .and_then(Value::as_str)
                .unwrap_or("")
        )
        .to_ascii_lowercase();
        let mut markers = Vec::new();
        for part in identity.split(|ch: char| ch.is_whitespace() || ch == ':' || ch == '/') {
            if let Some(service) = drone_docker_build_service_name(part) {
                markers.push(service);
            }
        }
        for image in drone_docker_build_tag_images(&output) {
            markers.extend(drone_docker_image_marker_candidates(&image));
        }
        dedup_strings(&mut markers);
        if !markers.is_empty() && !requirements.contains(&markers) {
            requirements.push(markers);
        }
    }
    requirements
}

fn drone_docker_build_service_name(value: &str) -> Option<String> {
    let lower = value.to_ascii_lowercase();
    for separator in [
        "docker-build-",
        "docker_build_",
        "docker-build/",
        "docker_build/",
    ] {
        if let Some(rest) = lower.split(separator).nth(1) {
            let service = rest
                .chars()
                .take_while(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '.' | '-'))
                .collect::<String>();
            if !service.is_empty() {
                return Some(service);
            }
        }
    }
    None
}

fn drone_docker_build_tag_images(output: &str) -> Vec<String> {
    output
        .split_whitespace()
        .collect::<Vec<_>>()
        .windows(2)
        .filter_map(|window| {
            if matches!(window[0], "-t" | "--tag") {
                Some(window[1].trim_matches(|ch| matches!(ch, '\'' | '"' | ',')))
            } else {
                None
            }
        })
        .filter(|image| drone_docker_image_ref_is_named_artifact(image))
        .map(ToOwned::to_owned)
        .collect()
}

fn drone_docker_image_ref_is_named_artifact(image: &str) -> bool {
    let normalized = image.trim_matches(|ch| matches!(ch, '\'' | '"' | ','));
    if normalized.is_empty() {
        return false;
    }
    let without_digest = normalized.split('@').next().unwrap_or(normalized);
    let basename = without_digest.rsplit('/').next().unwrap_or(without_digest);
    without_digest.contains('/')
        || basename.contains(':')
        || basename.contains('-')
        || basename.contains('_')
        || basename.contains('.')
}

fn drone_docker_image_marker_candidates(image: &str) -> Vec<String> {
    let normalized = image.trim_matches(|ch| matches!(ch, '\'' | '"' | ','));
    if normalized.is_empty() {
        return Vec::new();
    }
    let without_digest = normalized.split('@').next().unwrap_or(normalized);
    let mut path_parts = without_digest.split('/').collect::<Vec<_>>();
    if path_parts.len() > 1
        && path_parts.first().is_some_and(|value| {
            value.contains('.') || value.contains(':') || *value == "localhost"
        })
    {
        path_parts.remove(0);
    }
    let mut repository = path_parts.join("/");
    if let Some((before_tag, _)) = repository.rsplit_once(':') {
        repository = before_tag.to_string();
    }
    let basename = repository.rsplit('/').next().unwrap_or(&repository);
    let mut markers = vec![
        normalized.to_ascii_lowercase(),
        repository.to_ascii_lowercase(),
        basename.to_ascii_lowercase(),
    ];
    for separator in ['-', '_', '.'] {
        if let Some((_, suffix)) = basename.rsplit_once(separator) {
            markers.push(suffix.to_ascii_lowercase());
        }
    }
    dedup_strings(&mut markers);
    markers
}

fn combine_failure_preview(error_text: &str, log_text: &str) -> String {
    let mut parts = Vec::new();
    for text in [error_text, log_text] {
        let value = text.trim();
        if !value.is_empty() && !parts.contains(&value) {
            parts.push(value);
        }
    }
    compact_text(&parts.join("\n"), 4_000)
}

fn first_failed_drone_stage(
    stages: &[DronePipelineStageResult],
) -> Option<&DronePipelineStageResult> {
    stages.iter().find(|stage| stage.status == "failed")
}

fn source_publish_stage_metadata(failure: &DroneSourcePublishFailure) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.extend(failure.metadata.clone());
    metadata
}

fn drone_source_publish_run_metadata(
    contract: &PipelineContractFoundation,
    failure: &DroneSourcePublishFailure,
    completed_at: DateTime<Utc>,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("stage_count".to_string(), json!(1));
    metadata.insert(
        "service_count".to_string(),
        json!(contract.services_json.as_array().map_or(0, Vec::len)),
    );
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("pipeline_failed_stage".to_string(), json!("source_publish"));
    metadata.insert(
        "pipeline_failure_summary".to_string(),
        json!(failure.reason),
    );
    metadata.insert("pipeline_last_summary".to_string(), json!(failure.reason));
    metadata.insert(
        "pipeline_finished_at".to_string(),
        json!(completed_at.to_rfc3339()),
    );
    metadata.extend(failure.metadata.clone());
    metadata
}

fn pipeline_contract_metadata(
    contract: &PipelineContractFoundation,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Value {
    source_publish_outcome.map_or_else(
        || contract.metadata_json.clone(),
        |outcome| {
            let mut metadata = object_or_empty(contract.metadata_json.clone());
            metadata.extend(outcome.metadata().clone());
            Value::Object(metadata)
        },
    )
}

fn pipeline_run_metadata(
    reason: &str,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Value {
    let mut metadata = Map::new();
    metadata.insert("reason".to_string(), json!(reason));
    if let Some(outcome) = source_publish_outcome {
        metadata.extend(outcome.metadata().clone());
    }
    Value::Object(metadata)
}

fn source_publish_source_commit_ref(
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Option<String> {
    source_publish_outcome.and_then(|outcome| {
        outcome
            .metadata()
            .get("source_publish_source_commit_ref")
            .and_then(Value::as_str)
            .and_then(commit_ref_token)
    })
}

fn merge_object_values(left: &Value, right: &Value) -> Value {
    let mut merged = object_or_empty(left.clone());
    merged.extend(object_or_empty(right.clone()));
    Value::Object(merged)
}

async fn prepare_drone_source_publish(
    contract: &mut PipelineContractFoundation,
    workspace: &WorkspaceRecord,
    node: &WorkspacePlanNodeRecord,
    attempt_id: Option<&str>,
) -> CoreResult<Option<DroneSourcePublishOutcome>> {
    if contract.provider != DRONE_PROVIDER {
        return Ok(None);
    }
    let provider_config = object_or_empty(contract.provider_config_json.clone());
    let workspace_metadata = object_or_empty(workspace.metadata_json.clone());
    let source_control = drone_source_control_config(&workspace_metadata, &provider_config);
    let branch = drone_source_branch(&source_control, &provider_config);
    let token_env = source_control_token_env(&source_control);

    if attempt_id.is_none() {
        let metadata = source_publish_metadata(
            "skipped",
            Some("missing attempt_id; using remote branch head"),
            pipeline_contract_commit_ref(&provider_config).as_deref(),
            branch.as_deref(),
            None,
            token_env.as_deref(),
        );
        if let Some(branch) = branch.as_deref() {
            if string_from_map(&provider_config, "branch").is_none() {
                let mut patched = provider_config.clone();
                patched.insert("branch".to_string(), json!(branch));
                apply_drone_provider_config(contract, patched);
            }
        }
        return Ok(Some(DroneSourcePublishOutcome::Skipped(
            DroneSourcePublishSkipped { metadata },
        )));
    }

    let Some(commit_ref) = node_expected_commit_ref(node) else {
        let mut metadata = Map::new();
        metadata.insert("source_publish_status".to_string(), json!("skipped"));
        metadata.insert(
            "source_publish_reason".to_string(),
            json!("missing commit_ref"),
        );
        return Ok(Some(DroneSourcePublishOutcome::Skipped(
            DroneSourcePublishSkipped { metadata },
        )));
    };

    if host_code_root_from_workspace(&workspace.metadata_json).is_none() {
        let reason = "host_code_root is not available for Drone source publish".to_string();
        return Ok(Some(DroneSourcePublishOutcome::Failed(
            DroneSourcePublishFailure {
                metadata: source_publish_metadata(
                    "failed",
                    Some(&reason),
                    Some(&commit_ref),
                    None,
                    Some(&commit_ref),
                    None,
                ),
                reason,
            },
        )));
    }

    if branch.is_none() {
        let reason =
            "source_control.default_branch or delivery_cicd.drone.branch is required".to_string();
        return Ok(Some(DroneSourcePublishOutcome::Failed(
            DroneSourcePublishFailure {
                metadata: source_publish_metadata(
                    "failed",
                    Some(&reason),
                    Some(&commit_ref),
                    None,
                    Some(&commit_ref),
                    None,
                ),
                reason,
            },
        )));
    }

    let host_code_root = host_code_root_from_workspace(&workspace.metadata_json)
        .expect("host_code_root checked above");
    let branch = branch.expect("branch checked above");
    let remote_url = source_control_remote_url(&source_control);
    let token = source_control_token(token_env.as_deref());
    let publish = publish_git_ref_to_source_control(
        Path::new(&host_code_root),
        &commit_ref,
        &branch,
        remote_url.as_deref(),
        token_env.as_deref(),
        token.as_deref(),
    )
    .await?;
    let metadata = source_publish_metadata(
        &publish.status,
        publish.reason.as_deref(),
        publish.published_commit.as_deref().or(Some(&commit_ref)),
        Some(&branch),
        Some(&commit_ref),
        token_env.as_deref(),
    );
    if publish.status != "published" {
        let reason = publish
            .reason
            .clone()
            .unwrap_or_else(|| "source publish failed".to_string());
        return Ok(Some(DroneSourcePublishOutcome::Failed(
            DroneSourcePublishFailure { reason, metadata },
        )));
    }

    let published_commit = publish
        .published_commit
        .clone()
        .unwrap_or_else(|| commit_ref.clone());
    let mut patched = provider_config.clone();
    patched.insert("branch".to_string(), json!(branch));
    patched.insert("commit".to_string(), json!(published_commit));
    let mut publish_config = Map::new();
    publish_config.insert("status".to_string(), json!("published"));
    publish_config.insert(
        "branch".to_string(),
        metadata
            .get("source_publish_branch")
            .cloned()
            .unwrap_or(Value::Null),
    );
    publish_config.insert(
        "commit".to_string(),
        metadata
            .get("source_publish_commit_ref")
            .cloned()
            .unwrap_or(Value::Null),
    );
    publish_config.insert(
        "source_commit_ref".to_string(),
        metadata
            .get("source_publish_source_commit_ref")
            .cloned()
            .unwrap_or(Value::Null),
    );
    if let Some(token_env) = metadata.get("source_publish_token_env") {
        publish_config.insert("token_env".to_string(), token_env.clone());
    }
    patched.insert("source_publish".to_string(), Value::Object(publish_config));
    apply_drone_provider_config(contract, patched);

    Ok(Some(DroneSourcePublishOutcome::Published(
        DroneSourcePublishSuccess { metadata },
    )))
}

fn source_publish_metadata(
    status: &str,
    reason: Option<&str>,
    commit_ref: Option<&str>,
    branch: Option<&str>,
    source_commit_ref: Option<&str>,
    token_env: Option<&str>,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("source_publish_status".to_string(), json!(status));
    metadata.insert("source_publish_provider".to_string(), json!("git"));
    if let Some(reason) = reason {
        metadata.insert("source_publish_reason".to_string(), json!(reason));
    }
    if let Some(commit_ref) = commit_ref {
        metadata.insert("source_publish_commit_ref".to_string(), json!(commit_ref));
    }
    if let Some(branch) = branch {
        metadata.insert("source_publish_branch".to_string(), json!(branch));
    }
    if let Some(source_commit_ref) = source_commit_ref {
        metadata.insert(
            "source_publish_source_commit_ref".to_string(),
            json!(source_commit_ref),
        );
    }
    if let Some(token_env) = token_env {
        metadata.insert("source_publish_token_env".to_string(), json!(token_env));
    }
    metadata
}

fn drone_source_control_config(
    workspace_metadata: &Map<String, Value>,
    provider_config: &Map<String, Value>,
) -> Map<String, Value> {
    let mut source_control = Map::new();
    if let Some(config) = provider_config
        .get("source_control")
        .and_then(Value::as_object)
    {
        source_control.extend(config.clone());
    }
    if let Some(config) = workspace_metadata
        .get("source_control")
        .and_then(Value::as_object)
    {
        source_control.extend(config.clone());
    }
    if !source_control.contains_key("repo") {
        if let Some(value) = provider_config
            .get("repo")
            .or_else(|| provider_config.get("repository"))
            .filter(|value| value.is_string())
        {
            source_control.insert("repo".to_string(), value.clone());
        }
    }
    if !source_control.contains_key("default_branch") {
        if let Some(value) = provider_config
            .get("branch")
            .filter(|value| value.is_string())
        {
            source_control.insert("default_branch".to_string(), value.clone());
        }
    }
    source_control
}

fn drone_source_branch(
    source_control: &Map<String, Value>,
    provider_config: &Map<String, Value>,
) -> Option<String> {
    string_from_map(provider_config, "branch")
        .or_else(|| string_from_map(source_control, "default_branch"))
        .filter(|branch| is_safe_git_branch(branch))
}

fn host_code_root_from_workspace(workspace_metadata: &Value) -> Option<String> {
    metadata_string_from_path(workspace_metadata, &["host_code_root"]).or_else(|| {
        metadata_string_from_path(workspace_metadata, &["code_context", "host_code_root"])
    })
}

fn is_safe_git_branch(value: &str) -> bool {
    let value = value.trim();
    if value.is_empty()
        || value.starts_with('-')
        || value.starts_with('/')
        || value.ends_with('/')
        || value.contains("..")
        || value.contains("//")
        || value.contains("@{")
        || value.contains('\\')
    {
        return false;
    }
    value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '/' | '-'))
}

fn pipeline_contract_commit_ref(provider_config: &Map<String, Value>) -> Option<String> {
    string_from_map(provider_config, "commit").and_then(|value| commit_ref_token(&value))
}

fn source_control_remote_url(source_control: &Map<String, Value>) -> Option<String> {
    if let Some(remote_url) = string_from_map(source_control, "clone_url") {
        return Some(remote_url);
    }
    let repo = string_from_map(source_control, "repo")?;
    let provider = string_from_map(source_control, "provider")
        .unwrap_or_else(|| "github".to_string())
        .to_ascii_lowercase();
    let server_url = string_from_map(source_control, "server_url");
    let base_url = if provider == "gitlab" {
        server_url.unwrap_or_else(|| "https://gitlab.com".to_string())
    } else {
        server_url.unwrap_or_else(|| "https://github.com".to_string())
    };
    let suffix = if repo.ends_with(".git") { "" } else { ".git" };
    Some(format!("{}/{repo}{suffix}", base_url.trim_end_matches('/')))
}

fn source_control_token_env(source_control: &Map<String, Value>) -> Option<String> {
    if let Some(configured) = string_from_map(source_control, "auth_token_env") {
        return Some(configured);
    }
    let provider = string_from_map(source_control, "provider")
        .unwrap_or_else(|| "github".to_string())
        .to_ascii_lowercase();
    Some(if provider == "gitlab" {
        "GITLAB_TOKEN".to_string()
    } else {
        "GITHUB_TOKEN".to_string()
    })
}

fn source_control_token(token_env: Option<&str>) -> Option<String> {
    let token_env = token_env?;
    std::env::var(token_env)
        .ok()
        .and_then(|value| metadata_string(Some(&Value::String(value))))
        .or_else(|| source_publish_dotenv_value(token_env))
}

fn source_publish_dotenv_value(token_env: &str) -> Option<String> {
    let path = std::env::var("MEMSTACK_DRONE_DOTENV_PATH").unwrap_or_else(|_| ".env".to_string());
    let content = std::fs::read_to_string(path).ok()?;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let Some((key, value)) = trimmed.split_once('=') else {
            continue;
        };
        if key.trim() == token_env {
            let value = value.trim().trim_matches('"').trim_matches('\'');
            if !value.is_empty() {
                return Some(value.to_string());
            }
        }
    }
    None
}

fn apply_drone_provider_config(
    contract: &mut PipelineContractFoundation,
    provider_config: Map<String, Value>,
) {
    contract.provider_config_json = Value::Object(provider_config.clone());
    let mut metadata = object_or_empty(contract.metadata_json.clone());
    metadata.insert(
        "provider_config".to_string(),
        Value::Object(provider_config),
    );
    contract.metadata_json = Value::Object(metadata);
}

async fn publish_git_ref_to_source_control(
    host_code_root: &Path,
    commit_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    token_env: Option<&str>,
    token: Option<&str>,
) -> CoreResult<GitPublishResult> {
    if !host_code_root.exists() {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(format!(
                "host_code_root does not exist: {}",
                host_code_root.display()
            )),
            published_commit: None,
        });
    }
    if !is_safe_git_branch(branch) {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some("unsafe git branch name".to_string()),
            published_commit: None,
        });
    }

    let mut env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    let askpass_path = if let Some(token) = token {
        let path = create_git_askpass_script()?;
        env.push((
            "GIT_ASKPASS".to_string(),
            path.to_string_lossy().to_string(),
        ));
        env.push(("GIT_TOKEN".to_string(), token.to_string()));
        env.push((
            "GIT_USERNAME".to_string(),
            if token_env == Some("GITLAB_TOKEN") {
                "oauth2".to_string()
            } else {
                "x-access-token".to_string()
            },
        ));
        Some(path)
    } else {
        None
    };

    let result = publish_git_ref_to_source_control_with_env(
        host_code_root,
        commit_ref,
        branch,
        remote_url,
        &env,
    )
    .await;
    if let Some(path) = askpass_path {
        let _ = std::fs::remove_file(path);
    }
    result
}

async fn publish_git_ref_to_source_control_with_env(
    host_code_root: &Path,
    commit_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
) -> CoreResult<GitPublishResult> {
    let exists = run_git_command(
        host_code_root,
        &["cat-file", "-e", &format!("{commit_ref}^{{commit}}")],
        env,
        60,
    )
    .await?;
    if exists.exit_code != 0 {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&exists)),
            published_commit: None,
        });
    }

    let dirty = run_git_command(host_code_root, &["status", "--porcelain"], env, 60).await?;
    if !dirty.stdout.trim().is_empty() {
        return publish_git_ref_from_temporary_worktree(
            host_code_root,
            commit_ref,
            branch,
            remote_url,
            env,
            "published from temporary worktree because main checkout has uncommitted changes",
        )
        .await;
    }

    let already_ancestor = run_git_command(
        host_code_root,
        &["merge-base", "--is-ancestor", commit_ref, "HEAD"],
        env,
        60,
    )
    .await?;
    if already_ancestor.exit_code != 0 {
        let fast_forward = run_git_command(
            host_code_root,
            &["merge", "--ff-only", commit_ref],
            env,
            120,
        )
        .await?;
        if fast_forward.exit_code != 0 {
            if is_non_fast_forward_push_rejection(&fast_forward)
                || is_unrelated_history_merge_rejection(&fast_forward)
            {
                return publish_git_ref_from_temporary_worktree(
                    host_code_root,
                    commit_ref,
                    branch,
                    remote_url,
                    env,
                    "published from temporary worktree after local branch could not fast-forward to candidate",
                )
                .await;
            }
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&fast_forward)),
                published_commit: None,
            });
        }
    }

    let head = run_git_command(host_code_root, &["rev-parse", "HEAD"], env, 60).await?;
    if head.exit_code != 0 {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&head)),
            published_commit: None,
        });
    }
    let published_commit = head.stdout.trim().to_string();
    push_git_head_to_source_branch(host_code_root, &published_commit, branch, remote_url, env).await
}

async fn push_git_head_to_source_branch(
    host_code_root: &Path,
    published_commit: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
) -> CoreResult<GitPublishResult> {
    let remote = remote_url.unwrap_or("origin");
    let refspec = format!("HEAD:refs/heads/{branch}");
    let push = run_git_command(host_code_root, &["push", remote, &refspec], env, 180).await?;
    if push.exit_code == 0 {
        return Ok(GitPublishResult {
            status: "published".to_string(),
            reason: None,
            published_commit: Some(published_commit.to_string()),
        });
    }
    if is_non_fast_forward_push_rejection(&push) {
        return publish_git_ref_from_temporary_worktree(
            host_code_root,
            published_commit,
            branch,
            remote_url,
            env,
            "published from temporary worktree after remote branch advanced",
        )
        .await;
    }
    Ok(GitPublishResult {
        status: "failed".to_string(),
        reason: Some(compact_git_error(&push)),
        published_commit: Some(published_commit.to_string()),
    })
}

async fn publish_git_ref_from_temporary_worktree(
    host_code_root: &Path,
    publish_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
    default_reason: &str,
) -> CoreResult<GitPublishResult> {
    let temp_parent =
        std::env::temp_dir().join(format!("memstack-source-publish-{}", generate_uuid_v4()));
    let worktree_path = temp_parent.join("worktree");
    std::fs::create_dir_all(&temp_parent).map_err(|err| {
        CoreError::Storage(format!(
            "failed to create source publish temp dir {}: {err}",
            temp_parent.display()
        ))
    })?;
    let mut added = false;
    let result = async {
        let worktree_path_string = worktree_path.to_string_lossy().to_string();
        let add = run_git_command(
            host_code_root,
            &[
                "worktree",
                "add",
                "--detach",
                &worktree_path_string,
                publish_ref,
            ],
            env,
            120,
        )
        .await?;
        if add.exit_code != 0 {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&add)),
                published_commit: None,
            });
        }
        added = true;
        let remote = remote_url.unwrap_or("origin");
        let remote_merge =
            merge_remote_branch_for_publish(&worktree_path, publish_ref, remote, branch, env)
                .await?;
        if remote_merge.status == "failed" {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(
                    remote_merge
                        .reason
                        .unwrap_or_else(|| "remote branch merge failed".to_string()),
                ),
                published_commit: None,
            });
        }
        let head = run_git_command(&worktree_path, &["rev-parse", "HEAD"], env, 60).await?;
        if head.exit_code != 0 {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&head)),
                published_commit: None,
            });
        }
        let published_commit = head.stdout.trim().to_string();
        let refspec = format!("HEAD:refs/heads/{branch}");
        let push = run_git_command(&worktree_path, &["push", remote, &refspec], env, 180).await?;
        if push.exit_code != 0 {
            if is_non_fast_forward_push_rejection(&push) {
                if let Some(retried) = retry_temporary_worktree_push_after_non_fast_forward(
                    &worktree_path,
                    &published_commit,
                    remote,
                    branch,
                    env,
                    default_reason,
                )
                .await?
                {
                    return Ok(retried);
                }
            }
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&push)),
                published_commit: Some(published_commit),
            });
        }
        Ok(GitPublishResult {
            status: "published".to_string(),
            reason: Some(
                remote_merge
                    .reason
                    .unwrap_or_else(|| default_reason.to_string()),
            ),
            published_commit: Some(published_commit),
        })
    }
    .await;

    if added {
        let worktree_path_string = worktree_path.to_string_lossy().to_string();
        let _ = run_git_command(
            host_code_root,
            &["worktree", "remove", "--force", &worktree_path_string],
            env,
            120,
        )
        .await;
    }
    let _ = std::fs::remove_dir_all(&temp_parent);
    result
}

async fn retry_temporary_worktree_push_after_non_fast_forward(
    worktree_path: &Path,
    candidate_ref: &str,
    remote: &str,
    branch: &str,
    env: &[(String, String)],
    default_reason: &str,
) -> CoreResult<Option<GitPublishResult>> {
    let retry_merge =
        merge_remote_branch_for_publish(worktree_path, candidate_ref, remote, branch, env).await?;
    if retry_merge.status == "failed" {
        return Ok(Some(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(
                retry_merge.reason.unwrap_or_else(|| {
                    "remote branch merge failed after push rejection".to_string()
                }),
            ),
            published_commit: Some(candidate_ref.to_string()),
        }));
    }
    let retry_head = run_git_command(worktree_path, &["rev-parse", "HEAD"], env, 60).await?;
    if retry_head.exit_code != 0 {
        return Ok(Some(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&retry_head)),
            published_commit: Some(candidate_ref.to_string()),
        }));
    }
    let retried_commit = retry_head.stdout.trim().to_string();
    let refspec = format!("HEAD:refs/heads/{branch}");
    let retry_push = run_git_command(worktree_path, &["push", remote, &refspec], env, 180).await?;
    if retry_push.exit_code == 0 {
        let retry_reason = retry_merge
            .reason
            .unwrap_or_else(|| default_reason.to_string());
        return Ok(Some(GitPublishResult {
            status: "published".to_string(),
            reason: Some(format!(
                "{retry_reason}; retried after non-fast-forward push"
            )),
            published_commit: Some(retried_commit),
        }));
    }
    Ok(None)
}

async fn merge_remote_branch_for_publish(
    worktree_path: &Path,
    candidate_ref: &str,
    remote: &str,
    branch: &str,
    env: &[(String, String)],
) -> CoreResult<GitRemoteMergeResult> {
    let remote_ref = format!("refs/remotes/memstack-source-publish/{branch}");
    let fetch_refspec = format!("+refs/heads/{branch}:{remote_ref}");
    let fetch = run_git_command(
        worktree_path,
        &["fetch", "--no-tags", remote, &fetch_refspec],
        env,
        180,
    )
    .await?;
    if fetch.exit_code != 0 {
        let reason = compact_git_error(&fetch);
        let normalized = reason.to_ascii_lowercase();
        if normalized.contains("couldn't find remote ref")
            || normalized.contains("could not find remote ref")
        {
            return Ok(GitRemoteMergeResult {
                status: "skipped".to_string(),
                reason: None,
            });
        }
        return Ok(GitRemoteMergeResult {
            status: "failed".to_string(),
            reason: Some(reason),
        });
    }

    let remote_ancestor = run_git_command(
        worktree_path,
        &["merge-base", "--is-ancestor", &remote_ref, "HEAD"],
        env,
        60,
    )
    .await?;
    if remote_ancestor.exit_code == 0 {
        return Ok(GitRemoteMergeResult {
            status: "skipped".to_string(),
            reason: None,
        });
    }

    let local_ancestor = run_git_command(
        worktree_path,
        &["merge-base", "--is-ancestor", "HEAD", &remote_ref],
        env,
        60,
    )
    .await?;
    if local_ancestor.exit_code == 0 {
        return merge_remote_branch_preserving_local_tree(worktree_path, &remote_ref, env).await;
    }

    let merge = run_git_command(
        worktree_path,
        &["merge", "--no-edit", &remote_ref],
        env,
        120,
    )
    .await?;
    if merge.exit_code == 0 {
        return restore_candidate_publish_paths_after_merge(
            worktree_path,
            candidate_ref,
            &remote_ref,
            env,
            "merged remote branch before publish",
        )
        .await;
    }

    let _ = run_git_command(worktree_path, &["merge", "--abort"], env, 60).await;
    let merged = merge_remote_branch_with_local_preference(worktree_path, &remote_ref, env).await?;
    if merged.status == "failed" {
        return Ok(merged);
    }
    let reason = merged
        .reason
        .clone()
        .unwrap_or_else(|| "merged remote branch before publish".to_string());
    restore_candidate_publish_paths_after_merge(
        worktree_path,
        candidate_ref,
        &remote_ref,
        env,
        &reason,
    )
    .await
}

async fn merge_remote_branch_preserving_local_tree(
    worktree_path: &Path,
    remote_ref: &str,
    env: &[(String, String)],
) -> CoreResult<GitRemoteMergeResult> {
    let merge_ours_strategy = run_git_command(
        worktree_path,
        &["merge", "--no-edit", "-s", "ours", remote_ref],
        env,
        120,
    )
    .await?;
    if merge_ours_strategy.exit_code == 0 {
        return Ok(GitRemoteMergeResult {
            status: "merged".to_string(),
            reason: Some(
                "merged remote branch history before publish preserving candidate tree".to_string(),
            ),
        });
    }
    Ok(GitRemoteMergeResult {
        status: "failed".to_string(),
        reason: Some(compact_git_error(&merge_ours_strategy)),
    })
}

async fn restore_candidate_publish_paths_after_merge(
    worktree_path: &Path,
    candidate_ref: &str,
    remote_ref: &str,
    env: &[(String, String)],
    reason: &str,
) -> CoreResult<GitRemoteMergeResult> {
    let paths =
        candidate_publish_restore_path_states(worktree_path, candidate_ref, remote_ref, env)
            .await?;
    if paths.is_empty() {
        return Ok(GitRemoteMergeResult {
            status: "merged".to_string(),
            reason: Some(reason.to_string()),
        });
    }

    let present_paths: Vec<String> = paths
        .iter()
        .filter_map(|(path, present)| present.then_some(path.clone()))
        .collect();
    let removed_paths: Vec<String> = paths
        .iter()
        .filter_map(|(path, present)| (!present).then_some(path.clone()))
        .collect();
    if !present_paths.is_empty() {
        let mut args = vec![
            "checkout".to_string(),
            candidate_ref.to_string(),
            "--".to_string(),
        ];
        args.extend(present_paths);
        let checkout = run_git_command_owned(worktree_path, args, env, 120).await?;
        if checkout.exit_code != 0 {
            return Ok(GitRemoteMergeResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&checkout)),
            });
        }
    }
    if !removed_paths.is_empty() {
        let mut args = vec![
            "rm".to_string(),
            "-f".to_string(),
            "--ignore-unmatch".to_string(),
            "--".to_string(),
        ];
        args.extend(removed_paths);
        let remove = run_git_command_owned(worktree_path, args, env, 120).await?;
        if remove.exit_code != 0 {
            return Ok(GitRemoteMergeResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&remove)),
            });
        }
    }

    let mut diff_args = vec![
        "diff".to_string(),
        "--cached".to_string(),
        "--quiet".to_string(),
        "--".to_string(),
    ];
    diff_args.extend(paths.iter().map(|(path, _)| path.clone()));
    let changed = run_git_command_owned(worktree_path, diff_args, env, 60).await?;
    if changed.exit_code == 0 {
        return Ok(GitRemoteMergeResult {
            status: "merged".to_string(),
            reason: Some(reason.to_string()),
        });
    }
    if changed.exit_code != 1 {
        return Ok(GitRemoteMergeResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&changed)),
        });
    }

    let commit = run_git_command(
        worktree_path,
        &["commit", "-m", "Preserve candidate source publish paths"],
        env,
        120,
    )
    .await?;
    if commit.exit_code != 0 {
        return Ok(GitRemoteMergeResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&commit)),
        });
    }
    Ok(GitRemoteMergeResult {
        status: "merged".to_string(),
        reason: Some(format!(
            "{reason}; restored candidate tree paths after merge"
        )),
    })
}

async fn candidate_publish_restore_path_states(
    worktree_path: &Path,
    candidate_ref: &str,
    remote_ref: &str,
    env: &[(String, String)],
) -> CoreResult<Vec<(String, bool)>> {
    candidate_publish_path_states(worktree_path, candidate_ref, remote_ref, env).await
}

async fn candidate_publish_path_states(
    worktree_path: &Path,
    candidate_ref: &str,
    remote_ref: &str,
    env: &[(String, String)],
) -> CoreResult<Vec<(String, bool)>> {
    let base = run_git_command(
        worktree_path,
        &["merge-base", candidate_ref, remote_ref],
        env,
        60,
    )
    .await?;
    if base.exit_code != 0 {
        return Ok(Vec::new());
    }
    let base_ref = base.stdout.trim().to_string();
    if base_ref.is_empty() {
        return Ok(Vec::new());
    }
    let diff = run_git_command(
        worktree_path,
        &["diff", "--name-status", "-z", &base_ref, candidate_ref],
        env,
        60,
    )
    .await?;
    if diff.exit_code != 0 {
        return Ok(Vec::new());
    }
    Ok(parse_git_name_status_path_states(&diff.stdout))
}

fn parse_git_name_status_path_states(raw: &str) -> Vec<(String, bool)> {
    let parts: Vec<&str> = raw.split('\0').filter(|part| !part.is_empty()).collect();
    let mut paths = Vec::new();
    let mut index = 0usize;
    while index < parts.len() {
        let status = parts[index];
        index += 1;
        let Some(code) = status.chars().next() else {
            continue;
        };
        if matches!(code, 'R' | 'C') {
            if index + 1 >= parts.len() {
                break;
            }
            let old_path = parts[index];
            let new_path = parts[index + 1];
            index += 2;
            if code == 'R' && !old_path.is_empty() {
                set_path_state(&mut paths, old_path.to_string(), false);
            }
            if !new_path.is_empty() {
                set_path_state(&mut paths, new_path.to_string(), true);
            }
            continue;
        }
        if index >= parts.len() {
            break;
        }
        let path = parts[index];
        index += 1;
        if !path.is_empty() {
            set_path_state(&mut paths, path.to_string(), code != 'D');
        }
    }
    paths
}

fn set_path_state(paths: &mut Vec<(String, bool)>, path: String, present: bool) {
    if let Some((_, existing_present)) = paths
        .iter_mut()
        .find(|(existing_path, _)| existing_path == &path)
    {
        *existing_present = present;
    } else {
        paths.push((path, present));
    }
}

async fn merge_remote_branch_with_local_preference(
    worktree_path: &Path,
    remote_ref: &str,
    env: &[(String, String)],
) -> CoreResult<GitRemoteMergeResult> {
    let merge_ours = run_git_command(
        worktree_path,
        &["merge", "--no-edit", "-X", "ours", remote_ref],
        env,
        120,
    )
    .await?;
    if merge_ours.exit_code == 0 {
        return Ok(GitRemoteMergeResult {
            status: "merged".to_string(),
            reason: Some(
                "merged remote branch before publish using local conflict preference".to_string(),
            ),
        });
    }
    if is_unrelated_history_merge_rejection(&merge_ours) {
        let _ = run_git_command(worktree_path, &["merge", "--abort"], env, 60).await;
        let merge_unrelated_ours = run_git_command(
            worktree_path,
            &[
                "merge",
                "--no-edit",
                "--allow-unrelated-histories",
                "-X",
                "ours",
                remote_ref,
            ],
            env,
            120,
        )
        .await?;
        if merge_unrelated_ours.exit_code == 0 {
            return Ok(GitRemoteMergeResult {
                status: "merged".to_string(),
                reason: Some(
                    "merged unrelated remote branch before publish using local conflict preference"
                        .to_string(),
                ),
            });
        }
        return Ok(GitRemoteMergeResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&merge_unrelated_ours)),
        });
    }
    Ok(GitRemoteMergeResult {
        status: "failed".to_string(),
        reason: Some(compact_git_error(&merge_ours)),
    })
}

async fn run_git_command_owned(
    cwd: &Path,
    args: Vec<String>,
    env: &[(String, String)],
    timeout_seconds: u64,
) -> CoreResult<GitCommandOutput> {
    let arg_refs: Vec<&str> = args.iter().map(String::as_str).collect();
    run_git_command(cwd, &arg_refs, env, timeout_seconds).await
}

async fn run_git_command(
    cwd: &Path,
    args: &[&str],
    env: &[(String, String)],
    timeout_seconds: u64,
) -> CoreResult<GitCommandOutput> {
    let mut command = tokio::process::Command::new("git");
    command
        .args(args)
        .current_dir(cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    let output = tokio::time::timeout(Duration::from_secs(timeout_seconds), command.output())
        .await
        .map_err(|_| {
            CoreError::Storage(format!(
                "git {} timed out after {timeout_seconds}s",
                args.join(" ")
            ))
        })?
        .map_err(|err| {
            CoreError::Storage(format!("git {} failed to start: {err}", args.join(" ")))
        })?;
    Ok(GitCommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

async fn run_git_command_with_stdin(
    cwd: &Path,
    args: &[&str],
    env: &[(String, String)],
    timeout_seconds: u64,
    stdin_text: &str,
) -> CoreResult<GitCommandOutput> {
    let mut command = tokio::process::Command::new("git");
    command
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    let mut child = command.spawn().map_err(|err| {
        CoreError::Storage(format!("git {} failed to start: {err}", args.join(" ")))
    })?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(stdin_text.as_bytes())
            .await
            .map_err(|err| {
                CoreError::Storage(format!("git {} stdin failed: {err}", args.join(" ")))
            })?;
    }
    let output = tokio::time::timeout(
        Duration::from_secs(timeout_seconds),
        child.wait_with_output(),
    )
    .await
    .map_err(|_| {
        CoreError::Storage(format!(
            "git {} timed out after {timeout_seconds}s",
            args.join(" ")
        ))
    })?
    .map_err(|err| CoreError::Storage(format!("git {} failed: {err}", args.join(" "))))?;
    Ok(GitCommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

async fn integrate_accepted_attempt_worktree_with_git(
    sandbox_code_root: &Path,
    worktree_path: &Path,
    commit_ref: &str,
) -> CoreResult<AcceptedWorktreeIntegrationResult> {
    let env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    if !sandbox_code_root.exists() {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: format!(
                "sandbox_code_root does not exist: {}",
                sandbox_code_root.display()
            ),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    }
    if !worktree_path.exists() {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: format!(
                "accepted worktree does not exist: {}",
                worktree_path.display()
            ),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    }

    let resolved_commit = resolve_accepted_worktree_commit(worktree_path, commit_ref, &env).await?;
    let Some(resolved_commit) = resolved_commit else {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: "status=failed\nreason=commit_ref not found in attempt worktree".to_string(),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    };

    let already_merged = run_git_command(
        sandbox_code_root,
        &["merge-base", "--is-ancestor", &resolved_commit, "HEAD"],
        &env,
        60,
    )
    .await?;
    if already_merged.exit_code == 0 {
        let git_head = short_git_head(sandbox_code_root, &env).await?;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "already_merged".to_string(),
            summary: format!(
                "resolved_commit_ref={resolved_commit}\nstatus=already_merged\ngit_head={git_head}"
            ),
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }

    let dirty = run_git_command(sandbox_code_root, &["status", "--porcelain"], &env, 60).await?;
    if dirty.exit_code != 0 {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: compact_git_error(&dirty),
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }
    if !dirty.stdout.trim().is_empty() {
        let signature = git_blob_hash(sandbox_code_root, &dirty.stdout, &env).await?;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "blocked_dirty_main".to_string(),
            summary: compact_text(
                &format!(
                    "status=blocked_dirty_main\nreason=sandbox_code_root has uncommitted changes\ndirty_signature={}\n{}",
                    signature,
                    dirty.stdout.trim()
                ),
                1200,
            ),
            commit_ref: resolved_commit,
            dirty_signature: Some(signature),
        });
    }

    let merge = run_git_command(
        sandbox_code_root,
        &["merge", "--no-edit", &resolved_commit],
        &env,
        120,
    )
    .await?;
    let merge = if merge.exit_code != 0 && is_unrelated_history_merge_rejection(&merge) {
        let _ = run_git_command(sandbox_code_root, &["merge", "--abort"], &env, 60).await;
        run_git_command(
            sandbox_code_root,
            &[
                "merge",
                "--no-edit",
                "--allow-unrelated-histories",
                "-X",
                "theirs",
                &resolved_commit,
            ],
            &env,
            120,
        )
        .await?
    } else {
        merge
    };
    if merge.exit_code != 0 {
        let summary = compact_text(
            &format!(
                "{}\nstatus=failed\nreason=merge_failed_aborted",
                compact_git_error(&merge)
            ),
            1200,
        );
        let _ = run_git_command(sandbox_code_root, &["merge", "--abort"], &env, 60).await;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary,
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }

    let git_head = short_git_head(sandbox_code_root, &env).await?;
    Ok(AcceptedWorktreeIntegrationResult {
        status: "merged".to_string(),
        summary: compact_text(
            &format!(
                "resolved_commit_ref={resolved_commit}\n{}\nstatus=merged\ngit_head={git_head}",
                merge.stdout.trim()
            ),
            1200,
        ),
        commit_ref: resolved_commit,
        dirty_signature: None,
    })
}

async fn resolve_accepted_worktree_commit(
    worktree_path: &Path,
    commit_ref: &str,
    env: &[(String, String)],
) -> CoreResult<Option<String>> {
    let exists = run_git_command(
        worktree_path,
        &["cat-file", "-e", &format!("{commit_ref}^{{commit}}")],
        env,
        60,
    )
    .await?;
    if exists.exit_code == 0 {
        let resolved = run_git_command(
            worktree_path,
            &["rev-parse", &format!("{commit_ref}^{{commit}}")],
            env,
            60,
        )
        .await?;
        if resolved.exit_code == 0 {
            return Ok(Some(resolved.stdout.trim().to_string()));
        }
    }
    let short_commit = commit_ref.chars().take(12).collect::<String>();
    let repaired = run_git_command(
        worktree_path,
        &[
            "rev-parse",
            "--verify",
            "--quiet",
            &format!("{short_commit}^{{commit}}"),
        ],
        env,
        60,
    )
    .await?;
    if repaired.exit_code == 0 {
        let value = repaired.stdout.trim();
        if !value.is_empty() {
            return Ok(Some(value.to_string()));
        }
    }
    Ok(None)
}

async fn short_git_head(cwd: &Path, env: &[(String, String)]) -> CoreResult<String> {
    let head = run_git_command(cwd, &["rev-parse", "--short", "HEAD"], env, 60).await?;
    if head.exit_code == 0 {
        Ok(head.stdout.trim().to_string())
    } else {
        Ok("unknown".to_string())
    }
}

async fn git_blob_hash(cwd: &Path, text: &str, env: &[(String, String)]) -> CoreResult<String> {
    let hash = run_git_command_with_stdin(cwd, &["hash-object", "--stdin"], env, 60, text).await?;
    if hash.exit_code == 0 {
        Ok(hash.stdout.trim().to_string())
    } else {
        Ok(format!("git_hash_failed:{}", compact_git_error(&hash)))
    }
}

async fn current_worktree_dirty_signature(cwd: &Path) -> CoreResult<Option<String>> {
    if !cwd.exists() {
        return Ok(None);
    }
    let env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    let dirty = run_git_command(cwd, &["status", "--porcelain"], &env, 60).await?;
    if dirty.exit_code != 0 || dirty.stdout.trim().is_empty() {
        return Ok(None);
    }
    git_blob_hash(cwd, &dirty.stdout, &env).await.map(Some)
}

fn create_git_askpass_script() -> CoreResult<PathBuf> {
    let path = std::env::temp_dir().join(format!("memstack-git-askpass-{}.sh", generate_uuid_v4()));
    std::fs::write(
        &path,
        "#!/bin/sh\ncase \"$1\" in\n*Username*) printf '%s\\n' \"${GIT_USERNAME:-x-access-token}\" ;;\n*) printf '%s\\n' \"$GIT_TOKEN\" ;;\nesac\n",
    )
    .map_err(|err| {
        CoreError::Storage(format!(
            "failed to write git askpass script {}: {err}",
            path.display()
        ))
    })?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = std::fs::metadata(&path)
            .map_err(|err| {
                CoreError::Storage(format!(
                    "failed to stat git askpass script {}: {err}",
                    path.display()
                ))
            })?
            .permissions();
        permissions.set_mode(0o700);
        std::fs::set_permissions(&path, permissions).map_err(|err| {
            CoreError::Storage(format!(
                "failed to chmod git askpass script {}: {err}",
                path.display()
            ))
        })?;
    }
    Ok(path)
}

fn compact_git_error(result: &GitCommandOutput) -> String {
    let text = if result.stderr.trim().is_empty() {
        result.stdout.trim()
    } else {
        result.stderr.trim()
    };
    if text.is_empty() {
        return format!("git exited with {}", result.exit_code);
    }
    compact_text(text, 1200)
}

fn is_non_fast_forward_push_rejection(result: &GitCommandOutput) -> bool {
    let text = format!("{}\n{}", result.stdout, result.stderr).to_ascii_lowercase();
    text.contains("non-fast-forward")
        || text.contains("fetch first")
        || text.contains("updates were rejected")
        || text.contains("tip of your current branch is behind")
        || text.contains("not possible to fast-forward")
}

fn is_unrelated_history_merge_rejection(result: &GitCommandOutput) -> bool {
    let text = format!("{}\n{}", result.stdout, result.stderr);
    text.to_ascii_lowercase()
        .contains("refusing to merge unrelated histories")
        || text.contains("拒绝合并无关的历史")
}

fn pipeline_stage_specs_from_json(
    commands_json: &Value,
    default_timeout: i32,
) -> Vec<PipelineStageSpec> {
    commands_json
        .as_array()
        .map(|stages| {
            stages
                .iter()
                .filter_map(|stage| {
                    let map = stage.as_object()?;
                    let stage_name =
                        string_from_map(map, "stage").or_else(|| string_from_map(map, "id"))?;
                    let command = string_from_map(map, "command")?;
                    Some(PipelineStageSpec {
                        stage: stage_name,
                        command,
                        required: bool_from_map_default(map, "required", true),
                        timeout_seconds: positive_i32_from_map(
                            map,
                            "timeout_seconds",
                            default_timeout,
                        ),
                        service_id: string_from_map(map, "service_id"),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

fn wrapped_pipeline_command(command: &str, code_root: Option<&str>, env_json: &Value) -> String {
    let mut lines = vec!["set +e".to_string()];
    if let Some(code_root) = code_root.filter(|value| !value.trim().is_empty()) {
        let quoted = shell_quote(code_root);
        lines.push(format!("cd {quoted}"));
        lines.push("code=$?".to_string());
        lines.push("if [ \"$code\" -ne 0 ]; then".to_string());
        lines.push(format!(
            "  printf 'workspace pipeline code_root is not accessible: %s\\n' {quoted} >&2"
        ));
        lines.push(format!(
            "  printf \"\\n{PIPELINE_EXIT_MARKER}%s\\n\" \"$code\""
        ));
        lines.push("  exit 0".to_string());
        lines.push("fi".to_string());
    }
    for (key, value) in sorted_pipeline_env(env_json) {
        lines.push(format!("export {key}={}", shell_quote(&value)));
    }
    lines.push("(".to_string());
    lines.push(command.to_string());
    lines.push(")".to_string());
    lines.push("code=$?".to_string());
    lines.push(format!(
        "printf \"\\n{PIPELINE_EXIT_MARKER}%s\\n\" \"$code\""
    ));
    lines.push("exit 0".to_string());
    lines.join("\n")
}

fn sorted_pipeline_env(env_json: &Value) -> Vec<(String, String)> {
    let mut values = env_json
        .as_object()
        .into_iter()
        .flat_map(|env| env.iter())
        .filter_map(|(key, value)| {
            if key
                .replace('_', "")
                .chars()
                .all(|ch| ch.is_ascii_alphanumeric())
            {
                value.as_str().map(|value| (key.clone(), value.to_string()))
            } else {
                None
            }
        })
        .collect::<Vec<_>>();
    values.sort_by(|left, right| left.0.cmp(&right.0));
    values
}

fn shell_quote(value: &str) -> String {
    if value.is_empty() {
        return "''".to_string();
    }
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn pipeline_stage_result_from_tool_response(
    stage: &PipelineStageSpec,
    response: ExecuteToolResponse,
    duration_ms: i32,
) -> PipelineStageResult {
    let text = tool_response_text(&response);
    let stdout = if response.is_error {
        String::new()
    } else {
        text.clone()
    };
    let stderr = if response.is_error {
        text.clone()
    } else {
        String::new()
    };
    let combined = format!("{stdout}\n{stderr}").trim().to_string();
    let exit_code =
        exit_code_from_pipeline_output(&combined).unwrap_or(if response.is_error { 1 } else { 0 });
    let cleaned = strip_pipeline_exit_markers(&combined);
    let status = if exit_code == 0 { "success" } else { "failed" }.to_string();
    let log_ref = format!(
        "sandbox://pipeline/{}/{}.log",
        generate_uuid_v4(),
        stage.stage
    );
    PipelineStageResult {
        stage: stage.stage.clone(),
        status,
        command: stage.command.clone(),
        exit_code: Some(exit_code),
        stdout_preview: compact_text(&cleaned, 4_000),
        stderr_preview: if exit_code == 0 {
            String::new()
        } else {
            compact_text(&stderr, 4_000)
        },
        duration_ms,
        log_ref: Some(log_ref.clone()),
        artifact_refs: vec![format!("pipeline_log:{}:{log_ref}", stage.stage)],
        service_id: stage.service_id.clone(),
        required: stage.required,
    }
}

fn tool_response_text(response: &ExecuteToolResponse) -> String {
    response
        .content
        .iter()
        .filter_map(|item| {
            item.get("text")
                .and_then(Value::as_str)
                .or_else(|| item.as_str())
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn exit_code_from_pipeline_output(output: &str) -> Option<i32> {
    let start = output.find(PIPELINE_EXIT_MARKER)? + PIPELINE_EXIT_MARKER.len();
    let digits = output[start..]
        .chars()
        .take_while(|ch| ch.is_ascii_digit())
        .collect::<String>();
    digits.parse().ok()
}

fn strip_pipeline_exit_markers(output: &str) -> String {
    output
        .lines()
        .filter(|line| !line.contains(PIPELINE_EXIT_MARKER))
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string()
}

fn compact_text(value: &str, limit: usize) -> String {
    let compacted = value.trim();
    if compacted.len() <= limit {
        return compacted.to_string();
    }
    let prefix = compacted
        .chars()
        .take(limit.saturating_sub(15))
        .collect::<String>();
    format!("{prefix}...[truncated]")
}

fn saturating_duration_ms(duration_ms: u128) -> i32 {
    i32::try_from(duration_ms).unwrap_or(i32::MAX)
}

fn pipeline_contract_foundation(workspace: &WorkspaceRecord) -> PipelineContractFoundation {
    let workspace_metadata = object_or_empty(workspace.metadata_json.clone());
    let delivery = workspace_metadata
        .get("delivery_cicd")
        .cloned()
        .map(object_or_empty)
        .unwrap_or_default();
    let provider = normalize_pipeline_provider(
        string_from_map(&delivery, "provider")
            .unwrap_or_else(|| SANDBOX_NATIVE_PROVIDER.to_string())
            .as_str(),
    );
    let timeout_seconds = positive_i32_from_map(
        &delivery,
        "timeout_seconds",
        DEFAULT_PIPELINE_TIMEOUT_SECONDS,
    );
    let auto_deploy = bool_from_map_default(&delivery, "auto_deploy", true);
    let preview_port = Some(positive_i32_from_map(
        &delivery,
        "preview_port",
        DEFAULT_PREVIEW_PORT,
    ));
    let health_url = string_from_map(&delivery, "health_url");
    let deploy_command = string_from_map(&delivery, "deploy_command");
    let agent_managed = bool_from_map_default(&delivery, "agent_managed", true);
    let contract_source = string_from_map(&delivery, "contract_source").unwrap_or_else(|| {
        if delivery.get("agent_proposal").is_some_and(Value::is_object) {
            "agent_proposal".to_string()
        } else {
            "metadata".to_string()
        }
    });
    let contract_confidence = delivery
        .get("contract_confidence")
        .and_then(Value::as_f64)
        .filter(|value| (0.0..=1.0).contains(value))
        .unwrap_or(1.0);
    let host_code_root = host_code_root_from_workspace(&workspace.metadata_json);
    let code_root = string_from_map(&delivery, "code_root")
        .or_else(|| string_from_map(&workspace_metadata, "sandbox_code_root"))
        .or_else(|| {
            workspace_metadata
                .get("code_context")
                .and_then(Value::as_object)
                .and_then(|code_context| string_from_map(code_context, "sandbox_code_root"))
        });
    let commands_json = pipeline_stage_specs_json(&delivery, timeout_seconds);
    let env_json = string_map_json(delivery.get("env"));
    let services_json = delivery
        .get("services")
        .filter(|value| value.is_array())
        .cloned()
        .unwrap_or_else(|| json!([]));
    let provider_config = pipeline_provider_config_json(&delivery, &provider);
    let metadata_json = json!({
        "source": "workspace_plan.pipeline_run_requested",
        "agent_managed": agent_managed,
        "contract_source": contract_source,
        "contract_confidence": contract_confidence,
        "services": services_json.clone(),
        "provider_config": provider_config.clone()
    });
    PipelineContractFoundation {
        provider,
        host_code_root,
        code_root,
        commands_json,
        env_json,
        timeout_seconds,
        auto_deploy,
        preview_port,
        health_url,
        services_json,
        deploy_command,
        agent_managed,
        contract_source,
        provider_config_json: provider_config,
        metadata_json,
    }
}

fn normalize_pipeline_provider(value: &str) -> String {
    match value.trim() {
        "memstack-sandbox" | "sandbox_native" | "" => SANDBOX_NATIVE_PROVIDER.to_string(),
        other => other.to_string(),
    }
}

fn pipeline_provider_config_json(delivery: &Map<String, Value>, provider: &str) -> Value {
    let mut provider_config = Map::new();
    if let Some(raw) = delivery.get("provider_config").and_then(Value::as_object) {
        if let Some(scoped) = raw.get(provider).and_then(Value::as_object) {
            provider_config.extend(scoped.clone());
        } else {
            provider_config.extend(raw.clone());
        }
    }
    if let Some(scoped) = delivery.get(provider).and_then(Value::as_object) {
        provider_config.extend(scoped.clone());
    }
    for key in [
        "repo",
        "repository",
        "branch",
        "commit",
        "target",
        "params",
        "build_params",
        "server_url",
        "server_url_env",
        "token_env",
        "poll_interval_seconds",
        "deploy",
    ] {
        if !provider_config.contains_key(key) {
            if let Some(value) = delivery.get(key) {
                provider_config.insert(key.to_string(), value.clone());
            }
        }
    }
    Value::Object(provider_config)
}

fn pipeline_stage_specs_json(delivery: &Map<String, Value>, timeout_seconds: i32) -> Value {
    if let Some(stages) = delivery.get("stages").and_then(Value::as_array) {
        let normalized = stages
            .iter()
            .filter_map(|stage| pipeline_stage_from_value(stage, timeout_seconds))
            .collect::<Vec<_>>();
        return Value::Array(normalized);
    }
    let command_keys = [
        ("install", "install_command"),
        ("lint", "lint_command"),
        ("test", "test_command"),
        ("build", "build_command"),
    ];
    let configured = command_keys
        .iter()
        .filter_map(|(stage, key)| {
            string_from_map(delivery, key).map(|command| {
                json!({
                    "stage": stage,
                    "command": command,
                    "required": true,
                    "timeout_seconds": timeout_seconds
                })
            })
        })
        .collect::<Vec<_>>();
    if !configured.is_empty() {
        return Value::Array(configured);
    }
    Value::Array(default_pipeline_stage_specs(timeout_seconds))
}

fn pipeline_stage_from_value(stage: &Value, default_timeout: i32) -> Option<Value> {
    let map = stage.as_object()?;
    let stage_name = string_from_map(map, "stage").or_else(|| string_from_map(map, "id"))?;
    let command = string_from_map(map, "command")?;
    let mut payload = Map::new();
    payload.insert("stage".to_string(), json!(stage_name));
    payload.insert("command".to_string(), json!(command));
    payload.insert(
        "required".to_string(),
        json!(bool_from_map_default(map, "required", true)),
    );
    payload.insert(
        "timeout_seconds".to_string(),
        json!(positive_i32_from_map(
            map,
            "timeout_seconds",
            default_timeout
        )),
    );
    if let Some(service_id) = string_from_map(map, "service_id") {
        payload.insert("service_id".to_string(), json!(service_id));
    }
    Some(Value::Object(payload))
}

fn default_pipeline_stage_specs(timeout_seconds: i32) -> Vec<Value> {
    vec![
        json!({
            "stage": "install",
            "command": default_install_command(),
            "required": true,
            "timeout_seconds": timeout_seconds
        }),
        json!({
            "stage": "lint",
            "command": default_lint_command(),
            "required": false,
            "timeout_seconds": timeout_seconds
        }),
        json!({
            "stage": "test",
            "command": default_test_command(),
            "required": true,
            "timeout_seconds": timeout_seconds
        }),
        json!({
            "stage": "build",
            "command": default_build_command(),
            "required": true,
            "timeout_seconds": timeout_seconds
        }),
    ]
}

fn default_install_command() -> &'static str {
    "if [ -f package.json ]; then if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; then pnpm install --frozen-lockfile || pnpm install; elif [ -f package-lock.json ]; then npm ci || npm install; else npm install; fi; elif [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1; then uv sync; else echo 'no install step'; fi"
}

fn default_lint_command() -> &'static str {
    "if [ -f Makefile ] && grep -qE '^lint:' Makefile; then make lint; elif [ -f package.json ]; then npm run lint --if-present; else echo 'no lint step'; fi"
}

fn default_test_command() -> &'static str {
    "if [ -f Makefile ] && grep -qE '^test:' Makefile; then make test; elif [ -f package.json ]; then if node -e \"const p=require('./package.json');process.exit(p.scripts&&p.scripts.test?0:1)\"; then npm test -- --runInBand=false 2>/dev/null || npm test; else echo 'no npm test script'; fi; elif [ -d tests ]; then pytest; else echo 'no test step'; fi"
}

fn default_build_command() -> &'static str {
    "if [ -f Makefile ] && grep -qE '^build:' Makefile; then make build; elif [ -f package.json ]; then npm run build --if-present; else echo 'no build step'; fi"
}

fn string_map_json(value: Option<&Value>) -> Value {
    let Some(map) = value.and_then(Value::as_object) else {
        return json!({});
    };
    let normalized = map
        .iter()
        .filter_map(|(key, value)| {
            if value.is_null() {
                None
            } else {
                Some((
                    key.clone(),
                    json!(value
                        .as_str()
                        .map_or_else(|| value.to_string(), ToOwned::to_owned)),
                ))
            }
        })
        .collect::<Map<_, _>>();
    Value::Object(normalized)
}

fn bool_from_map_default(map: &Map<String, Value>, key: &str, default: bool) -> bool {
    map.get(key).and_then(Value::as_bool).unwrap_or(default)
}

fn positive_i32_from_map(map: &Map<String, Value>, key: &str, default: i32) -> i32 {
    let parsed = map
        .get(key)
        .and_then(Value::as_i64)
        .and_then(|value| i32::try_from(value).ok())
        .unwrap_or(default);
    if parsed > 0 {
        parsed
    } else {
        default
    }
}

fn mark_pipeline_requested(
    node: &mut WorkspacePlanNodeRecord,
    item: &WorkspacePlanOutboxRecord,
    reason: &str,
    attempt_id: Option<&str>,
    now: DateTime<Utc>,
    runtime_state: &str,
) {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    metadata.insert("pipeline_status".to_string(), json!("requested"));
    metadata.insert("pipeline_gate_status".to_string(), json!("requested"));
    metadata.insert("pipeline_requested_at".to_string(), json!(now.to_rfc3339()));
    metadata.insert("pipeline_request_outbox_id".to_string(), json!(item.id));
    metadata.insert("pipeline_request_reason".to_string(), json!(reason));
    metadata.insert("pipeline_runtime_state".to_string(), json!(runtime_state));
    if let Some(attempt_id) = attempt_id {
        metadata.insert(
            "pipeline_requested_attempt_id".to_string(),
            json!(attempt_id),
        );
    }
    node.execution = "idle".to_string();
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
}

fn can_reflect_existing_pipeline_run(
    run: &WorkspacePipelineRunRecord,
    node: &WorkspacePlanNodeRecord,
) -> bool {
    if run.status != "success" {
        return false;
    }
    pipeline_run_matches_node_expected_commit(run, node)
}

fn pipeline_run_matches_node_expected_commit(
    run: &WorkspacePipelineRunRecord,
    node: &WorkspacePlanNodeRecord,
) -> bool {
    let Some(expected) = node_expected_commit_ref(node) else {
        return true;
    };
    pipeline_run_source_commit_ref(run)
        .is_some_and(|actual| git_commit_refs_match(&actual, &expected))
}

fn pipeline_run_source_commit_ref(run: &WorkspacePipelineRunRecord) -> Option<String> {
    let metadata = object_or_empty(run.metadata_json.clone());
    metadata
        .get("source_publish_source_commit_ref")
        .and_then(Value::as_str)
        .and_then(commit_ref_token)
        .or_else(|| run.commit_ref.as_deref().and_then(commit_ref_token))
}

fn stale_pipeline_run_failure_metadata(
    run: &WorkspacePipelineRunRecord,
    node: &WorkspacePlanNodeRecord,
) -> (String, Value) {
    let stale_source_commit_ref = pipeline_run_source_commit_ref(run);
    let requested_source_commit_ref = node_expected_commit_ref(node);
    let stale = stale_source_commit_ref.as_deref().unwrap_or("unknown");
    let requested = requested_source_commit_ref.as_deref().unwrap_or("unknown");
    (
        format!("stale pipeline run source commit {stale} superseded by {requested}"),
        json!({
            "stale_pipeline_run": true,
            "stale_source_commit_ref": stale_source_commit_ref,
            "superseded_by_source_commit_ref": requested_source_commit_ref
        }),
    )
}

fn mark_existing_pipeline_run_running(
    node: &mut WorkspacePlanNodeRecord,
    run: &WorkspacePipelineRunRecord,
    now: DateTime<Utc>,
) {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    metadata.insert("pipeline_run_id".to_string(), json!(run.id));
    metadata.insert("pipeline_status".to_string(), json!("running"));
    metadata.insert("pipeline_gate_status".to_string(), json!("running"));
    metadata.insert("pipeline_started_at".to_string(), json!(now.to_rfc3339()));
    node.execution = "idle".to_string();
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
}

fn reflect_existing_pipeline_run_to_node(
    node: &mut WorkspacePlanNodeRecord,
    run: &WorkspacePipelineRunRecord,
    now: DateTime<Utc>,
) {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    for (key, value) in pipeline_node_metadata_projection(&run.metadata_json) {
        metadata.insert(key, value);
    }
    metadata.insert("pipeline_run_id".to_string(), json!(run.id));
    metadata.insert("pipeline_status".to_string(), json!(run.status));
    metadata.insert("pipeline_gate_status".to_string(), json!(run.status));

    if run.status == "success" {
        let evidence_refs = merge_string_values(
            metadata.get("pipeline_evidence_refs"),
            &[
                "ci_pipeline:passed".to_string(),
                format!("pipeline_run:success:{}", run.id),
            ],
        );
        metadata.insert("pipeline_evidence_refs".to_string(), json!(evidence_refs));
        metadata.insert(
            "last_verification_summary".to_string(),
            json!("harness-native CI/CD pipeline passed"),
        );
        metadata.insert("last_verification_passed".to_string(), json!(true));
        metadata.insert("last_verification_hard_fail".to_string(), json!(false));
        metadata.insert(
            "last_verification_ran_at".to_string(),
            json!(now.to_rfc3339()),
        );
        let (intent, execution) = pipeline_completion_node_state(node, &metadata, &run.status);
        node.intent = intent;
        node.execution = execution;
    }

    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
}

#[allow(clippy::too_many_arguments)]
fn finish_pipeline_on_node(
    node: &mut WorkspacePlanNodeRecord,
    run: &WorkspacePipelineRunRecord,
    status: &str,
    reason: Option<&str>,
    evidence_refs: &[String],
    preview_url: Option<&str>,
    health_url: Option<&str>,
    now: DateTime<Utc>,
) {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    for (key, value) in pipeline_node_metadata_projection(&run.metadata_json) {
        metadata.insert(key, value);
    }
    let summary = reason.unwrap_or("harness-native CI/CD pipeline passed");
    metadata.insert("pipeline_run_id".to_string(), json!(run.id));
    metadata.insert("pipeline_status".to_string(), json!(status));
    metadata.insert("pipeline_gate_status".to_string(), json!(status));
    metadata.insert("pipeline_finished_at".to_string(), json!(now.to_rfc3339()));
    metadata.insert("pipeline_last_summary".to_string(), json!(summary));
    let pipeline_evidence_refs =
        merge_string_values(metadata.get("pipeline_evidence_refs"), evidence_refs);
    metadata.insert(
        "pipeline_evidence_refs".to_string(),
        json!(pipeline_evidence_refs),
    );
    let execution_verifications =
        merge_string_values(metadata.get("execution_verifications"), evidence_refs);
    metadata.insert(
        "execution_verifications".to_string(),
        json!(execution_verifications),
    );
    let merged_evidence_refs = merge_string_values(metadata.get("evidence_refs"), evidence_refs);
    metadata.insert("evidence_refs".to_string(), json!(merged_evidence_refs));
    if let Some(preview_url) = preview_url {
        metadata.insert("preview_url".to_string(), json!(preview_url));
    }
    if let Some(health_url) = health_url {
        metadata.insert("health_url".to_string(), json!(health_url));
    }
    if status == "success" {
        metadata.insert("last_verification_summary".to_string(), json!(summary));
        metadata.insert("last_verification_passed".to_string(), json!(true));
        metadata.insert("last_verification_hard_fail".to_string(), json!(false));
        metadata.insert(
            "last_verification_ran_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.remove("pipeline_stop_reason");
    }
    let (intent, execution) = pipeline_completion_node_state(node, &metadata, status);
    node.intent = intent;
    node.execution = execution;
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
}

fn pipeline_completed_supervisor_tick(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    pipeline_run_id: &str,
    pipeline_status: &str,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    pipeline_completed_supervisor_tick_with_source(
        workspace_id,
        plan_id,
        node_id,
        pipeline_run_id,
        pipeline_status,
        "workspace_plan.pipeline_run_completed",
        now,
    )
}

fn pipeline_completed_supervisor_tick_with_source(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    pipeline_run_id: &str,
    pipeline_status: &str,
    source: &str,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: SUPERVISOR_TICK_EVENT.to_string(),
        payload_json: json!({
            "workspace_id": workspace_id,
            "plan_id": plan_id,
            "node_id": node_id,
            "pipeline_run_id": pipeline_run_id,
            "pipeline_status": pipeline_status
        }),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 3,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": source}),
        created_at: now,
        updated_at: None,
    }
}

fn pipeline_node_metadata_projection(run_metadata: &Value) -> Map<String, Value> {
    let mut projected = Map::new();
    let Some(run_metadata) = run_metadata.as_object() else {
        return projected;
    };
    for (key, value) in run_metadata {
        if key.starts_with("source_publish_") {
            projected.insert(key.clone(), value.clone());
        }
    }
    for key in [
        "deploy_mode",
        "deploy_validation",
        "deployment_status",
        "external_id",
        "external_provider",
        "external_url",
        "pipeline_failed_stage",
        "pipeline_failure_summary",
        "pipeline_last_summary",
    ] {
        if let Some(value) = run_metadata.get(key) {
            projected.insert(key.to_string(), value.clone());
        }
    }
    projected
}

fn merge_string_values(existing: Option<&Value>, additions: &[String]) -> Vec<String> {
    let mut values = metadata_string_values(existing);
    for value in additions {
        let value = value.trim();
        if !value.is_empty() {
            values.push(value.to_string());
        }
    }
    dedup_strings(&mut values);
    values
}

fn build_worker_report_payload(
    task_metadata: &Map<String, Value>,
    report_type: &str,
    summary: &str,
    artifacts: &[String],
    report_id: Option<&str>,
) -> WorkerReportPayload {
    let (normalized_summary, mut report_artifacts, mut report_verifications) =
        parse_worker_report_payload(report_type, summary, artifacts);
    let mut merged_artifacts = metadata_string_values(task_metadata.get("evidence_refs"));
    let mut report_artifacts_for_merge = report_artifacts.clone();
    merged_artifacts.append(&mut report_artifacts_for_merge);
    dedup_strings(&mut merged_artifacts);
    let mut merged_verifications =
        metadata_string_values(task_metadata.get("execution_verifications"));
    let mut report_verifications_for_merge = report_verifications.clone();
    merged_verifications.append(&mut report_verifications_for_merge);
    dedup_strings(&mut merged_verifications);
    let fingerprint = worker_report_fingerprint(
        report_type,
        &normalized_summary,
        &merged_artifacts,
        &report_verifications,
        report_id,
    );
    dedup_strings(&mut report_artifacts);
    dedup_strings(&mut report_verifications);
    WorkerReportPayload {
        normalized_summary,
        report_artifacts,
        merged_artifacts,
        report_verifications,
        merged_verifications,
        fingerprint,
    }
}

fn parse_worker_report_payload(
    report_type: &str,
    summary: &str,
    artifacts: &[String],
) -> (String, Vec<String>, Vec<String>) {
    let mut normalized_summary = summary.trim().to_string();
    if normalized_summary.is_empty() {
        normalized_summary = format!("worker_report:{report_type}");
    }
    let mut merged_artifacts = artifacts
        .iter()
        .map(|artifact| artifact.trim())
        .filter(|artifact| !artifact.is_empty())
        .map(ToOwned::to_owned)
        .collect::<Vec<_>>();
    let mut verifications = Vec::new();

    if let Ok(Value::Object(payload)) = serde_json::from_str::<Value>(summary) {
        if let Some(payload_summary) = metadata_string(payload.get("summary")) {
            normalized_summary = payload_summary;
        }
        for item in metadata_string_values(payload.get("artifacts")) {
            merged_artifacts.push(item);
        }
        for item in metadata_string_values(payload.get("verifications")) {
            verifications.push(item);
        }
        if let Some(commit_ref) = metadata_string(payload.get("commit_ref")) {
            merged_artifacts.push(format!("commit_ref:{commit_ref}"));
        }
        if let Some(git_diff_summary) = metadata_string(payload.get("git_diff_summary")) {
            merged_artifacts.push(format!("git_diff_summary:{git_diff_summary}"));
        }
        for path in metadata_string_values(payload.get("changed_files")) {
            merged_artifacts.push(format!("changed_file:{path}"));
        }
        for command in metadata_string_values(payload.get("test_commands")) {
            verifications.push(format!("test_run:{command}"));
        }
        if let Some(verdict) = metadata_string(payload.get("verdict"))
            .or_else(|| metadata_string(payload.get("outcome")))
        {
            verifications.push(format!("worker_verdict:{verdict}"));
        }
        if let Some(grade) = metadata_string(payload.get("verification_grade")) {
            verifications.push(format!("verification_grade:{grade}"));
        }
    }

    if report_type == "completed" && verifications.is_empty() {
        verifications.push("worker_report:completed".to_string());
    }
    dedup_strings(&mut merged_artifacts);
    dedup_strings(&mut verifications);
    (normalized_summary, merged_artifacts, verifications)
}

fn worker_report_fingerprint(
    report_type: &str,
    summary: &str,
    artifacts: &[String],
    verifications: &[String],
    report_id: Option<&str>,
) -> String {
    let serialized = format!(
        "{{\"artifacts\": {}, \"report_id\": {}, \"report_type\": {}, \"summary\": {}, \"verifications\": {}}}",
        python_json_string_array(artifacts),
        python_json_string(report_id.unwrap_or("")),
        python_json_string(report_type),
        python_json_string(summary),
        python_json_string_array(verifications)
    );
    let mut hasher = Sha256::new();
    hasher.update(serialized.as_bytes());
    format!("{:x}", hasher.finalize())
}

fn python_json_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_string())
}

fn python_json_string_array(values: &[String]) -> String {
    if values.is_empty() {
        return "[]".to_string();
    }
    format!(
        "[{}]",
        values
            .iter()
            .map(|value| python_json_string(value))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

fn is_stale_terminal_worker_report(task_metadata: &Map<String, Value>, attempt_id: &str) -> bool {
    string_from_map(task_metadata, CURRENT_ATTEMPT_ID)
        .as_deref()
        .is_some_and(|current_attempt_id| {
            !current_attempt_id.is_empty() && current_attempt_id != attempt_id
        })
}

fn worker_execution_state(
    phase: &str,
    reason: &str,
    action: &str,
    actor_id: &str,
    now: DateTime<Utc>,
) -> Value {
    json!({
        "phase": phase,
        "last_agent_reason": reason,
        "last_agent_action": action,
        "updated_by_actor_type": "agent",
        "updated_by_actor_id": actor_id,
        "updated_at": now.to_rfc3339()
    })
}

fn pipeline_completion_node_state(
    node: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
    status: &str,
) -> (String, String) {
    if status != "success" {
        return ("in_progress".to_string(), "reported".to_string());
    }
    let phase = metadata_string(metadata.get("iteration_phase"));
    if node.current_attempt_id.is_some()
        || matches!(phase.as_deref(), Some("test" | "deploy" | "review"))
    {
        return ("done".to_string(), "idle".to_string());
    }
    ("in_progress".to_string(), "reported".to_string())
}

pub(crate) struct SupervisorTickAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
}

impl SupervisorTickAdmissionHandler {
    pub(crate) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self { store }
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for SupervisorTickAdmissionHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_or_empty(item.payload_json.clone());
        let workspace_id =
            string_from_map(&payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let node_id = string_from_map(&payload, "retry_node_id")
            .or_else(|| string_from_map(&payload, "node_id"));
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(&payload, "plan_id"));
        let Some(node_id) = node_id else {
            let Some(plan_id) = plan_id else {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                    reason: Some("supervisor_tick_requires_full_runtime".to_string()),
                });
            };
            let changed_worktree_failed = self
                .reopen_failed_worktree_integration_nodes(&item, &payload, &workspace_id, &plan_id)
                .await?;
            let changed_missing = self
                .recover_missing_attempt_nodes(&item, &payload, &workspace_id, &plan_id)
                .await?;
            let changed_disposed = self
                .reconcile_supervisor_disposed_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_accepted = self
                .reconcile_accepted_terminal_attempt_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_supervisor_retry = self
                .reconcile_supervisor_retry_same_node_attempt_nodes(
                    &item,
                    &payload,
                    &workspace_id,
                    &plan_id,
                )
                .await?;
            let changed_terminal = self
                .reconcile_terminal_attempt_nodes(&item, &payload, &workspace_id, &plan_id)
                .await?;
            let changed_reported = self
                .reconcile_reported_attempt_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_dirty_main_dependency_dispatch = self
                .dispatch_ready_dirty_main_dependency_node(&item, &payload, &workspace_id, &plan_id)
                .await?;
            if changed_worktree_failed
                + changed_missing
                + changed_disposed
                + changed_accepted
                + changed_supervisor_retry
                + changed_terminal
                + changed_reported
                + changed_dirty_main_dependency_dispatch
                > 0
            {
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
            return Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_requires_full_runtime".to_string()),
            });
        };
        let plan_id = plan_id.ok_or_else(|| {
            CoreError::Storage("supervisor_tick retry requires plan_id".to_string())
        })?;
        let plan = self.store.get_plan(&plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut nodes = self.store.list_plan_nodes(&plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        };
        if node.intent == "done" {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }
        let retry_attempt_id = string_from_map(&payload, "retry_attempt_id")
            .or_else(|| string_from_map(&payload, "attempt_id"));
        if retry_attempt_id.is_some()
            && node.current_attempt_id.as_deref().is_some()
            && node.current_attempt_id.as_deref() != retry_attempt_id.as_deref()
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let task_id = string_from_map(&payload, "task_id")
            .or_else(|| node.workspace_task_id.clone())
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "supervisor_tick retry node {node_id} has no workspace task"
                ))
            })?;
        let task = self
            .store
            .get_task(&workspace_id, &task_id)
            .await?
            .ok_or_else(|| {
                CoreError::Storage(format!(
                    "workspace task {task_id} not found for workspace {workspace_id}"
                ))
            })?;
        let task_metadata = object_or_empty(task.metadata_json.clone());
        let Some(worker_agent_id) = string_from_map(&payload, "worker_agent_id")
            .or_else(|| node.assignee_agent_id.clone())
            .or_else(|| task.assignee_agent_id.clone())
        else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_retry_requires_worker_agent".to_string()),
            });
        };
        let actor_user_id =
            string_from_map(&payload, "actor_user_id").unwrap_or_else(|| task.created_by.clone());
        let leader_agent_id = string_from_map(&payload, "leader_agent_id")
            .or_else(|| string_from_map(&task_metadata, "leader_agent_id"))
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let root_goal_task_id = string_from_map(&payload, ROOT_GOAL_TASK_ID)
            .or_else(|| string_from_map(&payload, "root_task_id"))
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID));
        if is_worker_report_supervisor_tick(&item, &payload) {
            return self
                .handle_worker_report_supervisor_tick(
                    &item,
                    &payload,
                    &workspace_id,
                    &plan_id,
                    node,
                    &task_id,
                    &worker_agent_id,
                    &actor_user_id,
                    &leader_agent_id,
                    root_goal_task_id.as_deref(),
                    retry_attempt_id.as_deref(),
                )
                .await;
        }
        let retry_reason = string_from_map(&payload, "retry_reason")
            .unwrap_or_else(|| "supervisor_tick_retry".to_string());

        let now = Utc::now();
        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert(
            "supervisor_tick_status".to_string(),
            json!("retry_admitted"),
        );
        metadata.insert(
            "supervisor_tick_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "supervisor_tick_outbox_id".to_string(),
            json!(item.id.clone()),
        );
        metadata.insert(
            "supervisor_tick_retry_reason".to_string(),
            json!(retry_reason.clone()),
        );
        if let Some(attempt_id) = retry_attempt_id.as_deref() {
            metadata.insert(
                "supervisor_tick_retry_attempt_id".to_string(),
                json!(attempt_id),
            );
        }
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;

        self.store
            .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                &item,
                &payload,
                &workspace_id,
                &plan_id,
                &node_id,
                &task_id,
                &worker_agent_id,
                &actor_user_id,
                &leader_agent_id,
                root_goal_task_id.as_deref(),
                retry_attempt_id.as_deref(),
                &retry_reason,
                now,
            ))
            .await?;

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

struct SupervisorRetryContext {
    task_id: String,
    worker_agent_id: String,
    actor_user_id: String,
    leader_agent_id: String,
    root_goal_task_id: Option<String>,
}

impl SupervisorTickAdmissionHandler {
    #[allow(clippy::too_many_arguments)]
    async fn handle_worker_report_supervisor_tick(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
        mut node: WorkspacePlanNodeRecord,
        task_id: &str,
        worker_agent_id: &str,
        actor_user_id: &str,
        leader_agent_id: &str,
        root_goal_task_id: Option<&str>,
        attempt_id: Option<&str>,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let Some(attempt_id) = attempt_id else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        };
        let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? else {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        };
        if attempt.status != AWAITING_LEADER_ADJUDICATION_STATUS
            || !attempt_has_candidate_output(&attempt)
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let now = Utc::now();
        let node_metadata = object_or_empty(node.metadata_json.clone());
        if let Some(retry_reason) =
            worker_stream_orphan_report_retry_reason(&node_metadata, &attempt)
        {
            self.store
                .finish_task_session_attempt(
                    attempt_id,
                    "blocked",
                    attempt.candidate_summary.as_deref(),
                    Some(&retry_reason),
                    now,
                )
                .await?;
            let max_retries = plan_terminal_attempt_max_retries();
            let retry_exhausted =
                release_node_for_terminal_retry(&mut node, &retry_reason, now, max_retries);
            let mut metadata = object_or_empty(node.metadata_json.clone());
            let retry_count = metadata
                .get("terminal_attempt_retry_count")
                .and_then(Value::as_i64)
                .unwrap_or_default();
            let retry_status = if retry_exhausted {
                "orphan_retry_exhausted"
            } else {
                "orphan_retry_admitted"
            };
            metadata.insert(
                "worker_report_supervisor_tick_status".to_string(),
                json!(retry_status),
            );
            metadata.insert(
                "worker_stream_orphan_retry_reason".to_string(),
                json!(retry_reason.clone()),
            );
            metadata.insert(
                "worker_stream_orphan_retry_exhausted".to_string(),
                json!(retry_exhausted),
            );
            metadata.insert(
                "worker_stream_orphan_retry_count".to_string(),
                json!(retry_count),
            );
            metadata.insert(
                "worker_stream_orphan_retry_max_retries".to_string(),
                json!(max_retries),
            );
            node.metadata_json = Value::Object(metadata);
            self.store.save_plan_node(node.clone()).await?;

            let retry_event_type = if retry_exhausted {
                "worker_stream_orphan_retry_exhausted"
            } else {
                "worker_stream_orphan_retry_admitted"
            };
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node.id.clone()),
                    attempt_id: Some(attempt_id.to_string()),
                    event_type: retry_event_type.to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "retry_reason": retry_reason.clone(),
                        "summary": attempt.candidate_summary.clone(),
                        "retry_exhausted": retry_exhausted,
                        "retry_count": retry_count,
                        "max_retries": max_retries,
                    }),
                    created_at: now,
                })
                .await?;

            if !retry_exhausted {
                let mut retry_payload = payload.clone();
                retry_payload.insert(
                    "retry_origin".to_string(),
                    json!("worker_stream_orphan_report"),
                );
                retry_payload.insert(
                    "worker_stream_orphan_retry_reason".to_string(),
                    json!(retry_reason.clone()),
                );
                if let Some(summary) = attempt.candidate_summary.as_deref() {
                    retry_payload
                        .insert("worker_stream_orphan_summary".to_string(), json!(summary));
                }
                self.store
                    .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                        item,
                        &retry_payload,
                        workspace_id,
                        plan_id,
                        &node.id,
                        task_id,
                        worker_agent_id,
                        actor_user_id,
                        leader_agent_id,
                        root_goal_task_id,
                        Some(attempt_id),
                        &retry_reason,
                        now,
                    ))
                    .await?;
            }
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert(
            "reported_attempt_reconciled_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "reported_attempt_status".to_string(),
            json!(AWAITING_LEADER_ADJUDICATION_STATUS),
        );
        metadata.insert(
            "worker_report_supervisor_tick_status".to_string(),
            json!("reported_candidate_observed"),
        );
        node.execution = "reported".to_string();
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node.clone()).await?;
        self.store
            .create_plan_event(WorkspacePlanEventRecord {
                id: generate_uuid_v4(),
                plan_id: plan_id.to_string(),
                workspace_id: workspace_id.to_string(),
                node_id: Some(node.id.clone()),
                attempt_id: Some(attempt_id.to_string()),
                event_type: "auto_reported_attempt_reconciled".to_string(),
                source: "workspace_plan_supervisor_tick".to_string(),
                actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                payload_json: json!({
                    "reason": "worker_report_supervisor_tick",
                    "node_ids": [node.id]
                }),
                created_at: now,
            })
            .await?;
        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }

    async fn reopen_failed_worktree_integration_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if !done_node_needs_worktree_integration_retry(&node) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let previous_metadata = object_or_empty(node.metadata_json.clone());
            let previous_attempt_id =
                metadata_string(previous_metadata.get("worktree_integration_attempt_id"))
                    .or_else(|| node.current_attempt_id.clone());
            let previous_commit_ref = node_verified_commit_ref(&node);
            let previous_summary =
                metadata_string(previous_metadata.get("worktree_integration_summary"))
                    .unwrap_or_else(|| "accepted worktree integration failed".to_string());

            let mut metadata =
                clear_failed_worktree_retry_stale_attempt_metadata(previous_metadata);
            metadata.insert("last_verification_passed".to_string(), json!(false));
            metadata.insert(
                "last_verification_summary".to_string(),
                json!(format!(
                    "accepted worktree integration failed after verification: {previous_summary}"
                )),
            );
            metadata.insert(
                "terminal_attempt_retry_reason".to_string(),
                json!("worktree_integration_failed"),
            );
            metadata.insert(
                "worktree_integration_failed_done_reopened_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if let Some(previous_attempt_id) = previous_attempt_id.as_deref() {
                metadata.insert(
                    "worktree_integration_failed_previous_attempt_id".to_string(),
                    json!(previous_attempt_id),
                );
            }
            if let Some(previous_commit_ref) = previous_commit_ref.as_deref() {
                metadata.insert(
                    "worktree_integration_failed_previous_commit_ref".to_string(),
                    json!(previous_commit_ref),
                );
            }
            metadata.insert(
                "worktree_integration_failed_previous_summary".to_string(),
                json!(previous_summary.clone()),
            );

            let node_id = node.id.clone();
            node.intent = "todo".to_string();
            node.execution = "idle".to_string();
            node.assignee_agent_id = None;
            node.current_attempt_id = None;
            node.feature_checkpoint_json =
                reset_feature_checkpoint(node.feature_checkpoint_json.clone());
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            node.completed_at = None;
            self.store.save_plan_node(node.clone()).await?;
            changed += 1;

            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node_id.clone()),
                    attempt_id: previous_attempt_id.clone(),
                    event_type: "worktree_integration_failed_done_node_reopened".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "previous_attempt_id": previous_attempt_id,
                        "previous_commit_ref": previous_commit_ref,
                        "summary": "done node reopened because accepted worktree integration failed",
                        "worktree_integration_summary": previous_summary,
                    }),
                    created_at: now,
                })
                .await?;

            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node_id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    previous_attempt_id.as_deref(),
                    "worktree_integration_failed",
                    now,
                ))
                .await?;
        }
        Ok(changed)
    }

    async fn recover_missing_attempt_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            let Some(attempt_id) = recoverable_node_attempt_id(&node) else {
                continue;
            };
            if self
                .store
                .get_task_session_attempt(&attempt_id)
                .await?
                .is_some()
            {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let node_id = node.id.clone();
            let retry_exhausted = release_node_for_terminal_retry(
                &mut node,
                "missing_attempt",
                now,
                plan_terminal_attempt_max_retries(),
            );
            self.store.save_plan_node(node).await?;
            changed += 1;

            if retry_exhausted {
                continue;
            }
            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node_id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    Some(&attempt_id),
                    "missing_attempt",
                    now,
                ))
                .await?;
        }
        Ok(changed)
    }

    async fn dispatch_ready_dirty_main_dependency_node(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        nodes.sort_by(|left, right| {
            left.priority
                .cmp(&right.priority)
                .then_with(|| left.id.cmp(&right.id))
        });
        let nodes_by_id = nodes
            .iter()
            .map(|node| (node.id.clone(), node.clone()))
            .collect::<HashMap<_, _>>();

        for mut node in nodes {
            if !dirty_main_dependency_dispatch_candidate(&node) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };
            if self
                .store
                .find_active_task_session_attempt(&context.task_id)
                .await?
                .is_some()
            {
                continue;
            }
            let (blocking_dependencies, dirty_main_seed_dependencies) =
                dependency_dispatch_blockers(&node, &nodes_by_id);
            if !blocking_dependencies.is_empty() || dirty_main_seed_dependencies.is_empty() {
                continue;
            }

            let dependency_base_ref = dependency_base_ref_for_dispatch(&node, &nodes_by_id);
            if let Some(base_ref) = dependency_base_ref.as_deref() {
                node.feature_checkpoint_json = feature_checkpoint_with_base_ref(
                    node.feature_checkpoint_json.clone(),
                    base_ref,
                );
            }
            let now = Utc::now();
            let mut metadata = object_or_empty(node.metadata_json.clone());
            metadata.insert(
                "dirty_main_dependency_dispatch_status".to_string(),
                json!("queued"),
            );
            metadata.insert(
                "dirty_main_dependency_dispatch_outbox_id".to_string(),
                json!(item.id.clone()),
            );
            metadata.insert(
                "dirty_main_dependency_dispatch_queued_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "dirty_main_dependency_seed_node_ids".to_string(),
                json!(dirty_main_seed_dependencies),
            );
            if let Some(base_ref) = dependency_base_ref.as_deref() {
                metadata.insert(
                    "dirty_main_dependency_base_ref".to_string(),
                    json!(base_ref),
                );
            }
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node.id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    None,
                    "dirty_main_dependency_ready",
                    now,
                ))
                .await?;
            return Ok(1);
        }

        Ok(0)
    }

    async fn reconcile_accepted_terminal_attempt_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            let Some(attempt_id) = recoverable_node_attempt_id(&node) else {
                continue;
            };
            let Some(mut attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            if attempt.status.trim().to_ascii_lowercase() != ACCEPTED_ATTEMPT_STATUS {
                if !done_idle_node_has_accepted_supervisor_judge(&node) {
                    continue;
                }
                let summary = accepted_supervisor_judge_summary(&node, &attempt);
                let Some(updated) = self
                    .store
                    .finish_task_session_attempt(
                        &attempt_id,
                        ACCEPTED_ATTEMPT_STATUS,
                        Some(&summary),
                        Some("supervisor_decision_accept_node_reconciled"),
                        now,
                    )
                    .await?
                else {
                    continue;
                };
                attempt = updated;
            }
            if self
                .accepted_projection_already_complete(workspace_id, &node, &attempt)
                .await?
            {
                continue;
            }
            if !accepted_attempt_matches_node_expected_commit(&node, &attempt) {
                continue;
            }

            let evidence_refs = accepted_attempt_evidence_refs(&attempt);
            let commit_ref = first_valid_commit_ref(&evidence_refs);
            let git_diff_summary = first_prefixed_ref(&evidence_refs, "git_diff_summary:");
            let test_commands = prefixed_refs(&evidence_refs, "test_run:");
            let summary = accepted_attempt_summary(&attempt);
            let Some(integration_metadata) = self
                .project_accepted_attempt_to_task(
                    workspace_id,
                    &node,
                    &attempt,
                    &summary,
                    &evidence_refs,
                    commit_ref.as_deref(),
                    git_diff_summary.as_deref(),
                    &test_commands,
                    now,
                )
                .await?
            else {
                continue;
            };

            let mut metadata = accepted_attempt_projection_base_metadata(&node, &attempt);
            metadata.insert(
                "terminal_attempt_status".to_string(),
                json!(ACCEPTED_ATTEMPT_STATUS),
            );
            metadata.insert(
                "terminal_attempt_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert("last_verification_summary".to_string(), json!(summary));
            metadata.insert("last_verification_passed".to_string(), json!(true));
            metadata.insert("last_verification_hard_fail".to_string(), json!(false));
            metadata.insert(
                "last_verification_attempt_id".to_string(),
                json!(attempt.id.clone()),
            );
            metadata.insert(
                "last_verification_ran_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if !attempt.candidate_artifacts_json.is_empty() {
                metadata.insert(
                    "candidate_artifacts".to_string(),
                    json!(attempt.candidate_artifacts_json.clone()),
                );
            }
            if !attempt.candidate_verifications_json.is_empty() {
                metadata.insert(
                    "candidate_verifications".to_string(),
                    json!(attempt.candidate_verifications_json.clone()),
                );
            }
            metadata.extend(integration_metadata);
            node.intent = "done".to_string();
            node.execution = "idle".to_string();
            node.current_attempt_id = Some(attempt.id.clone());
            node.feature_checkpoint_json =
                accepted_attempt_projection_feature_checkpoint(&node, &attempt);
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node).await?;
            changed += 1;
        }
        Ok(changed)
    }

    async fn reconcile_supervisor_disposed_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if node.workspace_task_id.as_deref().is_none_or(str::is_empty) {
                continue;
            }
            let has_dispose_metadata = supervisor_dispose_metadata_present(&node);
            let has_dispose_event = self
                .store
                .has_supervisor_dispose_decision_for_node(workspace_id, plan_id, &node.id)
                .await?;
            if !has_dispose_metadata && !has_dispose_event {
                continue;
            }

            let mut metadata = object_or_empty(node.metadata_json.clone());
            let disposition = supervisor_disposition_value(&metadata);
            let summary = supervisor_disposition_summary(&metadata);
            let already_projected_node = node.intent == "done"
                && node.execution == "idle"
                && metadata_string(metadata.get("verification_feedback_disposition")).as_deref()
                    == Some(disposition.as_str())
                && metadata_string(metadata.get("workspace_task_projection_status")).as_deref()
                    == Some("done");

            metadata.insert(
                "verification_feedback_disposition".to_string(),
                json!(disposition.clone()),
            );
            metadata.insert(
                "last_supervisor_decision_action".to_string(),
                json!(SUPERVISOR_DECISION_DISPOSE_NODE_ACTION),
            );
            metadata.insert(
                "last_supervisor_decision_rationale".to_string(),
                json!(summary.clone()),
            );
            metadata.insert(
                "supervisor_disposition_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "workspace_task_projection_status".to_string(),
                json!("done"),
            );
            metadata.insert(
                "workspace_task_projected_at".to_string(),
                json!(now.to_rfc3339()),
            );
            node.intent = "done".to_string();
            node.execution = "idle".to_string();
            node.metadata_json = Value::Object(metadata.clone());
            node.updated_at = Some(now);
            if node.completed_at.is_none() {
                node.completed_at = Some(now);
            }

            let task_projected = self
                .project_supervisor_disposition_to_task(
                    workspace_id,
                    &node,
                    &summary,
                    &disposition,
                    now,
                )
                .await?;
            if !already_projected_node || task_projected {
                self.store.save_plan_node(node.clone()).await?;
                self.store
                    .create_plan_event(WorkspacePlanEventRecord {
                        id: generate_uuid_v4(),
                        plan_id: plan_id.to_string(),
                        workspace_id: workspace_id.to_string(),
                        node_id: Some(node.id.clone()),
                        attempt_id: node.current_attempt_id.clone(),
                        event_type: "supervisor_disposition_reconciled".to_string(),
                        source: "workspace_plan_supervisor_tick".to_string(),
                        actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                        payload_json: json!({
                            "action": SUPERVISOR_DECISION_DISPOSE_NODE_ACTION,
                            "disposition": disposition,
                            "rationale": summary,
                            "workspace_task_id": node.workspace_task_id.clone(),
                            "task_projected": task_projected,
                            "had_dispose_event": has_dispose_event,
                        }),
                        created_at: now,
                    })
                    .await?;
                changed += 1;
            }
        }
        Ok(changed)
    }

    async fn project_supervisor_disposition_to_task(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        summary: &str,
        disposition: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let Some(task_id) = node.workspace_task_id.as_deref() else {
            return Ok(false);
        };
        let Some(mut task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(false);
        };
        if task.workspace_id != workspace_id {
            return Ok(false);
        }
        let mut metadata = object_or_empty(task.metadata_json.clone());
        if task.status == "done"
            && metadata_string(metadata.get("durable_plan_verdict")).as_deref() == Some("disposed")
            && metadata_string(metadata.get("durable_plan_disposition")).as_deref()
                == Some(disposition)
            && metadata_string(metadata.get("durable_plan_verification_summary")).as_deref()
                == Some(summary)
        {
            return Ok(false);
        }

        metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(false));
        metadata.insert("durable_plan_verdict".to_string(), json!("disposed"));
        metadata.insert("durable_plan_disposition".to_string(), json!(disposition));
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        metadata.insert(
            "last_worker_report_type".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        metadata.insert(LAST_WORKER_REPORT_SUMMARY.to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!(DISPOSED_ATTEMPT_STATUS),
        );
        if let Some(attempt_id) = node.current_attempt_id.as_deref() {
            metadata.insert("last_attempt_id".to_string(), json!(attempt_id));
            metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        copy_supervisor_disposition_event_payload_fields(
            &object_or_empty(node.metadata_json.clone()),
            &mut metadata,
        );

        task.metadata_json = Value::Object(metadata);
        task.status = "done".to_string();
        task.blocker_reason = None;
        task.completed_at = Some(now);
        task.updated_at = Some(now);
        let saved_task = self.store.save_task(task).await?;
        if let Some(root_goal_task_id) =
            string_from_value_object(&saved_task.metadata_json, ROOT_GOAL_TASK_ID)
        {
            if root_goal_task_id != saved_task.id {
                self.reconcile_root_goal_progress(workspace_id, &root_goal_task_id, now)
                    .await?;
            }
        }
        Ok(true)
    }

    #[allow(clippy::too_many_arguments)]
    async fn project_accepted_attempt_to_task(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        summary: &str,
        evidence_refs: &[String],
        commit_ref: Option<&str>,
        git_diff_summary: Option<&str>,
        test_commands: &[String],
        now: DateTime<Utc>,
    ) -> CoreResult<Option<Map<String, Value>>> {
        let task_id = node
            .workspace_task_id
            .as_ref()
            .unwrap_or(&attempt.workspace_task_id);
        let Some(mut task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(Some(Map::new()));
        };
        if task.workspace_id != workspace_id {
            return Ok(Some(Map::new()));
        }

        let integration_metadata = self
            .integrate_accepted_attempt_worktree(
                workspace_id,
                node,
                &attempt.id,
                &task,
                commit_ref,
                now,
            )
            .await?;
        let Some(integration_metadata) = integration_metadata else {
            return Ok(None);
        };

        let mut metadata = object_or_empty(task.metadata_json.clone());
        metadata.insert("pending_leader_adjudication".to_string(), json!(false));
        metadata.remove("retry_verification_only");
        metadata.insert("durable_plan_verdict".to_string(), json!("accepted"));
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(ACCEPTED_ATTEMPT_STATUS),
        );
        metadata.insert("last_attempt_id".to_string(), json!(attempt.id.clone()));
        metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
        metadata.insert("last_worker_report_type".to_string(), json!("completed"));
        metadata.insert("last_worker_report_summary".to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!(ACCEPTED_ATTEMPT_STATUS),
        );
        if !evidence_refs.is_empty() {
            metadata.insert("evidence_refs".to_string(), json!(evidence_refs));
        }
        apply_verification_checkpoint_metadata(
            &mut metadata,
            summary,
            commit_ref,
            git_diff_summary,
            test_commands,
            now,
        );
        metadata.extend(integration_metadata.clone());

        task.metadata_json = Value::Object(metadata);
        task.status = "done".to_string();
        task.blocker_reason = None;
        task.completed_at = Some(now);
        task.updated_at = Some(now);
        let saved_task = self.store.save_task(task).await?;
        self.reconcile_root_goal_progress_for_task(workspace_id, &saved_task, attempt, now)
            .await?;
        Ok(Some(integration_metadata))
    }

    async fn reconcile_root_goal_progress_for_task(
        &self,
        workspace_id: &str,
        task: &WorkspaceTaskRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let Some(root_goal_task_id) = root_goal_task_id_for_progress(task, attempt) else {
            return Ok(());
        };
        if root_goal_task_id == task.id {
            return Ok(());
        }
        self.reconcile_root_goal_progress(workspace_id, &root_goal_task_id, now)
            .await
    }

    async fn reconcile_root_goal_progress(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let Some(mut root_task) = self.store.get_task(workspace_id, root_goal_task_id).await?
        else {
            return Ok(());
        };
        if !is_goal_root_task(&root_task) {
            return Ok(());
        }

        let mut child_tasks = self
            .store
            .list_current_plan_child_tasks_by_root_goal_task_id(workspace_id, root_goal_task_id)
            .await?;
        if child_tasks.is_empty() {
            child_tasks = select_root_progress_child_tasks(
                self.store
                    .list_tasks_by_root_goal_task_id(workspace_id, root_goal_task_id)
                    .await?,
            );
        }

        let active_child_task_ids = child_tasks
            .iter()
            .filter(|task| task.status != "done" && task.archived_at.is_none())
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let blocked_tasks = child_tasks
            .iter()
            .filter(|task| task.status == "blocked")
            .collect::<Vec<_>>();
        let blocked_child_task_ids = blocked_tasks
            .iter()
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let in_progress_count = child_tasks
            .iter()
            .filter(|task| task.status == "in_progress")
            .count();
        let done_count = child_tasks
            .iter()
            .filter(|task| task.status == "done")
            .count();
        let assigned_count = child_tasks
            .iter()
            .filter(|task| task.assignee_agent_id.is_some() || task.assignee_user_id.is_some())
            .count();
        let total_count = child_tasks.len();
        let all_children_done = total_count > 0 && done_count == total_count;

        let (goal_health, blocked_reason, remediation_status, remediation_summary) =
            if root_task.status == "done" {
                ("achieved", None, "none", None)
            } else if let Some(blocked_task) = blocked_tasks.first() {
                (
                    "blocked",
                    blocked_task
                        .blocker_reason
                        .clone()
                        .or_else(|| Some(blocked_task.title.clone())),
                    "replan_required",
                    Some(format!(
                        "{} child task(s) blocked; root goal requires replan or intervention",
                        blocked_tasks.len()
                    )),
                )
            } else if in_progress_count > 0 {
                ("healthy", None, "none", None)
            } else if all_children_done {
                (
                "achieved",
                None,
                "ready_for_completion",
                Some(
                    "All child tasks are done; root goal should now validate completion evidence"
                        .to_string(),
                ),
            )
            } else {
                ("healthy", None, "none", None)
            };

        let progress_summary = format!(
            "{done_count}/{total_count} child tasks done; {in_progress_count} in progress; {} blocked; {assigned_count}/{total_count} assigned",
            blocked_tasks.len()
        );
        let mut metadata = object_or_empty(root_task.metadata_json);
        metadata.insert("goal_progress_summary".to_string(), json!(progress_summary));
        metadata.insert("last_progress_at".to_string(), json!(now.to_rfc3339()));
        metadata.insert(
            "active_child_task_ids".to_string(),
            json!(active_child_task_ids),
        );
        metadata.insert(
            "blocked_child_task_ids".to_string(),
            json!(blocked_child_task_ids),
        );
        metadata.insert(
            "blocked_reason".to_string(),
            blocked_reason.map_or(Value::Null, Value::String),
        );
        metadata.insert("goal_health".to_string(), json!(goal_health));
        metadata.insert(REMEDIATION_STATUS.to_string(), json!(remediation_status));
        metadata.insert(
            REMEDIATION_SUMMARY.to_string(),
            remediation_summary.map_or(Value::Null, Value::String),
        );
        root_task.metadata_json = Value::Object(metadata);
        root_task.updated_at = Some(now);
        self.store.save_task(root_task).await?;
        Ok(())
    }

    async fn integrate_accepted_attempt_worktree(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt_id: &str,
        task: &WorkspaceTaskRecord,
        commit_ref: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<Map<String, Value>>> {
        let Some(commit_ref) = commit_ref
            .and_then(commit_ref_token)
            .or_else(|| accepted_attempt_integration_commit_ref(node))
        else {
            return Ok(Some(Map::new()));
        };
        let Some(workspace) = self.store.get_workspace(workspace_id).await? else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "workspace not found",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        let Some(sandbox_code_root) =
            sandbox_code_root_for_integration(&task.metadata_json, &workspace.metadata_json)
        else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "sandbox_code_root is not available for accepted worktree integration",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        let Some(worktree_path) = accepted_attempt_worktree_path(
            node,
            &task.metadata_json,
            &sandbox_code_root,
            attempt_id,
        ) else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "accepted attempt has no worktree_path",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        if normalize_posix_path(&worktree_path) == normalize_posix_path(&sandbox_code_root) {
            let metadata = worktree_integration_metadata(
                "already_merged",
                "accepted attempt already ran in sandbox_code_root",
                attempt_id,
                Some(commit_ref.as_str()),
                Some(worktree_path.as_str()),
                now,
                None,
            );
            self.record_worktree_integration_event(
                workspace_id,
                node,
                attempt_id,
                task,
                &metadata,
                "accepted_worktree_integration_skipped",
                now,
            )
            .await?;
            return Ok(Some(metadata));
        }
        let integration = integrate_accepted_attempt_worktree_with_git(
            Path::new(&sandbox_code_root),
            Path::new(&worktree_path),
            &commit_ref,
        )
        .await?;
        let metadata = worktree_integration_metadata(
            &integration.status,
            &integration.summary,
            attempt_id,
            Some(integration.commit_ref.as_str()),
            Some(worktree_path.as_str()),
            now,
            integration.dirty_signature.as_deref(),
        );
        let event_type = worktree_integration_event_type(&integration.status);
        self.record_worktree_integration_event(
            workspace_id,
            node,
            attempt_id,
            task,
            &metadata,
            event_type,
            now,
        )
        .await?;
        Ok(Some(metadata))
    }

    async fn record_worktree_integration_event(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt_id: &str,
        task: &WorkspaceTaskRecord,
        metadata: &Map<String, Value>,
        event_type: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        self.store
            .create_plan_event(WorkspacePlanEventRecord {
                id: generate_uuid_v4(),
                plan_id: node.plan_id.clone(),
                workspace_id: workspace_id.to_string(),
                node_id: Some(node.id.clone()),
                attempt_id: Some(attempt_id.to_string()),
                event_type: event_type.to_string(),
                source: "workspace_plan.accepted_worktree_integration".to_string(),
                actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                payload_json: json!({
                    "status": metadata.get("worktree_integration_status").cloned().unwrap_or(Value::Null),
                    "summary": metadata.get("worktree_integration_summary").cloned().unwrap_or(Value::Null),
                    "commit_ref": metadata.get("worktree_integration_commit_ref").cloned().unwrap_or(Value::Null),
                    "worktree_path": metadata.get("worktree_integration_worktree_path").cloned().unwrap_or(Value::Null),
                    "workspace_task_id": task.id.clone(),
                    "dirty_signature": metadata.get("worktree_integration_dirty_signature").cloned().unwrap_or(Value::Null),
                }),
                created_at: now,
            })
            .await?;
        Ok(())
    }

    async fn accepted_projection_already_complete(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<bool> {
        let metadata = object_or_empty(node.metadata_json.clone());
        if !accepted_projection_already_complete_base(node, attempt, &metadata) {
            return Ok(false);
        }
        if metadata_string(metadata.get("worktree_integration_status")).as_deref()
            != Some("blocked_dirty_main")
        {
            return Ok(true);
        }
        self.blocked_dirty_main_projection_still_current(workspace_id, node, attempt, &metadata)
            .await
    }

    async fn blocked_dirty_main_projection_still_current(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        metadata: &Map<String, Value>,
    ) -> CoreResult<bool> {
        let task_id = node
            .workspace_task_id
            .as_ref()
            .unwrap_or(&attempt.workspace_task_id);
        let Some(task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(false);
        };
        if task.workspace_id != workspace_id {
            return Ok(false);
        }
        let task_metadata = object_or_empty(task.metadata_json.clone());
        let Some(stored_signature) =
            metadata_string(metadata.get("worktree_integration_dirty_signature")).or_else(|| {
                metadata_string(task_metadata.get("worktree_integration_dirty_signature"))
            })
        else {
            return Ok(false);
        };
        let Some(workspace) = self.store.get_workspace(workspace_id).await? else {
            return Ok(false);
        };
        let Some(sandbox_code_root) =
            sandbox_code_root_for_integration(&task.metadata_json, &workspace.metadata_json)
        else {
            return Ok(false);
        };
        let current = current_worktree_dirty_signature(Path::new(&sandbox_code_root)).await?;
        Ok(current.as_deref() == Some(stored_signature.as_str()))
    }

    async fn reconcile_terminal_attempt_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            let Some(attempt_id) = recoverable_node_attempt_id(&node) else {
                continue;
            };
            let Some(attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            let status = attempt.status.trim().to_ascii_lowercase();
            if terminal_attempt_pending_pipeline_verification(&node, &status) {
                continue;
            }
            if !TERMINAL_RETRY_ATTEMPT_STATUSES.contains(&status.as_str()) {
                continue;
            }
            if let Some(accepted_attempt) = self
                .reconciling_accepted_attempt_for_terminal_attempt(workspace_id, &node, &attempt)
                .await?
            {
                let now = Utc::now();
                let evidence_refs = accepted_attempt_evidence_refs(&accepted_attempt);
                let commit_ref = first_valid_commit_ref(&evidence_refs);
                let git_diff_summary = first_prefixed_ref(&evidence_refs, "git_diff_summary:");
                let test_commands = prefixed_refs(&evidence_refs, "test_run:");
                let summary = accepted_attempt_summary(&accepted_attempt);
                let Some(integration_metadata) = self
                    .project_accepted_attempt_to_task(
                        workspace_id,
                        &node,
                        &accepted_attempt,
                        &summary,
                        &evidence_refs,
                        commit_ref.as_deref(),
                        git_diff_summary.as_deref(),
                        &test_commands,
                        now,
                    )
                    .await?
                else {
                    continue;
                };

                let mut metadata =
                    accepted_attempt_projection_base_metadata(&node, &accepted_attempt);
                metadata.insert(
                    "terminal_attempt_status".to_string(),
                    json!(ACCEPTED_ATTEMPT_STATUS),
                );
                metadata.insert(
                    "terminal_attempt_reconciled_at".to_string(),
                    json!(now.to_rfc3339()),
                );
                metadata.insert(
                    "terminal_attempt_superseded_attempt_id".to_string(),
                    json!(attempt.id.clone()),
                );
                metadata.insert(
                    "terminal_attempt_superseded_status".to_string(),
                    json!(status.clone()),
                );
                if let Some(reason) = attempt
                    .adjudication_reason
                    .as_deref()
                    .or(attempt.leader_feedback.as_deref())
                {
                    metadata.insert(
                        "terminal_attempt_superseded_reason".to_string(),
                        json!(reason),
                    );
                }
                metadata.insert("last_verification_summary".to_string(), json!(summary));
                metadata.insert("last_verification_passed".to_string(), json!(true));
                metadata.insert("last_verification_hard_fail".to_string(), json!(false));
                metadata.insert(
                    "last_verification_attempt_id".to_string(),
                    json!(accepted_attempt.id.clone()),
                );
                metadata.insert(
                    "last_verification_ran_at".to_string(),
                    json!(now.to_rfc3339()),
                );
                if !accepted_attempt.candidate_artifacts_json.is_empty() {
                    metadata.insert(
                        "candidate_artifacts".to_string(),
                        json!(accepted_attempt.candidate_artifacts_json.clone()),
                    );
                }
                if !accepted_attempt.candidate_verifications_json.is_empty() {
                    metadata.insert(
                        "candidate_verifications".to_string(),
                        json!(accepted_attempt.candidate_verifications_json.clone()),
                    );
                }
                metadata.extend(integration_metadata);

                node.intent = "done".to_string();
                node.execution = "idle".to_string();
                node.current_attempt_id = Some(accepted_attempt.id.clone());
                node.feature_checkpoint_json =
                    accepted_attempt_projection_feature_checkpoint(&node, &accepted_attempt);
                node.metadata_json = Value::Object(metadata);
                node.updated_at = Some(now);
                self.store.save_plan_node(node).await?;
                changed += 1;
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let node_id = node.id.clone();
            let retry_reason = format!("terminal_attempt_{status}");
            let retry_exhausted = release_node_for_terminal_retry(
                &mut node,
                &retry_reason,
                now,
                plan_terminal_attempt_max_retries(),
            );
            self.store.save_plan_node(node).await?;
            changed += 1;

            if retry_exhausted {
                continue;
            }
            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node_id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    Some(&attempt_id),
                    &retry_reason,
                    now,
                ))
                .await?;
        }
        Ok(changed)
    }

    async fn reconcile_supervisor_retry_same_node_attempt_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if !supervisor_retry_same_node_reconcilable_node(&node) {
                continue;
            }
            let mut metadata = object_or_empty(node.metadata_json.clone());
            if metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
                != Some(SUPERVISOR_DECISION_RETRY_SAME_NODE_ACTION)
            {
                continue;
            }
            let Some(attempt_id) = node.current_attempt_id.clone() else {
                continue;
            };
            let Some(attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            if attempt.status.trim().to_ascii_lowercase() != AWAITING_LEADER_ADJUDICATION_STATUS {
                continue;
            }
            if !attempt_has_candidate_output(&attempt) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let summary = supervisor_retry_same_node_summary(&metadata, &attempt);
            let retry_not_before =
                future_metadata_datetime_utc(metadata.get("retry_not_before"), now);
            let Some(rejected_attempt) = self
                .store
                .finish_task_session_attempt(
                    &attempt_id,
                    REJECTED_ATTEMPT_STATUS,
                    Some(&summary),
                    Some(SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON),
                    now,
                )
                .await?
            else {
                continue;
            };

            let node_id = node.id.clone();
            let retry_exhausted = release_node_for_terminal_retry(
                &mut node,
                SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON,
                now,
                plan_terminal_attempt_max_retries(),
            );
            metadata = object_or_empty(node.metadata_json.clone());
            metadata.insert(
                "supervisor_decision_retry_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "supervisor_decision_retry_attempt_id".to_string(),
                json!(rejected_attempt.id.clone()),
            );
            metadata.insert(
                "supervisor_decision_retry_attempt_status".to_string(),
                json!(REJECTED_ATTEMPT_STATUS),
            );
            node.metadata_json = Value::Object(metadata.clone());
            self.store.save_plan_node(node).await?;
            changed += 1;

            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node_id.clone()),
                    attempt_id: Some(rejected_attempt.id.clone()),
                    event_type: "supervisor_decision_retry_same_node_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "reason": SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON,
                        "action": SUPERVISOR_DECISION_RETRY_SAME_NODE_ACTION,
                        "rationale": metadata.get("last_supervisor_decision_rationale").cloned().unwrap_or(Value::Null),
                        "confidence": metadata.get("last_supervisor_decision_confidence").cloned().unwrap_or(Value::Null),
                        "feedback_items": metadata.get("last_supervisor_decision_feedback_items").cloned().unwrap_or(Value::Null),
                        "workspace_task_id": context.task_id.clone(),
                        "retry_exhausted": retry_exhausted,
                    }),
                    created_at: now,
                })
                .await?;

            if retry_exhausted {
                continue;
            }
            let mut retry_outbox = supervisor_retry_attempt_outbox(
                item,
                payload,
                workspace_id,
                plan_id,
                &node_id,
                &context.task_id,
                &context.worker_agent_id,
                &context.actor_user_id,
                &context.leader_agent_id,
                context.root_goal_task_id.as_deref(),
                Some(&attempt_id),
                SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON,
                now,
            );
            if let Some(retry_at) = retry_not_before {
                retry_outbox.next_attempt_at = Some(retry_at);
                if let Value::Object(retry_payload) = &mut retry_outbox.payload_json {
                    retry_payload
                        .insert("retry_not_before".to_string(), json!(retry_at.to_rfc3339()));
                }
            }
            self.store.enqueue_plan_outbox(retry_outbox).await?;
        }
        Ok(changed)
    }

    async fn reconciling_accepted_attempt_for_terminal_attempt(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        terminal_attempt: &WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let Some(accepted_attempt) = self
            .store
            .find_latest_accepted_task_session_attempt(
                workspace_id,
                &terminal_attempt.workspace_task_id,
            )
            .await?
        else {
            return Ok(None);
        };
        if accepted_attempt.id == terminal_attempt.id {
            return Ok(None);
        }
        if !accepted_attempt_matches_node_expected_commit(node, &accepted_attempt) {
            return Ok(None);
        }
        if accepted_attempt.attempt_number > terminal_attempt.attempt_number
            || attempt_cancelled_because_parent_done_without_output(terminal_attempt)
        {
            return Ok(Some(accepted_attempt));
        }
        Ok(None)
    }

    async fn reconcile_reported_attempt_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let now = Utc::now();
        let mut changed = Vec::new();
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if !reported_reconcilable_node(&node) {
                continue;
            }
            let Some(attempt_id) = node.current_attempt_id.as_deref() else {
                continue;
            };
            let Some(attempt) = self.store.get_task_session_attempt(attempt_id).await? else {
                continue;
            };
            if attempt.status != AWAITING_LEADER_ADJUDICATION_STATUS {
                continue;
            }
            if !attempt_has_candidate_output(&attempt) {
                continue;
            }

            let mut metadata = object_or_empty(node.metadata_json.clone());
            metadata.insert(
                "reported_attempt_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "reported_attempt_status".to_string(),
                json!(AWAITING_LEADER_ADJUDICATION_STATUS),
            );
            node.execution = "reported".to_string();
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            changed.push(node);
        }

        if let Some(first) = changed.first() {
            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(first.id.clone()),
                    attempt_id: first.current_attempt_id.clone(),
                    event_type: "auto_reported_attempt_reconciled".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "reason": "active_plan_node_points_to_reported_attempt",
                        "node_ids": changed.iter().map(|node| node.id.clone()).collect::<Vec<_>>()
                    }),
                    created_at: now,
                })
                .await?;
        }

        Ok(changed.len())
    }

    async fn retry_context_for_node(
        &self,
        payload: &Map<String, Value>,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
    ) -> CoreResult<Option<SupervisorRetryContext>> {
        let Some(task_id) =
            string_from_map(payload, "task_id").or_else(|| node.workspace_task_id.clone())
        else {
            return Ok(None);
        };
        let Some(task) = self.store.get_task(workspace_id, &task_id).await? else {
            return Ok(None);
        };
        let task_metadata = object_or_empty(task.metadata_json.clone());
        let Some(worker_agent_id) = string_from_map(payload, "worker_agent_id")
            .or_else(|| node.assignee_agent_id.clone())
            .or_else(|| task.assignee_agent_id.clone())
        else {
            return Ok(None);
        };
        let actor_user_id =
            string_from_map(payload, "actor_user_id").unwrap_or_else(|| task.created_by.clone());
        let leader_agent_id = string_from_map(payload, "leader_agent_id")
            .or_else(|| string_from_map(&task_metadata, "leader_agent_id"))
            .unwrap_or_else(|| WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string());
        let root_goal_task_id = string_from_map(payload, ROOT_GOAL_TASK_ID)
            .or_else(|| string_from_map(payload, "root_task_id"))
            .or_else(|| string_from_map(&task_metadata, ROOT_GOAL_TASK_ID));
        Ok(Some(SupervisorRetryContext {
            task_id,
            worker_agent_id,
            actor_user_id,
            leader_agent_id,
            root_goal_task_id,
        }))
    }
}

pub(crate) struct WorkspacePlanOutboxWorker {
    store: Arc<dyn WorkspacePlanOutboxStore>,
    config: WorkspacePlanOutboxWorkerConfig,
    handlers: WorkspacePlanOutboxHandlers,
}

impl WorkspacePlanOutboxWorker {
    pub(crate) fn new(
        store: Arc<dyn WorkspacePlanOutboxStore>,
        config: WorkspacePlanOutboxWorkerConfig,
        handlers: WorkspacePlanOutboxHandlers,
    ) -> Self {
        Self {
            store,
            config,
            handlers,
        }
    }

    pub(crate) fn handler_count(&self) -> usize {
        self.handlers.len()
    }

    pub(crate) fn spawn_if_enabled(self: Arc<Self>) -> Option<WorkspacePlanOutboxWorkerRuntime> {
        if !self.config.autostart {
            return None;
        }
        if !self.config.production_ready {
            eprintln!(
                "[agistack] workspace plan outbox worker: autostart requested but production readiness gate is disabled (set {WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY_ENV}=true after full handler parity); not consuming queue"
            );
            return None;
        }
        let missing_handlers = missing_required_handler_event_types(&self.handlers);
        if !missing_handlers.is_empty() {
            eprintln!(
                "[agistack] workspace plan outbox worker: autostart requested but handlers are incomplete (missing: {}); not consuming queue",
                missing_handlers.join(", ")
            );
            return None;
        }
        let worker = Arc::clone(&self);
        let join = tokio::spawn(async move {
            worker.run_loop().await;
        });
        Some(WorkspacePlanOutboxWorkerRuntime { join: Some(join) })
    }

    pub(crate) async fn run_once(&self) -> CoreResult<WorkspacePlanOutboxRunReport> {
        let now = Utc::now();
        let claimed = self
            .store
            .claim_due(
                self.config.batch_size,
                &self.config.worker_id,
                self.config.lease_seconds,
                now,
            )
            .await?;
        let mut report = WorkspacePlanOutboxRunReport {
            claimed: claimed.len(),
            ..Default::default()
        };
        for item in claimed {
            self.process_item(item, &mut report).await?;
        }
        Ok(report)
    }

    async fn run_loop(self: Arc<Self>) {
        loop {
            if let Err(err) = self.run_once().await {
                eprintln!("[agistack] workspace plan outbox worker poll failed: {err}");
            }
            sleep(Duration::from_millis(
                self.config.poll_interval_millis.max(1),
            ))
            .await;
        }
    }

    async fn process_item(
        &self,
        item: WorkspacePlanOutboxRecord,
        report: &mut WorkspacePlanOutboxRunReport,
    ) -> CoreResult<()> {
        let Some(handler) = self.handlers.get(&item.event_type) else {
            let marked = self
                .store
                .mark_failed(
                    &item.id,
                    &format!("no handler for event_type={}", item.event_type),
                    Some(&self.config.worker_id),
                    Utc::now(),
                )
                .await?;
            if marked {
                report.failed += 1;
                report.missing_handler += 1;
            } else {
                report.skipped += 1;
            }
            return Ok(());
        };

        match handler.handle(item.clone()).await {
            Ok(WorkspacePlanOutboxHandlerOutcome::Complete) => {
                if self
                    .store
                    .mark_completed(&item.id, Some(&self.config.worker_id), Utc::now())
                    .await?
                {
                    report.completed += 1;
                } else {
                    report.skipped += 1;
                }
            }
            Ok(WorkspacePlanOutboxHandlerOutcome::Release { reason }) => {
                if self
                    .store
                    .release_processing(
                        &item.id,
                        reason.as_deref(),
                        Some(&self.config.worker_id),
                        Utc::now(),
                    )
                    .await?
                {
                    report.released += 1;
                } else {
                    report.skipped += 1;
                }
            }
            Err(err) => {
                if self
                    .store
                    .mark_failed(
                        &item.id,
                        &err.to_string(),
                        Some(&self.config.worker_id),
                        Utc::now(),
                    )
                    .await?
                {
                    report.failed += 1;
                } else {
                    report.skipped += 1;
                }
            }
        }
        Ok(())
    }
}

fn positive_i64_env(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn i64_env(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .unwrap_or(default)
}

fn positive_millis_env(name: &str, default_millis: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value > 0.0)
        .map(|seconds| (seconds * 1000.0).ceil().max(1.0) as u64)
        .unwrap_or(default_millis)
}

fn bool_env(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .map(|raw| {
            matches!(
                raw.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(default)
}

fn required_handler_event_types() -> [&'static str; 5] {
    [
        SUPERVISOR_TICK_EVENT,
        WORKER_LAUNCH_EVENT,
        HANDOFF_RESUME_EVENT,
        ATTEMPT_RETRY_EVENT,
        PIPELINE_RUN_REQUESTED_EVENT,
    ]
}

fn missing_required_handler_event_types(handlers: &WorkspacePlanOutboxHandlers) -> Vec<String> {
    required_handler_event_types()
        .into_iter()
        .filter(|event_type| !handlers.contains_key(*event_type))
        .map(ToOwned::to_owned)
        .collect()
}

fn object_or_empty(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

fn string_from_map(map: &Map<String, Value>, key: &str) -> Option<String> {
    map.get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn string_from_value_object(value: &Value, key: &str) -> Option<String> {
    value.as_object().and_then(|map| string_from_map(map, key))
}

fn root_goal_task_id_for_progress(
    task: &WorkspaceTaskRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Option<String> {
    string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).or_else(|| {
        let candidate = attempt.root_goal_task_id.trim();
        if candidate.is_empty() {
            None
        } else {
            Some(candidate.to_string())
        }
    })
}

fn is_goal_root_task(task: &WorkspaceTaskRecord) -> bool {
    string_from_value_object(&task.metadata_json, TASK_ROLE).as_deref() == Some(GOAL_ROOT_TASK_ROLE)
}

fn select_root_progress_child_tasks(
    child_tasks: Vec<WorkspaceTaskRecord>,
) -> Vec<WorkspaceTaskRecord> {
    let plan_projected = child_tasks
        .iter()
        .filter(|task| string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_ID).is_some())
        .cloned()
        .collect::<Vec<_>>();
    if plan_projected.is_empty() {
        child_tasks
    } else {
        plan_projected
    }
}

fn bool_from_map(map: &Map<String, Value>, key: &str) -> bool {
    map.get(key).and_then(Value::as_bool).unwrap_or(false)
}

fn required_string(map: &Map<String, Value>, key: &str) -> CoreResult<String> {
    string_from_map(map, key)
        .ok_or_else(|| CoreError::Storage(format!("{key} is required in outbox payload")))
}

fn persisted_attempt_leader_agent_id(leader_agent_id: &str) -> Option<String> {
    if leader_agent_id == WORKSPACE_PLAN_SYSTEM_ACTOR_ID {
        None
    } else {
        Some(leader_agent_id.to_string())
    }
}

fn recoverable_node_attempt_id(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let attempt_id = node.current_attempt_id.as_deref()?.trim();
    if attempt_id.is_empty() {
        return None;
    }
    if matches!(
        node.execution.as_str(),
        "dispatched" | "running" | "reported" | "verifying"
    ) {
        return Some(attempt_id.to_string());
    }
    if node.execution == "idle"
        && matches!(node.intent.as_str(), "in_progress" | "blocked" | "done")
    {
        return Some(attempt_id.to_string());
    }
    None
}

fn reported_reconcilable_node(node: &WorkspacePlanNodeRecord) -> bool {
    if node
        .current_attempt_id
        .as_deref()
        .is_none_or(|attempt_id| attempt_id.trim().is_empty())
    {
        return false;
    }
    if matches!(
        node.execution.as_str(),
        "dispatched" | "running" | "verifying"
    ) {
        return true;
    }
    node.intent == "in_progress" && node.execution == "idle"
}

fn supervisor_retry_same_node_reconcilable_node(node: &WorkspacePlanNodeRecord) -> bool {
    if node
        .current_attempt_id
        .as_deref()
        .is_none_or(|attempt_id| attempt_id.trim().is_empty())
    {
        return false;
    }
    if matches!(
        node.execution.as_str(),
        "dispatched" | "running" | "reported" | "verifying"
    ) {
        return true;
    }
    node.intent == "in_progress" && node.execution == "idle"
}

fn supervisor_retry_same_node_summary(
    metadata: &Map<String, Value>,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| attempt.leader_feedback.clone())
        .or_else(|| attempt.candidate_summary.clone())
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested same-node retry".to_string())
}

fn future_metadata_datetime_utc(
    value: Option<&Value>,
    now: DateTime<Utc>,
) -> Option<DateTime<Utc>> {
    let due = value
        .and_then(Value::as_str)
        .and_then(|raw| DateTime::parse_from_rfc3339(raw.trim()).ok())
        .map(|parsed| parsed.with_timezone(&Utc))?;
    (due > now).then_some(due)
}

fn is_worker_report_supervisor_tick(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
) -> bool {
    string_from_value_object(&item.metadata_json, "source").as_deref() == Some("worker_report")
        && string_from_map(payload, "node_id").is_some()
        && string_from_map(payload, "attempt_id").is_some()
        && string_from_map(payload, "retry_node_id").is_none()
        && string_from_map(payload, "retry_reason").is_none()
}

fn attempt_has_candidate_output(attempt: &WorkspaceTaskSessionAttemptRecord) -> bool {
    attempt
        .candidate_summary
        .as_deref()
        .is_some_and(|summary| !summary.trim().is_empty())
        || !attempt.candidate_artifacts_json.is_empty()
        || !attempt.candidate_verifications_json.is_empty()
}

fn worker_stream_orphan_report_retry_reason(
    node_metadata: &Map<String, Value>,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Option<String> {
    if metadata_string(node_metadata.get("last_worker_report_type")).as_deref() != Some("blocked")
        || metadata_string(node_metadata.get("launch_state")).as_deref()
            != Some("no_terminal_event")
    {
        return None;
    }
    let summary = attempt.candidate_summary.as_deref()?.trim();
    if !summary.contains("Worker stream stopped without a terminal complete/error event") {
        return None;
    }
    if summary.contains("agent_finished_without_terminal_event") {
        Some("worker_stream_agent_finished_without_terminal_event".to_string())
    } else if summary.contains("agent_not_running_stream_idle") {
        Some("worker_stream_agent_not_running_stream_idle".to_string())
    } else {
        Some("worker_stream_no_terminal_event".to_string())
    }
}

fn accepted_projection_already_complete_base(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    metadata: &Map<String, Value>,
) -> bool {
    node.intent == "done"
        && node.execution == "idle"
        && metadata
            .get("terminal_attempt_status")
            .and_then(Value::as_str)
            == Some(ACCEPTED_ATTEMPT_STATUS)
        && metadata
            .get("last_verification_attempt_id")
            .and_then(Value::as_str)
            == Some(attempt.id.as_str())
        && accepted_worktree_projection_complete_for_node(node, attempt, &metadata)
}

fn accepted_attempt_summary(attempt: &WorkspaceTaskSessionAttemptRecord) -> String {
    attempt
        .leader_feedback
        .as_deref()
        .or(attempt.candidate_summary.as_deref())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("accepted terminal attempt")
        .to_string()
}

fn done_idle_node_has_accepted_supervisor_judge(node: &WorkspacePlanNodeRecord) -> bool {
    if node.intent != "done" || node.execution != "idle" || node.current_attempt_id.is_none() {
        return false;
    }
    metadata_string(
        object_or_empty(node.metadata_json.clone()).get("last_verification_judge_verdict"),
    )
    .map(|value| value.eq_ignore_ascii_case(ACCEPTED_ATTEMPT_STATUS))
    .unwrap_or(false)
}

fn accepted_supervisor_judge_summary(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> String {
    let metadata = object_or_empty(node.metadata_json.clone());
    metadata_string(metadata.get("last_verification_summary"))
        .or_else(|| attempt.leader_feedback.clone())
        .or_else(|| attempt.candidate_summary.clone())
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "accepted terminal attempt".to_string())
}

fn supervisor_dispose_metadata_present(node: &WorkspacePlanNodeRecord) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_DISPOSE_NODE_ACTION)
        || metadata_string(metadata.get("verification_feedback_disposition")).as_deref()
            == Some(SUPERVISOR_DISPOSED_NODE_DISPOSITION)
}

fn supervisor_disposition_value(metadata: &Map<String, Value>) -> String {
    let event_payload = supervisor_disposition_event_payload(metadata);
    if let Some(disposition) = metadata_string(event_payload.get("disposition")) {
        return disposition.chars().take(120).collect();
    }
    metadata_string(metadata.get("verification_feedback_disposition"))
        .map(|value| value.chars().take(120).collect::<String>())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| SUPERVISOR_DISPOSED_NODE_DISPOSITION.to_string())
}

fn supervisor_disposition_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "disposed by workspace supervisor".to_string())
}

fn supervisor_disposition_event_payload(metadata: &Map<String, Value>) -> Map<String, Value> {
    match metadata.get("last_supervisor_decision_event_payload") {
        Some(Value::Object(payload)) => payload.clone(),
        _ => Map::new(),
    }
}

fn copy_supervisor_disposition_event_payload_fields(
    node_metadata: &Map<String, Value>,
    task_metadata: &mut Map<String, Value>,
) {
    let event_payload = supervisor_disposition_event_payload(node_metadata);
    for key in [
        "superseded_by_task_id",
        "superseded_by_node_id",
        "disposed_node_id",
    ] {
        if let Some(value) = metadata_string(event_payload.get(key)) {
            task_metadata.insert(key.to_string(), json!(value));
        }
    }
}

fn accepted_attempt_projection_base_metadata(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Map<String, Value> {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    metadata.remove("terminal_attempt_retry_count");
    metadata.remove("terminal_attempt_retry_reason");
    metadata.remove("retry_not_before");
    if !attempt_commit_refs(attempt).is_empty() {
        return metadata;
    }
    for key in NO_COMMIT_ACCEPTED_ATTEMPT_STALE_METADATA_KEYS {
        metadata.remove(key);
    }
    metadata
}

fn accepted_attempt_projection_feature_checkpoint(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Option<Value> {
    if !attempt_commit_refs(attempt).is_empty() || node.feature_checkpoint_json.is_none() {
        return node.feature_checkpoint_json.clone();
    }
    reset_feature_checkpoint(node.feature_checkpoint_json.clone())
}

fn accepted_worktree_projection_complete_for_node(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    metadata: &Map<String, Value>,
) -> bool {
    let has_commit_for_integration = !attempt_commit_refs(attempt).is_empty()
        || accepted_attempt_integration_commit_ref(node).is_some();
    if !has_commit_for_integration {
        return true;
    }
    let status = metadata_string(metadata.get("worktree_integration_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    WORKTREE_INTEGRATION_DONE_STATUSES.contains(&status.as_str())
}

fn done_node_needs_worktree_integration_retry(node: &WorkspacePlanNodeRecord) -> bool {
    if node.intent != "done" || node.execution != "idle" {
        return false;
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    if metadata_string(metadata.get("worktree_integration_status")).as_deref() != Some("failed") {
        return false;
    }
    dependency_commit_needs_integration(node, &metadata)
}

fn dependency_commit_needs_integration(
    node: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
) -> bool {
    if node_disposition_satisfies_dependency_without_integration(metadata) {
        return false;
    }
    if node_verified_commit_ref(node).is_none() {
        return false;
    }
    let Some(worktree_path) = node_attempt_worktree_path(node, metadata) else {
        return false;
    };
    if !looks_like_attempt_worktree(&worktree_path) {
        return false;
    }
    let status = metadata_string(metadata.get("worktree_integration_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    if status == "failed"
        && metadata
            .get("terminal_attempt_status")
            .and_then(Value::as_str)
            == Some("accepted")
        && metadata
            .get("worktree_integration_dirty_signature")
            .is_none_or(Value::is_null)
        && metadata_string(metadata.get("worktree_integration_summary"))
            .unwrap_or_default()
            .to_ascii_lowercase()
            .contains("commit_ref not found in attempt worktree")
    {
        return false;
    }
    !matches!(status.as_str(), "merged" | "already_merged" | "skipped")
}

fn dirty_main_dependency_dispatch_candidate(node: &WorkspacePlanNodeRecord) -> bool {
    if node.intent != "todo" || node.execution != "idle" || node.depends_on_json.is_empty() {
        return false;
    }
    if node
        .current_attempt_id
        .as_deref()
        .is_some_and(|attempt_id| !attempt_id.trim().is_empty())
    {
        return false;
    }
    if node.workspace_task_id.as_deref().is_none_or(str::is_empty) {
        return false;
    }
    metadata_string(
        object_or_empty(node.metadata_json.clone()).get("dirty_main_dependency_dispatch_outbox_id"),
    )
    .is_none()
}

fn dependency_dispatch_blockers(
    node: &WorkspacePlanNodeRecord,
    nodes_by_id: &HashMap<String, WorkspacePlanNodeRecord>,
) -> (Vec<String>, Vec<String>) {
    let metadata = object_or_empty(node.metadata_json.clone());
    let repair_dependency = metadata_string(metadata.get("blocked_by_repair_node_id"));
    let mut dependency_ids = node.depends_on_json.clone();
    if let Some(repair_dependency) = repair_dependency.as_deref() {
        if !dependency_ids.iter().any(|id| id == repair_dependency) {
            dependency_ids.push(repair_dependency.to_string());
        }
    }
    dependency_ids.sort();
    dependency_ids.dedup();

    let mut blocking = Vec::new();
    let mut dirty_main_seed_dependencies = Vec::new();
    for dependency_id in dependency_ids {
        let Some(dependency) = nodes_by_id.get(&dependency_id) else {
            blocking.push(dependency_id);
            continue;
        };
        if dependency.intent != "done" {
            blocking.push(dependency_id);
            continue;
        }
        let dependency_metadata = object_or_empty(dependency.metadata_json.clone());
        if dependency_commit_needs_integration(dependency, &dependency_metadata) {
            if repair_dependency_can_seed_downstream_worktree(
                node,
                &dependency_id,
                repair_dependency.as_deref(),
                dependency,
                &dependency_metadata,
            ) {
                dirty_main_seed_dependencies.push(dependency_id);
                continue;
            }
            blocking.push(dependency_id);
        }
    }
    (blocking, dirty_main_seed_dependencies)
}

fn repair_dependency_can_seed_downstream_worktree(
    node: &WorkspacePlanNodeRecord,
    dependency_id: &str,
    repair_dependency: Option<&str>,
    dependency: &WorkspacePlanNodeRecord,
    dependency_metadata: &Map<String, Value>,
) -> bool {
    if metadata_string(dependency_metadata.get("worktree_integration_status")).as_deref()
        != Some("blocked_dirty_main")
    {
        return false;
    }
    if dependency_dispatch_commit_ref(dependency).is_none() {
        return false;
    }
    repair_dependency.is_some_and(|repair_dependency| repair_dependency == dependency_id)
        || metadata_string(object_or_empty(node.metadata_json.clone()).get("repair_for_node_id"))
            .is_some()
        || node_is_iteration_artifact(node, "plan", "sprint_backlog")
        || node_is_iteration_artifact(node, "implement", "increment")
        || node_is_iteration_artifact(node, "test", "verification")
        || node_is_iteration_artifact(node, "review", "feedback")
        || node_is_iteration_artifact(node, "deploy", "release_candidate")
        || nodes_repair_same_original(node, dependency)
}

fn node_is_iteration_artifact(node: &WorkspacePlanNodeRecord, phase: &str, artifact: &str) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
    metadata_string(metadata.get("iteration_phase")).as_deref() == Some(phase)
        && metadata_string(metadata.get("scrum_artifact")).as_deref() == Some(artifact)
}

fn nodes_repair_same_original(
    node: &WorkspacePlanNodeRecord,
    dependency: &WorkspacePlanNodeRecord,
) -> bool {
    let node_metadata = object_or_empty(node.metadata_json.clone());
    let dependency_metadata = object_or_empty(dependency.metadata_json.clone());
    let Some(node_repair_for) = metadata_string(node_metadata.get("repair_for_node_id")) else {
        return false;
    };
    metadata_string(dependency_metadata.get("repair_for_node_id")).as_deref()
        == Some(node_repair_for.as_str())
}

fn dependency_base_ref_for_dispatch(
    node: &WorkspacePlanNodeRecord,
    nodes_by_id: &HashMap<String, WorkspacePlanNodeRecord>,
) -> Option<String> {
    let mut candidates = Vec::new();
    for dependency_id in &node.depends_on_json {
        let Some(dependency) = nodes_by_id.get(dependency_id) else {
            continue;
        };
        if dependency.intent != "done" {
            continue;
        }
        let Some(commit_ref) = dependency_dispatch_commit_ref(dependency) else {
            continue;
        };
        let timestamp = dependency
            .completed_at
            .or(dependency.updated_at)
            .unwrap_or(dependency.created_at);
        candidates.push((timestamp, dependency_id.clone(), commit_ref));
    }
    candidates
        .into_iter()
        .max_by(|left, right| left.0.cmp(&right.0).then_with(|| left.1.cmp(&right.1)))
        .map(|(_, _, commit_ref)| commit_ref)
}

fn dependency_dispatch_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let metadata = object_or_empty(node.metadata_json.clone());
    if metadata_string(metadata.get("worktree_integration_status")).as_deref()
        == Some("blocked_dirty_main")
    {
        if let Some(commit_ref) = metadata_string(metadata.get("verified_commit_ref")) {
            return Some(commit_ref);
        }
    }
    for key in [
        "source_publish_commit_ref",
        "worktree_integration_commit_ref",
        "verified_commit_ref",
    ] {
        if let Some(commit_ref) = metadata_string(metadata.get(key)) {
            return Some(commit_ref);
        }
    }
    feature_checkpoint_commit_ref(node)
}

fn feature_checkpoint_with_base_ref(value: Option<Value>, base_ref: &str) -> Option<Value> {
    match value {
        Some(Value::Object(mut checkpoint)) => {
            checkpoint.insert("base_ref".to_string(), json!(base_ref));
            Some(Value::Object(checkpoint))
        }
        other => other,
    }
}

fn node_disposition_satisfies_dependency_without_integration(
    metadata: &Map<String, Value>,
) -> bool {
    metadata_string(metadata.get("verification_feedback_disposition")).as_deref()
        == Some("supervisor_agent_disposed_node")
        && metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
            == Some("dispose_node")
        && metadata_string(metadata.get("last_verification_judge_next_action_kind")).as_deref()
            != Some("retry_same_node")
}

fn node_verified_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let metadata = object_or_empty(node.metadata_json.clone());
    metadata
        .get("verified_commit_ref")
        .and_then(Value::as_str)
        .and_then(commit_ref_token)
        .or_else(|| {
            metadata
                .get("worktree_integration_commit_ref")
                .and_then(Value::as_str)
                .and_then(commit_ref_token)
        })
        .or_else(|| feature_checkpoint_commit_ref(node))
}

fn node_attempt_worktree_path(
    node: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
) -> Option<String> {
    metadata_string(metadata.get("worktree_integration_worktree_path"))
        .or_else(|| metadata_string(metadata.get("active_execution_root")))
        .or_else(|| metadata_string(metadata.get("worktree_path")))
        .or_else(|| {
            metadata_string_from_path(
                node.feature_checkpoint_json
                    .as_ref()
                    .unwrap_or(&Value::Null),
                &["worktree_path"],
            )
        })
}

fn looks_like_attempt_worktree(path: &str) -> bool {
    path.contains("/.memstack/worktrees/")
}

fn clear_failed_worktree_retry_stale_attempt_metadata(
    mut metadata: Map<String, Value>,
) -> Map<String, Value> {
    for key in FAILED_WORKTREE_RETRY_STALE_METADATA_KEYS {
        metadata.remove(*key);
    }
    metadata
}

fn apply_verification_checkpoint_metadata(
    metadata: &mut Map<String, Value>,
    summary: &str,
    commit_ref: Option<&str>,
    git_diff_summary: Option<&str>,
    test_commands: &[String],
    created_at: DateTime<Utc>,
) {
    if commit_ref.is_none() && git_diff_summary.is_none() && test_commands.is_empty() {
        return;
    }
    if let Some(commit_ref) = commit_ref {
        if let Some(Value::Object(feature_checkpoint)) = metadata.get_mut("feature_checkpoint") {
            feature_checkpoint.insert("commit_ref".to_string(), json!(commit_ref));
        }
    }
    let handoff = metadata
        .entry("handoff_package".to_string())
        .or_insert_with(|| {
            json!({
                "reason": "planned",
                "summary": "Accepted by durable plan verifier.",
                "next_steps": [],
                "completed_steps": [],
                "changed_files": [],
                "git_head": Value::Null,
                "git_diff_summary": "",
                "test_commands": [],
                "verification_notes": "",
                "created_at": created_at.to_rfc3339()
            })
        });
    if !handoff.is_object() {
        *handoff = json!({
            "reason": "planned",
            "summary": "Accepted by durable plan verifier.",
            "next_steps": [],
            "completed_steps": [],
            "changed_files": [],
            "git_head": Value::Null,
            "git_diff_summary": "",
            "test_commands": [],
            "verification_notes": "",
            "created_at": created_at.to_rfc3339()
        });
    }
    if let Value::Object(handoff) = handoff {
        if let Some(commit_ref) = commit_ref {
            handoff.insert("git_head".to_string(), json!(commit_ref));
        }
        if let Some(git_diff_summary) = git_diff_summary {
            handoff.insert("git_diff_summary".to_string(), json!(git_diff_summary));
        }
        if !test_commands.is_empty() {
            handoff.insert("test_commands".to_string(), json!(test_commands));
        }
        handoff.insert("verification_notes".to_string(), json!(summary));
    }
}

fn accepted_attempt_integration_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    feature_checkpoint_commit_ref(node).or_else(|| node_expected_commit_ref(node))
}

fn feature_checkpoint_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    if let Some(Value::Object(checkpoint)) = &node.feature_checkpoint_json {
        return checkpoint
            .get("commit_ref")
            .and_then(Value::as_str)
            .and_then(commit_ref_token);
    }
    None
}

fn worktree_integration_metadata(
    status: &str,
    summary: &str,
    attempt_id: &str,
    commit_ref: Option<&str>,
    worktree_path: Option<&str>,
    now: DateTime<Utc>,
    dirty_signature: Option<&str>,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("worktree_integration_status".to_string(), json!(status));
    metadata.insert("worktree_integration_summary".to_string(), json!(summary));
    metadata.insert(
        "worktree_integration_attempt_id".to_string(),
        json!(attempt_id),
    );
    metadata.insert(
        "worktree_integration_ran_at".to_string(),
        json!(now.to_rfc3339()),
    );
    if let Some(commit_ref) = commit_ref {
        metadata.insert(
            "worktree_integration_commit_ref".to_string(),
            json!(commit_ref),
        );
    }
    if let Some(worktree_path) = worktree_path {
        metadata.insert(
            "worktree_integration_worktree_path".to_string(),
            json!(worktree_path),
        );
    }
    metadata.insert(
        "worktree_integration_dirty_signature".to_string(),
        dirty_signature.map_or(Value::Null, |value| json!(value)),
    );
    metadata
}

fn worktree_integration_event_type(status: &str) -> &'static str {
    match status {
        "merged" => "accepted_worktree_integrated",
        "already_merged" | "skipped" => "accepted_worktree_integration_skipped",
        "blocked_dirty_main" => "accepted_worktree_integration_blocked",
        "failed" => "accepted_worktree_integration_failed",
        _ => "accepted_worktree_integration_failed",
    }
}

fn sandbox_code_root_for_integration(
    task_metadata: &Value,
    workspace_metadata: &Value,
) -> Option<String> {
    metadata_string_from_path(task_metadata, &["sandbox_code_root"])
        .or_else(|| {
            metadata_string_from_path(task_metadata, &["code_context", "sandbox_code_root"])
        })
        .or_else(|| metadata_string_from_path(workspace_metadata, &["sandbox_code_root"]))
        .or_else(|| {
            metadata_string_from_path(workspace_metadata, &["code_context", "sandbox_code_root"])
        })
}

fn accepted_attempt_worktree_path(
    node: &WorkspacePlanNodeRecord,
    task_metadata: &Value,
    sandbox_code_root: &str,
    attempt_id: &str,
) -> Option<String> {
    let raw_path = metadata_string_from_path(
        node.feature_checkpoint_json
            .as_ref()
            .unwrap_or(&Value::Null),
        &["worktree_path"],
    )
    .or_else(|| metadata_string_from_path(task_metadata, &["feature_checkpoint", "worktree_path"]))
    .unwrap_or_else(|| default_attempt_worktree_path(sandbox_code_root, attempt_id));
    let path = raw_path.replace("${sandbox_code_root}", sandbox_code_root);
    if path.contains("${sandbox_code_root}") {
        return None;
    }
    Some(normalize_posix_path(&path))
}

fn apply_attempt_worktree_checkpoint(node: &mut WorkspacePlanNodeRecord, attempt_id: &str) {
    let Some(Value::Object(mut checkpoint)) = node.feature_checkpoint_json.clone() else {
        return;
    };
    let base_ref = attempt_retry_base_ref(node)
        .or_else(|| {
            checkpoint
                .get("commit_ref")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
        })
        .or_else(|| {
            checkpoint
                .get("base_ref")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
        })
        .unwrap_or_else(|| "HEAD".to_string());
    checkpoint.insert(
        "worktree_path".to_string(),
        json!(format!(
            "${{sandbox_code_root}}/../.memstack/worktrees/{attempt_id}"
        )),
    );
    checkpoint.insert(
        "branch_name".to_string(),
        json!(worktree_branch_name(&node.id, attempt_id)),
    );
    checkpoint.insert("base_ref".to_string(), json!(base_ref));
    node.feature_checkpoint_json = Some(Value::Object(checkpoint));
}

fn attempt_retry_base_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let metadata = object_or_empty(node.metadata_json.clone());
    for key in [
        "source_publish_commit_ref",
        "source_publish_source_commit_ref",
        "worktree_integration_commit_ref",
        "verified_commit_ref",
        "dirty_main_dependency_base_ref",
    ] {
        if let Some(value) = metadata_string(metadata.get(key)) {
            return Some(value);
        }
    }
    None
}

fn worktree_branch_name(node_id: &str, attempt_id: &str) -> String {
    let node_token = safe_git_token(node_id).chars().take(48).collect::<String>();
    let attempt_token = safe_git_token(attempt_id)
        .chars()
        .take(12)
        .collect::<String>();
    format!("workspace/{node_token}-{attempt_token}")
}

fn safe_git_token(value: &str) -> String {
    let token = value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-') {
                ch
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches(&['.', '/', '-'][..])
        .to_string();
    if token.is_empty() {
        "node".to_string()
    } else {
        token
    }
}

fn default_attempt_worktree_path(sandbox_code_root: &str, attempt_id: &str) -> String {
    normalize_posix_path(&format!(
        "{}/../.memstack/worktrees/{}",
        sandbox_code_root.trim_end_matches('/'),
        attempt_id
    ))
}

fn normalize_posix_path(value: &str) -> String {
    let absolute = value.starts_with('/');
    let mut parts = Vec::new();
    for part in value.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                if !parts.is_empty() {
                    parts.pop();
                } else if !absolute {
                    parts.push("..");
                }
            }
            other => parts.push(other),
        }
    }
    let mut normalized = parts.join("/");
    if absolute {
        normalized.insert(0, '/');
    }
    if normalized.is_empty() {
        if absolute {
            "/".to_string()
        } else {
            ".".to_string()
        }
    } else {
        normalized
    }
}

fn metadata_string_from_path(value: &Value, path: &[&str]) -> Option<String> {
    let mut cursor = value;
    for key in path {
        cursor = cursor.get(*key)?;
    }
    metadata_string(Some(cursor))
}

fn accepted_attempt_matches_node_expected_commit(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> bool {
    let Some(expected) = node_expected_commit_ref(node) else {
        return true;
    };
    let actual_refs = attempt_commit_refs(attempt);
    if actual_refs.is_empty() {
        return last_verified_attempt_matches_expected_commit(node, attempt, &expected);
    }
    if actual_refs
        .iter()
        .any(|actual| git_commit_refs_match(&expected, actual))
    {
        return true;
    }
    last_verified_attempt_contains_attempt_commit(node, attempt, &actual_refs)
}

fn attempt_cancelled_because_parent_done_without_output(
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> bool {
    attempt_cancelled_because_parent_done(attempt) && !attempt_has_candidate_output(attempt)
}

fn attempt_cancelled_because_parent_done(attempt: &WorkspaceTaskSessionAttemptRecord) -> bool {
    if attempt.status.trim().to_ascii_lowercase() != "cancelled" {
        return false;
    }
    attempt.adjudication_reason.as_deref() == Some("recovery:parent_done")
        || attempt.leader_feedback.as_deref() == Some("recovery:parent_done")
}

fn accepted_attempt_evidence_refs(attempt: &WorkspaceTaskSessionAttemptRecord) -> Vec<String> {
    let mut refs = Vec::new();
    for artifact in &attempt.candidate_artifacts_json {
        let artifact = artifact.trim();
        if artifact.is_empty() {
            continue;
        }
        if artifact.starts_with("artifact:") {
            refs.push(artifact.to_string());
        } else {
            refs.push(format!("artifact:{artifact}"));
        }
    }
    for verification in &attempt.candidate_verifications_json {
        let verification = verification.trim();
        if !verification.is_empty() {
            refs.push(verification.to_string());
        }
    }
    dedup_strings(&mut refs);
    refs
}

fn first_valid_commit_ref(refs: &[String]) -> Option<String> {
    refs.iter()
        .filter_map(|reference| prefixed_ref(reference, "commit_ref:"))
        .filter_map(|value| commit_ref_token(&value))
        .next()
}

fn first_prefixed_ref(refs: &[String], prefix: &str) -> Option<String> {
    refs.iter()
        .filter_map(|reference| prefixed_ref(reference, prefix))
        .next()
}

fn prefixed_refs(refs: &[String], prefix: &str) -> Vec<String> {
    refs.iter()
        .filter_map(|reference| prefixed_ref(reference, prefix))
        .collect()
}

fn attempt_commit_refs(attempt: &WorkspaceTaskSessionAttemptRecord) -> Vec<String> {
    let mut refs: Vec<String> = accepted_attempt_evidence_refs(attempt)
        .iter()
        .filter_map(|reference| prefixed_ref(reference, "commit_ref:"))
        .filter_map(|value| commit_ref_token(&value))
        .collect();
    dedup_strings(&mut refs);
    refs
}

fn node_expected_commit_ref(node: &WorkspacePlanNodeRecord) -> Option<String> {
    if let Some(Value::Object(checkpoint)) = &node.feature_checkpoint_json {
        if let Some(token) = commit_ref_token(checkpoint.get("commit_ref")?.as_str()?) {
            return Some(token);
        }
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    for key in [
        "source_publish_source_commit_ref",
        "verified_commit_ref",
        "worktree_integration_commit_ref",
    ] {
        if let Some(token) = metadata
            .get(key)
            .and_then(Value::as_str)
            .and_then(commit_ref_token)
        {
            return Some(token);
        }
    }
    None
}

fn last_verified_attempt_matches_expected_commit(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    expected: &str,
) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
    if metadata
        .get("last_verification_passed")
        .and_then(Value::as_bool)
        != Some(true)
        || metadata
            .get("last_verification_attempt_id")
            .and_then(Value::as_str)
            != Some(attempt.id.as_str())
    {
        return false;
    }
    let mut refs = node_metadata_commit_refs(&metadata);
    for key in [
        "source_publish_source_commit_ref",
        "source_publish_commit_ref",
        "verified_commit_ref",
        "worktree_integration_commit_ref",
    ] {
        if let Some(token) = metadata
            .get(key)
            .and_then(Value::as_str)
            .and_then(commit_ref_token)
        {
            refs.push(token);
        }
    }
    dedup_strings(&mut refs);
    refs.iter()
        .any(|metadata_ref| git_commit_refs_match(expected, metadata_ref))
}

fn last_verified_attempt_contains_attempt_commit(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    actual_refs: &[String],
) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
    if metadata
        .get("last_verification_passed")
        .and_then(Value::as_bool)
        != Some(true)
        || metadata
            .get("last_verification_attempt_id")
            .and_then(Value::as_str)
            != Some(attempt.id.as_str())
    {
        return false;
    }
    let metadata_refs = node_metadata_commit_refs(&metadata);
    metadata_refs.iter().any(|metadata_ref| {
        actual_refs
            .iter()
            .any(|actual_ref| git_commit_refs_match(metadata_ref, actual_ref))
    })
}

fn node_metadata_commit_refs(metadata: &Map<String, Value>) -> Vec<String> {
    let mut refs = Vec::new();
    for key in [
        "verification_evidence_refs",
        "candidate_artifacts",
        "candidate_verifications",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "execution_verifications",
    ] {
        for value in metadata_string_values(metadata.get(key)) {
            if let Some(token) = prefixed_ref(&value, "commit_ref:")
                .and_then(|candidate| commit_ref_token(&candidate))
            {
                refs.push(token);
            }
        }
    }
    dedup_strings(&mut refs);
    refs
}

fn prefixed_ref(reference: &str, prefix: &str) -> Option<String> {
    let trimmed = reference.trim();
    if trimmed.starts_with(prefix) {
        return Some(trimmed[prefix.len()..].trim().to_string());
    }
    let artifact_prefix = format!("artifact:{prefix}");
    if trimmed.starts_with(&artifact_prefix) {
        return Some(trimmed[artifact_prefix.len()..].trim().to_string());
    }
    None
}

fn commit_ref_token(value: &str) -> Option<String> {
    let token = value.split_whitespace().next()?.trim();
    if (6..=40).contains(&token.len()) && token.chars().all(|ch| ch.is_ascii_hexdigit()) {
        Some(token.to_string())
    } else {
        None
    }
}

fn git_commit_refs_match(left: &str, right: &str) -> bool {
    let left = left.trim();
    let right = right.trim();
    if left.is_empty() || right.is_empty() {
        return false;
    }
    left == right
        || (left.len() >= 7 && right.starts_with(left))
        || (right.len() >= 7 && left.starts_with(right))
}

fn metadata_string_values(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(values)) => values
            .iter()
            .filter_map(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned)
            .collect(),
        Some(Value::String(value)) if !value.trim().is_empty() => vec![value.trim().to_string()],
        _ => Vec::new(),
    }
}

fn reset_feature_checkpoint(value: Option<Value>) -> Option<Value> {
    match value {
        Some(Value::Object(mut checkpoint)) => {
            checkpoint.insert("worktree_path".to_string(), Value::Null);
            checkpoint.insert("branch_name".to_string(), Value::Null);
            checkpoint.insert("base_ref".to_string(), json!("HEAD"));
            checkpoint.insert("commit_ref".to_string(), Value::Null);
            Some(Value::Object(checkpoint))
        }
        other => other,
    }
}

fn dedup_strings(values: &mut Vec<String>) {
    let mut deduped = Vec::with_capacity(values.len());
    for value in values.drain(..) {
        if !deduped.contains(&value) {
            deduped.push(value);
        }
    }
    *values = deduped;
}

fn terminal_attempt_pending_pipeline_verification(
    node: &WorkspacePlanNodeRecord,
    status: &str,
) -> bool {
    if node_waiting_for_verification_retry(node) {
        return true;
    }
    if node_has_pipeline_gate_in_flight(node, status) {
        return true;
    }
    if node.execution != "reported" || status == "accepted" {
        return false;
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    let pipeline_status = metadata_string(metadata.get("pipeline_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !matches!(
        pipeline_status.as_str(),
        "failed" | "failure" | "error" | "success"
    ) {
        return false;
    }
    metadata_string(metadata.get("pipeline_run_id")).is_some()
        || metadata_string(metadata.get("external_id")).is_some()
}

fn node_waiting_for_verification_retry(node: &WorkspacePlanNodeRecord) -> bool {
    node.execution == "reported"
        && object_or_empty(node.metadata_json.clone())
            .get("retry_verification_only")
            .and_then(Value::as_bool)
            == Some(true)
}

fn node_has_pipeline_gate_in_flight(node: &WorkspacePlanNodeRecord, status: &str) -> bool {
    if status == "accepted" || node.intent != "in_progress" {
        return false;
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    let pipeline_status = metadata_string(metadata.get("pipeline_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    let gate_status = metadata_string(metadata.get("pipeline_gate_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    matches!(
        pipeline_status.as_str(),
        "requested" | "running" | "processing"
    ) || matches!(gate_status.as_str(), "requested" | "running" | "processing")
}

fn metadata_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn copy_retry_context_payload_fields(source: &Map<String, Value>, target: &mut Map<String, Value>) {
    for key in [
        "previous_attempt_id",
        "retry_attempt_id",
        "retry_reason",
        "retry_origin",
        "worker_stream_orphan_retry_reason",
        "worker_stream_orphan_summary",
    ] {
        if let Some(value) = source.get(key).filter(|value| !value.is_null()) {
            target.insert(key.to_string(), value.clone());
        }
    }
}

fn should_reset_attempt_retry_worker_state(event_type: &str, payload: &Map<String, Value>) -> bool {
    event_type == ATTEMPT_RETRY_EVENT
        && (string_from_map(payload, "retry_reason").is_some()
            || string_from_map(payload, "previous_attempt_id").is_some()
            || string_from_map(payload, "retry_attempt_id").is_some()
            || metadata_string(payload.get("retry_origin")).is_some()
            || metadata_string(payload.get("worker_stream_orphan_retry_reason")).is_some()
            || metadata_string(payload.get("worker_stream_orphan_summary")).is_some())
}

fn clear_attempt_retry_worker_stream_state(metadata: &mut Map<String, Value>) {
    for key in ATTEMPT_RETRY_STALE_WORKER_STREAM_METADATA_KEYS {
        metadata.remove(*key);
    }
}

fn worker_stream_replay_metadata_matches_attempt(
    metadata: &Map<String, Value>,
    attempt_id: &str,
) -> bool {
    string_from_map(metadata, "worker_stream_replay_attempt_id")
        .or_else(|| string_from_map(metadata, LAST_WORKER_REPORT_ATTEMPT_ID))
        .as_deref()
        .is_none_or(|recorded_attempt_id| recorded_attempt_id == attempt_id)
}

fn copy_metadata_string_field(
    source: &Map<String, Value>,
    target: &mut Map<String, Value>,
    key: &str,
) {
    if let Some(value) = metadata_string(source.get(key)) {
        target.insert(key.to_string(), json!(value));
    }
}

fn apply_attempt_retry_context(
    metadata: &mut Map<String, Value>,
    payload: &Map<String, Value>,
    now: DateTime<Utc>,
) {
    let mut has_retry_context = false;
    if let Some(retry_reason) = string_from_map(payload, "retry_reason") {
        metadata.insert("last_retry_reason".to_string(), json!(retry_reason));
        has_retry_context = true;
    }
    if let Some(previous_attempt_id) = string_from_map(payload, "previous_attempt_id")
        .or_else(|| string_from_map(payload, "retry_attempt_id"))
    {
        metadata.insert(
            "last_retry_previous_attempt_id".to_string(),
            json!(previous_attempt_id),
        );
        has_retry_context = true;
    }
    for key in [
        "retry_origin",
        "worker_stream_orphan_retry_reason",
        "worker_stream_orphan_summary",
    ] {
        if let Some(value) = metadata_string(payload.get(key)) {
            metadata.insert(key.to_string(), json!(value));
            has_retry_context = true;
        }
    }
    if has_retry_context {
        metadata.insert("last_retry_context_at".to_string(), json!(now.to_rfc3339()));
    }
}

fn release_node_for_terminal_retry(
    node: &mut WorkspacePlanNodeRecord,
    reason: &str,
    now: DateTime<Utc>,
    max_retries: i64,
) -> bool {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    let retry_count = metadata
        .get("terminal_attempt_retry_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "terminal_attempt_retry_count".to_string(),
        json!(retry_count),
    );
    metadata.insert("terminal_attempt_retry_reason".to_string(), json!(reason));
    metadata.insert(
        "terminal_attempt_reconciled_at".to_string(),
        json!(now.to_rfc3339()),
    );
    metadata.remove("retry_not_before");

    let retry_exhausted = retry_count > max_retries;
    node.intent = if retry_exhausted {
        "blocked".to_string()
    } else {
        "todo".to_string()
    };
    node.execution = "idle".to_string();
    node.current_attempt_id = None;
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
    retry_exhausted
}

fn plan_terminal_attempt_max_retries() -> i64 {
    positive_i64_env(
        PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV,
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES,
    )
}

#[allow(clippy::too_many_arguments)]
fn worker_launch_outbox(
    plan_id: Option<&str>,
    workspace_id: &str,
    source_event_type: &str,
    payload: &Map<String, Value>,
    task_id: &str,
    worker_agent_id: &str,
    actor_user_id: &str,
    leader_agent_id: &str,
    attempt_id: &str,
    node_id: Option<&str>,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut launch_payload = Map::new();
    launch_payload.insert("workspace_id".to_string(), json!(workspace_id));
    launch_payload.insert("task_id".to_string(), json!(task_id));
    launch_payload.insert("worker_agent_id".to_string(), json!(worker_agent_id));
    launch_payload.insert("actor_user_id".to_string(), json!(actor_user_id));
    launch_payload.insert("leader_agent_id".to_string(), json!(leader_agent_id));
    launch_payload.insert("attempt_id".to_string(), json!(attempt_id));
    if let Some(node_id) = node_id {
        launch_payload.insert("node_id".to_string(), json!(node_id));
    }
    for optional_key in [
        "extra_instructions",
        "reuse_conversation_id",
        "repair_brief_prompt",
    ] {
        if let Some(value) = payload.get(optional_key) {
            launch_payload.insert(optional_key.to_string(), value.clone());
        }
    }
    copy_retry_context_payload_fields(payload, &mut launch_payload);
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: plan_id.map(ToOwned::to_owned),
        workspace_id: workspace_id.to_string(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(launch_payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": format!("workspace_plan.{source_event_type}"),
            "previous_attempt_id": string_from_map(payload, "previous_attempt_id")
        }),
        created_at,
        updated_at: None,
    }
}

fn deferred_worker_launch_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    active_count: i64,
    max_active: i64,
    delay_seconds: i64,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut metadata = object_or_empty(item.metadata_json.clone());
    let defer_count = metadata
        .get("defer_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "source".to_string(),
        json!("workspace_plan.worker_launch.deferred_capacity"),
    );
    metadata.insert(
        "deferred_from_outbox_id".to_string(),
        json!(item.id.clone()),
    );
    metadata.insert("defer_count".to_string(), json!(defer_count));
    metadata.insert(
        "active_worker_conversations".to_string(),
        json!(active_count),
    );
    metadata.insert(
        "max_active_worker_conversations".to_string(),
        json!(max_active),
    );
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: item.plan_id.clone(),
        workspace_id: item.workspace_id.clone(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(payload.clone()),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: item.max_attempts,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: Some(now + ChronoDuration::seconds(delay_seconds.max(1))),
        processed_at: None,
        metadata_json: Value::Object(metadata),
        created_at: now,
        updated_at: None,
    }
}

fn worker_stream_poll_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    conversation_id: &str,
    replay: &WorkerStreamReplayResult,
    delay_seconds: i64,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut poll_payload = payload.clone();
    poll_payload.insert("worker_stream_poll".to_string(), json!(true));
    poll_payload.insert("stream_after_id".to_string(), json!(replay.next_after_id()));
    poll_payload.insert(
        "worker_stream_poll_conversation_id".to_string(),
        json!(conversation_id),
    );
    poll_payload.remove("reuse_conversation_id");

    let mut metadata = object_or_empty(item.metadata_json.clone());
    let poll_count = metadata
        .get("stream_poll_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "source".to_string(),
        json!("workspace_plan.worker_launch.stream_poll"),
    );
    metadata.insert(
        "stream_poll_from_outbox_id".to_string(),
        json!(item.id.clone()),
    );
    metadata.insert("stream_poll_count".to_string(), json!(poll_count));
    metadata.insert(
        "stream_poll_after_id".to_string(),
        json!(replay.next_after_id()),
    );
    metadata.insert(
        "stream_poll_conversation_id".to_string(),
        json!(conversation_id),
    );
    metadata.insert(
        "stream_poll_entries_read".to_string(),
        json!(replay.entries_read),
    );

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: item.plan_id.clone(),
        workspace_id: item.workspace_id.clone(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(poll_payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: item.max_attempts,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: Some(now + ChronoDuration::seconds(delay_seconds.max(1))),
        processed_at: None,
        metadata_json: Value::Object(metadata),
        created_at: now,
        updated_at: None,
    }
}

#[allow(clippy::too_many_arguments)]
fn worker_report_supervisor_tick(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    attempt_id: &str,
    root_goal_task_id: &str,
    actor_user_id: &str,
    leader_agent_id: Option<&str>,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: SUPERVISOR_TICK_EVENT.to_string(),
        payload_json: json!({
            "workspace_id": workspace_id,
            "root_task_id": root_goal_task_id,
            "actor_user_id": actor_user_id,
            "leader_agent_id": leader_agent_id,
            "plan_id": plan_id,
            "node_id": node_id,
            "attempt_id": attempt_id
        }),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 3,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "worker_report",
            "node_id": node_id,
            "attempt_id": attempt_id
        }),
        created_at: now,
        updated_at: None,
    }
}

#[allow(clippy::too_many_arguments)]
fn supervisor_retry_attempt_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    task_id: &str,
    worker_agent_id: &str,
    actor_user_id: &str,
    leader_agent_id: &str,
    root_goal_task_id: Option<&str>,
    retry_attempt_id: Option<&str>,
    retry_reason: &str,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut retry_payload = Map::new();
    retry_payload.insert("workspace_id".to_string(), json!(workspace_id));
    retry_payload.insert("plan_id".to_string(), json!(plan_id));
    retry_payload.insert("node_id".to_string(), json!(node_id));
    retry_payload.insert("task_id".to_string(), json!(task_id));
    retry_payload.insert("worker_agent_id".to_string(), json!(worker_agent_id));
    retry_payload.insert("actor_user_id".to_string(), json!(actor_user_id));
    retry_payload.insert("leader_agent_id".to_string(), json!(leader_agent_id));
    retry_payload.insert("retry_reason".to_string(), json!(retry_reason));
    if let Some(root_goal_task_id) = root_goal_task_id {
        retry_payload.insert(ROOT_GOAL_TASK_ID.to_string(), json!(root_goal_task_id));
    }
    if let Some(retry_attempt_id) = retry_attempt_id {
        retry_payload.insert("previous_attempt_id".to_string(), json!(retry_attempt_id));
        retry_payload.insert("retry_attempt_id".to_string(), json!(retry_attempt_id));
    }
    for optional_key in [
        "extra_instructions",
        "force_schedule",
        "repair_brief_prompt",
        "reuse_conversation_id",
    ] {
        if let Some(value) = payload.get(optional_key) {
            retry_payload.insert(optional_key.to_string(), value.clone());
        }
    }
    copy_retry_context_payload_fields(payload, &mut retry_payload);

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: ATTEMPT_RETRY_EVENT.to_string(),
        payload_json: Value::Object(retry_payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: item.max_attempts,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "workspace_plan.supervisor_tick.retry_admission",
            "previous_outbox_id": item.id,
            "retry_node_id": node_id,
            "retry_attempt_id": retry_attempt_id,
            "retry_reason": retry_reason
        }),
        created_at,
        updated_at: None,
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{HashSet, VecDeque};
    use std::process::Command;
    use std::sync::Mutex;

    use agistack_core::ports::CoreError;
    use chrono::{Duration, TimeZone};
    use serde_json::json;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    use super::*;

    #[derive(Default)]
    struct FakeWorkspacePlanOutboxStore {
        items: Mutex<HashMap<String, WorkspacePlanOutboxRecord>>,
    }

    impl FakeWorkspacePlanOutboxStore {
        fn insert(&self, item: WorkspacePlanOutboxRecord) {
            self.items.lock().unwrap().insert(item.id.clone(), item);
        }

        fn get(&self, id: &str) -> WorkspacePlanOutboxRecord {
            self.items.lock().unwrap().get(id).unwrap().clone()
        }
    }

    #[async_trait]
    impl WorkspacePlanOutboxStore for FakeWorkspacePlanOutboxStore {
        async fn claim_due(
            &self,
            limit: i64,
            lease_owner: &str,
            lease_seconds: i64,
            now: DateTime<Utc>,
        ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
            let mut items = self.items.lock().unwrap();
            let mut due = items
                .values()
                .filter(|item| {
                    item.attempt_count < item.max_attempts
                        && ((matches!(item.status.as_str(), "pending" | "failed")
                            && item.next_attempt_at.map(|due| due <= now).unwrap_or(true))
                            || (item.status == "processing"
                                && item
                                    .lease_expires_at
                                    .map(|expires_at| expires_at <= now)
                                    .unwrap_or(false)))
                })
                .map(|item| item.id.clone())
                .collect::<Vec<_>>();
            due.sort();
            due.truncate(limit.max(0) as usize);

            let mut claimed = Vec::new();
            for id in due {
                let item = items.get_mut(&id).unwrap();
                item.status = "processing".to_string();
                item.attempt_count += 1;
                item.lease_owner = Some(lease_owner.to_string());
                item.lease_expires_at = Some(now + Duration::seconds(lease_seconds.max(1)));
                item.next_attempt_at = None;
                item.last_error = None;
                item.updated_at = Some(now);
                claimed.push(item.clone());
            }
            Ok(claimed)
        }

        async fn mark_completed(
            &self,
            outbox_id: &str,
            lease_owner: Option<&str>,
            now: DateTime<Utc>,
        ) -> CoreResult<bool> {
            let mut items = self.items.lock().unwrap();
            let Some(item) = items.get_mut(outbox_id) else {
                return Ok(false);
            };
            if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
                return Ok(false);
            }
            item.status = "completed".to_string();
            item.lease_owner = None;
            item.lease_expires_at = None;
            item.last_error = None;
            item.next_attempt_at = None;
            item.processed_at = Some(now);
            item.updated_at = Some(now);
            Ok(true)
        }

        async fn mark_failed(
            &self,
            outbox_id: &str,
            error_message: &str,
            lease_owner: Option<&str>,
            now: DateTime<Utc>,
        ) -> CoreResult<bool> {
            let mut items = self.items.lock().unwrap();
            let Some(item) = items.get_mut(outbox_id) else {
                return Ok(false);
            };
            if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
                return Ok(false);
            }
            item.status = if item.attempt_count >= item.max_attempts {
                "dead_letter".to_string()
            } else {
                "failed".to_string()
            };
            item.lease_owner = None;
            item.lease_expires_at = None;
            item.last_error = Some(error_message.to_string());
            item.next_attempt_at = Some(now + Duration::seconds(2));
            item.updated_at = Some(now);
            Ok(true)
        }

        async fn release_processing(
            &self,
            outbox_id: &str,
            error_message: Option<&str>,
            lease_owner: Option<&str>,
            now: DateTime<Utc>,
        ) -> CoreResult<bool> {
            let mut items = self.items.lock().unwrap();
            let Some(item) = items.get_mut(outbox_id) else {
                return Ok(false);
            };
            if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
                return Ok(false);
            }
            item.status = "pending".to_string();
            item.lease_owner = None;
            item.lease_expires_at = None;
            item.last_error = error_message.map(str::to_string);
            item.next_attempt_at = None;
            item.attempt_count = (item.attempt_count - 1).max(0);
            item.updated_at = Some(now);
            Ok(true)
        }
    }

    #[derive(Clone)]
    enum HandlerBehavior {
        Complete,
        Release,
        Fail,
    }

    struct StaticHandler {
        behavior: HandlerBehavior,
    }

    #[async_trait]
    impl WorkspacePlanOutboxHandler for StaticHandler {
        async fn handle(
            &self,
            _item: WorkspacePlanOutboxRecord,
        ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
            match self.behavior {
                HandlerBehavior::Complete => Ok(WorkspacePlanOutboxHandlerOutcome::Complete),
                HandlerBehavior::Release => Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                    reason: Some("shutdown".to_string()),
                }),
                HandlerBehavior::Fail => Err(CoreError::Storage("handler boom".to_string())),
            }
        }
    }

    #[derive(Default)]
    struct StaticPipelineStageRunner {
        results: Mutex<HashMap<String, PipelineStageResult>>,
        seen: Mutex<Vec<(String, String, String)>>,
    }

    impl StaticPipelineStageRunner {
        fn with_result(self, result: PipelineStageResult) -> Self {
            self.results
                .lock()
                .unwrap()
                .insert(result.stage.clone(), result);
            self
        }

        fn seen(&self) -> Vec<(String, String, String)> {
            self.seen.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl WorkspacePipelineStageRunner for StaticPipelineStageRunner {
        async fn run_stage(
            &self,
            project_id: &str,
            _contract: &PipelineContractFoundation,
            stage: &PipelineStageSpec,
        ) -> PipelineStageResult {
            self.seen.lock().unwrap().push((
                project_id.to_string(),
                stage.stage.clone(),
                stage.command.clone(),
            ));
            self.results
                .lock()
                .unwrap()
                .get(&stage.stage)
                .cloned()
                .unwrap_or_else(|| PipelineStageResult {
                    stage: stage.stage.clone(),
                    status: "success".to_string(),
                    command: stage.command.clone(),
                    exit_code: Some(0),
                    stdout_preview: "ok".to_string(),
                    stderr_preview: String::new(),
                    duration_ms: 25,
                    log_ref: Some(format!("sandbox://pipeline/test/{}.log", stage.stage)),
                    artifact_refs: vec![format!(
                        "pipeline_log:{}:sandbox://pipeline/test/{}.log",
                        stage.stage, stage.stage
                    )],
                    service_id: stage.service_id.clone(),
                    required: stage.required,
                })
        }
    }

    #[derive(Default)]
    struct FakeWorkerLaunchRuntimeStateStore {
        cooldowns: Mutex<HashSet<String>>,
        running: Mutex<HashSet<String>>,
        finished: Mutex<HashMap<String, String>>,
        claims: Mutex<Vec<String>>,
        clears: Mutex<Vec<String>>,
        refresh_cooldowns: Mutex<Vec<String>>,
        refresh_running: Mutex<Vec<String>>,
    }

    impl FakeWorkerLaunchRuntimeStateStore {
        fn insert_cooldown(&self, conversation_id: &str) {
            self.cooldowns
                .lock()
                .unwrap()
                .insert(conversation_id.to_string());
        }

        fn insert_running(&self, conversation_id: &str) {
            self.running
                .lock()
                .unwrap()
                .insert(conversation_id.to_string());
        }

        fn insert_finished(&self, conversation_id: &str) {
            self.finished
                .lock()
                .unwrap()
                .insert(conversation_id.to_string(), "msg-1".to_string());
        }

        fn has_cooldown(&self, conversation_id: &str) -> bool {
            self.cooldowns.lock().unwrap().contains(conversation_id)
        }

        fn has_finished(&self, conversation_id: &str) -> bool {
            self.finished.lock().unwrap().contains_key(conversation_id)
        }

        fn claims(&self) -> Vec<String> {
            self.claims.lock().unwrap().clone()
        }

        fn clears(&self) -> Vec<String> {
            self.clears.lock().unwrap().clone()
        }

        fn refresh_cooldowns(&self) -> Vec<String> {
            self.refresh_cooldowns.lock().unwrap().clone()
        }

        fn refresh_running(&self) -> Vec<String> {
            self.refresh_running.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl WorkerLaunchRuntimeStateStore for FakeWorkerLaunchRuntimeStateStore {
        async fn claim_launch_cooldown(
            &self,
            conversation_id: &str,
            _ttl_seconds: u64,
        ) -> CoreResult<bool> {
            self.claims
                .lock()
                .unwrap()
                .push(conversation_id.to_string());
            let mut cooldowns = self.cooldowns.lock().unwrap();
            if cooldowns.contains(conversation_id) {
                return Ok(false);
            }
            cooldowns.insert(conversation_id.to_string());
            Ok(true)
        }

        async fn refresh_launch_cooldown(
            &self,
            conversation_id: &str,
            _ttl_seconds: u64,
        ) -> CoreResult<bool> {
            self.refresh_cooldowns
                .lock()
                .unwrap()
                .push(conversation_id.to_string());
            Ok(self.cooldowns.lock().unwrap().contains(conversation_id))
        }

        async fn agent_finished_message_id(
            &self,
            conversation_id: &str,
        ) -> CoreResult<Option<String>> {
            Ok(self.finished.lock().unwrap().get(conversation_id).cloned())
        }

        async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool> {
            Ok(self.running.lock().unwrap().contains(conversation_id))
        }

        async fn refresh_agent_running_marker(
            &self,
            conversation_id: &str,
            _ttl_seconds: u64,
        ) -> CoreResult<bool> {
            if self.finished.lock().unwrap().contains_key(conversation_id) {
                return Ok(false);
            }
            self.refresh_running
                .lock()
                .unwrap()
                .push(conversation_id.to_string());
            Ok(self.running.lock().unwrap().contains(conversation_id))
        }

        async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()> {
            self.clears
                .lock()
                .unwrap()
                .push(conversation_id.to_string());
            self.finished.lock().unwrap().remove(conversation_id);
            self.cooldowns.lock().unwrap().remove(conversation_id);
            Ok(())
        }
    }

    #[derive(Default)]
    struct FakeWorkerLaunchEventStream {
        entries: Mutex<HashMap<String, Vec<StreamEntry>>>,
    }

    impl FakeWorkerLaunchEventStream {
        fn push(&self, conversation_id: &str, id: &str, payload: Value) {
            self.entries
                .lock()
                .unwrap()
                .entry(conversation_id.to_string())
                .or_default()
                .push(StreamEntry {
                    id: id.to_string(),
                    payload: payload.to_string(),
                });
        }
    }

    #[async_trait]
    impl WorkerLaunchEventStream for FakeWorkerLaunchEventStream {
        async fn read_after(
            &self,
            conversation_id: &str,
            after_id: &str,
            limit: usize,
        ) -> CoreResult<Vec<StreamEntry>> {
            let entries = self.entries.lock().unwrap();
            let mut seen_after = after_id.is_empty() || after_id == "0";
            let mut out = Vec::new();
            for entry in entries.get(conversation_id).into_iter().flatten() {
                if !seen_after {
                    seen_after = entry.id == after_id;
                    continue;
                }
                out.push(entry.clone());
                if out.len() >= limit {
                    break;
                }
            }
            Ok(out)
        }
    }

    #[derive(Debug, Clone, PartialEq)]
    struct FakePipelineContractRecord {
        id: String,
        workspace_id: String,
        plan_id: String,
        provider: String,
        code_root: Option<String>,
        commands_json: Value,
        env_json: Value,
        trigger_policy_json: Value,
        timeout_seconds: i32,
        auto_deploy: bool,
        preview_port: Option<i32>,
        health_url: Option<String>,
        metadata_json: Value,
        created_at: DateTime<Utc>,
        updated_at: Option<DateTime<Utc>>,
    }

    #[derive(Debug, Clone, PartialEq)]
    struct FakeWorkerConversationRecord {
        id: String,
        project_id: String,
        tenant_id: String,
        user_id: String,
        title: String,
        agent_config_json: Value,
        metadata_json: Value,
        participant_agents_json: Vec<String>,
        focused_agent_id: String,
        workspace_id: String,
        linked_workspace_task_id: String,
        updated_at: DateTime<Utc>,
    }

    #[derive(Default)]
    struct FakeWorkspacePlanDispatchStore {
        workspaces: Mutex<HashMap<String, WorkspaceRecord>>,
        tasks: Mutex<HashMap<String, WorkspaceTaskRecord>>,
        plans: Mutex<HashMap<String, WorkspacePlanRecord>>,
        nodes: Mutex<HashMap<String, WorkspacePlanNodeRecord>>,
        attempts: Mutex<HashMap<String, WorkspaceTaskSessionAttemptRecord>>,
        conversations: Mutex<HashMap<String, FakeWorkerConversationRecord>>,
        pipeline_contracts: Mutex<HashMap<(String, String), FakePipelineContractRecord>>,
        pipeline_runs: Mutex<HashMap<String, WorkspacePipelineRunRecord>>,
        pipeline_stage_runs: Mutex<HashMap<String, WorkspacePipelineStageRunRecord>>,
        plan_events: Mutex<Vec<WorkspacePlanEventRecord>>,
        outbox: Mutex<Vec<WorkspacePlanOutboxRecord>>,
        active_worker_conversations: Mutex<i64>,
        supervisor_dispose_nodes: Mutex<HashSet<(String, String, String)>>,
    }

    impl FakeWorkspacePlanDispatchStore {
        fn insert_workspace(&self, workspace: WorkspaceRecord) {
            self.workspaces
                .lock()
                .unwrap()
                .insert(workspace.id.clone(), workspace);
        }

        fn insert_task(&self, task: WorkspaceTaskRecord) {
            self.tasks.lock().unwrap().insert(task.id.clone(), task);
        }

        fn insert_plan(&self, plan: WorkspacePlanRecord) {
            self.plans.lock().unwrap().insert(plan.id.clone(), plan);
        }

        fn insert_node(&self, node: WorkspacePlanNodeRecord) {
            self.nodes.lock().unwrap().insert(node.id.clone(), node);
        }

        fn insert_attempt(&self, attempt: WorkspaceTaskSessionAttemptRecord) {
            self.attempts
                .lock()
                .unwrap()
                .insert(attempt.id.clone(), attempt);
        }

        fn insert_supervisor_dispose_decision(
            &self,
            workspace_id: &str,
            plan_id: &str,
            node_id: &str,
        ) {
            self.supervisor_dispose_nodes.lock().unwrap().insert((
                workspace_id.to_string(),
                plan_id.to_string(),
                node_id.to_string(),
            ));
        }

        fn insert_pipeline_run(&self, run: WorkspacePipelineRunRecord) {
            self.pipeline_runs
                .lock()
                .unwrap()
                .insert(run.id.clone(), run);
        }

        fn set_active_worker_conversations(&self, count: i64) {
            *self.active_worker_conversations.lock().unwrap() = count;
        }

        fn task(&self, id: &str) -> WorkspaceTaskRecord {
            self.tasks.lock().unwrap().get(id).unwrap().clone()
        }

        fn node(&self, id: &str) -> WorkspacePlanNodeRecord {
            self.nodes.lock().unwrap().get(id).unwrap().clone()
        }

        fn pipeline_run(&self, id: &str) -> WorkspacePipelineRunRecord {
            self.pipeline_runs.lock().unwrap().get(id).unwrap().clone()
        }

        fn pipeline_runs(&self) -> Vec<WorkspacePipelineRunRecord> {
            self.pipeline_runs
                .lock()
                .unwrap()
                .values()
                .cloned()
                .collect()
        }

        fn pipeline_stage_run(&self, id: &str) -> WorkspacePipelineStageRunRecord {
            self.pipeline_stage_runs
                .lock()
                .unwrap()
                .get(id)
                .unwrap()
                .clone()
        }

        fn pipeline_stage_runs(&self) -> Vec<WorkspacePipelineStageRunRecord> {
            self.pipeline_stage_runs
                .lock()
                .unwrap()
                .values()
                .cloned()
                .collect()
        }

        fn pipeline_contract(
            &self,
            workspace_id: &str,
            plan_id: &str,
        ) -> FakePipelineContractRecord {
            self.pipeline_contracts
                .lock()
                .unwrap()
                .get(&(workspace_id.to_string(), plan_id.to_string()))
                .unwrap()
                .clone()
        }

        fn attempts(&self) -> Vec<WorkspaceTaskSessionAttemptRecord> {
            self.attempts.lock().unwrap().values().cloned().collect()
        }

        fn attempt(&self, id: &str) -> WorkspaceTaskSessionAttemptRecord {
            self.attempts.lock().unwrap().get(id).unwrap().clone()
        }

        fn conversation(&self, id: &str) -> FakeWorkerConversationRecord {
            self.conversations
                .lock()
                .unwrap()
                .get(id)
                .cloned()
                .unwrap_or_else(|| panic!("conversation {id} not found"))
        }

        fn conversation_count(&self) -> usize {
            self.conversations.lock().unwrap().len()
        }

        fn plan_events(&self) -> Vec<WorkspacePlanEventRecord> {
            self.plan_events.lock().unwrap().clone()
        }

        fn outbox(&self) -> Vec<WorkspacePlanOutboxRecord> {
            self.outbox.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl WorkspacePlanDispatchStore for FakeWorkspacePlanDispatchStore {
        async fn get_workspace(&self, workspace_id: &str) -> CoreResult<Option<WorkspaceRecord>> {
            Ok(self.workspaces.lock().unwrap().get(workspace_id).cloned())
        }

        async fn get_task(
            &self,
            workspace_id: &str,
            task_id: &str,
        ) -> CoreResult<Option<WorkspaceTaskRecord>> {
            Ok(self
                .tasks
                .lock()
                .unwrap()
                .get(task_id)
                .filter(|task| task.workspace_id == workspace_id)
                .cloned())
        }

        async fn list_tasks_by_root_goal_task_id(
            &self,
            workspace_id: &str,
            root_goal_task_id: &str,
        ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
            let mut tasks = self
                .tasks
                .lock()
                .unwrap()
                .values()
                .filter(|task| {
                    task.workspace_id == workspace_id
                        && task.archived_at.is_none()
                        && string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID)
                            .as_deref()
                            == Some(root_goal_task_id)
                })
                .cloned()
                .collect::<Vec<_>>();
            tasks.sort_by(|left, right| {
                left.created_at
                    .cmp(&right.created_at)
                    .then_with(|| left.id.cmp(&right.id))
            });
            Ok(tasks)
        }

        async fn list_current_plan_child_tasks_by_root_goal_task_id(
            &self,
            workspace_id: &str,
            root_goal_task_id: &str,
        ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
            let nodes = self.nodes.lock().unwrap().clone();
            let mut tasks = self
                .tasks
                .lock()
                .unwrap()
                .values()
                .filter(|task| {
                    if task.workspace_id != workspace_id || task.archived_at.is_some() {
                        return false;
                    }
                    if string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).as_deref()
                        != Some(root_goal_task_id)
                    {
                        return false;
                    }
                    let Some(plan_id) =
                        string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_ID)
                    else {
                        return false;
                    };
                    let Some(node_id) =
                        string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_NODE_ID)
                    else {
                        return false;
                    };
                    nodes.get(&node_id).is_some_and(|node| {
                        node.plan_id == plan_id
                            && node.workspace_task_id.as_deref() == Some(task.id.as_str())
                    })
                })
                .cloned()
                .collect::<Vec<_>>();
            tasks.sort_by(|left, right| {
                left.created_at
                    .cmp(&right.created_at)
                    .then_with(|| left.id.cmp(&right.id))
            });
            Ok(tasks)
        }

        async fn save_task(&self, task: WorkspaceTaskRecord) -> CoreResult<WorkspaceTaskRecord> {
            self.tasks
                .lock()
                .unwrap()
                .insert(task.id.clone(), task.clone());
            Ok(task)
        }

        async fn get_plan(&self, plan_id: &str) -> CoreResult<Option<WorkspacePlanRecord>> {
            Ok(self.plans.lock().unwrap().get(plan_id).cloned())
        }

        async fn list_plan_nodes(&self, plan_id: &str) -> CoreResult<Vec<WorkspacePlanNodeRecord>> {
            Ok(self
                .nodes
                .lock()
                .unwrap()
                .values()
                .filter(|node| node.plan_id == plan_id)
                .cloned()
                .collect())
        }

        async fn save_plan_node(
            &self,
            node: WorkspacePlanNodeRecord,
        ) -> CoreResult<WorkspacePlanNodeRecord> {
            self.nodes
                .lock()
                .unwrap()
                .insert(node.id.clone(), node.clone());
            Ok(node)
        }

        async fn find_active_task_session_attempt(
            &self,
            workspace_task_id: &str,
        ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
            let mut attempts = self
                .attempts
                .lock()
                .unwrap()
                .values()
                .filter(|attempt| {
                    attempt.workspace_task_id == workspace_task_id
                        && matches!(
                            attempt.status.as_str(),
                            "pending" | "running" | "awaiting_leader_adjudication"
                        )
                })
                .cloned()
                .collect::<Vec<_>>();
            attempts.sort_by(|left, right| {
                right
                    .attempt_number
                    .cmp(&left.attempt_number)
                    .then_with(|| left.id.cmp(&right.id))
            });
            Ok(attempts.into_iter().next())
        }

        async fn find_latest_accepted_task_session_attempt(
            &self,
            workspace_id: &str,
            workspace_task_id: &str,
        ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
            let mut attempts = self
                .attempts
                .lock()
                .unwrap()
                .values()
                .filter(|attempt| {
                    attempt.workspace_id == workspace_id
                        && attempt.workspace_task_id == workspace_task_id
                        && attempt.status == ACCEPTED_ATTEMPT_STATUS
                })
                .cloned()
                .collect::<Vec<_>>();
            attempts.sort_by(|left, right| {
                right
                    .attempt_number
                    .cmp(&left.attempt_number)
                    .then_with(|| left.id.cmp(&right.id))
            });
            Ok(attempts.into_iter().next())
        }

        async fn get_task_session_attempt(
            &self,
            attempt_id: &str,
        ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
            Ok(self.attempts.lock().unwrap().get(attempt_id).cloned())
        }

        async fn latest_pipeline_run_for_node(
            &self,
            plan_id: &str,
            node_id: &str,
            attempt_id: Option<&str>,
        ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
            let mut runs = self
                .pipeline_runs
                .lock()
                .unwrap()
                .values()
                .filter(|run| {
                    run.plan_id.as_deref() == Some(plan_id)
                        && run.node_id.as_deref() == Some(node_id)
                        && attempt_id
                            .is_none_or(|attempt_id| run.attempt_id.as_deref() == Some(attempt_id))
                })
                .cloned()
                .collect::<Vec<_>>();
            runs.sort_by(|left, right| {
                right
                    .created_at
                    .cmp(&left.created_at)
                    .then_with(|| right.id.cmp(&left.id))
            });
            Ok(runs.into_iter().next())
        }

        async fn ensure_pipeline_contract(
            &self,
            contract_id: &str,
            workspace_id: &str,
            plan_id: &str,
            provider: &str,
            code_root: Option<&str>,
            commands_json: &Value,
            env_json: &Value,
            trigger_policy_json: &Value,
            timeout_seconds: i32,
            auto_deploy: bool,
            preview_port: Option<i32>,
            health_url: Option<&str>,
            metadata_json: &Value,
            now: DateTime<Utc>,
        ) -> CoreResult<String> {
            let mut contracts = self.pipeline_contracts.lock().unwrap();
            let key = (workspace_id.to_string(), plan_id.to_string());
            if let Some(existing) = contracts.get_mut(&key) {
                existing.provider = provider.to_string();
                existing.code_root = code_root.map(ToOwned::to_owned);
                existing.commands_json = commands_json.clone();
                existing.env_json = env_json.clone();
                existing.trigger_policy_json = trigger_policy_json.clone();
                existing.timeout_seconds = timeout_seconds.max(1);
                existing.auto_deploy = auto_deploy;
                existing.preview_port = preview_port;
                existing.health_url = health_url.map(ToOwned::to_owned);
                existing.metadata_json = metadata_json.clone();
                existing.updated_at = Some(now);
                return Ok(existing.id.clone());
            }
            let record = FakePipelineContractRecord {
                id: contract_id.to_string(),
                workspace_id: workspace_id.to_string(),
                plan_id: plan_id.to_string(),
                provider: provider.to_string(),
                code_root: code_root.map(ToOwned::to_owned),
                commands_json: commands_json.clone(),
                env_json: env_json.clone(),
                trigger_policy_json: trigger_policy_json.clone(),
                timeout_seconds: timeout_seconds.max(1),
                auto_deploy,
                preview_port,
                health_url: health_url.map(ToOwned::to_owned),
                metadata_json: metadata_json.clone(),
                created_at: now,
                updated_at: None,
            };
            let id = record.id.clone();
            contracts.insert(key, record);
            Ok(id)
        }

        async fn create_pipeline_run(
            &self,
            run: WorkspacePipelineRunRecord,
        ) -> CoreResult<WorkspacePipelineRunRecord> {
            self.pipeline_runs
                .lock()
                .unwrap()
                .insert(run.id.clone(), run.clone());
            Ok(run)
        }

        async fn finish_pipeline_run(
            &self,
            run_id: &str,
            status: &str,
            reason: Option<&str>,
            metadata_patch: &Value,
            completed_at: DateTime<Utc>,
        ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
            let mut runs = self.pipeline_runs.lock().unwrap();
            let Some(run) = runs.get_mut(run_id) else {
                return Ok(None);
            };
            run.status = status.to_string();
            run.reason = reason.map(ToOwned::to_owned);
            run.completed_at = Some(completed_at);
            run.updated_at = Some(completed_at);
            let mut metadata = object_or_empty(run.metadata_json.clone());
            for (key, value) in object_or_empty(metadata_patch.clone()) {
                metadata.insert(key, value);
            }
            run.metadata_json = Value::Object(metadata);
            Ok(Some(run.clone()))
        }

        async fn create_pipeline_stage_run(
            &self,
            stage_run: WorkspacePipelineStageRunRecord,
        ) -> CoreResult<WorkspacePipelineStageRunRecord> {
            self.pipeline_stage_runs
                .lock()
                .unwrap()
                .insert(stage_run.id.clone(), stage_run.clone());
            Ok(stage_run)
        }

        async fn finish_pipeline_stage_run(
            &self,
            stage_run_id: &str,
            status: &str,
            exit_code: Option<i32>,
            stdout_preview: Option<&str>,
            stderr_preview: Option<&str>,
            log_ref: Option<&str>,
            artifact_refs: &[String],
            metadata_patch: &Value,
            completed_at: DateTime<Utc>,
        ) -> CoreResult<Option<WorkspacePipelineStageRunRecord>> {
            let mut stage_runs = self.pipeline_stage_runs.lock().unwrap();
            let Some(stage_run) = stage_runs.get_mut(stage_run_id) else {
                return Ok(None);
            };
            stage_run.status = status.to_string();
            stage_run.exit_code = exit_code;
            stage_run.stdout_preview = stdout_preview.map(ToOwned::to_owned);
            stage_run.stderr_preview = stderr_preview.map(ToOwned::to_owned);
            stage_run.log_ref = log_ref.map(ToOwned::to_owned);
            stage_run.artifact_refs_json = artifact_refs.to_vec();
            stage_run.completed_at = Some(completed_at);
            let duration_ms = stage_run
                .started_at
                .map(|started_at| (completed_at - started_at).num_milliseconds().max(0))
                .unwrap_or(0);
            stage_run.duration_ms = Some(i32::try_from(duration_ms).unwrap_or(i32::MAX));
            stage_run.updated_at = Some(completed_at);
            let mut metadata = object_or_empty(stage_run.metadata_json.clone());
            for (key, value) in object_or_empty(metadata_patch.clone()) {
                metadata.insert(key, value);
            }
            stage_run.metadata_json = Value::Object(metadata);
            Ok(Some(stage_run.clone()))
        }

        async fn latest_task_session_attempt_number(
            &self,
            workspace_task_id: &str,
        ) -> CoreResult<i32> {
            Ok(self
                .attempts
                .lock()
                .unwrap()
                .values()
                .filter(|attempt| attempt.workspace_task_id == workspace_task_id)
                .map(|attempt| attempt.attempt_number)
                .max()
                .unwrap_or(0))
        }

        async fn create_task_session_attempt(
            &self,
            attempt: WorkspaceTaskSessionAttemptRecord,
        ) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
            self.attempts
                .lock()
                .unwrap()
                .insert(attempt.id.clone(), attempt.clone());
            Ok(attempt)
        }

        async fn mark_task_session_attempt_running(
            &self,
            attempt_id: &str,
            now: DateTime<Utc>,
        ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
            let mut attempts = self.attempts.lock().unwrap();
            let Some(attempt) = attempts.get_mut(attempt_id) else {
                return Ok(None);
            };
            attempt.status = "running".to_string();
            attempt.updated_at = Some(now);
            Ok(Some(attempt.clone()))
        }

        async fn ensure_worker_launch_conversation(
            &self,
            conversation_id: &str,
            project_id: &str,
            tenant_id: &str,
            user_id: &str,
            title: &str,
            agent_config_json: &Value,
            metadata_json: &Value,
            participant_agents_json: &[String],
            focused_agent_id: &str,
            workspace_id: &str,
            linked_workspace_task_id: &str,
            now: DateTime<Utc>,
        ) -> CoreResult<()> {
            let mut conversations = self.conversations.lock().unwrap();
            if let Some(existing) = conversations.get(conversation_id) {
                if existing.workspace_id != workspace_id
                    || existing.linked_workspace_task_id != linked_workspace_task_id
                {
                    return Err(CoreError::Storage(format!(
                        "worker launch conversation {conversation_id} is linked to another workspace task"
                    )));
                }
            }
            conversations.insert(
                conversation_id.to_string(),
                FakeWorkerConversationRecord {
                    id: conversation_id.to_string(),
                    project_id: project_id.to_string(),
                    tenant_id: tenant_id.to_string(),
                    user_id: user_id.to_string(),
                    title: title.to_string(),
                    agent_config_json: agent_config_json.clone(),
                    metadata_json: metadata_json.clone(),
                    participant_agents_json: participant_agents_json.to_vec(),
                    focused_agent_id: focused_agent_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    linked_workspace_task_id: linked_workspace_task_id.to_string(),
                    updated_at: now,
                },
            );
            Ok(())
        }

        async fn bind_task_session_attempt_conversation(
            &self,
            attempt_id: &str,
            conversation_id: &str,
            now: DateTime<Utc>,
        ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
            let mut attempts = self.attempts.lock().unwrap();
            let Some(attempt) = attempts.get_mut(attempt_id) else {
                return Ok(None);
            };
            attempt.status = "running".to_string();
            attempt.conversation_id = Some(conversation_id.to_string());
            attempt.updated_at = Some(now);
            Ok(Some(attempt.clone()))
        }

        async fn finish_task_session_attempt(
            &self,
            attempt_id: &str,
            status: &str,
            leader_feedback: Option<&str>,
            adjudication_reason: Option<&str>,
            completed_at: DateTime<Utc>,
        ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
            let mut attempts = self.attempts.lock().unwrap();
            let Some(attempt) = attempts.get_mut(attempt_id) else {
                return Ok(None);
            };
            attempt.status = status.to_string();
            attempt.leader_feedback = leader_feedback.map(ToOwned::to_owned);
            attempt.adjudication_reason = adjudication_reason.map(ToOwned::to_owned);
            attempt.completed_at = Some(completed_at);
            attempt.updated_at = Some(completed_at);
            Ok(Some(attempt.clone()))
        }

        async fn record_task_session_attempt_candidate_output(
            &self,
            attempt_id: &str,
            summary: Option<&str>,
            artifacts_json: &[String],
            verifications_json: &[String],
            conversation_id: Option<&str>,
            updated_at: DateTime<Utc>,
        ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
            let mut attempts = self.attempts.lock().unwrap();
            let Some(attempt) = attempts.get_mut(attempt_id) else {
                return Ok(None);
            };
            if matches!(
                attempt.status.as_str(),
                "accepted" | "rejected" | "blocked" | "cancelled"
            ) {
                return Ok(Some(attempt.clone()));
            }
            attempt.status = AWAITING_LEADER_ADJUDICATION_STATUS.to_string();
            if let Some(conversation_id) = conversation_id {
                attempt.conversation_id = Some(conversation_id.to_string());
            }
            attempt.candidate_summary = summary.map(ToOwned::to_owned);
            attempt.candidate_artifacts_json = artifacts_json.to_vec();
            attempt.candidate_verifications_json = verifications_json.to_vec();
            attempt.updated_at = Some(updated_at);
            Ok(Some(attempt.clone()))
        }

        async fn count_recent_running_task_session_attempts_with_conversation(
            &self,
            _workspace_id: &str,
            _active_after: DateTime<Utc>,
        ) -> CoreResult<i64> {
            Ok(*self.active_worker_conversations.lock().unwrap())
        }

        async fn has_supervisor_dispose_decision_for_node(
            &self,
            workspace_id: &str,
            plan_id: &str,
            node_id: &str,
        ) -> CoreResult<bool> {
            Ok(self.supervisor_dispose_nodes.lock().unwrap().contains(&(
                workspace_id.to_string(),
                plan_id.to_string(),
                node_id.to_string(),
            )))
        }

        async fn create_plan_event(
            &self,
            event: WorkspacePlanEventRecord,
        ) -> CoreResult<WorkspacePlanEventRecord> {
            self.plan_events.lock().unwrap().push(event.clone());
            Ok(event)
        }

        async fn enqueue_plan_outbox(
            &self,
            item: WorkspacePlanOutboxRecord,
        ) -> CoreResult<WorkspacePlanOutboxRecord> {
            self.outbox.lock().unwrap().push(item.clone());
            Ok(item)
        }
    }

    fn worker(
        store: Arc<FakeWorkspacePlanOutboxStore>,
        handlers: WorkspacePlanOutboxHandlers,
    ) -> WorkspacePlanOutboxWorker {
        WorkspacePlanOutboxWorker::new(
            store,
            WorkspacePlanOutboxWorkerConfig {
                worker_id: "worker-test".to_string(),
                batch_size: 10,
                lease_seconds: 60,
                poll_interval_millis: 5,
                autostart: false,
                production_ready: false,
            },
            handlers,
        )
    }

    fn handler(behavior: HandlerBehavior) -> Arc<dyn WorkspacePlanOutboxHandler> {
        Arc::new(StaticHandler { behavior })
    }

    fn outbox(id: &str, event_type: &str) -> WorkspacePlanOutboxRecord {
        WorkspacePlanOutboxRecord {
            id: id.to_string(),
            plan_id: Some("plan-test".to_string()),
            workspace_id: "workspace-test".to_string(),
            event_type: event_type.to_string(),
            payload_json: json!({"id": id}),
            status: "pending".to_string(),
            attempt_count: 0,
            max_attempts: 3,
            lease_owner: None,
            lease_expires_at: None,
            last_error: None,
            next_attempt_at: None,
            processed_at: None,
            metadata_json: json!({}),
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: None,
        }
    }

    fn task_with_plan_metadata() -> WorkspaceTaskRecord {
        WorkspaceTaskRecord {
            id: "task-test".to_string(),
            workspace_id: "workspace-test".to_string(),
            title: "Build feature".to_string(),
            description: None,
            created_by: "actor-test".to_string(),
            assignee_user_id: None,
            assignee_agent_id: Some("agent-worker".to_string()),
            status: "todo".to_string(),
            priority: 1,
            estimated_effort: None,
            blocker_reason: None,
            metadata_json: json!({
                ROOT_GOAL_TASK_ID: "root-task",
                WORKSPACE_PLAN_ID: "plan-test",
                WORKSPACE_PLAN_NODE_ID: "node-test"
            }),
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: None,
            completed_at: None,
            archived_at: None,
        }
    }

    fn root_goal_task() -> WorkspaceTaskRecord {
        WorkspaceTaskRecord {
            id: "root-task".to_string(),
            workspace_id: "workspace-test".to_string(),
            title: "Finish root goal".to_string(),
            description: None,
            created_by: "actor-test".to_string(),
            assignee_user_id: None,
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: 1,
            estimated_effort: None,
            blocker_reason: None,
            metadata_json: json!({
                TASK_ROLE: GOAL_ROOT_TASK_ROLE,
                "goal_health": "healthy"
            }),
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: None,
            completed_at: None,
            archived_at: None,
        }
    }

    fn workspace_with_metadata(metadata_json: Value) -> WorkspaceRecord {
        WorkspaceRecord {
            id: "workspace-test".to_string(),
            tenant_id: "tenant-test".to_string(),
            project_id: "project-test".to_string(),
            name: "Workspace".to_string(),
            description: None,
            created_by: "actor-test".to_string(),
            is_archived: false,
            metadata_json,
            office_status: "active".to_string(),
            hex_layout_config_json: json!({}),
            default_blocking_categories_json: Vec::new(),
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: None,
        }
    }

    fn workspace_with_code_root(root: &str) -> WorkspaceRecord {
        workspace_with_metadata(json!({
            "code_context": {
                "sandbox_code_root": root
            }
        }))
    }

    fn workspace_with_pipeline_contract() -> WorkspaceRecord {
        workspace_with_metadata(json!({
            "delivery_cicd": {
                "provider": "sandbox_native",
                "code_root": "/workspace/project",
                "auto_deploy": false,
                "timeout_seconds": 120,
                "contract_source": PLANNING_CONTRACT_SOURCE,
                "contract_confidence": 0.82,
                "env": {"CI": "true"},
                "stages": [
                    {
                        "stage": "test",
                        "command": "cargo test --workspace",
                        "required": true,
                        "timeout_seconds": 120
                    }
                ]
            }
        }))
    }

    fn workspace_with_drone_pipeline_contract_missing_host_root() -> WorkspaceRecord {
        workspace_with_metadata(json!({
            "source_control": {
                "default_branch": "main"
            },
            "delivery_cicd": {
                "provider": "drone",
                "auto_deploy": true,
                "contract_source": PLANNING_CONTRACT_SOURCE,
                "drone": {
                    "repo": "owner/repo",
                    "branch": "main"
                }
            }
        }))
    }

    fn workspace_with_drone_pipeline_contract_missing_branch() -> WorkspaceRecord {
        workspace_with_metadata(json!({
            "code_context": {
                "host_code_root": "/tmp/worktree",
                "sandbox_code_root": "/workspace/project"
            },
            "delivery_cicd": {
                "provider": "drone",
                "auto_deploy": true,
                "contract_source": PLANNING_CONTRACT_SOURCE,
                "provider_config": {
                    "drone": {
                        "repo": "owner/repo"
                    }
                }
            }
        }))
    }

    fn workspace_with_drone_pipeline_contract_git_publish(
        host_code_root: &Path,
        remote_url: &Path,
    ) -> WorkspaceRecord {
        workspace_with_metadata(json!({
            "code_context": {
                "host_code_root": host_code_root.to_string_lossy().to_string(),
                "sandbox_code_root": "/workspace/project"
            },
            "source_control": {
                "clone_url": remote_url.to_string_lossy().to_string(),
                "default_branch": "main"
            },
            "delivery_cicd": {
                "provider": "drone",
                "auto_deploy": true,
                "contract_source": PLANNING_CONTRACT_SOURCE,
                "drone": {
                    "repo": "owner/repo"
                }
            }
        }))
    }

    fn workspace_with_drone_api_pipeline_contract(
        server_url: &str,
        token_env: &str,
    ) -> WorkspaceRecord {
        workspace_with_drone_api_pipeline_contract_with_host_root(server_url, token_env, None)
    }

    fn workspace_with_drone_api_pipeline_contract_with_host_root(
        server_url: &str,
        token_env: &str,
        host_code_root: Option<&Path>,
    ) -> WorkspaceRecord {
        let mut metadata = json!({
            "source_control": {
                "default_branch": "main"
            },
            "delivery_cicd": {
                "provider": "drone",
                "auto_deploy": true,
                "contract_source": PLANNING_CONTRACT_SOURCE,
                "drone": {
                    "repo": "owner/repo",
                    "branch": "main",
                    "commit": "abc123",
                    "server_url": server_url,
                    "token_env": token_env,
                    "poll_interval_seconds": 1,
                    "timeout_seconds": 1,
                    "params": {
                        "target": "workspace-ci"
                    }
                }
            }
        });
        if let Some(host_code_root) = host_code_root {
            metadata
                .as_object_mut()
                .expect("workspace metadata object")
                .insert(
                    "code_context".to_string(),
                    json!({
                        "host_code_root": host_code_root.to_string_lossy().to_string(),
                        "sandbox_code_root": "/workspace/project"
                    }),
                );
        }
        workspace_with_metadata(metadata)
    }

    fn workspace_with_drone_cli_pipeline_contract(
        server_url: &str,
        token_env: &str,
        command: &Path,
    ) -> WorkspaceRecord {
        workspace_with_metadata(json!({
            "source_control": {
                "default_branch": "main"
            },
            "delivery_cicd": {
                "provider": "drone",
                "auto_deploy": true,
                "contract_source": PLANNING_CONTRACT_SOURCE,
                "drone": {
                    "repo": "owner/repo",
                    "branch": "main",
                    "commit": "abc123",
                    "server_url": server_url,
                    "token_env": token_env,
                    "client": "cli",
                    "command": command.to_string_lossy().to_string(),
                    "poll_interval_seconds": 1,
                    "timeout_seconds": 1,
                    "params": {
                        "target": "workspace-ci"
                    }
                }
            }
        }))
    }

    fn workspace_with_drone_docker_deploy_pipeline_contract(
        server_url: &str,
        token_env: &str,
    ) -> WorkspaceRecord {
        workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(
            server_url, token_env, None,
        )
    }

    fn workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(
        server_url: &str,
        token_env: &str,
        host_code_root: Option<&Path>,
    ) -> WorkspaceRecord {
        let mut metadata = json!({
            "source_control": {
                "default_branch": "main"
            },
            "delivery_cicd": {
                "provider": "drone",
                "auto_deploy": true,
                "contract_source": PLANNING_CONTRACT_SOURCE,
                "deploy": {
                    "enabled": true,
                    "mode": "docker",
                    "stage": "deploy",
                    "required": true,
                    "target": "production",
                    "docker": {
                        "trusted": true,
                        "host_port": 18080,
                        "labels": ["blue", "green"],
                        "deploy_services": [
                            {
                                "service_id": "web",
                                "container_name": "app-web",
                                "image": "registry.local/app-web:abc"
                            }
                        ]
                    }
                },
                "drone": {
                    "repo": "owner/repo",
                    "branch": "main",
                    "commit": "abc123",
                    "server_url": server_url,
                    "token_env": token_env,
                    "poll_interval_seconds": 1,
                    "timeout_seconds": 1
                }
            }
        });
        if let Some(host_code_root) = host_code_root {
            metadata
                .as_object_mut()
                .expect("workspace metadata object")
                .insert(
                    "code_context".to_string(),
                    json!({
                        "host_code_root": host_code_root.to_string_lossy().to_string(),
                        "sandbox_code_root": "/workspace/project"
                    }),
                );
        }
        workspace_with_metadata(metadata)
    }

    async fn drone_api_mock(
        responses: Vec<(u16, &'static str)>,
    ) -> (String, Arc<tokio::sync::Mutex<Vec<String>>>) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let captured = Arc::new(tokio::sync::Mutex::new(Vec::<String>::new()));
        let responses = Arc::new(tokio::sync::Mutex::new(VecDeque::from(responses)));
        let captured_sink = captured.clone();
        let response_queue = responses.clone();
        tokio::spawn(async move {
            loop {
                let Ok((mut socket, _)) = listener.accept().await else {
                    break;
                };
                let mut request = Vec::new();
                loop {
                    let mut buffer = vec![0u8; 8192];
                    let read = socket.read(&mut buffer).await.unwrap_or(0);
                    if read == 0 {
                        break;
                    }
                    request.extend_from_slice(&buffer[..read]);
                    if http_request_complete(&request) {
                        break;
                    }
                }
                captured_sink
                    .lock()
                    .await
                    .push(String::from_utf8_lossy(&request).to_string());
                let (status, body) = response_queue
                    .lock()
                    .await
                    .pop_front()
                    .unwrap_or((500, r#"{"error":"unexpected request"}"#));
                let reason = if status < 400 { "OK" } else { "ERROR" };
                let response = format!(
                    "HTTP/1.1 {status} {reason}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                let _ = socket.write_all(response.as_bytes()).await;
                let _ = socket.flush().await;
            }
        });
        (format!("http://{addr}"), captured)
    }

    fn http_request_complete(request: &[u8]) -> bool {
        let Some(header_end) = request.windows(4).position(|window| window == b"\r\n\r\n") else {
            return false;
        };
        let headers = String::from_utf8_lossy(&request[..header_end]).to_ascii_lowercase();
        let content_length = headers
            .lines()
            .find_map(|line| line.strip_prefix("content-length:"))
            .and_then(|value| value.trim().parse::<usize>().ok())
            .unwrap_or(0);
        request.len() >= header_end + 4 + content_length
    }

    struct GitPublishFixture {
        root: PathBuf,
        repo: PathBuf,
        remote: PathBuf,
        commit_ref: String,
    }

    impl Drop for GitPublishFixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    struct DroneYamlFixture {
        root: PathBuf,
    }

    impl Drop for DroneYamlFixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    struct DroneCliFixture {
        root: PathBuf,
        command: PathBuf,
        capture: PathBuf,
    }

    impl Drop for DroneCliFixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    fn drone_yaml_fixture(content: &str) -> DroneYamlFixture {
        let root =
            std::env::temp_dir().join(format!("agistack-drone-yaml-test-{}", generate_uuid_v4()));
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join(".drone.yml"), content).unwrap();
        DroneYamlFixture { root }
    }

    fn drone_cli_fixture() -> DroneCliFixture {
        let root =
            std::env::temp_dir().join(format!("agistack-drone-cli-test-{}", generate_uuid_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let command = root.join("drone");
        let capture = root.join("commands.log");
        let capture_text = capture.to_string_lossy();
        std::fs::write(
            &command,
            format!(
                r#"#!/bin/sh
CAPTURE="{capture_text}"
printf 'server=%s token=%s args=%s\n' "$DRONE_SERVER" "$DRONE_TOKEN" "$*" >> "$CAPTURE"
case "$1 $2" in
  "repo info")
    printf '%s\n' '{{"active":true,"trusted":true}}'
    ;;
  "repo enable")
    printf '%s\n' enabled
    ;;
  "repo update")
    printf '%s\n' updated
    ;;
  "build ls")
    exit 0
    ;;
  "build create")
    printf '%s\n' '{{"number":51,"status":"running"}}'
    ;;
  "build info")
    printf '%s\n' '{{"number":51,"status":"success","link":"http://drone.local/owner/repo/51","stages":[{{"name":"ci","number":1,"steps":[{{"name":"test","number":1,"status":"success","exit_code":0}}]}}]}}'
    ;;
  "log view")
    printf '%s\n' 'cargo test ok'
    ;;
  "build stop")
    printf '%s\n' stopped
    ;;
  *)
    printf 'unexpected drone args: %s\n' "$*" >&2
    exit 64
    ;;
esac
"#
            ),
        )
        .unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut permissions = std::fs::metadata(&command).unwrap().permissions();
            permissions.set_mode(0o700);
            std::fs::set_permissions(&command, permissions).unwrap();
        }
        DroneCliFixture {
            root,
            command,
            capture,
        }
    }

    fn git_publish_fixture() -> Option<GitPublishFixture> {
        if std::env::var_os("AGISTACK_RUN_GIT_PUBLISH_TESTS").is_none() {
            eprintln!(
                "[skip] set AGISTACK_RUN_GIT_PUBLISH_TESTS=1 to run subprocess-backed git publish tests"
            );
            return None;
        }
        if !git_available() {
            eprintln!("[skip] git binary is not available");
            return None;
        }
        let root = std::env::temp_dir().join(format!(
            "agistack-drone-publish-test-{}",
            generate_uuid_v4()
        ));
        let repo = root.join("repo");
        let remote = root.join("remote.git");
        std::fs::create_dir_all(&repo).unwrap();
        run_git_ok(&repo, &["init"]);
        run_git_ok(&repo, &["config", "user.email", "agent@example.test"]);
        run_git_ok(&repo, &["config", "user.name", "Agent Test"]);
        std::fs::write(repo.join("README.md"), "hello\n").unwrap();
        run_git_ok(&repo, &["add", "README.md"]);
        run_git_ok(&repo, &["commit", "-m", "initial"]);
        let commit_ref = run_git_ok(&repo, &["rev-parse", "HEAD"]).trim().to_string();
        run_git_ok(&root, &["init", "--bare", remote.to_str().unwrap()]);
        run_git_ok(
            &repo,
            &["remote", "add", "origin", remote.to_str().unwrap()],
        );
        Some(GitPublishFixture {
            root,
            repo,
            remote,
            commit_ref,
        })
    }

    fn git_available() -> bool {
        Command::new("git")
            .arg("--version")
            .output()
            .is_ok_and(|output| output.status.success())
    }

    fn run_git_ok(cwd: &Path, args: &[&str]) -> String {
        let output = Command::new("git")
            .args(args)
            .current_dir(cwd)
            .output()
            .unwrap_or_else(|err| panic!("git {} failed to start: {err}", args.join(" ")));
        assert!(
            output.status.success(),
            "git {} failed\nstdout:\n{}\nstderr:\n{}",
            args.join(" "),
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8_lossy(&output.stdout).into_owned()
    }

    fn plan() -> WorkspacePlanRecord {
        WorkspacePlanRecord {
            id: "plan-test".to_string(),
            workspace_id: "workspace-test".to_string(),
            goal_id: "root-task".to_string(),
            status: "active".to_string(),
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: None,
        }
    }

    fn plan_node() -> WorkspacePlanNodeRecord {
        WorkspacePlanNodeRecord {
            id: "node-test".to_string(),
            plan_id: "plan-test".to_string(),
            parent_id: None,
            kind: "task".to_string(),
            title: "Build feature".to_string(),
            description: String::new(),
            depends_on_json: Vec::new(),
            inputs_schema_json: json!({}),
            outputs_schema_json: json!({}),
            acceptance_criteria_json: Vec::new(),
            feature_checkpoint_json: None,
            handoff_package_json: None,
            recommended_capabilities_json: Vec::new(),
            preferred_agent_id: None,
            estimated_effort_json: json!({}),
            priority: 1,
            intent: "blocked".to_string(),
            execution: "idle".to_string(),
            progress_json: json!({}),
            assignee_agent_id: Some("agent-worker".to_string()),
            current_attempt_id: None,
            workspace_task_id: Some("task-test".to_string()),
            metadata_json: json!({"terminal_attempt_retry_reason": "worker_crashed"}),
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: None,
            completed_at: None,
        }
    }

    fn task_session_attempt(
        id: &str,
        status: &str,
        conversation_id: Option<&str>,
    ) -> WorkspaceTaskSessionAttemptRecord {
        WorkspaceTaskSessionAttemptRecord {
            id: id.to_string(),
            workspace_task_id: "task-test".to_string(),
            root_goal_task_id: "root-task".to_string(),
            workspace_id: "workspace-test".to_string(),
            attempt_number: 1,
            status: status.to_string(),
            conversation_id: conversation_id.map(ToOwned::to_owned),
            worker_agent_id: Some("agent-worker".to_string()),
            leader_agent_id: None,
            candidate_summary: None,
            candidate_artifacts_json: Vec::new(),
            candidate_verifications_json: Vec::new(),
            leader_feedback: None,
            adjudication_reason: None,
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: Some(Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap()),
            completed_at: None,
        }
    }

    fn worker_launch_handler(
        store: Arc<FakeWorkspacePlanDispatchStore>,
        max_active: i64,
    ) -> WorkerLaunchAdmissionHandler {
        WorkerLaunchAdmissionHandler::with_config(
            store as Arc<dyn WorkspacePlanDispatchStore>,
            WorkerLaunchAdmissionConfig {
                max_active_worker_conversations: max_active,
                defer_seconds: 30,
                active_event_grace_seconds: 60,
                stream_poll_interval_seconds: 5,
            },
        )
    }

    fn worker_launch_handler_with_state(
        store: Arc<FakeWorkspacePlanDispatchStore>,
        runtime_state: Arc<FakeWorkerLaunchRuntimeStateStore>,
        max_active: i64,
    ) -> WorkerLaunchAdmissionHandler {
        WorkerLaunchAdmissionHandler::with_config_and_runtime_state(
            store as Arc<dyn WorkspacePlanDispatchStore>,
            runtime_state as Arc<dyn WorkerLaunchRuntimeStateStore>,
            WorkerLaunchAdmissionConfig {
                max_active_worker_conversations: max_active,
                defer_seconds: 30,
                active_event_grace_seconds: 60,
                stream_poll_interval_seconds: 5,
            },
        )
    }

    fn worker_launch_handler_with_event_stream(
        store: Arc<FakeWorkspacePlanDispatchStore>,
        stream_events: Arc<FakeWorkerLaunchEventStream>,
        max_active: i64,
    ) -> WorkerLaunchAdmissionHandler {
        WorkerLaunchAdmissionHandler::with_config_and_event_stream(
            store as Arc<dyn WorkspacePlanDispatchStore>,
            stream_events as Arc<dyn WorkerLaunchEventStream>,
            WorkerLaunchAdmissionConfig {
                max_active_worker_conversations: max_active,
                defer_seconds: 30,
                active_event_grace_seconds: 60,
                stream_poll_interval_seconds: 5,
            },
        )
    }

    fn worker_launch_handler_with_state_and_event_stream(
        store: Arc<FakeWorkspacePlanDispatchStore>,
        runtime_state: Arc<FakeWorkerLaunchRuntimeStateStore>,
        stream_events: Arc<FakeWorkerLaunchEventStream>,
        max_active: i64,
    ) -> WorkerLaunchAdmissionHandler {
        WorkerLaunchAdmissionHandler::with_config_and_runtime_state_and_event_stream(
            store as Arc<dyn WorkspacePlanDispatchStore>,
            runtime_state as Arc<dyn WorkerLaunchRuntimeStateStore>,
            stream_events as Arc<dyn WorkerLaunchEventStream>,
            WorkerLaunchAdmissionConfig {
                max_active_worker_conversations: max_active,
                defer_seconds: 30,
                active_event_grace_seconds: 60,
                stream_poll_interval_seconds: 5,
            },
        )
    }

    fn worker_launch_item() -> WorkspacePlanOutboxRecord {
        let mut item = outbox("job-worker-launch", WORKER_LAUNCH_EVENT);
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "task_id": "task-test",
            "node_id": "node-test",
            "worker_agent_id": "agent-worker",
            "actor_user_id": "actor-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
            "attempt_id": "attempt-test",
            "extra_instructions": "continue implementation"
        });
        item
    }

    fn pipeline_run_handler(
        store: Arc<FakeWorkspacePlanDispatchStore>,
    ) -> PipelineRunAdmissionHandler {
        PipelineRunAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>, None)
    }

    fn pipeline_run_handler_with_stage_runner(
        store: Arc<FakeWorkspacePlanDispatchStore>,
        stage_runner: Arc<dyn WorkspacePipelineStageRunner>,
    ) -> PipelineRunAdmissionHandler {
        PipelineRunAdmissionHandler::new(
            store as Arc<dyn WorkspacePlanDispatchStore>,
            Some(stage_runner),
        )
    }

    fn pipeline_run_item() -> WorkspacePlanOutboxRecord {
        let mut item = outbox("job-pipeline-run", PIPELINE_RUN_REQUESTED_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "node_id": "node-test",
            "attempt_id": "attempt-test",
            "reason": "operator requested harness-native pipeline"
        });
        item
    }

    fn pipeline_run_item_without_attempt() -> WorkspacePlanOutboxRecord {
        let mut item = pipeline_run_item();
        if let Some(payload) = item.payload_json.as_object_mut() {
            payload.remove("attempt_id");
        }
        item
    }

    fn pipeline_run_record(
        id: &str,
        status: &str,
        attempt_id: Option<&str>,
        commit_ref: Option<&str>,
        metadata_json: Value,
    ) -> WorkspacePipelineRunRecord {
        let timestamp = Utc.with_ymd_and_hms(2026, 1, 2, 3, 5, 5).unwrap();
        WorkspacePipelineRunRecord {
            id: id.to_string(),
            contract_id: "pipeline-contract-test".to_string(),
            workspace_id: "workspace-test".to_string(),
            plan_id: Some("plan-test".to_string()),
            node_id: Some("node-test".to_string()),
            attempt_id: attempt_id.map(ToOwned::to_owned),
            commit_ref: commit_ref.map(ToOwned::to_owned),
            provider: "sandbox_native".to_string(),
            status: status.to_string(),
            reason: None,
            started_at: Some(Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap()),
            completed_at: if status == "running" {
                None
            } else {
                Some(timestamp)
            },
            metadata_json,
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 6, 5).unwrap(),
            updated_at: None,
        }
    }

    fn pipeline_stage_run_record(id: &str, run_id: &str) -> WorkspacePipelineStageRunRecord {
        let timestamp = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        WorkspacePipelineStageRunRecord {
            id: id.to_string(),
            run_id: run_id.to_string(),
            workspace_id: "workspace-test".to_string(),
            stage: "test".to_string(),
            status: "running".to_string(),
            command: Some("cargo test --workspace".to_string()),
            exit_code: None,
            stdout_preview: None,
            stderr_preview: None,
            log_ref: None,
            artifact_refs_json: Vec::new(),
            started_at: Some(timestamp),
            completed_at: None,
            duration_ms: None,
            metadata_json: json!({"required": true}),
            created_at: timestamp,
            updated_at: None,
        }
    }

    fn supervisor_tick_handler(
        store: Arc<FakeWorkspacePlanDispatchStore>,
    ) -> SupervisorTickAdmissionHandler {
        SupervisorTickAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>)
    }

    fn supervisor_tick_retry_item() -> WorkspacePlanOutboxRecord {
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "retry_node_id": "node-test",
            "retry_attempt_id": "attempt-stale",
            "retry_reason": "stale_plan_node_no_terminal_worker_report",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
            "extra_instructions": "recover stale node"
        });
        item
    }

    #[test]
    fn workspace_plan_outbox_handlers_register_required_foundations() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        let handlers = workspace_plan_outbox_handlers(store as Arc<dyn WorkspacePlanDispatchStore>);

        assert!(missing_required_handler_event_types(&handlers).is_empty());
        assert_eq!(handlers.len(), required_handler_event_types().len());
    }

    #[tokio::test]
    async fn handoff_retry_handler_projects_attempt_and_queues_worker_launch() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = DurableHandoffResumeHandler::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>
        );
        let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "task_id": "task-test",
            "node_id": "node-test",
            "worker_agent_id": "agent-worker",
            "actor_user_id": "actor-test",
            "previous_attempt_id": "attempt-old",
            "extra_instructions": "retry with context"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let attempts = store.attempts();
        assert_eq!(attempts.len(), 1);
        let attempt = &attempts[0];
        assert_eq!(attempt.workspace_task_id, "task-test");
        assert_eq!(attempt.root_goal_task_id, "root-task");
        assert_eq!(attempt.status, "running");
        assert_eq!(attempt.attempt_number, 1);
        assert_eq!(attempt.worker_agent_id.as_deref(), Some("agent-worker"));
        assert_eq!(attempt.leader_agent_id, None);

        let task = store.task("task-test");
        assert_eq!(task.status, "in_progress");
        assert_eq!(
            task.metadata_json[CURRENT_ATTEMPT_ID].as_str(),
            Some(attempt.id.as_str())
        );
        assert_eq!(task.metadata_json["launch_state"], "scheduled");
        assert_eq!(task.metadata_json["last_attempt_status"], "running");

        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "dispatched");
        assert_eq!(
            node.current_attempt_id.as_deref(),
            Some(attempt.id.as_str())
        );
        assert_eq!(
            node.handoff_package_json
                .as_ref()
                .and_then(|value| value["previous_attempt_id"].as_str()),
            Some("attempt-old")
        );

        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
        assert_eq!(
            queued[0].payload_json["attempt_id"].as_str(),
            Some(attempt.id.as_str())
        );
        assert_eq!(
            queued[0].payload_json["extra_instructions"].as_str(),
            Some("retry with context")
        );
        assert_eq!(
            queued[0].metadata_json["source"].as_str(),
            Some("workspace_plan.attempt_retry")
        );
    }

    #[tokio::test]
    async fn handoff_retry_handler_preserves_worker_stream_orphan_retry_context() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        let mut task = task_with_plan_metadata();
        task.blocker_reason =
            Some("Worker stream stopped without a terminal complete/error event".to_string());
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("42-0"));
        task_metadata.insert(
            "worker_stream_replay_attempt_id".to_string(),
            json!("attempt-old"),
        );
        task_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
        task_metadata.insert(
            "worker_stream_terminal_outcome".to_string(),
            json!("no_terminal_event"),
        );
        task_metadata.insert("last_worker_report_type".to_string(), json!("blocked"));
        task_metadata.insert(
            LAST_WORKER_REPORT_SUMMARY.to_string(),
            json!("old orphan report"),
        );
        task_metadata.insert(
            LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
            json!("attempt-old"),
        );
        task_metadata.insert(PENDING_LEADER_ADJUDICATION.to_string(), json!(true));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        let mut node_metadata = object_or_empty(node.metadata_json.clone());
        node_metadata.insert("worker_stream_last_entry_id".to_string(), json!("42-0"));
        node_metadata.insert(
            "worker_stream_replay_attempt_id".to_string(),
            json!("attempt-old"),
        );
        node_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
        node_metadata.insert("last_worker_report_type".to_string(), json!("blocked"));
        node_metadata.insert(
            LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
            json!("attempt-old"),
        );
        node.metadata_json = Value::Object(node_metadata);
        store.insert_node(node);
        let handler = DurableHandoffResumeHandler::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>
        );
        let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "task_id": "task-test",
            "node_id": "node-test",
            "worker_agent_id": "agent-worker",
            "actor_user_id": "actor-test",
            "previous_attempt_id": "attempt-old",
            "retry_reason": "worker_stream_agent_not_running_stream_idle",
            "retry_origin": "worker_stream_orphan_report",
            "worker_stream_orphan_retry_reason": "worker_stream_agent_not_running_stream_idle",
            "worker_stream_orphan_summary": "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert!(task.blocker_reason.is_none());
        assert_eq!(
            task.metadata_json["last_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(
            task.metadata_json["last_retry_previous_attempt_id"],
            "attempt-old"
        );
        assert_eq!(
            task.metadata_json["retry_origin"],
            "worker_stream_orphan_report"
        );
        assert_eq!(
            task.metadata_json["worker_stream_orphan_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert!(task
            .metadata_json
            .get("last_retry_context_at")
            .and_then(Value::as_str)
            .is_some());
        for key in [
            "worker_stream_last_entry_id",
            "worker_stream_replay_attempt_id",
            "worker_stream_message_id",
            "worker_stream_terminal_outcome",
            "last_worker_report_type",
            LAST_WORKER_REPORT_SUMMARY,
            LAST_WORKER_REPORT_ATTEMPT_ID,
            PENDING_LEADER_ADJUDICATION,
        ] {
            assert!(
                task.metadata_json.get(key).is_none(),
                "task metadata key {key} should be cleared for retry"
            );
        }

        let node = store.node("node-test");
        let handoff = node.handoff_package_json.as_ref().unwrap();
        assert_eq!(
            handoff["retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(
            handoff["worker_stream_orphan_summary"],
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        );
        assert_eq!(
            node.metadata_json["worker_stream_orphan_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        for key in [
            "worker_stream_last_entry_id",
            "worker_stream_replay_attempt_id",
            "worker_stream_message_id",
            "last_worker_report_type",
            LAST_WORKER_REPORT_ATTEMPT_ID,
        ] {
            assert!(
                node.metadata_json.get(key).is_none(),
                "node metadata key {key} should be cleared for retry"
            );
        }

        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
        assert_eq!(queued[0].payload_json["previous_attempt_id"], "attempt-old");
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(
            queued[0].payload_json["retry_origin"],
            "worker_stream_orphan_report"
        );
        assert_eq!(
            queued[0].payload_json["worker_stream_orphan_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
    }

    #[tokio::test]
    async fn handoff_retry_handler_applies_attempt_worktree_checkpoint_to_feature_node() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.feature_checkpoint_json = Some(json!({
            "commit_ref": "abcdef1234567890",
            "base_ref": "main",
            "expected_artifacts": ["src/lib.rs"]
        }));
        store.insert_node(node);
        let handler = DurableHandoffResumeHandler::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanDispatchStore>
        );
        let mut item = outbox("job-retry", ATTEMPT_RETRY_EVENT);
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "task_id": "task-test",
            "node_id": "node-test",
            "worker_agent_id": "agent-worker",
            "actor_user_id": "actor-test",
            "previous_attempt_id": "attempt-old",
            "extra_instructions": "retry with context"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        let attempt_id = node.current_attempt_id.as_deref().unwrap();
        let checkpoint = node.feature_checkpoint_json.as_ref().unwrap();
        assert_eq!(
            checkpoint["worktree_path"],
            format!("${{sandbox_code_root}}/../.memstack/worktrees/{attempt_id}")
        );
        assert_eq!(
            checkpoint["branch_name"],
            worktree_branch_name("node-test", attempt_id)
        );
        assert_eq!(checkpoint["base_ref"], "abcdef1234567890");
    }

    #[test]
    fn worker_conversation_id_matches_python_uuid5_contract() {
        assert_eq!(
            worker_conversation_id(
                "workspace-test",
                "agent-worker",
                "task-test",
                Some("attempt-test")
            ),
            "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
        );
    }

    #[test]
    fn should_stop_orphaned_worker_stream_matches_python_contract() {
        let finished_without_stream =
            worker_stream_watchdog::should_stop(Some("msg-1"), None, true, 0.0, Some(900));
        assert!(finished_without_stream.should_stop);
        assert_eq!(
            finished_without_stream
                .reason
                .map(worker_stream_watchdog::StopReason::as_str),
            Some("agent_finished_without_terminal_event")
        );

        let finished_matching_stream =
            worker_stream_watchdog::should_stop(Some("msg-1"), Some("msg-1"), true, 0.0, Some(900));
        assert!(finished_matching_stream.should_stop);
        assert_eq!(
            finished_matching_stream
                .reason
                .map(worker_stream_watchdog::StopReason::as_str),
            Some("agent_finished_without_terminal_event")
        );

        let finished_for_other_message = worker_stream_watchdog::should_stop(
            Some("msg-2"),
            Some("msg-1"),
            true,
            999.0,
            Some(900),
        );
        assert!(!finished_for_other_message.should_stop);
        assert_eq!(finished_for_other_message.reason, None);

        let not_running_below_grace =
            worker_stream_watchdog::should_stop(None, Some("msg-1"), false, 899.0, Some(900));
        assert!(!not_running_below_grace.should_stop);
        assert_eq!(not_running_below_grace.reason, None);

        let not_running_at_grace =
            worker_stream_watchdog::should_stop(None, Some("msg-1"), false, 900.0, Some(900));
        assert!(not_running_at_grace.should_stop);
        assert_eq!(
            not_running_at_grace
                .reason
                .map(worker_stream_watchdog::StopReason::as_str),
            Some("agent_not_running_stream_idle")
        );

        let running_over_grace =
            worker_stream_watchdog::should_stop(None, Some("msg-1"), true, 1200.0, Some(900));
        assert!(!running_over_grace.should_stop);
        assert_eq!(running_over_grace.reason, None);

        let clamped_grace = worker_stream_watchdog::should_stop(None, None, false, 1.0, Some(0));
        assert!(clamped_grace.should_stop);
        assert_eq!(
            clamped_grace
                .reason
                .map(worker_stream_watchdog::StopReason::as_str),
            Some("agent_not_running_stream_idle")
        );

        let empty_finished_marker =
            worker_stream_watchdog::should_stop(Some(""), None, false, 0.5, Some(1));
        assert!(!empty_finished_marker.should_stop);
        assert_eq!(empty_finished_marker.reason, None);
    }

    #[test]
    fn worker_stream_watchdog_extracts_message_id_like_python() {
        assert_eq!(
            worker_stream_watchdog::message_id_from_event(&json!({
                "type": "message",
                "data": {"id": "msg-primary", "message_id": "msg-secondary"}
            })),
            Some("msg-primary")
        );
        assert_eq!(
            worker_stream_watchdog::message_id_from_event(&json!({
                "type": "message",
                "data": {"message_id": "msg-secondary"}
            })),
            Some("msg-secondary")
        );
        assert_eq!(
            worker_stream_watchdog::message_id_from_event(&json!({
                "type": "message",
                "data": {"id": ""}
            })),
            None
        );
        assert_eq!(
            worker_stream_watchdog::message_id_from_event(&json!({
                "type": "text_delta",
                "data": {"id": "msg-ignored"}
            })),
            None
        );
        assert_eq!(
            worker_stream_watchdog::message_id_from_event(&json!({
                "type": "message",
                "data": []
            })),
            None
        );
    }

    #[test]
    fn worker_stream_watchdog_idle_progress_matches_python_contract() {
        assert!(!worker_stream_watchdog::should_publish_idle_progress(
            59.9,
            0.0,
            100.0,
            Some(60)
        ));
        assert!(worker_stream_watchdog::should_publish_idle_progress(
            60.0,
            0.0,
            100.0,
            Some(60)
        ));
        assert!(!worker_stream_watchdog::should_publish_idle_progress(
            120.0,
            90.0,
            149.9,
            Some(60)
        ));
        assert!(worker_stream_watchdog::should_publish_idle_progress(
            120.0,
            90.0,
            150.0,
            Some(60)
        ));
        assert!(worker_stream_watchdog::should_publish_idle_progress(
            1.0,
            0.0,
            1.0,
            Some(0)
        ));

        assert_eq!(
            worker_stream_watchdog::idle_progress_summary(61.9, Some("observe"), true, None),
            "Worker stream still active; no new visible stream event for 61s; agent:running present; last_event=observe"
        );
        assert_eq!(
            worker_stream_watchdog::idle_progress_summary(
                900.0,
                Some(""),
                false,
                Some("msg-1")
            ),
            "Worker stream still active; no new visible stream event for 900s; agent:running missing; agent:finished=msg-1"
        );
    }

    #[test]
    fn worker_stream_watchdog_launch_started_summary_matches_python_contract() {
        assert_eq!(
            worker_stream_watchdog::worker_launch_started_summary(
                Some("9"),
                Some(
                    "verification failed:\n  - clean_worktree_after_commit: ?? .playwright-cache/; ?? logs/"
                ),
            ),
            "Worker attempt #9 started from verifier feedback: verification failed: - clean_worktree_after_commit: ?? .playwright-cache/; ?? logs/"
        );
        assert_eq!(
            worker_stream_watchdog::worker_launch_started_summary(None, None),
            "Worker attempt started; session is bound and streaming."
        );
        let long_feedback = "x".repeat(WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 50);
        let summary =
            worker_stream_watchdog::worker_launch_started_summary(Some("10"), Some(&long_feedback));
        assert!(summary.starts_with("Worker attempt #10 started from verifier feedback: "));
        assert!(summary.ends_with("..."));
        assert!(summary.len() < WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 80);

        let unicode_feedback = "验".repeat(WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 1);
        let unicode_summary = worker_stream_watchdog::worker_launch_started_summary(
            Some("11"),
            Some(&unicode_feedback),
        );
        assert!(unicode_summary.ends_with("..."));
    }

    #[test]
    fn worker_stream_watchdog_completion_summary_matches_python_contract() {
        assert_eq!(
            worker_stream_watchdog::stream_completion_summary("Finished the implementation.", ""),
            "Finished the implementation."
        );
        assert_eq!(
            worker_stream_watchdog::stream_completion_summary("", ""),
            "Worker stream completed without an explicit workspace terminal report."
        );
        let accumulated = "x".repeat(2500);
        let summary = worker_stream_watchdog::stream_completion_summary("", &accumulated);
        assert_eq!(summary.len(), WORKER_STREAM_COMPLETION_SUMMARY_CHARS);
        assert!(summary.ends_with("..."));

        let unicode_accumulated = "完".repeat(WORKER_STREAM_COMPLETION_SUMMARY_CHARS + 1);
        let unicode_summary =
            worker_stream_watchdog::stream_completion_summary("", &unicode_accumulated);
        assert_eq!(
            unicode_summary.chars().count(),
            WORKER_STREAM_COMPLETION_SUMMARY_CHARS
        );
        assert!(unicode_summary.ends_with("..."));
    }

    #[test]
    fn worker_stream_watchdog_terminal_report_observations_match_python_contract() {
        let denied = json!({
            "type": "observe",
            "data": {
                "tool_name": "workspace_report_complete",
                "result": "{\"error\": \"completion denied: protected test/review node includes failed evidence\"}",
                "error": null
            }
        });
        assert_eq!(
            worker_stream_watchdog::terminal_report_tool_observation_status(&denied)
                .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
            Some("denied")
        );
        assert!(!worker_stream_watchdog::should_synthesize_stream_completion_report(true));

        let applied = json!({
            "type": "observe",
            "data": {
                "tool_name": "workspace_report_blocked",
                "result": "{\"applied_report\": {\"applied\": true}}",
                "error": null
            }
        });
        assert_eq!(
            worker_stream_watchdog::terminal_report_tool_observation_status(&applied)
                .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
            Some("applied")
        );
        assert_eq!(
            worker_stream_watchdog::terminal_report_tool_report_type(&applied)
                .map(worker_stream_watchdog::TerminalReportType::as_str),
            Some("blocked")
        );

        let supervisor_only = json!({
            "type": "observe",
            "data": {
                "tool_name": "workspace_report_complete",
                "result": "{\"ok\": true, \"applied_report\": {\"skipped_supervisor_only\": true, \"reason\": \"WORKSPACE_WTP_V1_ONLY\"}}",
                "error": null
            }
        });
        assert_eq!(
            worker_stream_watchdog::terminal_report_tool_observation_status(&supervisor_only)
                .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
            Some("attempted")
        );

        let non_terminal_tool = json!({
            "type": "observe",
            "data": {"tool_name": "bash", "result": "done", "error": null}
        });
        assert_eq!(
            worker_stream_watchdog::terminal_report_tool_observation_status(&non_terminal_tool),
            None
        );
        assert!(worker_stream_watchdog::should_synthesize_stream_completion_report(false));
    }

    #[test]
    fn worker_stream_watchdog_terminal_report_metadata_matches_python_contract() {
        let metadata = json!({
            "last_worker_report_attempt_id": "attempt-1",
            "last_worker_report_type": "completed"
        });
        assert!(
            worker_stream_watchdog::terminal_report_metadata_matches_attempt(
                Some(&metadata),
                Some("attempt-1"),
                Some("completed")
            )
        );
        assert!(
            !worker_stream_watchdog::terminal_report_metadata_matches_attempt(
                Some(&metadata),
                Some("attempt-2"),
                Some("completed")
            )
        );
        assert!(
            !worker_stream_watchdog::terminal_report_metadata_matches_attempt(
                Some(&metadata),
                Some("attempt-1"),
                Some("blocked")
            )
        );
        assert!(worker_stream_watchdog::should_reconcile_terminal_report_tool(true, false));
        assert!(!worker_stream_watchdog::should_reconcile_terminal_report_tool(true, true));
        assert!(!worker_stream_watchdog::should_reconcile_terminal_report_tool(false, false));
    }

    #[test]
    fn worker_stream_watchdog_reduces_text_then_complete_like_python_stream_loop() {
        let mut state = worker_stream_watchdog::StreamState::default();
        assert_eq!(
            state.observe_event(&json!({
                "type": "message",
                "data": {"id": "msg-1"}
            })),
            None
        );
        assert_eq!(state.stream_message_id.as_deref(), Some("msg-1"));
        assert_eq!(
            state.observe_event(&json!({
                "type": "text_delta",
                "data": {"text": "Finished "}
            })),
            None
        );
        assert_eq!(
            state.observe_event(&json!({
                "type": "text_delta",
                "data": {"text": "implementation."}
            })),
            None
        );
        assert_eq!(
            state.observe_event(&json!({
                "type": "complete",
                "data": {"content": ""}
            })),
            Some(worker_stream_watchdog::StreamTerminalEvent::Complete)
        );
        assert_eq!(state.final_content, "Finished implementation.");
        assert_eq!(state.last_stream_event_type.as_deref(), Some("complete"));

        let outcome = state.terminal_outcome(false);
        assert_eq!(outcome.outcome_reason, "completed");
        assert_eq!(outcome.launch_state, "completed_via_stream");
        assert_eq!(
            outcome
                .report_type
                .map(worker_stream_watchdog::TerminalReportType::as_str),
            Some("completed")
        );
        assert_eq!(outcome.summary, "Finished implementation.");
        assert!(outcome.should_report);
        assert!(!outcome.should_reconcile);
    }

    #[test]
    fn worker_stream_watchdog_terminal_tool_outcomes_match_python_stream_loop() {
        let mut denied = worker_stream_watchdog::StreamState::default();
        denied.observe_event(&json!({
            "type": "observe",
            "data": {
                "tool_name": "workspace_report_complete",
                "result": "{\"error\": \"completion denied: failed tests\"}",
                "error": null
            }
        }));
        denied.observe_event(&json!({
            "type": "complete",
            "data": {"content": "ignored fallback"}
        }));
        let denied_outcome = denied.terminal_outcome(false);
        assert_eq!(denied_outcome.outcome_reason, "terminal_report_tool_denied");
        assert_eq!(denied_outcome.launch_state, "terminal_report_tool_denied");
        assert!(!denied_outcome.should_report);

        let mut applied = worker_stream_watchdog::StreamState::default();
        applied.observe_event(&json!({
            "type": "observe",
            "data": {
                "tool_name": "workspace_report_blocked",
                "result": "{\"applied_report\": {\"applied\": true}}",
                "error": null
            }
        }));
        applied.observe_event(&json!({
            "type": "complete",
            "data": {"content": "blocked summary"}
        }));
        let reconcile = applied.terminal_outcome(false);
        assert_eq!(reconcile.outcome_reason, "terminal_report_tool_reconciled");
        assert_eq!(reconcile.launch_state, "terminal_report_tool_reconciled");
        assert_eq!(
            reconcile
                .report_type
                .map(worker_stream_watchdog::TerminalReportType::as_str),
            Some("blocked")
        );
        assert!(reconcile.should_report);
        assert!(reconcile.should_reconcile);

        let already_recorded = applied.terminal_outcome(true);
        assert_eq!(
            already_recorded.outcome_reason,
            "terminal_report_tool_applied"
        );
        assert!(!already_recorded.should_report);
    }

    #[test]
    fn worker_stream_watchdog_error_and_missing_terminal_outcomes_match_python_loop() {
        let mut error = worker_stream_watchdog::StreamState::default();
        assert_eq!(
            error.observe_event(&json!({
                "type": "error",
                "data": {"message": "worker failed"}
            })),
            Some(worker_stream_watchdog::StreamTerminalEvent::Error)
        );
        let error_outcome = error.terminal_outcome(false);
        assert_eq!(error_outcome.outcome_reason, "blocked");
        assert_eq!(error_outcome.launch_state, "blocked");
        assert_eq!(
            error_outcome
                .report_type
                .map(worker_stream_watchdog::TerminalReportType::as_str),
            Some("blocked")
        );
        assert_eq!(error_outcome.summary, "worker failed");
        assert!(error_outcome.should_report);

        let mut ended = worker_stream_watchdog::StreamState::default();
        ended.mark_stream_ended_without_terminal();
        let ended_outcome = ended.terminal_outcome(false);
        assert_eq!(ended_outcome.outcome_reason, "no_terminal_event");
        assert_eq!(
            ended_outcome.summary,
            "Worker stream ended without a terminal complete/error event."
        );
        assert!(ended_outcome.should_report);

        let mut orphan = worker_stream_watchdog::StreamState::default();
        orphan.mark_orphaned_stream_stop(Some("agent_not_running_stream_idle"));
        let orphan_outcome = orphan.terminal_outcome(false);
        assert_eq!(orphan_outcome.outcome_reason, "no_terminal_event");
        assert_eq!(
            orphan_outcome.summary,
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        );
    }

    #[tokio::test]
    async fn worker_stream_terminal_outcome_persists_completed_report_like_python() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(root_goal_task());
        let mut task = task_with_plan_metadata();
        task.status = "in_progress".to_string();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt(
            "attempt-test",
            "running",
            Some("conversation-test"),
        ));
        let handler = worker_launch_handler(Arc::clone(&store), 4);
        let mut stream = worker_stream_watchdog::StreamState::default();
        stream.observe_event(&json!({
            "type": "complete",
            "data": {
                "content": "{\"summary\":\"finished from stream\",\"commit_ref\":\"abcdef1234567890\",\"test_commands\":[\"cargo test -p app\"]}"
            }
        }));
        let outcome = stream.terminal_outcome(false);

        let reported = handler
            .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
                workspace_id: "workspace-test",
                task_id: "task-test",
                root_goal_task_id: Some("root-task"),
                attempt_id: Some("attempt-test"),
                conversation_id: Some("conversation-test"),
                actor_user_id: "actor-test",
                worker_agent_id: "agent-worker",
                leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
                plan_id: Some("plan-test"),
                node_id: Some("node-test"),
                outcome: &outcome,
                now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 0, 0).unwrap(),
            })
            .await
            .unwrap();

        assert!(reported);
        let task = store.task("task-test");
        assert_eq!(task.status, "in_progress");
        assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
        assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
        assert_eq!(
            task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
            "finished from stream"
        );
        assert_eq!(
            task.metadata_json[LAST_WORKER_REPORT_ATTEMPT_ID],
            "attempt-test"
        );
        assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
        assert_eq!(
            task.metadata_json["last_attempt_status"],
            "awaiting_plan_verification"
        );
        assert_eq!(
            task.metadata_json["last_worker_report_artifacts"],
            json!(["commit_ref:abcdef1234567890"])
        );
        assert_eq!(
            task.metadata_json["last_worker_report_verifications"],
            json!(["test_run:cargo test -p app"])
        );
        assert_eq!(
            task.metadata_json["execution_state"]["last_agent_action"],
            "await_plan_verification"
        );
        assert_eq!(
            task.metadata_json["last_worker_report_fingerprint"]
                .as_str()
                .unwrap()
                .len(),
            64
        );
        let attempt = store.attempts().remove(0);
        assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
        assert_eq!(
            attempt.candidate_summary.as_deref(),
            Some("finished from stream")
        );
        assert_eq!(
            attempt.candidate_artifacts_json,
            vec!["commit_ref:abcdef1234567890".to_string()]
        );
        assert_eq!(
            attempt.candidate_verifications_json,
            vec!["test_run:cargo test -p app".to_string()]
        );
        assert_eq!(
            attempt.conversation_id.as_deref(),
            Some("conversation-test")
        );
        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.progress_json["note"], "finished from stream");
        assert_eq!(
            node.metadata_json["latest_worker_progress"]["attempt_id"],
            "attempt-test"
        );
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "worker_report_terminal");
        assert_eq!(events[0].payload_json["report_type"], "completed");
        let outbox = store.outbox();
        assert_eq!(outbox.len(), 1);
        assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
        assert_eq!(outbox[0].metadata_json["source"], "worker_report");
    }

    #[tokio::test]
    async fn worker_stream_terminal_outcome_persists_no_terminal_blocked_report() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(root_goal_task());
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let handler = worker_launch_handler(Arc::clone(&store), 4);
        let mut stream = worker_stream_watchdog::StreamState::default();
        stream.mark_stream_ended_without_terminal();
        let outcome = stream.terminal_outcome(false);

        let reported = handler
            .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
                workspace_id: "workspace-test",
                task_id: "task-test",
                root_goal_task_id: Some("root-task"),
                attempt_id: Some("attempt-test"),
                conversation_id: Some("conversation-test"),
                actor_user_id: "actor-test",
                worker_agent_id: "agent-worker",
                leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
                plan_id: Some("plan-test"),
                node_id: Some("node-test"),
                outcome: &outcome,
                now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 1, 0).unwrap(),
            })
            .await
            .unwrap();

        assert!(reported);
        let task = store.task("task-test");
        assert_eq!(task.status, "in_progress");
        assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
        assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
        assert_eq!(
            task.blocker_reason.as_deref(),
            Some("Worker stream ended without a terminal complete/error event.")
        );
        let attempt = store.attempts().remove(0);
        assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
        assert_eq!(
            attempt.candidate_summary.as_deref(),
            Some("Worker stream ended without a terminal complete/error event.")
        );
        assert!(attempt.candidate_verifications_json.is_empty());
        let node = store.node("node-test");
        assert_eq!(node.execution, "reported");
        assert_eq!(
            store.plan_events()[0].payload_json["report_type"],
            "blocked"
        );
    }

    #[tokio::test]
    async fn worker_stream_terminal_outcome_does_not_duplicate_applied_terminal_tool_report() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let handler = worker_launch_handler(Arc::clone(&store), 4);
        let mut stream = worker_stream_watchdog::StreamState::default();
        stream.observe_event(&json!({
            "type": "observe",
            "data": {
                "tool_name": "workspace_report_complete",
                "result": "{\"applied_report\":{\"applied\":true}}"
            }
        }));
        stream.observe_event(&json!({"type": "complete", "data": {"content": "done"}}));
        let outcome = stream.terminal_outcome(true);

        let reported = handler
            .persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
                workspace_id: "workspace-test",
                task_id: "task-test",
                root_goal_task_id: Some("root-task"),
                attempt_id: Some("attempt-test"),
                conversation_id: None,
                actor_user_id: "actor-test",
                worker_agent_id: "agent-worker",
                leader_agent_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
                plan_id: Some("plan-test"),
                node_id: Some("node-test"),
                outcome: &outcome,
                now: Utc.with_ymd_and_hms(2026, 1, 2, 4, 2, 0).unwrap(),
            })
            .await
            .unwrap();

        assert!(!reported);
        let task = store.task("task-test");
        assert_eq!(
            task.metadata_json["launch_state"],
            "terminal_report_tool_applied"
        );
        assert!(task.metadata_json.get("last_worker_report_type").is_none());
        let attempt = store.attempts().remove(0);
        assert_eq!(attempt.status, "running");
        assert!(attempt.candidate_summary.is_none());
        assert!(store.plan_events().is_empty());
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn worker_launch_handler_binds_conversation_and_marks_node_running() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task_metadata.insert("preferred_language".to_string(), json!("zh-CN"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let handler = worker_launch_handler(Arc::clone(&store), 4);
        let mut item = worker_launch_item();
        if let Some(payload) = item.payload_json.as_object_mut() {
            payload.insert("previous_attempt_id".to_string(), json!("attempt-old"));
            payload.insert(
                "retry_reason".to_string(),
                json!("worker_stream_agent_not_running_stream_idle"),
            );
            payload.insert(
                "retry_origin".to_string(),
                json!("worker_stream_orphan_report"),
            );
            payload.insert(
                "worker_stream_orphan_retry_reason".to_string(),
                json!("worker_stream_agent_not_running_stream_idle"),
            );
            payload.insert(
                "worker_stream_orphan_summary".to_string(),
                json!(
                    "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
                ),
            );
        }

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.status, "in_progress");
        assert_eq!(task.metadata_json["launch_state"], "bound");
        assert_eq!(
            task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
            "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
        );
        assert_eq!(task.metadata_json["current_attempt_number"], 1);
        assert_eq!(
            task.metadata_json["current_attempt_worker_agent_id"],
            "agent-worker"
        );
        assert!(task.metadata_json["worker_launch_admitted_at"].is_string());
        assert!(task.metadata_json["worker_launch_bound_at"].is_string());
        assert_eq!(
            task.metadata_json["last_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(
            task.metadata_json["last_retry_previous_attempt_id"],
            "attempt-old"
        );
        assert_eq!(
            task.metadata_json["worker_stream_orphan_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, "running");
        assert_eq!(
            attempt.conversation_id.as_deref(),
            Some("d267a78e-eefc-5d33-bfb3-ac4fa7ece855")
        );
        let conversation = store.conversation("d267a78e-eefc-5d33-bfb3-ac4fa7ece855");
        assert_eq!(conversation.project_id, "project-test");
        assert_eq!(conversation.tenant_id, "tenant-test");
        assert_eq!(conversation.user_id, "actor-test");
        assert_eq!(conversation.title, "Workspace Worker - Build feature");
        assert_eq!(
            conversation.agent_config_json["selected_agent_id"],
            "agent-worker"
        );
        assert_eq!(
            conversation.metadata_json["source"],
            "workspace_worker_launch"
        );
        assert_eq!(
            conversation.metadata_json["conversation_scope"],
            "task:task-test:attempt:attempt-test"
        );
        assert_eq!(conversation.metadata_json["preferred_language"], "zh-CN");
        assert_eq!(
            conversation.metadata_json["last_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(
            conversation.metadata_json["last_retry_previous_attempt_id"],
            "attempt-old"
        );
        assert_eq!(
            conversation.metadata_json["retry_origin"],
            "worker_stream_orphan_report"
        );
        assert_eq!(
            conversation.metadata_json["worker_stream_orphan_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(conversation.participant_agents_json, vec!["agent-worker"]);
        assert_eq!(conversation.focused_agent_id, "agent-worker");
        assert_eq!(conversation.linked_workspace_task_id, "task-test");
        let node = store.node("node-test");
        assert_eq!(node.execution, "running");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
        assert_eq!(node.metadata_json["launch_state"], "bound");
        assert_eq!(
            node.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
            "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
        );
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn worker_launch_handler_replays_bound_stream_complete_to_terminal_report() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(root_goal_task());
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
        let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
        stream_events.push(
            conversation_id,
            "1-0",
            json!({"type": "message", "data": {"id": "msg-1"}}),
        );
        stream_events.push(
            conversation_id,
            "2-0",
            json!({"type": "text_delta", "data": {"text": "finished "}}),
        );
        stream_events.push(
            conversation_id,
            "3-0",
            json!({
                "type": "complete",
                "data": {
                    "content": "{\"summary\":\"done via event stream\",\"test_commands\":[\"cargo test -p app\"]}"
                }
            }),
        );
        let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
        assert_eq!(
            task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
            conversation_id
        );
        assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
        assert_eq!(
            task.metadata_json["worker_stream_replay_status"],
            "terminal"
        );
        assert_eq!(
            task.metadata_json["worker_stream_last_event_type"],
            "complete"
        );
        assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-1");
        assert_eq!(
            task.metadata_json["worker_stream_terminal_outcome"],
            "completed"
        );
        assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
        assert_eq!(
            task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
            "done via event stream"
        );
        assert_eq!(
            task.metadata_json["last_worker_report_verifications"],
            json!(["test_run:cargo test -p app"])
        );

        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
        assert_eq!(
            attempt.candidate_summary.as_deref(),
            Some("done via event stream")
        );
        assert_eq!(attempt.conversation_id.as_deref(), Some(conversation_id));
        let node = store.node("node-test");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.progress_json["note"], "done via event stream");
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "worker_report_terminal");
        let outbox = store.outbox();
        assert_eq!(outbox.len(), 1);
        assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
    }

    #[tokio::test]
    async fn worker_launch_handler_ignores_previous_attempt_stream_cursor() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(root_goal_task());
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("99-0"));
        task_metadata.insert(
            "worker_stream_replay_attempt_id".to_string(),
            json!("attempt-old"),
        );
        task_metadata.insert("worker_stream_message_id".to_string(), json!("old-msg"));
        task_metadata.insert(
            "worker_stream_last_event_type".to_string(),
            json!("text_delta"),
        );
        task_metadata.insert(
            LAST_WORKER_REPORT_ATTEMPT_ID.to_string(),
            json!("attempt-old"),
        );
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
        let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
        stream_events.push(
            conversation_id,
            "1-0",
            json!({"type": "message", "data": {"id": "msg-new"}}),
        );
        stream_events.push(
            conversation_id,
            "2-0",
            json!({
                "type": "complete",
                "data": {
                    "content": "{\"summary\":\"done after retry\",\"test_commands\":[\"cargo test -p retry\"]}"
                }
            }),
        );
        let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "completed_via_stream");
        assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
        assert_eq!(
            task.metadata_json["worker_stream_replay_attempt_id"],
            "attempt-test"
        );
        assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-new");
        assert_eq!(task.metadata_json["last_worker_report_type"], "completed");
        assert_eq!(
            task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
            "done after retry"
        );
        assert_eq!(
            task.metadata_json[LAST_WORKER_REPORT_ATTEMPT_ID],
            "attempt-test"
        );
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
        assert_eq!(
            attempt.candidate_summary.as_deref(),
            Some("done after retry")
        );
        let outbox = store.outbox();
        assert_eq!(outbox.len(), 1);
        assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
    }

    #[tokio::test]
    async fn worker_launch_handler_replays_nonterminal_stream_without_reporting() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
        let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
        stream_events.push(
            conversation_id,
            "1-0",
            json!({"type": "message", "data": {"id": "msg-1"}}),
        );
        stream_events.push(
            conversation_id,
            "2-0",
            json!({"type": "text_delta", "data": {"text": "still running"}}),
        );
        let handler = worker_launch_handler_with_event_stream(Arc::clone(&store), stream_events, 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "bound");
        assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
        assert_eq!(
            task.metadata_json["worker_stream_replay_status"],
            "observed"
        );
        assert_eq!(
            task.metadata_json["worker_stream_last_event_type"],
            "text_delta"
        );
        assert_eq!(task.metadata_json["worker_stream_message_id"], "msg-1");
        assert!(task.metadata_json.get("last_worker_report_type").is_none());
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, "running");
        assert!(attempt.candidate_summary.is_none());
        let node = store.node("node-test");
        assert_eq!(node.execution, "running");
        assert!(store.plan_events().is_empty());
        let outbox = store.outbox();
        assert_eq!(outbox.len(), 1);
        assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
        assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
        assert_eq!(outbox[0].payload_json["stream_after_id"], "2-0");
        assert!(outbox[0]
            .payload_json
            .get("reuse_conversation_id")
            .is_none());
        assert!(outbox[0].next_attempt_at.is_some());
        assert_eq!(
            outbox[0].metadata_json["source"],
            "workspace_plan.worker_launch.stream_poll"
        );
        assert_eq!(outbox[0].metadata_json["stream_poll_after_id"], "2-0");
    }

    #[tokio::test]
    async fn worker_launch_handler_publishes_idle_progress_for_stale_nonterminal_stream() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
        let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
        runtime_state.insert_running(conversation_id);
        let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
        stream_events.push(
            conversation_id,
            "1-0",
            json!({
                "type": "message",
                "event_time_us": 0,
                "data": {"id": "msg-1"}
            }),
        );
        stream_events.push(
            conversation_id,
            "2-0",
            json!({
                "type": "text_delta",
                "event_time_us": 0,
                "data": {"text": "still running"}
            }),
        );
        let handler = worker_launch_handler_with_state_and_event_stream(
            Arc::clone(&store),
            runtime_state,
            stream_events,
            4,
        );

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "bound");
        assert_eq!(
            task.metadata_json["worker_stream_replay_status"],
            "stream_idle"
        );
        assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "2-0");
        assert_eq!(task.metadata_json["worker_stream_last_event_time_us"], 0);
        assert_eq!(
            task.metadata_json["worker_stream_idle_running_exists"],
            true
        );
        assert!(
            task.metadata_json["worker_stream_idle_seconds"]
                .as_i64()
                .unwrap()
                > DEFAULT_WORKER_STREAM_IDLE_PROGRESS_INTERVAL_SECONDS
        );
        let summary = task.metadata_json["worker_stream_idle_progress_summary"]
            .as_str()
            .unwrap();
        assert!(summary.contains("Worker stream still active"));
        assert!(summary.contains("agent:running present"));
        assert!(summary.contains("last_event=text_delta"));
        assert_eq!(
            task.metadata_json["execution_state"]["last_agent_action"],
            "observe_stream_idle"
        );
        assert!(task.metadata_json.get("last_worker_report_type").is_none());

        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, "running");
        assert!(attempt.candidate_summary.is_none());
        let node = store.node("node-test");
        assert_eq!(node.execution, "running");
        assert_eq!(node.metadata_json["launch_state"], "stream_idle");
        assert_eq!(
            node.metadata_json["latest_worker_progress"]["event_type"],
            "worker_stream_idle"
        );
        assert_eq!(
            node.metadata_json["latest_worker_progress"]["attempt_id"],
            "attempt-test"
        );
        assert!(node.progress_json["note"]
            .as_str()
            .unwrap()
            .contains("Worker stream still active"));
        assert!(store.plan_events().is_empty());
        let outbox = store.outbox();
        assert_eq!(outbox.len(), 1);
        assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
        assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
        assert_eq!(outbox[0].payload_json["stream_after_id"], "2-0");
        assert_eq!(
            outbox[0].metadata_json["source"],
            "workspace_plan.worker_launch.stream_poll"
        );
    }

    #[tokio::test]
    async fn worker_launch_stream_poll_bypasses_launch_gates_and_continues_from_cursor() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.set_active_worker_conversations(99);
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
        store.insert_attempt(task_session_attempt(
            "attempt-test",
            "running",
            Some(conversation_id),
        ));
        let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
        runtime_state.insert_cooldown(conversation_id);
        runtime_state.insert_running(conversation_id);
        let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
        stream_events.push(
            conversation_id,
            "2-0",
            json!({"type": "text_delta", "data": {"text": "already seen"}}),
        );
        stream_events.push(
            conversation_id,
            "3-0",
            json!({"type": "text_delta", "data": {"text": "next chunk"}}),
        );
        let handler = worker_launch_handler_with_state_and_event_stream(
            Arc::clone(&store),
            Arc::clone(&runtime_state),
            stream_events,
            1,
        );
        let mut item = worker_launch_item();
        let payload = item.payload_json.as_object_mut().unwrap();
        payload.insert("worker_stream_poll".to_string(), json!(true));
        payload.insert("stream_after_id".to_string(), json!("2-0"));

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert!(runtime_state.claims().is_empty());
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "stream_polling");
        assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
        assert_eq!(
            task.metadata_json["worker_stream_replay_status"],
            "observed"
        );
        assert_eq!(
            task.metadata_json["worker_stream_last_event_type"],
            "text_delta"
        );
        let node = store.node("node-test");
        assert_eq!(node.execution, "running");
        assert_eq!(node.metadata_json["launch_state"], "stream_polling");
        let outbox = store.outbox();
        assert_eq!(outbox.len(), 1);
        assert_eq!(outbox[0].event_type, WORKER_LAUNCH_EVENT);
        assert_eq!(outbox[0].payload_json["worker_stream_poll"], true);
        assert_eq!(outbox[0].payload_json["stream_after_id"], "3-0");
        assert_eq!(
            outbox[0].metadata_json["source"],
            "workspace_plan.worker_launch.stream_poll"
        );
        assert_eq!(outbox[0].metadata_json["stream_poll_entries_read"], 1);
        assert!(outbox[0].next_attempt_at.is_some());
    }

    #[tokio::test]
    async fn worker_launch_stream_poll_persists_orphan_stop_when_running_marker_is_missing() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(root_goal_task());
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
        task_metadata.insert("worker_stream_message_id".to_string(), json!("msg-1"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
        store.insert_attempt(task_session_attempt(
            "attempt-test",
            "running",
            Some(conversation_id),
        ));
        let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
        let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
        stream_events.push(
            conversation_id,
            "2-0",
            json!({
                "type": "text_delta",
                "event_time_us": 0,
                "data": {"text": "already seen"}
            }),
        );
        stream_events.push(
            conversation_id,
            "3-0",
            json!({
                "type": "text_delta",
                "event_time_us": 0,
                "data": {"text": "last visible output"}
            }),
        );
        let handler = worker_launch_handler_with_state_and_event_stream(
            Arc::clone(&store),
            runtime_state,
            stream_events,
            4,
        );
        let mut item = worker_launch_item();
        let payload = item.payload_json.as_object_mut().unwrap();
        payload.insert("worker_stream_poll".to_string(), json!(true));
        payload.insert("stream_after_id".to_string(), json!("2-0"));

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
        assert_eq!(
            task.metadata_json["worker_stream_replay_status"],
            "terminal"
        );
        assert_eq!(task.metadata_json["worker_stream_last_entry_id"], "3-0");
        assert_eq!(
            task.metadata_json["worker_stream_terminal_outcome"],
            "no_terminal_event"
        );
        assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
        assert!(task
            .blocker_reason
            .as_deref()
            .unwrap()
            .contains("agent_not_running_stream_idle"));
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
        assert!(attempt
            .candidate_summary
            .as_deref()
            .unwrap()
            .contains("agent_not_running_stream_idle"));
        let node = store.node("node-test");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.metadata_json["launch_state"], "no_terminal_event");
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "worker_report_terminal");
        assert_eq!(events[0].payload_json["report_type"], "blocked");
        let outbox = store.outbox();
        assert_eq!(outbox.len(), 1);
        assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
    }

    #[tokio::test]
    async fn worker_launch_stream_poll_persists_finished_marker_stop_without_new_entries() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(root_goal_task());
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task_metadata.insert("worker_stream_last_entry_id".to_string(), json!("2-0"));
        task_metadata.insert("worker_stream_message_id".to_string(), json!("msg-1"));
        task_metadata.insert(
            "worker_stream_last_event_type".to_string(),
            json!("text_delta"),
        );
        task_metadata.insert("worker_stream_last_event_time_us".to_string(), json!(0));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
        store.insert_attempt(task_session_attempt(
            "attempt-test",
            "running",
            Some(conversation_id),
        ));
        let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
        runtime_state.insert_finished(conversation_id);
        let stream_events = Arc::new(FakeWorkerLaunchEventStream::default());
        let handler = worker_launch_handler_with_state_and_event_stream(
            Arc::clone(&store),
            runtime_state,
            stream_events,
            4,
        );
        let mut item = worker_launch_item();
        let payload = item.payload_json.as_object_mut().unwrap();
        payload.insert("worker_stream_poll".to_string(), json!(true));
        payload.insert("stream_after_id".to_string(), json!("2-0"));

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "no_terminal_event");
        assert_eq!(
            task.metadata_json["worker_stream_replay_status"],
            "terminal"
        );
        assert_eq!(task.metadata_json["last_worker_report_type"], "blocked");
        assert!(task.metadata_json[LAST_WORKER_REPORT_SUMMARY]
            .as_str()
            .unwrap()
            .contains("agent_finished_without_terminal_event"));
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
        assert_eq!(attempt.conversation_id.as_deref(), Some(conversation_id));
        let node = store.node("node-test");
        assert_eq!(node.execution, "reported");
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].payload_json["report_type"], "blocked");
        let outbox = store.outbox();
        assert_eq!(outbox.len(), 1);
        assert_eq!(outbox[0].event_type, SUPERVISOR_TICK_EVENT);
    }

    #[tokio::test]
    async fn worker_launch_handler_refreshes_runtime_markers_after_binding() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
        let conversation_id = "d267a78e-eefc-5d33-bfb3-ac4fa7ece855";
        runtime_state.insert_running(conversation_id);
        let handler =
            worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert_eq!(runtime_state.claims(), vec![conversation_id]);
        assert_eq!(runtime_state.refresh_cooldowns(), vec![conversation_id]);
        assert_eq!(runtime_state.refresh_running(), vec![conversation_id]);
        let task = store.task("task-test");
        assert_eq!(
            task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
            conversation_id
        );
    }

    #[tokio::test]
    async fn worker_launch_handler_reuses_repair_conversation_id_when_present() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let handler = worker_launch_handler(Arc::clone(&store), 4);
        let mut item = worker_launch_item();
        if let Some(payload) = item.payload_json.as_object_mut() {
            payload.insert(
                "reuse_conversation_id".to_string(),
                json!("conv-existing-repair"),
            );
        }

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "bound");
        assert_eq!(
            task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
            "conv-existing-repair"
        );
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(
            attempt.conversation_id.as_deref(),
            Some("conv-existing-repair")
        );
        let conversation = store.conversation("conv-existing-repair");
        assert_eq!(conversation.metadata_json["attempt_id"], "attempt-test");
        assert_eq!(
            conversation.metadata_json["conversation_scope"],
            "task:task-test:attempt:attempt-test"
        );
    }

    #[tokio::test]
    async fn worker_launch_handler_skips_duplicate_launch_when_cooldown_exists() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
        runtime_state.insert_cooldown("d267a78e-eefc-5d33-bfb3-ac4fa7ece855");
        let handler =
            worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert_eq!(
            runtime_state.claims(),
            vec!["d267a78e-eefc-5d33-bfb3-ac4fa7ece855"]
        );
        assert!(runtime_state.has_cooldown("d267a78e-eefc-5d33-bfb3-ac4fa7ece855"));
        assert_eq!(store.conversation_count(), 0);
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert!(attempt.conversation_id.is_none());
        let task = store.task("task-test");
        assert_eq!(task.status, "todo");
        assert!(task.metadata_json.get("launch_state").is_none());
        let node = store.node("node-test");
        assert_eq!(node.execution, "dispatched");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
    }

    #[tokio::test]
    async fn worker_launch_handler_clears_reused_markers_before_repair_reuse() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
        runtime_state.insert_cooldown("conv-existing-repair");
        runtime_state.insert_finished("conv-existing-repair");
        let handler =
            worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);
        let mut item = worker_launch_item();
        if let Some(payload) = item.payload_json.as_object_mut() {
            payload.insert(
                "reuse_conversation_id".to_string(),
                json!("conv-existing-repair"),
            );
        }

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert_eq!(runtime_state.clears(), vec!["conv-existing-repair"]);
        assert_eq!(runtime_state.claims(), vec!["conv-existing-repair"]);
        assert!(runtime_state.has_cooldown("conv-existing-repair"));
        assert!(!runtime_state.has_finished("conv-existing-repair"));
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(
            attempt.conversation_id.as_deref(),
            Some("conv-existing-repair")
        );
        assert_eq!(store.conversation_count(), 1);
        let task = store.task("task-test");
        assert_eq!(
            task.metadata_json[CURRENT_ATTEMPT_CONVERSATION_ID],
            "conv-existing-repair"
        );
    }

    #[tokio::test]
    async fn worker_launch_handler_skips_reuse_when_agent_running_marker_exists() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let runtime_state = Arc::new(FakeWorkerLaunchRuntimeStateStore::default());
        runtime_state.insert_running("conv-existing-repair");
        let handler =
            worker_launch_handler_with_state(Arc::clone(&store), Arc::clone(&runtime_state), 4);
        let mut item = worker_launch_item();
        if let Some(payload) = item.payload_json.as_object_mut() {
            payload.insert(
                "reuse_conversation_id".to_string(),
                json!("conv-existing-repair"),
            );
        }

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert!(runtime_state.clears().is_empty());
        assert!(runtime_state.claims().is_empty());
        assert_eq!(store.conversation_count(), 0);
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert!(attempt.conversation_id.is_none());
        let task = store.task("task-test");
        assert_eq!(task.status, "todo");
        assert!(task.metadata_json.get("launch_state").is_none());
    }

    #[tokio::test]
    async fn worker_launch_handler_records_skipped_worktree_context_without_sandbox_root() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let handler = worker_launch_handler(Arc::clone(&store), 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.metadata_json["launch_state"], "bound");
        assert_eq!(task.metadata_json["worktree_setup"]["status"], "skipped");
        assert_eq!(
            task.metadata_json["worktree_setup"]["reason"],
            "sandbox_code_root is not available for this workspace"
        );
        assert_eq!(
            task.metadata_json["attempt_worktree"]["attempt_id"],
            "attempt-test"
        );
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, "running");
        assert_eq!(
            attempt.conversation_id.as_deref(),
            Some("d267a78e-eefc-5d33-bfb3-ac4fa7ece855")
        );
    }

    #[tokio::test]
    async fn worker_launch_handler_blocks_attempt_for_rejected_worktree_path() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_code_root("/workspace/project"));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": "${sandbox_code_root}/src",
            "branch_name": "workspace/node-test-attempt",
            "base_ref": "HEAD"
        }));
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let handler = worker_launch_handler(Arc::clone(&store), 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.status, "blocked");
        assert_eq!(task.metadata_json["launch_state"], "worktree_setup_failed");
        assert_eq!(task.metadata_json["worktree_setup"]["status"], "failed");
        assert!(task
            .blocker_reason
            .as_deref()
            .unwrap()
            .contains("worktree_path must not be inside sandbox_code_root"));
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, "blocked");
        assert_eq!(
            attempt.adjudication_reason.as_deref(),
            Some("worktree_setup_failed")
        );
        let node = store.node("node-test");
        assert_eq!(node.intent, "blocked");
        assert_eq!(node.execution, "idle");
        assert!(node.current_attempt_id.is_none());
        assert_eq!(node.metadata_json["terminal_attempt_status"], "blocked");
        assert_eq!(node.metadata_json["worktree_setup"]["status"], "failed");
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn worker_launch_handler_prepares_local_git_attempt_worktree_when_available() {
        let Some(fixture) = git_publish_fixture() else {
            return;
        };
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_code_root(&fixture.repo.to_string_lossy()));
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-test"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let handler = worker_launch_handler(Arc::clone(&store), 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.status, "in_progress");
        assert_eq!(task.metadata_json["launch_state"], "bound");
        assert_eq!(task.metadata_json["worktree_setup"]["status"], "prepared");
        let worktree_path = task.metadata_json["worktree_setup"]["worktree_path"]
            .as_str()
            .unwrap();
        assert!(Path::new(worktree_path).exists());
        assert_eq!(task.metadata_json["active_execution_root"], worktree_path);
        let inside = run_git_ok(
            Path::new(worktree_path),
            &["rev-parse", "--is-inside-work-tree"],
        );
        assert_eq!(inside.trim(), "true");
        let node = store.node("node-test");
        assert_eq!(node.execution, "running");
        assert_eq!(node.metadata_json["launch_state"], "bound");
    }

    #[tokio::test]
    async fn worker_launch_handler_defers_when_active_capacity_reached() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        store.set_active_worker_conversations(1);
        let handler = worker_launch_handler(Arc::clone(&store), 1);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, WORKER_LAUNCH_EVENT);
        assert_eq!(queued[0].status, "pending");
        assert!(queued[0].next_attempt_at.is_some());
        assert_eq!(
            queued[0].metadata_json["source"],
            "workspace_plan.worker_launch.deferred_capacity"
        );
        assert_eq!(
            queued[0].metadata_json["deferred_from_outbox_id"],
            "job-worker-launch"
        );
        assert_eq!(queued[0].metadata_json["active_worker_conversations"], 1);
        assert_eq!(
            queued[0].metadata_json["max_active_worker_conversations"],
            1
        );
        let task = store.task("task-test");
        assert_ne!(task.metadata_json["launch_state"], "runtime_admitted");
    }

    #[tokio::test]
    async fn worker_launch_handler_skips_stale_attempt_without_projection() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        let mut task = task_with_plan_metadata();
        let mut task_metadata = object_or_empty(task.metadata_json.clone());
        task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!("attempt-new"));
        task.metadata_json = Value::Object(task_metadata);
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "dispatched".to_string();
        node.current_attempt_id = Some("attempt-new".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt("attempt-test", "running", None));
        let handler = worker_launch_handler(Arc::clone(&store), 4);

        let outcome = handler.handle(worker_launch_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert!(store.outbox().is_empty());
        let task = store.task("task-test");
        assert_eq!(task.status, "todo");
        assert_ne!(task.metadata_json["launch_state"], "runtime_admitted");
        let node = store.node("node-test");
        assert_eq!(node.execution, "dispatched");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-new"));
    }

    #[tokio::test]
    async fn pipeline_run_handler_marks_node_requested_without_running_provider() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.metadata_json["pipeline_status"], "requested");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "requested");
        assert_eq!(
            node.metadata_json["pipeline_request_outbox_id"],
            "job-pipeline-run"
        );
        assert_eq!(
            node.metadata_json["pipeline_request_reason"],
            "operator requested harness-native pipeline"
        );
        assert_eq!(
            node.metadata_json["pipeline_runtime_state"],
            "runtime_admitted"
        );
        assert_eq!(
            node.metadata_json["pipeline_requested_attempt_id"],
            "attempt-test"
        );
        assert!(node.metadata_json["pipeline_requested_at"].is_string());
    }

    #[tokio::test]
    async fn pipeline_run_handler_creates_durable_running_run_for_planning_contract() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_pipeline_contract());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
        store.insert_node(node);
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.metadata_json["pipeline_status"], "running");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
        assert!(node.metadata_json["pipeline_run_id"].is_string());
        assert!(node.metadata_json["pipeline_started_at"].is_string());
        assert!(node.metadata_json.get("pipeline_requested_at").is_none());

        let runs = store.pipeline_runs();
        assert_eq!(runs.len(), 1);
        let run = &runs[0];
        assert_eq!(run.workspace_id, "workspace-test");
        assert_eq!(run.plan_id.as_deref(), Some("plan-test"));
        assert_eq!(run.node_id.as_deref(), Some("node-test"));
        assert_eq!(run.attempt_id.as_deref(), Some("attempt-test"));
        assert_eq!(run.commit_ref.as_deref(), Some("abcdef1234567890"));
        assert_eq!(run.provider, SANDBOX_NATIVE_PROVIDER);
        assert_eq!(run.status, "running");
        assert_eq!(
            run.metadata_json["reason"],
            "operator requested harness-native pipeline"
        );
        assert_eq!(
            node.metadata_json["pipeline_run_id"].as_str(),
            Some(run.id.as_str())
        );

        let contract = store.pipeline_contract("workspace-test", "plan-test");
        assert_eq!(contract.id, run.contract_id);
        assert_eq!(contract.provider, SANDBOX_NATIVE_PROVIDER);
        assert_eq!(contract.code_root.as_deref(), Some("/workspace/project"));
        assert_eq!(contract.timeout_seconds, 120);
        assert!(!contract.auto_deploy);
        assert_eq!(contract.env_json["CI"], "true");
        assert_eq!(
            contract.trigger_policy_json,
            json!({
                "trigger": "verification_gate",
                "node_id": "node-test",
                "attempt_id": "attempt-test"
            })
        );
        assert_eq!(contract.commands_json[0]["stage"], "test");
        assert_eq!(
            contract.commands_json[0]["command"],
            "cargo test --workspace"
        );
        assert_eq!(
            contract.metadata_json["source"],
            "workspace_plan.pipeline_run_requested"
        );
        assert_eq!(
            contract.metadata_json["contract_source"],
            PLANNING_CONTRACT_SOURCE
        );
    }

    #[tokio::test]
    async fn pipeline_run_handler_executes_no_service_stage_and_finishes_success() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_pipeline_contract());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
        store.insert_node(node);
        let runner = Arc::new(StaticPipelineStageRunner::default());
        let stage_runner: Arc<dyn WorkspacePipelineStageRunner> = runner.clone();
        let handler = pipeline_run_handler_with_stage_runner(Arc::clone(&store), stage_runner);

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert_eq!(
            runner.seen(),
            vec![(
                "project-test".to_string(),
                "test".to_string(),
                "cargo test --workspace".to_string()
            )]
        );
        let runs = store.pipeline_runs();
        assert_eq!(runs.len(), 1);
        let run = &runs[0];
        assert_eq!(run.status, "success");
        assert_eq!(run.reason, None);
        assert!(run.completed_at.is_some());
        assert_eq!(run.metadata_json["stage_count"], 1);
        assert_eq!(run.metadata_json["service_count"], 0);

        let stages = store.pipeline_stage_runs();
        assert_eq!(stages.len(), 1);
        let stage = &stages[0];
        assert_eq!(stage.run_id, run.id);
        assert_eq!(stage.stage, "test");
        assert_eq!(stage.status, "success");
        assert_eq!(stage.exit_code, Some(0));
        assert_eq!(stage.stdout_preview.as_deref(), Some("ok"));
        assert_eq!(stage.metadata_json["required"], true);
        assert_eq!(stage.metadata_json["duration_ms_observed"], 25);

        let node = store.node("node-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.metadata_json["pipeline_status"], "success");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "success");
        assert_eq!(node.metadata_json["last_verification_passed"], true);
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:passed".to_string(),
                "pipeline_stage:test:passed".to_string(),
                format!("pipeline_run:success:{}", run.id)
            ]
        );
        assert_eq!(
            metadata_string_values(node.metadata_json.get("execution_verifications")),
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs"))
        );

        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, SUPERVISOR_TICK_EVENT);
        assert_eq!(queued[0].payload_json["pipeline_run_id"], run.id);
        assert_eq!(queued[0].payload_json["pipeline_status"], "success");
        assert_eq!(
            queued[0].metadata_json["source"],
            "workspace_plan.pipeline_run_completed"
        );
    }

    #[tokio::test]
    async fn pipeline_run_handler_executes_no_service_stage_and_finishes_failure() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_pipeline_contract());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        let runner = Arc::new(StaticPipelineStageRunner::default().with_result(
            PipelineStageResult {
                stage: "test".to_string(),
                status: "failed".to_string(),
                command: "cargo test --workspace".to_string(),
                exit_code: Some(2),
                stdout_preview: "tests failed".to_string(),
                stderr_preview: "failure details".to_string(),
                duration_ms: 31,
                log_ref: Some("sandbox://pipeline/test/test.log".to_string()),
                artifact_refs: vec![
                    "pipeline_log:test:sandbox://pipeline/test/test.log".to_string(),
                ],
                service_id: None,
                required: true,
            },
        ));
        let stage_runner: Arc<dyn WorkspacePipelineStageRunner> = runner;
        let handler = pipeline_run_handler_with_stage_runner(Arc::clone(&store), stage_runner);

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.status, "failed");
        assert_eq!(run.reason.as_deref(), Some("stage test failed with exit 2"));
        let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
        assert_eq!(stage.status, "failed");
        assert_eq!(stage.exit_code, Some(2));
        assert_eq!(stage.stderr_preview.as_deref(), Some("failure details"));

        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "failed");
        assert!(node.metadata_json.get("last_verification_passed").is_none());
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:failed".to_string(),
                "pipeline_stage:test:failed".to_string(),
                format!("pipeline_run:failed:{}", run.id)
            ]
        );
        assert_eq!(store.outbox().len(), 1);
    }

    #[tokio::test]
    async fn pipeline_run_handler_fails_drone_source_publish_without_host_code_root() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_pipeline_contract_missing_host_root());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
        store.insert_node(node);
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let runs = store.pipeline_runs();
        assert_eq!(runs.len(), 1);
        let run = &runs[0];
        assert_eq!(run.provider, DRONE_PROVIDER);
        assert_eq!(run.status, "failed");
        assert_eq!(
            run.reason.as_deref(),
            Some("host_code_root is not available for Drone source publish")
        );
        assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
        assert_eq!(run.metadata_json["pipeline_failed_stage"], "source_publish");
        assert_eq!(run.metadata_json["source_publish_status"], "failed");
        assert_eq!(run.metadata_json["source_publish_provider"], "git");
        assert_eq!(
            run.metadata_json["source_publish_commit_ref"],
            "abcdef1234567890"
        );
        assert_eq!(
            run.metadata_json["source_publish_source_commit_ref"],
            "abcdef1234567890"
        );
        assert_eq!(
            run.metadata_json["source_publish_reason"],
            "host_code_root is not available for Drone source publish"
        );

        let stages = store.pipeline_stage_runs();
        assert_eq!(stages.len(), 1);
        let stage = &stages[0];
        assert_eq!(stage.run_id, run.id);
        assert_eq!(stage.stage, "source_publish");
        assert_eq!(stage.status, "failed");
        assert_eq!(stage.command.as_deref(), Some("git:publish"));
        assert_eq!(stage.exit_code, Some(1));
        assert_eq!(
            stage.stderr_preview.as_deref(),
            Some("host_code_root is not available for Drone source publish")
        );
        assert_eq!(stage.metadata_json["external_provider"], DRONE_PROVIDER);
        assert_eq!(stage.metadata_json["source_publish_status"], "failed");

        let contract = store.pipeline_contract("workspace-test", "plan-test");
        assert_eq!(contract.provider, DRONE_PROVIDER);
        assert_eq!(contract.metadata_json["source_publish_status"], "failed");
        assert_eq!(
            contract.metadata_json["provider_config"],
            json!({"branch": "main", "repo": "owner/repo"})
        );

        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "failed");
        assert_eq!(
            node.metadata_json["pipeline_failed_stage"],
            "source_publish"
        );
        assert_eq!(node.metadata_json["source_publish_status"], "failed");
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:failed".to_string(),
                "source_publish:failed".to_string(),
                format!("pipeline_run:failed:{}", run.id)
            ]
        );

        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, SUPERVISOR_TICK_EVENT);
        assert_eq!(
            queued[0].metadata_json["source"],
            "workspace_plan.drone_pipeline_run_completed"
        );
        assert_eq!(queued[0].payload_json["pipeline_status"], "failed");
    }

    #[tokio::test]
    async fn pipeline_run_handler_fails_drone_source_publish_without_branch() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_pipeline_contract_missing_branch());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
        store.insert_node(node);
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.provider, DRONE_PROVIDER);
        assert_eq!(run.status, "failed");
        assert_eq!(
            run.reason.as_deref(),
            Some("source_control.default_branch or delivery_cicd.drone.branch is required")
        );
        assert_eq!(run.metadata_json["pipeline_failed_stage"], "source_publish");
        assert_eq!(run.metadata_json["source_publish_status"], "failed");
        assert!(run.metadata_json.get("source_publish_branch").is_none());

        let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
        assert_eq!(stage.stage, "source_publish");
        assert_eq!(stage.status, "failed");
        assert_eq!(stage.exit_code, Some(1));
        assert_eq!(
            stage.stderr_preview.as_deref(),
            Some("source_control.default_branch or delivery_cicd.drone.branch is required")
        );

        let contract = store.pipeline_contract("workspace-test", "plan-test");
        assert_eq!(contract.provider, DRONE_PROVIDER);
        assert_eq!(
            contract.metadata_json["provider_config"],
            json!({"repo": "owner/repo"})
        );
        assert_eq!(contract.metadata_json["source_publish_status"], "failed");

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(node.metadata_json["source_publish_provider"], "git");
        assert_eq!(
            node.metadata_json["pipeline_failure_summary"],
            "source_control.default_branch or delivery_cicd.drone.branch is required"
        );
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:failed".to_string(),
                "source_publish:failed".to_string(),
                format!("pipeline_run:failed:{}", run.id)
            ]
        );
        assert_eq!(
            store.outbox()[0].metadata_json["source"],
            "workspace_plan.drone_pipeline_run_completed"
        );
    }

    #[tokio::test]
    async fn pipeline_run_handler_triggers_and_polls_drone_success() {
        let (server_url, captured) = drone_api_mock(vec![
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":41,"status":"running"}"#),
            (
                200,
                r#"{"number":41,"status":"success","link":"http://drone.local/owner/repo/41","stages":[{"name":"ci","number":1,"steps":[{"name":"test","number":1,"status":"success","exit_code":0}]}]}"#,
            ),
            (200, r#"[{"out":"cargo test ok\n"}]"#),
        ])
        .await;
        std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_SUCCESS", "token-success");
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_api_pipeline_contract(
            &server_url,
            "AGISTACK_TEST_DRONE_TOKEN_SUCCESS",
        ));
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler
            .handle(pipeline_run_item_without_attempt())
            .await
            .unwrap();
        std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_SUCCESS");

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.provider, DRONE_PROVIDER);
        assert_eq!(run.status, "success");
        assert_eq!(run.reason, None);
        assert_eq!(run.commit_ref, None);
        assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
        assert_eq!(run.metadata_json["external_id"], "owner/repo#41");
        assert_eq!(
            run.metadata_json["external_url"],
            format!("{server_url}/owner/repo/41")
        );
        assert_eq!(run.metadata_json["drone_build_number"], 41);
        assert_eq!(run.metadata_json["drone_status"], "success");
        assert_eq!(run.metadata_json["source_publish_status"], "skipped");

        let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
        assert_eq!(stage.stage, "ci/test");
        assert_eq!(stage.status, "success");
        assert_eq!(stage.command.as_deref(), Some("drone:ci/test"));
        assert_eq!(stage.exit_code, Some(0));
        assert_eq!(stage.stdout_preview.as_deref(), Some("cargo test ok"));
        assert_eq!(stage.metadata_json["drone_stage"], "ci");
        assert_eq!(stage.metadata_json["drone_step"], "test");

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "success");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "success");
        assert_eq!(node.metadata_json["external_id"], "owner/repo#41");
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:passed".to_string(),
                "drone_build:success:owner/repo#41".to_string(),
                "pipeline_external:drone:owner/repo#41".to_string(),
                "pipeline_stage:ci/test:success".to_string(),
                format!("pipeline_run:success:{}", run.id),
                "pipeline_run_external:drone:owner/repo#41".to_string(),
            ]
        );
        assert_eq!(store.outbox().len(), 1);
        assert_eq!(
            store.outbox()[0].metadata_json["source"],
            "workspace_plan.drone_pipeline_run_completed"
        );

        let requests = captured.lock().await;
        assert_eq!(requests.len(), 5);
        assert!(requests[0].contains("GET /api/repos/owner/repo"));
        assert!(requests[0].contains("authorization: Bearer token-success"));
        assert!(requests[2].contains(
            "POST /api/repos/owner/repo/builds?target=workspace-ci&branch=main&commit=abc123"
        ));
        assert!(requests[4].contains("GET /api/repos/owner/repo/builds/41/logs/1/1"));
    }

    #[tokio::test]
    async fn pipeline_run_handler_triggers_and_polls_drone_via_cli() {
        let fixture = drone_cli_fixture();
        std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_CLI", "token-cli");
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_cli_pipeline_contract(
            "http://drone-cli.local",
            "AGISTACK_TEST_DRONE_TOKEN_CLI",
            &fixture.command,
        ));
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler
            .handle(pipeline_run_item_without_attempt())
            .await
            .unwrap();
        std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_CLI");

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.provider, DRONE_PROVIDER);
        assert_eq!(run.status, "success");
        assert_eq!(run.reason, None);
        assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
        assert_eq!(run.metadata_json["external_id"], "owner/repo#51");
        assert_eq!(
            run.metadata_json["external_url"],
            "http://drone-cli.local/owner/repo/51"
        );
        assert_eq!(run.metadata_json["drone_client"], "cli");
        assert_eq!(run.metadata_json["drone_build_number"], 51);
        assert_eq!(run.metadata_json["drone_status"], "success");

        let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
        assert_eq!(stage.stage, "ci/test");
        assert_eq!(stage.status, "success");
        assert_eq!(stage.command.as_deref(), Some("drone:ci/test"));
        assert_eq!(stage.exit_code, Some(0));
        assert_eq!(stage.stdout_preview.as_deref(), Some("cargo test ok"));

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "success");
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:passed".to_string(),
                "drone_build:success:owner/repo#51".to_string(),
                "pipeline_external:drone:owner/repo#51".to_string(),
                "pipeline_stage:ci/test:success".to_string(),
                format!("pipeline_run:success:{}", run.id),
                "pipeline_run_external:drone:owner/repo#51".to_string(),
            ]
        );

        let captured = std::fs::read_to_string(&fixture.capture).unwrap();
        assert!(captured.contains("server=http://drone-cli.local token=token-cli args=repo info owner/repo --format {{ json . }}"));
        assert!(captured.contains("args=build ls owner/repo --limit=25 --format {{ json . }}"));
        assert!(captured.contains("args=build create owner/repo --branch=main --commit=abc123 --param=target=workspace-ci --format {{ json . }}"));
        assert!(captured.contains("args=build info owner/repo 51 --format {{ json . }}"));
        assert!(captured.contains("args=log view owner/repo 51 1 1"));
    }

    #[tokio::test]
    async fn pipeline_run_handler_falls_back_to_drone_http_when_cli_is_missing() {
        let (server_url, captured) = drone_api_mock(vec![
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":52,"status":"running"}"#),
            (
                200,
                r#"{"number":52,"status":"success","link":"http://drone.local/owner/repo/52","stages":[{"name":"ci","number":1,"steps":[{"name":"test","number":1,"status":"success","exit_code":0}]}]}"#,
            ),
            (200, r#"[{"out":"cargo test via fallback\n"}]"#),
        ])
        .await;
        let missing_command =
            std::env::temp_dir().join(format!("agistack-missing-drone-{}", generate_uuid_v4()));
        std::env::set_var(
            "AGISTACK_TEST_DRONE_TOKEN_CLI_FALLBACK",
            "token-cli-fallback",
        );
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_cli_pipeline_contract(
            &server_url,
            "AGISTACK_TEST_DRONE_TOKEN_CLI_FALLBACK",
            &missing_command,
        ));
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler
            .handle(pipeline_run_item_without_attempt())
            .await
            .unwrap();
        std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_CLI_FALLBACK");

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.status, "success");
        assert_eq!(run.metadata_json["external_id"], "owner/repo#52");
        assert_eq!(run.metadata_json["drone_client"], "http_fallback");
        let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
        assert_eq!(
            stage.stdout_preview.as_deref(),
            Some("cargo test via fallback")
        );

        let requests = captured.lock().await;
        assert_eq!(requests.len(), 5);
        assert!(requests[0].contains("GET /api/repos/owner/repo"));
        assert!(requests[0].contains("authorization: Bearer token-cli-fallback"));
        assert!(requests[2].contains(
            "POST /api/repos/owner/repo/builds?target=workspace-ci&branch=main&commit=abc123"
        ));
    }

    #[tokio::test]
    async fn pipeline_run_handler_persists_drone_failed_build() {
        let (server_url, _captured) = drone_api_mock(vec![
            (200, r#"{"active":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":42,"status":"running"}"#),
            (
                200,
                r#"{"number":42,"status":"failure","stages":[{"name":"ci","number":1,"steps":[{"name":"test","number":1,"status":"failure","exit_code":137,"error":"exit 137"}]}]}"#,
            ),
            (200, r#"[{"out":"module not found\nexit 137\n"}]"#),
        ])
        .await;
        std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_FAILURE", "token-failure");
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_api_pipeline_contract(
            &server_url,
            "AGISTACK_TEST_DRONE_TOKEN_FAILURE",
        ));
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler
            .handle(pipeline_run_item_without_attempt())
            .await
            .unwrap();
        std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_FAILURE");

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.status, "failed");
        assert_eq!(
            run.reason.as_deref(),
            Some("Drone build owner/repo#42 finished with status failure")
        );
        assert_eq!(run.metadata_json["drone_status"], "failure");
        assert_eq!(run.metadata_json["pipeline_failed_stage"], "ci/test");
        assert_eq!(
            run.metadata_json["pipeline_failure_summary"],
            "Drone build owner/repo#42 finished with status failure"
        );

        let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
        assert_eq!(stage.stage, "ci/test");
        assert_eq!(stage.status, "failed");
        assert_eq!(stage.exit_code, Some(137));
        assert!(stage
            .stderr_preview
            .as_deref()
            .is_some_and(|preview| preview.contains("module not found")));

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(node.metadata_json["pipeline_failed_stage"], "ci/test");
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:failed".to_string(),
                "drone_build:failure:owner/repo#42".to_string(),
                "pipeline_external:drone:owner/repo#42".to_string(),
                "pipeline_stage:ci/test:failed".to_string(),
                format!("pipeline_run:failed:{}", run.id),
                "pipeline_run_external:drone:owner/repo#42".to_string(),
            ]
        );
    }

    #[tokio::test]
    async fn pipeline_run_handler_fails_drone_yaml_preflight_for_non_string_command() {
        let fixture = drone_yaml_fixture(
            r#"
kind: pipeline
type: docker
name: default
steps:
  - name: ci
    image: alpine
    commands:
      - echo ok
      - label: value
"#,
        );
        let (server_url, captured) = drone_api_mock(vec![]).await;
        std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT", "token-preflight");
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_api_pipeline_contract_with_host_root(
            &server_url,
            "AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT",
            Some(&fixture.root),
        ));
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler
            .handle(pipeline_run_item_without_attempt())
            .await
            .unwrap();
        std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT");

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert!(captured.lock().await.is_empty());
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.status, "failed");
        assert!(run
            .reason
            .as_deref()
            .is_some_and(|reason| reason.contains("commands[1] must be a string")));
        assert_eq!(
            run.metadata_json["drone_preflight"],
            DRONE_YAML_PREFLIGHT_VALIDATION
        );
        assert_eq!(run.metadata_json["drone_preflight_status"], "failed");
        assert_eq!(
            run.metadata_json["pipeline_failed_stage"],
            "drone_preflight"
        );

        let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
        assert_eq!(stage.stage, "drone_preflight");
        assert_eq!(stage.status, "failed");
        assert_eq!(stage.command.as_deref(), Some("drone:preflight .drone.yml"));
        assert!(stage
            .stderr_preview
            .as_deref()
            .is_some_and(|preview| preview.contains("commands[1] must be a string")));

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(
            node.metadata_json["pipeline_failed_stage"],
            "drone_preflight"
        );
        let evidence = metadata_string_values(node.metadata_json.get("pipeline_evidence_refs"));
        assert!(evidence.contains(&"ci_pipeline:failed".to_string()));
        assert!(evidence.contains(&"drone:preflight_failed".to_string()));
        assert!(evidence.contains(&"drone_config:.drone.yml".to_string()));
        assert!(evidence.contains(&"drone_error:yaml_unmarshal_into_string".to_string()));
    }

    #[tokio::test]
    async fn pipeline_run_handler_fails_drone_yaml_preflight_for_missing_deploy_service() {
        let fixture = drone_yaml_fixture(
            r#"
kind: pipeline
type: docker
name: default
steps:
  - name: docker-build-web
    image: plugins/docker
    commands:
      - docker build -t registry.local/app-web:abc .
  - name: deploy
    image: docker:cli
    commands:
      - docker run -d --name other-service registry.local/other-service:abc
"#,
        );
        let (server_url, captured) = drone_api_mock(vec![]).await;
        std::env::set_var(
            "AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT_DEPLOY",
            "token-preflight-deploy",
        );
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(
            workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(
                &server_url,
                "AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT_DEPLOY",
                Some(&fixture.root),
            ),
        );
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler
            .handle(pipeline_run_item_without_attempt())
            .await
            .unwrap();
        std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT_DEPLOY");

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        assert!(captured.lock().await.is_empty());
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.status, "failed");
        assert_eq!(run.metadata_json["deployment_status"], "invalid");
        assert_eq!(
            run.metadata_json["deploy_preflight_validation"],
            DRONE_YAML_PREFLIGHT_VALIDATION
        );
        assert!(run.metadata_json["deploy_validation_failure"]
            .as_str()
            .is_some_and(|failure| failure.contains("required services: app-web")));
        assert!(run
            .reason
            .as_deref()
            .is_some_and(|reason| reason.contains("required services: app-web")));

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(node.metadata_json["deployment_status"], "invalid");
        let evidence = metadata_string_values(node.metadata_json.get("pipeline_evidence_refs"));
        assert!(evidence.contains(&"ci_pipeline:failed".to_string()));
        assert!(evidence.contains(&"drone:preflight_failed".to_string()));
        assert!(
            evidence.contains(&"drone_error:docker_deploy_missing_required_service".to_string())
        );
        assert!(evidence.contains(&"deployment:invalid:docker".to_string()));
    }

    #[tokio::test]
    async fn pipeline_run_handler_trusts_repo_and_marks_docker_deploy_success() {
        let (server_url, captured) = drone_api_mock(vec![
            (200, r#"{"active":true,"trusted":false}"#),
            (200, r#"{"active":true,"trusted":false}"#),
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":43,"status":"running"}"#),
            (
                200,
                r#"{"number":43,"status":"success","stages":[{"name":"docker-build-web","number":1,"steps":[{"name":"build","number":1,"status":"success","exit_code":0}]},{"name":"deploy","number":2,"steps":[{"name":"deploy","number":1,"status":"success","exit_code":0}]}]}"#,
            ),
            (
                200,
                r#"[{"out":"docker build -t registry.local/app-web:abc .\n"}]"#,
            ),
            (
                200,
                r#"[{"out":"docker run -d --name app-web registry.local/app-web:abc\n"}]"#,
            ),
        ])
        .await;
        std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_DEPLOY_SUCCESS", "token-deploy");
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_docker_deploy_pipeline_contract(
            &server_url,
            "AGISTACK_TEST_DRONE_TOKEN_DEPLOY_SUCCESS",
        ));
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler
            .handle(pipeline_run_item_without_attempt())
            .await
            .unwrap();
        std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_DEPLOY_SUCCESS");

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.status, "success");
        assert_eq!(run.metadata_json["deploy_enabled"], true);
        assert_eq!(run.metadata_json["deploy_mode"], "docker");
        assert_eq!(run.metadata_json["deploy_stage"], "deploy");
        assert_eq!(run.metadata_json["deploy_target"], "production");
        assert_eq!(run.metadata_json["deployment_status"], "deployed");
        assert_eq!(
            run.metadata_json["deploy_validation"],
            DRONE_DOCKER_DEPLOY_VALIDATION
        );
        let stages = store.pipeline_stage_runs();
        let deploy_stage = stages
            .iter()
            .find(|stage| stage.stage == "deploy")
            .expect("deploy stage should be persisted");
        assert_eq!(deploy_stage.status, "success");
        assert_eq!(deploy_stage.metadata_json["drone_step_kind"], "deploy");
        assert_eq!(deploy_stage.metadata_json["deploy_mode"], "docker");

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "success");
        assert_eq!(node.metadata_json["deployment_status"], "deployed");
        assert_eq!(
            node.metadata_json["deploy_validation"],
            DRONE_DOCKER_DEPLOY_VALIDATION
        );
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:passed".to_string(),
                "drone_build:success:owner/repo#43".to_string(),
                "pipeline_external:drone:owner/repo#43".to_string(),
                "pipeline_stage:docker-build-web/build:success".to_string(),
                "pipeline_stage:deploy:success".to_string(),
                "deployment:passed:docker".to_string(),
                "deployment_target:production".to_string(),
                format!("pipeline_run:success:{}", run.id),
                "pipeline_run_external:drone:owner/repo#43".to_string(),
            ]
        );

        let requests = captured.lock().await;
        assert_eq!(requests.len(), 8);
        assert!(requests[2].contains("PATCH /api/repos/owner/repo"));
        assert!(requests[2].contains(r#""trusted":true"#));
        assert!(requests[4].contains("POST /api/repos/owner/repo/builds?"));
        assert!(requests[4].contains("MEMSTACK_DEPLOY_ENABLED=true"));
        assert!(requests[4].contains("MEMSTACK_DEPLOY_MODE=docker"));
        assert!(requests[4].contains("MEMSTACK_DEPLOY_STAGE=deploy"));
        assert!(requests[4].contains("MEMSTACK_DEPLOY_TARGET=production"));
        assert!(requests[4].contains("MEMSTACK_DEPLOY_DOCKER_HOST_PORT=18080"));
        assert!(requests[4].contains("MEMSTACK_DEPLOY_DOCKER_LABELS=blue%2Cgreen"));
        assert!(requests[4].contains("target=production"));
    }

    #[tokio::test]
    async fn pipeline_run_handler_fails_required_docker_deploy_without_run_marker() {
        let (server_url, _captured) = drone_api_mock(vec![
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":44,"status":"running"}"#),
            (
                200,
                r#"{"number":44,"status":"success","stages":[{"name":"deploy","number":1,"steps":[{"name":"deploy","number":1,"status":"success","exit_code":0}]}]}"#,
            ),
            (200, r#"[{"out":"echo app-web deployed\n"}]"#),
        ])
        .await;
        std::env::set_var(
            "AGISTACK_TEST_DRONE_TOKEN_DEPLOY_INVALID",
            "token-deploy-invalid",
        );
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_docker_deploy_pipeline_contract(
            &server_url,
            "AGISTACK_TEST_DRONE_TOKEN_DEPLOY_INVALID",
        ));
        store.insert_plan(plan());
        store.insert_node(plan_node());
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler
            .handle(pipeline_run_item_without_attempt())
            .await
            .unwrap();
        std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_DEPLOY_INVALID");

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.status, "failed");
        assert_eq!(run.metadata_json["deployment_status"], "invalid");
        assert_eq!(
            run.metadata_json["deploy_validation_failure"],
            "missing docker run/compose/stack/service deploy command"
        );
        assert_eq!(
            run.reason.as_deref(),
            Some(
                "Drone build owner/repo#44 deploy stage deploy did not implement docker deployment semantics: missing docker run/compose/stack/service deploy command"
            )
        );

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(node.metadata_json["deployment_status"], "invalid");
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:failed".to_string(),
                "drone_build:success:owner/repo#44".to_string(),
                "pipeline_external:drone:owner/repo#44".to_string(),
                "pipeline_stage:deploy:success".to_string(),
                "deployment:invalid:docker".to_string(),
                "deployment_target:production".to_string(),
                format!("pipeline_run:failed:{}", run.id),
                "pipeline_run_external:drone:owner/repo#44".to_string(),
            ]
        );
    }

    #[tokio::test]
    async fn pipeline_run_handler_publishes_drone_source_ref_then_records_provider_unavailable() {
        let Some(fixture) = git_publish_fixture() else {
            return;
        };
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_pipeline_contract_git_publish(
            &fixture.repo,
            &fixture.remote,
        ));
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": fixture.commit_ref.clone()}));
        store.insert_node(node);
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let pushed = run_git_ok(
            &fixture.root,
            &[
                "--git-dir",
                fixture.remote.to_str().unwrap(),
                "rev-parse",
                "refs/heads/main",
            ],
        )
        .trim()
        .to_string();
        assert_eq!(pushed, fixture.commit_ref);

        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.provider, DRONE_PROVIDER);
        assert_eq!(run.status, "failed");
        assert_eq!(
            run.reason.as_deref(),
            Some("pipeline provider plugin is not enabled: drone")
        );
        assert_eq!(run.commit_ref.as_deref(), Some(fixture.commit_ref.as_str()));
        assert_eq!(run.metadata_json["source_publish_status"], "published");
        assert_eq!(run.metadata_json["source_publish_provider"], "git");
        assert_eq!(run.metadata_json["source_publish_branch"], "main");
        assert_eq!(
            run.metadata_json["source_publish_commit_ref"],
            fixture.commit_ref.as_str()
        );
        assert_eq!(
            run.metadata_json["source_publish_source_commit_ref"],
            fixture.commit_ref.as_str()
        );
        assert_eq!(
            run.metadata_json["source_publish_token_env"],
            "GITHUB_TOKEN"
        );
        assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
        assert_eq!(run.metadata_json["plugin_unavailable"], true);
        assert_eq!(run.metadata_json["pipeline_failed_stage"], "drone_plugin");
        assert_eq!(
            run.metadata_json["provider_error"],
            "pipeline provider plugin is not enabled: drone"
        );

        let stages = store.pipeline_stage_runs();
        assert_eq!(stages.len(), 1);
        let stage = &stages[0];
        assert_eq!(stage.stage, "drone_plugin");
        assert_eq!(stage.command.as_deref(), Some("plugin:resolve"));
        assert_eq!(stage.status, "failed");
        assert_eq!(stage.exit_code, Some(1));
        assert_eq!(stage.metadata_json["provider"], DRONE_PROVIDER);
        assert_eq!(stage.metadata_json["external_provider"], DRONE_PROVIDER);
        assert_eq!(stage.metadata_json["plugin_unavailable"], true);

        let contract = store.pipeline_contract("workspace-test", "plan-test");
        assert_eq!(contract.provider, DRONE_PROVIDER);
        assert_eq!(
            contract.metadata_json["provider_config"]["source_publish"]["status"],
            "published"
        );
        assert_eq!(
            contract.metadata_json["provider_config"]["source_publish"]["source_commit_ref"],
            fixture.commit_ref.as_str()
        );

        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(node.metadata_json["source_publish_status"], "published");
        assert_eq!(node.metadata_json["pipeline_failed_stage"], "drone_plugin");
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:failed".to_string(),
                "drone:plugin_unavailable".to_string(),
                format!("pipeline_run:failed:{}", run.id)
            ]
        );
        assert_eq!(
            store.outbox()[0].metadata_json["source"],
            "workspace_plan.drone_pipeline_run_completed"
        );
    }

    #[tokio::test]
    async fn pipeline_run_handler_merges_advanced_remote_branch_before_drone_source_publish() {
        let Some(fixture) = git_publish_fixture() else {
            return;
        };
        run_git_ok(
            &fixture.repo,
            &[
                "push",
                fixture.remote.to_str().unwrap(),
                "HEAD:refs/heads/main",
            ],
        );

        let remote_checkout = fixture.root.join("remote-checkout");
        run_git_ok(
            &fixture.root,
            &[
                "clone",
                fixture.remote.to_str().unwrap(),
                remote_checkout.to_str().unwrap(),
            ],
        );
        run_git_ok(&remote_checkout, &["checkout", "-B", "main", "origin/main"]);
        run_git_ok(
            &remote_checkout,
            &["config", "user.email", "remote@example.test"],
        );
        run_git_ok(&remote_checkout, &["config", "user.name", "Remote Test"]);
        std::fs::write(remote_checkout.join("remote.txt"), "remote-only\n").unwrap();
        run_git_ok(&remote_checkout, &["add", "remote.txt"]);
        run_git_ok(&remote_checkout, &["commit", "-m", "remote advance"]);
        let remote_commit = run_git_ok(&remote_checkout, &["rev-parse", "HEAD"])
            .trim()
            .to_string();
        run_git_ok(
            &remote_checkout,
            &["push", "origin", "HEAD:refs/heads/main"],
        );

        std::fs::write(fixture.repo.join("candidate.txt"), "candidate-only\n").unwrap();
        run_git_ok(&fixture.repo, &["add", "candidate.txt"]);
        run_git_ok(&fixture.repo, &["commit", "-m", "candidate change"]);
        let candidate_commit = run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
            .trim()
            .to_string();

        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_pipeline_contract_git_publish(
            &fixture.repo,
            &fixture.remote,
        ));
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": candidate_commit.clone()}));
        store.insert_node(node);
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let pushed = run_git_ok(
            &fixture.root,
            &[
                "--git-dir",
                fixture.remote.to_str().unwrap(),
                "rev-parse",
                "refs/heads/main",
            ],
        )
        .trim()
        .to_string();
        assert_ne!(pushed, candidate_commit);
        run_git_ok(
            &fixture.root,
            &[
                "--git-dir",
                fixture.remote.to_str().unwrap(),
                "merge-base",
                "--is-ancestor",
                &candidate_commit,
                "refs/heads/main",
            ],
        );
        run_git_ok(
            &fixture.root,
            &[
                "--git-dir",
                fixture.remote.to_str().unwrap(),
                "merge-base",
                "--is-ancestor",
                &remote_commit,
                "refs/heads/main",
            ],
        );
        assert_eq!(
            run_git_ok(
                &fixture.root,
                &[
                    "--git-dir",
                    fixture.remote.to_str().unwrap(),
                    "show",
                    "refs/heads/main:candidate.txt",
                ],
            ),
            "candidate-only\n"
        );
        assert_eq!(
            run_git_ok(
                &fixture.root,
                &[
                    "--git-dir",
                    fixture.remote.to_str().unwrap(),
                    "show",
                    "refs/heads/main:remote.txt",
                ],
            ),
            "remote-only\n"
        );

        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.provider, DRONE_PROVIDER);
        assert_eq!(run.status, "failed");
        assert_eq!(run.commit_ref.as_deref(), Some(candidate_commit.as_str()));
        assert_eq!(run.metadata_json["source_publish_status"], "published");
        assert_eq!(run.metadata_json["source_publish_commit_ref"], pushed);
        assert_eq!(
            run.metadata_json["source_publish_source_commit_ref"],
            candidate_commit
        );
        assert!(run.metadata_json["source_publish_reason"]
            .as_str()
            .is_some_and(|reason| reason.contains("merged remote branch before publish")));

        let contract = store.pipeline_contract("workspace-test", "plan-test");
        assert_eq!(
            contract.metadata_json["provider_config"]["source_publish"]["commit"],
            pushed
        );
        assert_eq!(
            contract.metadata_json["provider_config"]["source_publish"]["source_commit_ref"],
            candidate_commit
        );
        let node = store.node("node-test");
        assert_eq!(node.metadata_json["source_publish_status"], "published");
        assert_eq!(node.metadata_json["source_publish_commit_ref"], pushed);
        assert_eq!(
            node.metadata_json["source_publish_source_commit_ref"],
            candidate_commit
        );
    }

    #[tokio::test]
    async fn pipeline_run_handler_fails_drone_source_publish_when_git_push_fails() {
        let Some(fixture) = git_publish_fixture() else {
            return;
        };
        let missing_remote = fixture.root.join("missing.git");
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_drone_pipeline_contract_git_publish(
            &fixture.repo,
            &missing_remote,
        ));
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": fixture.commit_ref.clone()}));
        store.insert_node(node);
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let run = store.pipeline_runs().into_iter().next().unwrap();
        assert_eq!(run.provider, DRONE_PROVIDER);
        assert_eq!(run.status, "failed");
        assert!(run
            .reason
            .as_deref()
            .is_some_and(|reason| !reason.is_empty()));
        assert_eq!(run.metadata_json["pipeline_failed_stage"], "source_publish");
        assert_eq!(run.metadata_json["source_publish_status"], "failed");
        assert_eq!(run.metadata_json["source_publish_provider"], "git");
        assert_eq!(run.metadata_json["source_publish_branch"], "main");
        assert_eq!(
            run.metadata_json["source_publish_source_commit_ref"],
            fixture.commit_ref.as_str()
        );

        let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
        assert_eq!(stage.stage, "source_publish");
        assert_eq!(stage.command.as_deref(), Some("git:publish"));
        assert_eq!(stage.status, "failed");
        assert_eq!(stage.exit_code, Some(1));
        assert_eq!(stage.metadata_json["provider"], DRONE_PROVIDER);
        assert_eq!(stage.metadata_json["external_provider"], DRONE_PROVIDER);
        assert_eq!(stage.metadata_json["source_publish_status"], "failed");

        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "failed");
        assert_eq!(
            node.metadata_json["pipeline_failed_stage"],
            "source_publish"
        );
        assert_eq!(node.metadata_json["source_publish_status"], "failed");
        assert_eq!(
            metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
            vec![
                "ci_pipeline:failed".to_string(),
                "source_publish:failed".to_string(),
                format!("pipeline_run:failed:{}", run.id)
            ]
        );
    }

    #[tokio::test]
    async fn pipeline_stage_run_store_persists_finish_result() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        let started = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let completed = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 7).unwrap();
        let stage_run = WorkspacePlanDispatchStore::create_pipeline_stage_run(
            &*store,
            pipeline_stage_run_record("pipeline-stage-run-test", "pipeline-run-test"),
        )
        .await
        .unwrap();
        assert_eq!(stage_run.status, "running");
        assert_eq!(stage_run.started_at, Some(started));

        let artifact_refs = vec![
            "pipeline_log:test:sandbox://pipeline/run/test.log".to_string(),
            "artifact:test:coverage".to_string(),
        ];
        let finished = WorkspacePlanDispatchStore::finish_pipeline_stage_run(
            &*store,
            "pipeline-stage-run-test",
            "success",
            Some(0),
            Some("ok"),
            Some(""),
            Some("sandbox://pipeline/run/test.log"),
            &artifact_refs,
            &json!({"duration_ms_observed": 1800, "service_id": null}),
            completed,
        )
        .await
        .unwrap()
        .expect("stage run finished");

        assert_eq!(finished.status, "success");
        assert_eq!(finished.exit_code, Some(0));
        assert_eq!(finished.stdout_preview.as_deref(), Some("ok"));
        assert_eq!(finished.stderr_preview.as_deref(), Some(""));
        assert_eq!(
            finished.log_ref.as_deref(),
            Some("sandbox://pipeline/run/test.log")
        );
        assert_eq!(finished.artifact_refs_json, artifact_refs);
        assert_eq!(finished.completed_at, Some(completed));
        assert_eq!(finished.duration_ms, Some(2_000));
        assert_eq!(finished.updated_at, Some(completed));
        assert_eq!(finished.metadata_json["required"], true);
        assert_eq!(finished.metadata_json["duration_ms_observed"], 1800);
        assert!(finished.metadata_json["service_id"].is_null());

        let persisted = store.pipeline_stage_run("pipeline-stage-run-test");
        assert_eq!(persisted, finished);
    }

    #[tokio::test]
    async fn pipeline_run_handler_reflects_existing_success_run_to_node() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.metadata_json = json!({
            "iteration_phase": "test",
            "pipeline_evidence_refs": ["existing:evidence"]
        });
        store.insert_node(node);
        store.insert_pipeline_run(pipeline_run_record(
            "pipeline-run-success",
            "success",
            Some("attempt-test"),
            Some("abcdef1234567890"),
            json!({
                "source_publish_source_commit_ref": "abcdef1234567890",
                "source_publish_status": "published",
                "external_url": "https://ci.example/runs/pipeline-run-success",
                "external_provider": "sandbox_native",
                "pipeline_last_summary": "existing run already passed"
            }),
        ));
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(
            node.metadata_json["pipeline_run_id"],
            "pipeline-run-success"
        );
        assert_eq!(node.metadata_json["pipeline_status"], "success");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "success");
        assert_eq!(
            node.metadata_json["source_publish_source_commit_ref"],
            "abcdef1234567890"
        );
        assert_eq!(node.metadata_json["source_publish_status"], "published");
        assert_eq!(
            node.metadata_json["external_url"],
            "https://ci.example/runs/pipeline-run-success"
        );
        assert_eq!(
            node.metadata_json["pipeline_last_summary"],
            "existing run already passed"
        );
        assert_eq!(
            node.metadata_json["last_verification_summary"],
            "harness-native CI/CD pipeline passed"
        );
        assert_eq!(node.metadata_json["last_verification_passed"], true);
        assert_eq!(node.metadata_json["last_verification_hard_fail"], false);
        assert!(node.metadata_json["last_verification_ran_at"].is_string());
        assert_eq!(
            node.metadata_json["pipeline_evidence_refs"],
            json!([
                "existing:evidence",
                "ci_pipeline:passed",
                "pipeline_run:success:pipeline-run-success"
            ])
        );
        assert!(node.metadata_json.get("pipeline_requested_at").is_none());
    }

    #[tokio::test]
    async fn pipeline_run_handler_marks_existing_running_run_on_node() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
        store.insert_node(node);
        store.insert_pipeline_run(pipeline_run_record(
            "pipeline-run-running",
            "running",
            Some("attempt-test"),
            Some("abcdef1234567890"),
            json!({"source_publish_source_commit_ref": "abcdef1234567890"}),
        ));
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "idle");
        assert_eq!(
            node.metadata_json["pipeline_run_id"],
            "pipeline-run-running"
        );
        assert_eq!(node.metadata_json["pipeline_status"], "running");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
        assert!(node.metadata_json["pipeline_started_at"].is_string());
        assert!(node.metadata_json.get("pipeline_requested_at").is_none());
        assert!(node.metadata_json.get("last_verification_passed").is_none());
    }

    #[tokio::test]
    async fn pipeline_run_handler_ignores_running_run_with_commit_mismatch() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_pipeline_contract());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
        store.insert_node(node);
        store.insert_pipeline_run(pipeline_run_record(
            "pipeline-run-running-stale",
            "running",
            Some("attempt-test"),
            Some("bbbbbb1234567890"),
            json!({"source_publish_source_commit_ref": "bbbbbb1234567890"}),
        ));
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.metadata_json["pipeline_status"], "running");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
        let new_run_id = node.metadata_json["pipeline_run_id"].as_str().unwrap();
        assert_ne!(new_run_id, "pipeline-run-running-stale");
        assert!(node.metadata_json["pipeline_started_at"].is_string());
        let run = store.pipeline_run("pipeline-run-running-stale");
        assert_eq!(run.status, "failed");
        assert_eq!(
            run.reason.as_deref(),
            Some(
                "stale pipeline run source commit bbbbbb1234567890 superseded by abcdef1234567890"
            )
        );
        assert_eq!(run.metadata_json["stale_pipeline_run"], true);
        assert_eq!(
            run.metadata_json["stale_source_commit_ref"],
            "bbbbbb1234567890"
        );
        assert_eq!(
            run.metadata_json["superseded_by_source_commit_ref"],
            "abcdef1234567890"
        );
        assert!(run.completed_at.is_some());
        assert!(run.updated_at.is_some());
        let new_run = store.pipeline_run(new_run_id);
        assert_eq!(new_run.status, "running");
        assert_eq!(new_run.commit_ref.as_deref(), Some("abcdef1234567890"));
        assert_eq!(
            new_run.metadata_json["reason"],
            "operator requested harness-native pipeline"
        );
    }

    #[tokio::test]
    async fn pipeline_run_handler_marks_running_run_without_source_ref_stale() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_pipeline_contract());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
        store.insert_node(node);
        store.insert_pipeline_run(pipeline_run_record(
            "pipeline-run-running-unknown",
            "running",
            Some("attempt-test"),
            None,
            json!({"pipeline_last_summary": "still running without source ref"}),
        ));
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.metadata_json["pipeline_status"], "running");
        let new_run_id = node.metadata_json["pipeline_run_id"].as_str().unwrap();
        assert_ne!(new_run_id, "pipeline-run-running-unknown");
        let run = store.pipeline_run("pipeline-run-running-unknown");
        assert_eq!(run.status, "failed");
        assert_eq!(
            run.reason.as_deref(),
            Some("stale pipeline run source commit unknown superseded by abcdef1234567890")
        );
        assert_eq!(
            run.metadata_json["pipeline_last_summary"],
            "still running without source ref"
        );
        assert_eq!(run.metadata_json["stale_pipeline_run"], true);
        assert!(run.metadata_json["stale_source_commit_ref"].is_null());
        assert_eq!(
            run.metadata_json["superseded_by_source_commit_ref"],
            "abcdef1234567890"
        );
        let new_run = store.pipeline_run(new_run_id);
        assert_eq!(new_run.status, "running");
        assert_eq!(new_run.commit_ref.as_deref(), Some("abcdef1234567890"));
    }

    #[tokio::test]
    async fn pipeline_run_handler_keeps_requested_on_success_commit_mismatch() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_pipeline_contract());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
        store.insert_node(node);
        store.insert_pipeline_run(pipeline_run_record(
            "pipeline-run-stale",
            "success",
            Some("attempt-test"),
            Some("bbbbbb1234567890"),
            json!({
                "source_publish_source_commit_ref": "bbbbbb1234567890",
                "pipeline_last_summary": "stale run passed"
            }),
        ));
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.metadata_json["pipeline_status"], "running");
        assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
        let new_run_id = node.metadata_json["pipeline_run_id"].as_str().unwrap();
        assert_ne!(new_run_id, "pipeline-run-stale");
        let new_run = store.pipeline_run(new_run_id);
        assert_eq!(new_run.status, "running");
        assert_eq!(new_run.commit_ref.as_deref(), Some("abcdef1234567890"));
        assert!(node.metadata_json.get("last_verification_passed").is_none());
        assert!(node.metadata_json.get("pipeline_evidence_refs").is_none());
    }

    #[tokio::test]
    async fn pipeline_run_handler_skips_stale_attempt_without_projection() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-new".to_string());
        store.insert_node(node);
        let handler = pipeline_run_handler(Arc::clone(&store));

        let outcome = handler.handle(pipeline_run_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.execution, "reported");
        assert_ne!(node.metadata_json["pipeline_status"], "requested");
    }

    #[tokio::test]
    async fn supervisor_tick_handler_queues_attempt_retry_for_retry_node() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.current_attempt_id = Some("attempt-stale".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        store.insert_node(node);
        let handler = supervisor_tick_handler(Arc::clone(&store));

        let outcome = handler.handle(supervisor_tick_retry_item()).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(queued[0].plan_id.as_deref(), Some("plan-test"));
        assert_eq!(queued[0].payload_json["workspace_id"], "workspace-test");
        assert_eq!(queued[0].payload_json["task_id"], "task-test");
        assert_eq!(queued[0].payload_json["node_id"], "node-test");
        assert_eq!(queued[0].payload_json["worker_agent_id"], "agent-worker");
        assert_eq!(
            queued[0].payload_json["previous_attempt_id"],
            "attempt-stale"
        );
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            "stale_plan_node_no_terminal_worker_report"
        );
        assert_eq!(
            queued[0].payload_json["extra_instructions"],
            "recover stale node"
        );
        assert_eq!(
            queued[0].metadata_json["source"],
            "workspace_plan.supervisor_tick.retry_admission"
        );
        let node = store.node("node-test");
        assert_eq!(
            node.metadata_json["supervisor_tick_status"],
            "retry_admitted"
        );
        assert_eq!(
            node.metadata_json["supervisor_tick_retry_attempt_id"],
            "attempt-stale"
        );
        assert!(node.metadata_json["supervisor_tick_admitted_at"].is_string());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_dispatches_repair_from_blocked_dirty_main_dependency() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "todo".to_string();
        node.execution = "idle".to_string();
        node.depends_on_json = vec!["repair-node".to_string()];
        node.feature_checkpoint_json = Some(json!({
            "feature_id": "feature-node-test",
            "base_ref": "HEAD"
        }));
        node.metadata_json = json!({
            "blocked_by_repair_node_id": "repair-node"
        });
        store.insert_node(node);
        let mut repair = plan_node();
        repair.id = "repair-node".to_string();
        repair.workspace_task_id = None;
        repair.assignee_agent_id = None;
        repair.intent = "done".to_string();
        repair.execution = "idle".to_string();
        repair.depends_on_json = Vec::new();
        repair.feature_checkpoint_json = Some(json!({
            "feature_id": "feature-repair-node",
            "worktree_path": "/workspace/.memstack/worktrees/attempt-repair-node",
            "commit_ref": "abc1234"
        }));
        repair.metadata_json = json!({
            "repair_for_node_id": "node-test",
            "terminal_attempt_status": "accepted",
            "verified_commit_ref": "abc1234",
            "worktree_integration_commit_ref": "abc1234",
            "worktree_integration_status": "blocked_dirty_main",
            "verification_evidence_refs": ["commit_ref:abc1234"]
        });
        store.insert_node(repair);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-dirty-dispatch", SUPERVISOR_TICK_EVENT);
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "todo");
        assert_eq!(node.execution, "idle");
        assert_eq!(
            node.feature_checkpoint_json
                .as_ref()
                .and_then(|value| value["base_ref"].as_str()),
            Some("abc1234")
        );
        assert_eq!(
            node.metadata_json["dirty_main_dependency_base_ref"],
            "abc1234"
        );
        assert_eq!(
            node.metadata_json["dirty_main_dependency_seed_node_ids"],
            json!(["repair-node"])
        );
        assert_eq!(
            node.metadata_json["dirty_main_dependency_dispatch_status"],
            "queued"
        );
        assert!(node.metadata_json["dirty_main_dependency_dispatch_queued_at"].is_string());
        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(queued[0].payload_json["node_id"], "node-test");
        assert_eq!(queued[0].payload_json["task_id"], "task-test");
        assert_eq!(queued[0].payload_json["worker_agent_id"], "agent-worker");
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            "dirty_main_dependency_ready"
        );
        assert_eq!(
            queued[0].metadata_json["source"],
            "workspace_plan.supervisor_tick.retry_admission"
        );
        assert_eq!(
            queued[0].metadata_json["retry_reason"],
            "dirty_main_dependency_ready"
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_dispatches_release_candidate_from_dirty_main_dependencies() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "todo".to_string();
        node.execution = "idle".to_string();
        node.depends_on_json = vec!["dep-a".to_string(), "dep-b".to_string()];
        node.feature_checkpoint_json = Some(json!({
            "feature_id": "feature-release",
            "base_ref": "HEAD"
        }));
        node.metadata_json = json!({
            "iteration_phase": "deploy",
            "scrum_artifact": "release_candidate"
        });
        store.insert_node(node);
        for (dependency_id, commit_ref) in [("dep-a", "aaa1111"), ("dep-b", "bbb2222")] {
            let mut dependency = plan_node();
            dependency.id = dependency_id.to_string();
            dependency.workspace_task_id = None;
            dependency.assignee_agent_id = None;
            dependency.intent = "done".to_string();
            dependency.execution = "idle".to_string();
            dependency.depends_on_json = Vec::new();
            dependency.feature_checkpoint_json = Some(json!({
                "feature_id": format!("feature-{dependency_id}"),
                "worktree_path": format!("/workspace/.memstack/worktrees/attempt-{dependency_id}"),
                "commit_ref": commit_ref
            }));
            dependency.metadata_json = json!({
                "terminal_attempt_status": "accepted",
                "verified_commit_ref": commit_ref,
                "worktree_integration_commit_ref": commit_ref,
                "worktree_integration_status": "blocked_dirty_main",
                "verification_evidence_refs": [format!("commit_ref:{commit_ref}")]
            });
            store.insert_node(dependency);
        }
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox(
            "job-supervisor-release-dirty-dispatch",
            SUPERVISOR_TICK_EVENT,
        );
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(
            node.feature_checkpoint_json
                .as_ref()
                .and_then(|value| value["base_ref"].as_str()),
            Some("bbb2222")
        );
        assert_eq!(
            node.metadata_json["dirty_main_dependency_base_ref"],
            "bbb2222"
        );
        assert_eq!(
            node.metadata_json["dirty_main_dependency_seed_node_ids"],
            json!(["dep-a", "dep-b"])
        );
        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(queued[0].payload_json["node_id"], "node-test");
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            "dirty_main_dependency_ready"
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_keeps_regular_node_blocked_by_dirty_main_dependency() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "todo".to_string();
        node.execution = "idle".to_string();
        node.depends_on_json = vec!["dirty-dependency".to_string()];
        node.feature_checkpoint_json = Some(json!({
            "feature_id": "feature-node-test",
            "base_ref": "HEAD"
        }));
        store.insert_node(node);
        let mut dependency = plan_node();
        dependency.id = "dirty-dependency".to_string();
        dependency.workspace_task_id = None;
        dependency.assignee_agent_id = None;
        dependency.intent = "done".to_string();
        dependency.execution = "idle".to_string();
        dependency.depends_on_json = Vec::new();
        dependency.feature_checkpoint_json = Some(json!({
            "feature_id": "feature-dirty-dependency",
            "worktree_path": "/workspace/.memstack/worktrees/attempt-dirty-dependency",
            "commit_ref": "def5678"
        }));
        dependency.metadata_json = json!({
            "terminal_attempt_status": "accepted",
            "verified_commit_ref": "def5678",
            "worktree_integration_commit_ref": "def5678",
            "worktree_integration_status": "blocked_dirty_main",
            "verification_evidence_refs": ["commit_ref:def5678"]
        });
        store.insert_node(dependency);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-dirty-blocked", SUPERVISOR_TICK_EVENT);
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(
            outcome,
            WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_requires_full_runtime".to_string())
            }
        );
        let node = store.node("node-test");
        assert_eq!(
            node.feature_checkpoint_json
                .as_ref()
                .and_then(|value| value["base_ref"].as_str()),
            Some("HEAD")
        );
        assert!(node
            .metadata_json
            .get("dirty_main_dependency_dispatch_status")
            .is_none());
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_releases_missing_attempt_node_and_queues_retry() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("missing-attempt".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        node.metadata_json = json!({"retry_not_before": "2026-01-02T03:04:05Z"});
        store.insert_node(node);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "todo");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id, None);
        assert_eq!(
            node.metadata_json["terminal_attempt_retry_reason"],
            "missing_attempt"
        );
        assert_eq!(node.metadata_json["terminal_attempt_retry_count"], 1);
        assert!(node.metadata_json["terminal_attempt_reconciled_at"].is_string());
        assert!(node.metadata_json.get("retry_not_before").is_none());

        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(queued[0].payload_json["node_id"], "node-test");
        assert_eq!(queued[0].payload_json["task_id"], "task-test");
        assert_eq!(
            queued[0].payload_json["previous_attempt_id"],
            "missing-attempt"
        );
        assert_eq!(queued[0].payload_json["retry_reason"], "missing_attempt");
        assert_eq!(queued[0].metadata_json["retry_node_id"], "node-test");
        assert_eq!(
            queued[0].metadata_json["retry_attempt_id"],
            "missing-attempt"
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_releases_terminal_rejected_attempt_and_queues_retry() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-rejected".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        store.insert_node(node);
        store.insert_attempt(task_session_attempt(
            "attempt-rejected",
            "rejected",
            Some("conversation-test"),
        ));
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "todo");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id, None);
        assert_eq!(
            node.metadata_json["terminal_attempt_retry_reason"],
            "terminal_attempt_rejected"
        );
        assert_eq!(node.metadata_json["terminal_attempt_retry_count"], 1);
        assert!(node.metadata_json["terminal_attempt_reconciled_at"].is_string());

        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(queued[0].payload_json["node_id"], "node-test");
        assert_eq!(
            queued[0].payload_json["previous_attempt_id"],
            "attempt-rejected"
        );
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            "terminal_attempt_rejected"
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_projects_superseding_accepted_attempt_before_retry() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-cancelled".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": "/workspace/.worktrees/attempt-accepted",
            "branch_name": "attempt-accepted",
            "base_ref": "main",
            "commit_ref": "abcdef1"
        }));
        store.insert_node(node);
        let mut cancelled =
            task_session_attempt("attempt-cancelled", "cancelled", Some("conversation-test"));
        cancelled.attempt_number = 2;
        cancelled.adjudication_reason = Some("recovery:parent_done".to_string());
        store.insert_attempt(cancelled);
        let mut accepted = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        accepted.attempt_number = 1;
        accepted.leader_feedback = Some("accepted after parent recovery".to_string());
        accepted.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
        accepted.candidate_verifications_json = vec![
            "test_run:cargo test -p agistack-server workspace_outbox_worker".to_string(),
            "git_diff_summary:accepted sibling won".to_string(),
        ];
        store.insert_attempt(accepted);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
        assert_eq!(
            node.metadata_json["terminal_attempt_status"],
            ACCEPTED_ATTEMPT_STATUS
        );
        assert_eq!(
            node.metadata_json["terminal_attempt_superseded_attempt_id"],
            "attempt-cancelled"
        );
        assert_eq!(
            node.metadata_json["terminal_attempt_superseded_status"],
            "cancelled"
        );
        assert_eq!(
            node.metadata_json["terminal_attempt_superseded_reason"],
            "recovery:parent_done"
        );
        assert_eq!(
            node.metadata_json["last_verification_attempt_id"],
            "attempt-accepted"
        );
        assert_eq!(node.metadata_json["last_verification_passed"], true);

        let task = store.task("task-test");
        assert_eq!(task.status, "done");
        assert_eq!(task.metadata_json["durable_plan_verdict"], "accepted");
        assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-accepted");
        assert_eq!(
            task.metadata_json["last_worker_report_summary"],
            "accepted after parent recovery"
        );
        assert_eq!(
            task.metadata_json["handoff_package"]["git_head"],
            "abcdef1234567890"
        );
        assert_eq!(
            task.metadata_json["handoff_package"]["git_diff_summary"],
            "accepted sibling won"
        );
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_retries_terminal_parent_done_with_output() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-cancelled".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1"}));
        store.insert_node(node);
        let mut cancelled =
            task_session_attempt("attempt-cancelled", "cancelled", Some("conversation-test"));
        cancelled.attempt_number = 2;
        cancelled.adjudication_reason = Some("recovery:parent_done".to_string());
        cancelled.candidate_summary = Some("cancelled attempt already produced output".to_string());
        store.insert_attempt(cancelled);
        let mut accepted = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        accepted.attempt_number = 1;
        accepted.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
        store.insert_attempt(accepted);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "todo");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id, None);
        assert_eq!(
            node.metadata_json["terminal_attempt_retry_reason"],
            "terminal_attempt_cancelled"
        );
        assert!(node
            .metadata_json
            .get("terminal_attempt_superseded_attempt_id")
            .is_none());
        let task = store.task("task-test");
        assert_eq!(task.status, "todo");
        assert!(task.metadata_json.get("durable_plan_verdict").is_none());
        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(
            queued[0].payload_json["previous_attempt_id"],
            "attempt-cancelled"
        );
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            "terminal_attempt_cancelled"
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_skips_terminal_attempt_with_pipeline_result_pending() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-rejected".to_string());
        node.metadata_json = json!({
            "pipeline_status": "success",
            "pipeline_run_id": "pipeline-run-test"
        });
        store.insert_node(node);
        store.insert_attempt(task_session_attempt(
            "attempt-rejected",
            "rejected",
            Some("conversation-test"),
        ));
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(
            outcome,
            WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_requires_full_runtime".to_string())
            }
        );
        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-rejected"));
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_projects_accepted_attempt_to_node_and_task() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": "/workspace/.worktrees/attempt-accepted",
            "branch_name": "attempt-accepted",
            "base_ref": "main",
            "commit_ref": "abcdef1"
        }));
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        attempt.leader_feedback = Some("accepted after verification".to_string());
        attempt.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
        attempt.candidate_verifications_json = vec![
            "test_run:cargo test -p agistack-server workspace_outbox_worker".to_string(),
            "git_diff_summary:updated supervisor projection".to_string(),
        ];
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
        assert_eq!(
            node.metadata_json["terminal_attempt_status"],
            ACCEPTED_ATTEMPT_STATUS
        );
        assert_eq!(
            node.metadata_json["last_verification_summary"],
            "accepted after verification"
        );
        assert_eq!(node.metadata_json["last_verification_passed"], true);
        assert_eq!(
            node.metadata_json["last_verification_attempt_id"],
            "attempt-accepted"
        );
        assert_eq!(
            node.metadata_json["candidate_artifacts"],
            json!(["commit_ref:abcdef1234567890"])
        );

        let task = store.task("task-test");
        assert_eq!(task.status, "done");
        assert!(task.completed_at.is_some());
        assert_eq!(task.metadata_json["durable_plan_verdict"], "accepted");
        assert_eq!(
            task.metadata_json["last_attempt_status"],
            ACCEPTED_ATTEMPT_STATUS
        );
        assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-accepted");
        assert_eq!(
            task.metadata_json["last_worker_report_summary"],
            "accepted after verification"
        );
        assert_eq!(
            task.metadata_json["handoff_package"]["git_head"],
            "abcdef1234567890"
        );
        assert_eq!(
            task.metadata_json["handoff_package"]["git_diff_summary"],
            "updated supervisor projection"
        );
        assert_eq!(
            task.metadata_json["handoff_package"]["test_commands"],
            json!(["cargo test -p agistack-server workspace_outbox_worker"])
        );
        assert_eq!(task.metadata_json["worktree_integration_status"], "skipped");
        assert_eq!(
            task.metadata_json["worktree_integration_summary"],
            "sandbox_code_root is not available for accepted worktree integration"
        );
        assert_eq!(
            node.metadata_json["worktree_integration_commit_ref"],
            "abcdef1234567890"
        );
        assert_eq!(node.metadata_json["worktree_integration_status"], "skipped");
        assert!(store.plan_events().is_empty());
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_reconciles_accepted_supervisor_judge_attempt() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        let mut task = task_with_plan_metadata();
        task.status = "in_progress".to_string();
        task.metadata_json = json!({
            WORKSPACE_PLAN_ID: "plan-test",
            WORKSPACE_PLAN_NODE_ID: "node-test",
            ROOT_GOAL_TASK_ID: "root-task",
            CURRENT_ATTEMPT_ID: "attempt-judge",
            PENDING_LEADER_ADJUDICATION: true,
            "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS,
            "last_worker_report_summary": "candidate satisfies the acceptance criteria"
        });
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "done".to_string();
        node.execution = "idle".to_string();
        node.current_attempt_id = Some("attempt-judge".to_string());
        node.metadata_json = json!({
            "last_verification_judge_verdict": "accepted",
            "last_verification_summary": "supervisor accepted current evidence",
            "last_verification_passed": true,
            "verification_evidence_refs": ["worker_report:completed"]
        });
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-judge",
            AWAITING_LEADER_ADJUDICATION_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_summary = Some("candidate satisfies the acceptance criteria".to_string());
        attempt.candidate_artifacts_json = vec!["artifact:review-report".to_string()];
        attempt.candidate_verifications_json = vec!["worker_report:completed".to_string()];
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let attempt = store.attempt("attempt-judge");
        assert_eq!(attempt.status, ACCEPTED_ATTEMPT_STATUS);
        assert_eq!(
            attempt.leader_feedback.as_deref(),
            Some("supervisor accepted current evidence")
        );
        assert_eq!(
            attempt.adjudication_reason.as_deref(),
            Some("supervisor_decision_accept_node_reconciled")
        );
        assert!(attempt.completed_at.is_some());
        let node = store.node("node-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-judge"));
        assert_eq!(
            node.metadata_json["terminal_attempt_status"],
            ACCEPTED_ATTEMPT_STATUS
        );
        assert_eq!(
            node.metadata_json["last_verification_summary"],
            "supervisor accepted current evidence"
        );
        assert_eq!(
            node.metadata_json["last_verification_attempt_id"],
            "attempt-judge"
        );
        assert_eq!(
            node.metadata_json["candidate_artifacts"],
            json!(["artifact:review-report"])
        );
        let task = store.task("task-test");
        assert_eq!(task.status, "done");
        assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
        assert_eq!(task.metadata_json["durable_plan_verdict"], "accepted");
        assert_eq!(
            task.metadata_json["durable_plan_verification_summary"],
            "supervisor accepted current evidence"
        );
        assert_eq!(
            task.metadata_json["last_attempt_status"],
            ACCEPTED_ATTEMPT_STATUS
        );
        assert_eq!(task.metadata_json["last_attempt_id"], "attempt-judge");
        assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-judge");
        assert_eq!(
            task.metadata_json["last_leader_adjudication_status"],
            ACCEPTED_ATTEMPT_STATUS
        );
        assert_eq!(
            task.metadata_json["evidence_refs"],
            json!(["artifact:review-report", "worker_report:completed"])
        );
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_projects_dispose_node_supervisor_decision() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        let mut task = task_with_plan_metadata();
        task.status = "in_progress".to_string();
        task.metadata_json = json!({
            WORKSPACE_PLAN_ID: "plan-test",
            WORKSPACE_PLAN_NODE_ID: "node-test",
            ROOT_GOAL_TASK_ID: "root-task",
            CURRENT_ATTEMPT_ID: "attempt-dispose",
            PENDING_LEADER_ADJUDICATION: true,
            "last_attempt_status": AWAITING_LEADER_ADJUDICATION_STATUS
        });
        store.insert_task(task);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-dispose".to_string());
        node.metadata_json = json!({
            "last_supervisor_decision_action": "dispose_node",
            "last_supervisor_decision_rationale": "repair node superseded this obsolete node",
            "last_supervisor_decision_confidence": 0.81,
            "last_supervisor_decision_feedback_items": [{
                "target_layer": "planner",
                "recommended_action": "obsolete_node",
                "summary": "repair alternative already covers the requirement"
            }],
            "last_supervisor_decision_event_payload": {
                "disposed_node_id": "node-test",
                "superseded_by_node_id": "repair-node",
                "superseded_by_task_id": "repair-task"
            },
            "last_verification_summary": "obsolete after repair alternative"
        });
        store.insert_node(node);
        store.insert_supervisor_dispose_decision("workspace-test", "plan-test", "node-test");
        let mut attempt = task_session_attempt(
            "attempt-dispose",
            AWAITING_LEADER_ADJUDICATION_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_summary = Some("obsolete candidate".to_string());
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let attempt = store.attempt("attempt-dispose");
        assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
        assert_eq!(attempt.completed_at, None);

        let node = store.node("node-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-dispose"));
        assert!(node.completed_at.is_some());
        assert_eq!(
            node.metadata_json["verification_feedback_disposition"],
            SUPERVISOR_DISPOSED_NODE_DISPOSITION
        );
        assert_eq!(
            node.metadata_json["last_supervisor_decision_action"],
            "dispose_node"
        );
        assert_eq!(
            node.metadata_json["last_supervisor_decision_rationale"],
            "repair node superseded this obsolete node"
        );
        assert_eq!(
            node.metadata_json["workspace_task_projection_status"],
            "done"
        );
        assert!(node.metadata_json["workspace_task_projected_at"].is_string());
        assert!(node
            .metadata_json
            .get("reported_attempt_reconciled_at")
            .is_none());

        let task = store.task("task-test");
        assert_eq!(task.status, "done");
        assert_eq!(task.metadata_json[PENDING_LEADER_ADJUDICATION], false);
        assert_eq!(task.metadata_json["durable_plan_verdict"], "disposed");
        assert_eq!(
            task.metadata_json["durable_plan_disposition"],
            SUPERVISOR_DISPOSED_NODE_DISPOSITION
        );
        assert_eq!(
            task.metadata_json["durable_plan_verification_summary"],
            "repair node superseded this obsolete node"
        );
        assert_eq!(task.metadata_json["last_attempt_status"], "disposed");
        assert_eq!(task.metadata_json["last_worker_report_type"], "disposed");
        assert_eq!(
            task.metadata_json[LAST_WORKER_REPORT_SUMMARY],
            "repair node superseded this obsolete node"
        );
        assert_eq!(
            task.metadata_json["last_leader_adjudication_status"],
            "disposed"
        );
        assert_eq!(task.metadata_json["last_attempt_id"], "attempt-dispose");
        assert_eq!(task.metadata_json[CURRENT_ATTEMPT_ID], "attempt-dispose");
        assert_eq!(task.metadata_json["disposed_node_id"], "node-test");
        assert_eq!(task.metadata_json["superseded_by_node_id"], "repair-node");
        assert_eq!(task.metadata_json["superseded_by_task_id"], "repair-task");

        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "supervisor_disposition_reconciled");
        assert_eq!(events[0].payload_json["action"], "dispose_node");
        assert_eq!(events[0].payload_json["had_dispose_event"], true);
        assert_eq!(events[0].payload_json["task_projected"], true);
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_reconciles_retry_same_node_supervisor_decision() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-retry".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        node.metadata_json = json!({
            "last_supervisor_decision_action": "retry_same_node",
            "last_supervisor_decision_rationale": "retry after tightening the implementation",
            "last_supervisor_decision_confidence": 0.72,
            "last_supervisor_decision_feedback_items": [{
                "target_layer": "implementation",
                "recommended_action": "fix_regression",
                "summary": "missing regression coverage"
            }],
            "retry_not_before": "2999-01-02T03:04:05Z"
        });
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-retry",
            AWAITING_LEADER_ADJUDICATION_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_summary = Some("worker produced a candidate with a gap".to_string());
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let attempt = store.attempt("attempt-retry");
        assert_eq!(attempt.status, REJECTED_ATTEMPT_STATUS);
        assert_eq!(
            attempt.leader_feedback.as_deref(),
            Some("retry after tightening the implementation")
        );
        assert_eq!(
            attempt.adjudication_reason.as_deref(),
            Some(SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON)
        );
        assert!(attempt.completed_at.is_some());

        let node = store.node("node-test");
        assert_eq!(node.intent, "todo");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id, None);
        assert_eq!(
            node.metadata_json["terminal_attempt_retry_reason"],
            SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
        );
        assert_eq!(
            node.metadata_json["supervisor_decision_retry_attempt_id"],
            "attempt-retry"
        );
        assert_eq!(
            node.metadata_json["supervisor_decision_retry_attempt_status"],
            REJECTED_ATTEMPT_STATUS
        );
        assert!(node
            .metadata_json
            .get("reported_attempt_reconciled_at")
            .is_none());
        assert!(node.metadata_json.get("retry_not_before").is_none());

        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(
            events[0].event_type,
            "supervisor_decision_retry_same_node_reconciled"
        );
        assert_eq!(
            events[0].payload_json["reason"],
            SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
        );
        assert_eq!(events[0].payload_json["action"], "retry_same_node");
        assert_eq!(
            events[0].payload_json["rationale"],
            "retry after tightening the implementation"
        );
        assert_eq!(events[0].payload_json["retry_exhausted"], false);

        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(queued[0].payload_json["node_id"], "node-test");
        assert_eq!(queued[0].payload_json["task_id"], "task-test");
        assert_eq!(
            queued[0].payload_json["previous_attempt_id"],
            "attempt-retry"
        );
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON
        );
        assert_eq!(
            queued[0].payload_json["retry_not_before"],
            "2999-01-02T03:04:05+00:00"
        );
        assert_eq!(
            queued[0].next_attempt_at,
            Some(
                DateTime::parse_from_rfc3339("2999-01-02T03:04:05Z")
                    .unwrap()
                    .with_timezone(&Utc)
            )
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_reconciles_root_goal_progress_for_accepted_child() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_metadata(json!({})));
        store.insert_task(root_goal_task());
        store.insert_task(task_with_plan_metadata());
        let mut stale_child = task_with_plan_metadata();
        stale_child.id = "stale-helper-task".to_string();
        stale_child.title = "Old helper task".to_string();
        stale_child.status = "blocked".to_string();
        stale_child.blocker_reason = Some("stale helper blocked".to_string());
        stale_child.assignee_agent_id = None;
        stale_child.metadata_json = json!({
            ROOT_GOAL_TASK_ID: "root-task",
            WORKSPACE_PLAN_ID: "old-plan",
            WORKSPACE_PLAN_NODE_ID: "missing-node"
        });
        store.insert_task(stale_child);
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        attempt.leader_feedback = Some("accepted after verification".to_string());
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let task = store.task("task-test");
        assert_eq!(task.status, "done");
        let root = store.task("root-task");
        assert_eq!(root.status, "todo");
        assert_eq!(
            root.metadata_json["goal_progress_summary"],
            "1/1 child tasks done; 0 in progress; 0 blocked; 1/1 assigned"
        );
        assert_eq!(root.metadata_json["goal_health"], "achieved");
        assert_eq!(
            root.metadata_json[REMEDIATION_STATUS],
            "ready_for_completion"
        );
        assert_eq!(
            root.metadata_json[REMEDIATION_SUMMARY],
            "All child tasks are done; root goal should now validate completion evidence"
        );
        assert_eq!(root.metadata_json["active_child_task_ids"], json!([]));
        assert_eq!(root.metadata_json["blocked_child_task_ids"], json!([]));
        assert_eq!(root.metadata_json["blocked_reason"], Value::Null);
        assert!(root.metadata_json["last_progress_at"].is_string());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_records_already_merged_accepted_worktree() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_code_root("/workspace/app"));
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": "/workspace/app",
            "branch_name": "attempt-accepted",
            "base_ref": "main",
            "commit_ref": "abcdef1"
        }));
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        attempt.leader_feedback = Some("accepted in main checkout".to_string());
        attempt.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        let task = store.task("task-test");
        assert_eq!(node.intent, "done");
        assert_eq!(task.status, "done");
        assert_eq!(
            node.metadata_json["worktree_integration_status"],
            "already_merged"
        );
        assert_eq!(
            task.metadata_json["worktree_integration_worktree_path"],
            "/workspace/app"
        );
        assert_eq!(
            task.metadata_json["worktree_integration_summary"],
            "accepted attempt already ran in sandbox_code_root"
        );
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(
            events[0].event_type,
            "accepted_worktree_integration_skipped"
        );
        assert_eq!(
            events[0].source,
            "workspace_plan.accepted_worktree_integration"
        );
        assert_eq!(events[0].payload_json["status"], "already_merged");
        assert_eq!(events[0].payload_json["commit_ref"], "abcdef1234567890");
        assert_eq!(events[0].payload_json["worktree_path"], "/workspace/app");
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_integrates_accepted_attempt_worktree() {
        let Some(fixture) = git_publish_fixture() else {
            return;
        };
        let worktree_path = fixture.root.join(".memstack/worktrees/attempt-accepted");
        std::fs::create_dir_all(worktree_path.parent().unwrap()).unwrap();
        run_git_ok(
            &fixture.repo,
            &[
                "worktree",
                "add",
                "-b",
                "attempt-accepted",
                worktree_path.to_str().unwrap(),
                "HEAD",
            ],
        );
        std::fs::write(worktree_path.join("accepted.txt"), "accepted work\n").unwrap();
        run_git_ok(&worktree_path, &["add", "accepted.txt"]);
        run_git_ok(&worktree_path, &["commit", "-m", "accepted work"]);
        let candidate_commit = run_git_ok(&worktree_path, &["rev-parse", "HEAD"])
            .trim()
            .to_string();

        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_code_root(fixture.repo.to_str().unwrap()));
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": worktree_path.to_str().unwrap(),
            "branch_name": "attempt-accepted",
            "base_ref": "main",
            "commit_ref": candidate_commit
        }));
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        attempt.leader_feedback = Some("accepted in isolated worktree".to_string());
        attempt.candidate_artifacts_json = vec![format!("commit_ref:{candidate_commit}")];
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        let task = store.task("task-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
        assert_eq!(task.status, "done");
        assert_eq!(node.metadata_json["worktree_integration_status"], "merged");
        assert_eq!(
            node.metadata_json["worktree_integration_commit_ref"],
            candidate_commit
        );
        assert_eq!(
            task.metadata_json["worktree_integration_worktree_path"],
            worktree_path.to_str().unwrap()
        );
        assert_eq!(
            run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
                .trim()
                .to_string(),
            candidate_commit
        );
        assert_eq!(
            std::fs::read_to_string(fixture.repo.join("accepted.txt")).unwrap(),
            "accepted work\n"
        );
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "accepted_worktree_integrated");
        assert_eq!(events[0].payload_json["status"], "merged");
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_retries_blocked_accepted_worktree_when_main_is_clean() {
        let Some(fixture) = git_publish_fixture() else {
            return;
        };
        let worktree_path = fixture.root.join(".memstack/worktrees/attempt-accepted");
        std::fs::create_dir_all(worktree_path.parent().unwrap()).unwrap();
        run_git_ok(
            &fixture.repo,
            &[
                "worktree",
                "add",
                "-b",
                "attempt-accepted",
                worktree_path.to_str().unwrap(),
                "HEAD",
            ],
        );
        std::fs::write(worktree_path.join("accepted.txt"), "accepted work\n").unwrap();
        run_git_ok(&worktree_path, &["add", "accepted.txt"]);
        run_git_ok(&worktree_path, &["commit", "-m", "accepted work"]);
        let candidate_commit = run_git_ok(&worktree_path, &["rev-parse", "HEAD"])
            .trim()
            .to_string();
        std::fs::write(fixture.repo.join("dirty.txt"), "local dirty\n").unwrap();

        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_code_root(fixture.repo.to_str().unwrap()));
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": worktree_path.to_str().unwrap(),
            "branch_name": "attempt-accepted",
            "base_ref": "main",
            "commit_ref": candidate_commit
        }));
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        attempt.leader_feedback = Some("accepted in isolated worktree".to_string());
        attempt.candidate_artifacts_json = vec![format!("commit_ref:{candidate_commit}")];
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        let task = store.task("task-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(task.status, "done");
        assert_eq!(
            node.metadata_json["worktree_integration_status"],
            "blocked_dirty_main"
        );
        assert_eq!(
            task.metadata_json["worktree_integration_commit_ref"],
            candidate_commit
        );
        assert!(node.metadata_json["worktree_integration_dirty_signature"].is_string());
        assert!(node.metadata_json["worktree_integration_summary"]
            .as_str()
            .unwrap()
            .contains("sandbox_code_root has uncommitted changes"));
        assert_eq!(
            run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
                .trim()
                .to_string(),
            fixture.commit_ref
        );
        assert!(!fixture.repo.join("accepted.txt").exists());
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(
            events[0].event_type,
            "accepted_worktree_integration_blocked"
        );
        assert_eq!(events[0].payload_json["status"], "blocked_dirty_main");
        assert!(store.outbox().is_empty());

        std::fs::remove_file(fixture.repo.join("dirty.txt")).unwrap();
        let mut item = outbox("job-supervisor-tick-retry", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        let task = store.task("task-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(task.status, "done");
        assert_eq!(node.metadata_json["worktree_integration_status"], "merged");
        assert_eq!(
            node.metadata_json["worktree_integration_commit_ref"],
            candidate_commit
        );
        assert_eq!(
            run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
                .trim()
                .to_string(),
            candidate_commit
        );
        assert_eq!(
            std::fs::read_to_string(fixture.repo.join("accepted.txt")).unwrap(),
            "accepted work\n"
        );
        let events = store.plan_events();
        assert_eq!(events.len(), 2);
        assert_eq!(events[1].event_type, "accepted_worktree_integrated");
        assert_eq!(events[1].payload_json["status"], "merged");
    }

    #[tokio::test]
    async fn supervisor_tick_handler_reopens_failed_worktree_integration_done_node() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "done".to_string();
        node.execution = "idle".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        node.completed_at = Some(Utc.with_ymd_and_hms(2026, 1, 2, 4, 5, 6).unwrap());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
            "branch_name": "workspace/node-attempt-accepted",
            "base_ref": "main",
            "commit_ref": "abcdef1"
        }));
        node.metadata_json = json!({
            "terminal_attempt_status": "accepted",
            "last_verification_passed": true,
            "last_verification_attempt_id": "attempt-accepted",
            "verified_commit_ref": "abcdef1234567890",
            "worktree_integration_attempt_id": "attempt-accepted",
            "worktree_integration_status": "failed",
            "worktree_integration_commit_ref": "abcdef1234567890",
            "worktree_integration_worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
            "worktree_integration_dirty_signature": Value::Null,
            "worktree_integration_summary": "Exit code: 128\nstatus=failed\nreason=merge_failed_aborted\nfatal: refusing to merge unrelated histories",
            "candidate_artifacts": ["commit_ref:abcdef1234567890"]
        });
        store.insert_node(node);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
            "extra_instructions": "retry failed accepted worktree integration"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "todo");
        assert_eq!(node.execution, "idle");
        assert!(node.current_attempt_id.is_none());
        assert!(node.assignee_agent_id.is_none());
        assert!(node.completed_at.is_none());
        let checkpoint = node.feature_checkpoint_json.unwrap();
        assert!(checkpoint["worktree_path"].is_null());
        assert!(checkpoint["branch_name"].is_null());
        assert_eq!(checkpoint["base_ref"], "HEAD");
        assert!(checkpoint["commit_ref"].is_null());
        assert_eq!(node.metadata_json["last_verification_passed"], false);
        assert_eq!(
            node.metadata_json["terminal_attempt_retry_reason"],
            "worktree_integration_failed"
        );
        assert_eq!(
            node.metadata_json["worktree_integration_failed_previous_attempt_id"],
            "attempt-accepted"
        );
        assert_eq!(
            node.metadata_json["worktree_integration_failed_previous_commit_ref"],
            "abcdef1234567890"
        );
        assert!(node
            .metadata_json
            .get("worktree_integration_status")
            .is_none());
        assert!(node.metadata_json.get("candidate_artifacts").is_none());

        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(
            events[0].event_type,
            "worktree_integration_failed_done_node_reopened"
        );
        assert_eq!(events[0].source, "workspace_plan_supervisor_tick");
        assert_eq!(
            events[0].payload_json["previous_attempt_id"],
            "attempt-accepted"
        );
        assert_eq!(
            events[0].payload_json["previous_commit_ref"],
            "abcdef1234567890"
        );

        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(queued[0].payload_json["node_id"], "node-test");
        assert_eq!(
            queued[0].payload_json["previous_attempt_id"],
            "attempt-accepted"
        );
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            "worktree_integration_failed"
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_preserves_failed_worktree_when_commit_ref_was_missing() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "done".to_string();
        node.execution = "idle".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
            "branch_name": "workspace/node-attempt-accepted",
            "base_ref": "main",
            "commit_ref": "abcdef1"
        }));
        node.metadata_json = json!({
            "terminal_attempt_status": "accepted",
            "last_verification_passed": true,
            "last_verification_attempt_id": "attempt-accepted",
            "verified_commit_ref": "abcdef1234567890",
            "worktree_integration_attempt_id": "attempt-accepted",
            "worktree_integration_status": "failed",
            "worktree_integration_commit_ref": "abcdef1234567890",
            "worktree_integration_worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
            "worktree_integration_dirty_signature": Value::Null,
            "worktree_integration_summary": "status=failed\ncommit_ref not found in attempt worktree"
        });
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(
            outcome,
            WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_requires_full_runtime".to_string())
            }
        );
        let node = store.node("node-test");
        assert_eq!(node.intent, "done");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.metadata_json["worktree_integration_status"], "failed");
        assert!(store.plan_events().is_empty());
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_skips_accepted_attempt_with_commit_mismatch() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1"}));
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-accepted",
            ACCEPTED_ATTEMPT_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_artifacts_json = vec!["commit_ref:1234567890abcdef".to_string()];
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(
            outcome,
            WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_requires_full_runtime".to_string())
            }
        );
        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "running");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
        let task = store.task("task-test");
        assert_eq!(task.status, "todo");
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn supervisor_tick_handler_reconciles_reported_attempt_node_and_writes_event() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-test",
            AWAITING_LEADER_ADJUDICATION_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_summary = Some("worker produced a candidate".to_string());
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
        assert_eq!(
            node.metadata_json["reported_attempt_status"],
            AWAITING_LEADER_ADJUDICATION_STATUS
        );
        assert!(node.metadata_json["reported_attempt_reconciled_at"].is_string());
        assert!(store.outbox().is_empty());

        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "auto_reported_attempt_reconciled");
        assert_eq!(events[0].source, "workspace_plan_supervisor_tick");
        assert_eq!(events[0].node_id.as_deref(), Some("node-test"));
        assert_eq!(events[0].attempt_id.as_deref(), Some("attempt-test"));
        assert_eq!(
            events[0].payload_json["reason"],
            "active_plan_node_points_to_reported_attempt"
        );
        assert_eq!(events[0].payload_json["node_ids"], json!(["node-test"]));
    }

    #[tokio::test]
    async fn supervisor_tick_handler_observes_worker_report_without_retrying_completed_candidate() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        node.metadata_json = json!({
            "launch_state": "completed_via_stream",
            "last_worker_report_type": "completed",
            "last_worker_report_summary": "finished from stream"
        });
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-test",
            AWAITING_LEADER_ADJUDICATION_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_summary = Some("finished from stream".to_string());
        attempt.candidate_verifications_json = vec!["worker_report:completed".to_string()];
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let item = worker_report_supervisor_tick(
            "workspace-test",
            "plan-test",
            "node-test",
            "attempt-test",
            "root-task",
            "actor-test",
            Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            Utc.with_ymd_and_hms(2026, 1, 2, 5, 0, 0).unwrap(),
        );

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "reported");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
        assert_eq!(
            node.metadata_json["worker_report_supervisor_tick_status"],
            "reported_candidate_observed"
        );
        assert_eq!(
            node.metadata_json["reported_attempt_status"],
            AWAITING_LEADER_ADJUDICATION_STATUS
        );
        assert!(store.outbox().is_empty());
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, AWAITING_LEADER_ADJUDICATION_STATUS);
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "auto_reported_attempt_reconciled");
        assert_eq!(
            events[0].payload_json["reason"],
            "worker_report_supervisor_tick"
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_retries_worker_stream_orphan_report() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        node.metadata_json = json!({
            "launch_state": "no_terminal_event",
            "last_worker_report_type": "blocked",
            "last_worker_report_summary": "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        });
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-test",
            AWAITING_LEADER_ADJUDICATION_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_summary = Some(
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
                .to_string(),
        );
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let item = worker_report_supervisor_tick(
            "workspace-test",
            "plan-test",
            "node-test",
            "attempt-test",
            "root-task",
            "actor-test",
            Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            Utc.with_ymd_and_hms(2026, 1, 2, 5, 1, 0).unwrap(),
        );

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "todo");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id, None);
        assert_eq!(
            node.metadata_json["terminal_attempt_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(
            node.metadata_json["worker_report_supervisor_tick_status"],
            "orphan_retry_admitted"
        );
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, "blocked");
        assert_eq!(
            attempt.adjudication_reason.as_deref(),
            Some("worker_stream_agent_not_running_stream_idle")
        );
        let queued = store.outbox();
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
        assert_eq!(
            queued[0].payload_json["previous_attempt_id"],
            "attempt-test"
        );
        assert_eq!(
            queued[0].payload_json["retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(
            queued[0].payload_json["retry_origin"],
            "worker_stream_orphan_report"
        );
        assert_eq!(
            queued[0].payload_json["worker_stream_orphan_retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(
            queued[0].payload_json["worker_stream_orphan_summary"],
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        );
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "worker_stream_orphan_retry_admitted");
        assert_eq!(
            events[0].payload_json["retry_reason"],
            "worker_stream_agent_not_running_stream_idle"
        );
        assert_eq!(events[0].payload_json["retry_exhausted"], false);
        assert_eq!(events[0].payload_json["retry_count"], 1);
        assert_eq!(
            events[0].payload_json["max_retries"],
            DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_blocks_worker_stream_orphan_when_retry_budget_exhausted() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "reported".to_string();
        node.current_attempt_id = Some("attempt-test".to_string());
        node.assignee_agent_id = Some("agent-worker".to_string());
        node.metadata_json = json!({
            "launch_state": "no_terminal_event",
            "last_worker_report_type": "blocked",
            "last_worker_report_summary": "Worker stream stopped without a terminal complete/error event (agent_finished_without_terminal_event).",
            "terminal_attempt_retry_count": DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES
        });
        store.insert_node(node);
        let mut attempt = task_session_attempt(
            "attempt-test",
            AWAITING_LEADER_ADJUDICATION_STATUS,
            Some("conversation-test"),
        );
        attempt.candidate_summary = Some(
            "Worker stream stopped without a terminal complete/error event (agent_finished_without_terminal_event)."
                .to_string(),
        );
        store.insert_attempt(attempt);
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let item = worker_report_supervisor_tick(
            "workspace-test",
            "plan-test",
            "node-test",
            "attempt-test",
            "root-task",
            "actor-test",
            Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
            Utc.with_ymd_and_hms(2026, 1, 2, 5, 1, 0).unwrap(),
        );

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
        let node = store.node("node-test");
        assert_eq!(node.intent, "blocked");
        assert_eq!(node.execution, "idle");
        assert_eq!(node.current_attempt_id, None);
        assert_eq!(
            node.metadata_json["terminal_attempt_retry_reason"],
            "worker_stream_agent_finished_without_terminal_event"
        );
        assert_eq!(
            node.metadata_json["terminal_attempt_retry_count"],
            DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES + 1
        );
        assert_eq!(
            node.metadata_json["worker_report_supervisor_tick_status"],
            "orphan_retry_exhausted"
        );
        assert_eq!(
            node.metadata_json["worker_stream_orphan_retry_reason"],
            "worker_stream_agent_finished_without_terminal_event"
        );
        assert_eq!(
            node.metadata_json["worker_stream_orphan_retry_exhausted"],
            true
        );
        assert_eq!(
            node.metadata_json["worker_stream_orphan_retry_count"],
            DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES + 1
        );
        assert_eq!(
            node.metadata_json["worker_stream_orphan_retry_max_retries"],
            DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES
        );
        let attempt = store
            .attempts()
            .into_iter()
            .find(|attempt| attempt.id == "attempt-test")
            .unwrap();
        assert_eq!(attempt.status, "blocked");
        assert_eq!(
            attempt.adjudication_reason.as_deref(),
            Some("worker_stream_agent_finished_without_terminal_event")
        );
        assert!(store.outbox().is_empty());
        let events = store.plan_events();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event_type, "worker_stream_orphan_retry_exhausted");
        assert_eq!(
            events[0].payload_json["retry_reason"],
            "worker_stream_agent_finished_without_terminal_event"
        );
        assert_eq!(events[0].payload_json["retry_exhausted"], true);
        assert_eq!(
            events[0].payload_json["retry_count"],
            DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES + 1
        );
        assert_eq!(
            events[0].payload_json["max_retries"],
            DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES
        );
    }

    #[tokio::test]
    async fn supervisor_tick_handler_releases_generic_tick_until_full_runtime() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_plan(plan());
        let handler = supervisor_tick_handler(Arc::clone(&store));
        let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
        item.plan_id = Some("plan-test".to_string());
        item.payload_json = json!({
            "workspace_id": "workspace-test",
            "plan_id": "plan-test",
            "controller_reason": "delivery_contract_regeneration_requested"
        });

        let outcome = handler.handle(item).await.unwrap();

        assert_eq!(
            outcome,
            WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("supervisor_tick_requires_full_runtime".to_string())
            }
        );
        assert!(store.outbox().is_empty());
    }

    #[tokio::test]
    async fn workspace_outbox_worker_marks_registered_handler_completed() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-complete", "known"));
        let worker = worker(
            Arc::clone(&store),
            HashMap::from([("known".to_string(), handler(HandlerBehavior::Complete))]),
        );

        let report = worker.run_once().await.unwrap();

        assert_eq!(
            report,
            WorkspacePlanOutboxRunReport {
                claimed: 1,
                completed: 1,
                ..Default::default()
            }
        );
        let item = store.get("job-complete");
        assert_eq!(item.status, "completed");
        assert!(item.processed_at.is_some());
        assert_eq!(item.attempt_count, 1);
    }

    #[tokio::test]
    async fn workspace_outbox_worker_fails_missing_handler_without_dropping_job() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-missing", "unknown"));
        let worker = worker(Arc::clone(&store), HashMap::new());

        let report = worker.run_once().await.unwrap();

        assert_eq!(
            report,
            WorkspacePlanOutboxRunReport {
                claimed: 1,
                failed: 1,
                missing_handler: 1,
                ..Default::default()
            }
        );
        let item = store.get("job-missing");
        assert_eq!(item.status, "failed");
        assert_eq!(
            item.last_error.as_deref(),
            Some("no handler for event_type=unknown")
        );
        assert_eq!(item.attempt_count, 1);
    }

    #[tokio::test]
    async fn workspace_outbox_worker_release_outcome_returns_attempt_budget() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-release", "known"));
        let worker = worker(
            Arc::clone(&store),
            HashMap::from([("known".to_string(), handler(HandlerBehavior::Release))]),
        );

        let report = worker.run_once().await.unwrap();

        assert_eq!(
            report,
            WorkspacePlanOutboxRunReport {
                claimed: 1,
                released: 1,
                ..Default::default()
            }
        );
        let item = store.get("job-release");
        assert_eq!(item.status, "pending");
        assert_eq!(item.last_error.as_deref(), Some("shutdown"));
        assert_eq!(item.attempt_count, 0);
    }

    #[tokio::test]
    async fn workspace_outbox_worker_failed_handler_marks_retryable_failure() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-fail", "known"));
        let worker = worker(
            Arc::clone(&store),
            HashMap::from([("known".to_string(), handler(HandlerBehavior::Fail))]),
        );

        let report = worker.run_once().await.unwrap();

        assert_eq!(
            report,
            WorkspacePlanOutboxRunReport {
                claimed: 1,
                failed: 1,
                ..Default::default()
            }
        );
        let item = store.get("job-fail");
        assert_eq!(item.status, "failed");
        assert_eq!(
            item.last_error.as_deref(),
            Some("storage error: handler boom")
        );
        assert_eq!(item.attempt_count, 1);
    }

    #[tokio::test]
    async fn workspace_outbox_loop_refuses_autostart_without_handlers() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-safe", "unknown"));
        let worker = Arc::new(WorkspacePlanOutboxWorker::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
            WorkspacePlanOutboxWorkerConfig {
                autostart: true,
                production_ready: true,
                ..WorkspacePlanOutboxWorkerConfig::default()
            },
            HashMap::new(),
        ));

        let runtime = worker.spawn_if_enabled();

        assert!(runtime.is_none());
        let item = store.get("job-safe");
        assert_eq!(item.status, "pending");
        assert_eq!(item.attempt_count, 0);
    }

    #[tokio::test]
    async fn workspace_outbox_loop_refuses_partial_production_handlers() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-safe", HANDOFF_RESUME_EVENT));
        let worker = Arc::new(WorkspacePlanOutboxWorker::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
            WorkspacePlanOutboxWorkerConfig {
                autostart: true,
                production_ready: true,
                ..WorkspacePlanOutboxWorkerConfig::default()
            },
            HashMap::from([(
                HANDOFF_RESUME_EVENT.to_string(),
                handler(HandlerBehavior::Complete),
            )]),
        ));

        let runtime = worker.spawn_if_enabled();

        assert!(runtime.is_none());
        let item = store.get("job-safe");
        assert_eq!(item.status, "pending");
        assert_eq!(item.attempt_count, 0);
    }

    #[tokio::test]
    async fn workspace_outbox_loop_refuses_autostart_without_production_ready_gate() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-safe", "known"));
        let mut handlers = required_handler_event_types()
            .into_iter()
            .map(|event_type| (event_type.to_string(), handler(HandlerBehavior::Complete)))
            .collect::<WorkspacePlanOutboxHandlers>();
        handlers.insert("known".to_string(), handler(HandlerBehavior::Complete));
        let worker = Arc::new(WorkspacePlanOutboxWorker::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
            WorkspacePlanOutboxWorkerConfig {
                autostart: true,
                production_ready: false,
                ..WorkspacePlanOutboxWorkerConfig::default()
            },
            handlers,
        ));

        let runtime = worker.spawn_if_enabled();

        assert!(runtime.is_none());
        let item = store.get("job-safe");
        assert_eq!(item.status, "pending");
        assert_eq!(item.attempt_count, 0);
    }

    #[tokio::test]
    async fn workspace_outbox_loop_polls_until_stopped_when_handlers_exist() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-loop", "known"));
        let mut handlers = required_handler_event_types()
            .into_iter()
            .map(|event_type| (event_type.to_string(), handler(HandlerBehavior::Complete)))
            .collect::<WorkspacePlanOutboxHandlers>();
        handlers.insert("known".to_string(), handler(HandlerBehavior::Complete));
        let worker = Arc::new(WorkspacePlanOutboxWorker::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
            WorkspacePlanOutboxWorkerConfig {
                worker_id: "worker-test".to_string(),
                batch_size: 10,
                lease_seconds: 60,
                poll_interval_millis: 5,
                autostart: true,
                production_ready: true,
            },
            handlers,
        ));
        let runtime = worker.spawn_if_enabled().expect("runtime should start");

        for _ in 0..20 {
            if store.get("job-loop").status == "completed" {
                runtime.shutdown().await;
                let item = store.get("job-loop");
                assert_eq!(item.status, "completed");
                assert_eq!(item.attempt_count, 1);
                return;
            }
            sleep(tokio::time::Duration::from_millis(5)).await;
        }
        runtime.shutdown().await;
        panic!("worker loop did not complete the job");
    }
}
