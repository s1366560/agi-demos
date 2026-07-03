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
    BlackboardOutboxRecord, PgWorkspaceRepository, WorkspaceAgentRecord, WorkspaceMessageRecord,
    WorkspacePipelineRunRecord, WorkspacePipelineStageRunRecord, WorkspacePlanEventRecord,
    WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord, WorkspacePlanRecord, WorkspaceRecord,
    WorkspaceTaskRecord, WorkspaceTaskSessionAttemptRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::ports::{CoreError, CoreResult, EventStream, StreamEntry};
use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, SecondsFormat, Utc};
use serde_json::{json, Map, Value};
use serde_yaml_ng::Value as YamlValue;
use sha2::{Digest, Sha256};
use tokio::io::AsyncWriteExt;
use tokio::task::JoinHandle;
use tokio::time::{sleep, Duration};
use uuid::Uuid;

use crate::sandbox_api::{ExecuteToolResponse, ProjectSandboxService};

mod agent_mention;

#[cfg(test)]
pub(crate) use agent_mention::{
    workspace_agent_conversation_id, WorkspaceAgentMentionRuntimeInput,
};
pub(crate) use agent_mention::{
    workspace_agent_mention_runtime_from_env, WorkspaceAgentMentionBindingHandler,
    WorkspaceAgentMentionRuntime,
};

pub(crate) type SharedWorkspacePlanOutboxWorker = Arc<WorkspacePlanOutboxWorker>;
pub(crate) type WorkspacePlanOutboxHandlers = HashMap<String, Arc<dyn WorkspacePlanOutboxHandler>>;

const SUPERVISOR_TICK_EVENT: &str = "supervisor_tick";
const WORKER_LAUNCH_EVENT: &str = "worker_launch";
const HANDOFF_RESUME_EVENT: &str = "handoff_resume";
const ATTEMPT_RETRY_EVENT: &str = "attempt_retry";
const PIPELINE_RUN_REQUESTED_EVENT: &str = "pipeline_run_requested";
const WORKSPACE_AGENT_MENTION_EVENT: &str = "workspace_agent_mention";
const WORKSPACE_AGENT_MENTION_PENDING_RUNTIME_STATUS: &str = "pending_runtime";
const WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS: &str = "runtime_bound";
#[allow(dead_code)]
const WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS: &str = "runtime_response_ready";
#[allow(dead_code)]
const WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS: &str = "runtime_error_ready";
const WORKSPACE_MESSAGE_CREATED_EVENT: &str = "workspace_message_created";
const WORKSPACE_MENTION_RUNTIME_ENABLED_ENV: &str = "AGISTACK_WORKSPACE_MENTION_RUNTIME_ENABLED";
const MAX_WORKSPACE_AGENT_MENTION_CHAIN_DEPTH: i64 = 3;
const WORKSPACE_AGENT_CHAIN_MENTION_SOURCE: &str = "workspace_agent_chain_mention";
const WORKSPACE_AGENT_CHAIN_MENTION_STAGE: &str = "agent_chain_mention";
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
const SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION: &str = "mark_blocked_human";
const SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_REASON: &str =
    "supervisor_decision_mark_blocked_human";
const SUPERVISOR_BLOCKED_HUMAN_VERDICT: &str = "blocked_human_required";
const SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION: &str = "request_pipeline";
const SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON: &str = "supervisor_decision_request_pipeline";
const SUPERVISOR_DECISION_WAIT_PIPELINE_ACTION: &str = "wait_pipeline";
const SUPERVISOR_DECISION_WAIT_PIPELINE_REASON: &str = "supervisor_decision_wait_pipeline";
const SUPERVISOR_DECISION_NOOP_ACTION: &str = "noop";
const SUPERVISOR_DECISION_NOOP_REASON: &str = "supervisor_decision_noop";
const SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION: &str = "create_repair_node";
const SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON: &str =
    "supervisor_decision_create_repair_node";
const SUPERVISOR_DECISION_REPLAN_NODE_ACTION: &str = "replan_node";
const SUPERVISOR_DECISION_REPLAN_NODE_REASON: &str = "supervisor_decision_replan_node";
const SUPERVISOR_REPLAN_REQUESTED_VERDICT: &str = "replan_requested";
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

mod outbox_core;
use outbox_core::{
    bool_env, i64_env, merge_metadata_patch, object_or_empty, positive_i64_env, string_from_map,
    string_from_value_object,
};
#[cfg(test)]
use outbox_core::{
    missing_required_handler_event_types, required_handler_event_types,
    WorkspacePlanOutboxRunReport, WorkspacePlanOutboxStore,
};
pub(crate) use outbox_core::{
    PgWorkspacePlanOutboxStore, WorkspacePipelineStageRunner, WorkspacePlanDispatchStore,
    WorkspacePlanOutboxHandler, WorkspacePlanOutboxHandlerOutcome, WorkspacePlanOutboxWorker,
    WorkspacePlanOutboxWorkerConfig,
};

mod handoff;
use handoff::DurableHandoffResumeHandler;

mod worker_stream_watchdog;

mod supervisor;
use supervisor::SupervisorTickAdmissionHandler;

mod pipeline_run;
use pipeline_run::{
    build_worker_report_payload, compact_git_error, compact_text, current_worktree_dirty_signature,
    integrate_accepted_attempt_worktree_with_git, is_stale_terminal_worker_report, run_git_command,
    short_git_head, worker_execution_state, PipelineRunAdmissionHandler,
};
pub(crate) use pipeline_run::{
    PipelineContractFoundation, PipelineStageResult, PipelineStageSpec,
    ProjectSandboxPipelineStageRunner,
};

mod worker_launch;
#[cfg(test)]
use worker_launch::WorkerStreamTerminalPersistence;
#[cfg(test)]
pub(crate) use worker_launch::{worker_conversation_id, WorkerLaunchAdmissionConfig};
pub(crate) use worker_launch::{
    worker_launch_event_stream_source, WorkerLaunchAdmissionHandler, WorkerLaunchEventStream,
    WorkerLaunchRuntimeStateStore,
};
use worker_launch::{worker_launch_outbox, NoopWorkerLaunchEventStream, WorkerReportPayload};

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
        None,
    )
}

pub(crate) fn workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
    worker_launch_state: Option<Arc<dyn WorkerLaunchRuntimeStateStore>>,
    worker_stream_events: Option<Arc<dyn WorkerLaunchEventStream>>,
    workspace_mention_runtime: Option<Arc<dyn WorkspaceAgentMentionRuntime>>,
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
    let workspace_agent_mention = Arc::new(match workspace_mention_runtime {
        Some(runtime) => {
            WorkspaceAgentMentionBindingHandler::with_runtime(Arc::clone(&dispatch_store), runtime)
        }
        None => WorkspaceAgentMentionBindingHandler::new(Arc::clone(&dispatch_store)),
    });
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
        (
            WORKSPACE_AGENT_MENTION_EVENT.to_string(),
            workspace_agent_mention as Arc<dyn WorkspacePlanOutboxHandler>,
        ),
    ])
}

fn workspace_message_event_payload(message: &WorkspaceMessageRecord) -> Value {
    json!({
        "id": &message.id,
        "workspace_id": &message.workspace_id,
        "sender_id": &message.sender_id,
        "sender_type": &message.sender_type,
        "content": &message.content,
        "mentions": &message.mentions_json,
        "parent_message_id": &message.parent_message_id,
        "metadata": &message.metadata_json,
        "created_at": workspace_event_iso(message.created_at),
    })
}

fn workspace_event_iso(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Millis, true)
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
    let metadata = object_or_empty(node.metadata_json.clone());
    if supervisor_noop_metadata_present(&metadata) {
        return false;
    }
    if node_has_pipeline_gate_in_flight(node, AWAITING_LEADER_ADJUDICATION_STATUS) {
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

fn supervisor_blocked_human_metadata_present(metadata: &Map<String, Value>) -> bool {
    if metadata_string(metadata.get("last_verification_judge_verdict")).as_deref()
        == Some(SUPERVISOR_BLOCKED_HUMAN_VERDICT)
    {
        return true;
    }
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION)
        && supervisor_decision_allows_human_block(metadata)
}

fn supervisor_decision_allows_human_block(metadata: &Map<String, Value>) -> bool {
    if supervisor_disposition_event_payload(metadata)
        .get("human_required")
        .and_then(Value::as_bool)
        == Some(true)
    {
        return true;
    }
    let Some(Value::Array(items)) = metadata.get("last_supervisor_decision_feedback_items") else {
        return false;
    };
    items.iter().any(|item| {
        let Some(item) = item.as_object() else {
            return false;
        };
        metadata_string(item.get("target_layer")).as_deref() == Some("human")
            || metadata_string(item.get("recommended_action")).as_deref() == Some("escalate_human")
            || metadata_string(item.get("next_action")).as_deref() == Some("human_required")
    })
}

fn supervisor_request_pipeline_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION)
}

fn supervisor_request_pipeline_projection_complete(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("supervisor_pipeline_outbox_id")).is_some()
        && matches!(
            metadata_string(metadata.get("pipeline_gate_status"))
                .or_else(|| metadata_string(metadata.get("pipeline_status")))
                .as_deref(),
            Some("requested" | "running" | "success" | "failed")
        )
}

fn supervisor_request_pipeline_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested platform pipeline".to_string())
}

fn supervisor_wait_pipeline_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_WAIT_PIPELINE_ACTION)
}

fn supervisor_wait_pipeline_projection_complete(metadata: &Map<String, Value>) -> bool {
    let status = metadata_string(metadata.get("pipeline_gate_status"))
        .or_else(|| metadata_string(metadata.get("pipeline_status")))
        .unwrap_or_default()
        .to_ascii_lowercase();
    if matches!(
        status.as_str(),
        "success" | "failed" | "failure" | "error" | "skipped" | "suspended"
    ) {
        return true;
    }
    metadata_string(metadata.get("supervisor_wait_pipeline_reconciled_at")).is_some()
        && matches!(status.as_str(), "requested" | "running" | "processing")
}

fn supervisor_wait_pipeline_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor waiting for platform pipeline".to_string())
}

fn supervisor_noop_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_NOOP_ACTION)
}

fn supervisor_noop_projection_complete(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("supervisor_noop_reconciled_at")).is_some()
}

fn supervisor_noop_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor chose no state transition".to_string())
}

fn metadata_positive_i64(value: Option<&Value>) -> i64 {
    value
        .and_then(Value::as_i64)
        .or_else(|| {
            value
                .and_then(Value::as_u64)
                .and_then(|value| i64::try_from(value).ok())
        })
        .or_else(|| {
            value
                .and_then(Value::as_str)
                .and_then(|raw| raw.trim().parse::<i64>().ok())
        })
        .filter(|value| *value > 0)
        .unwrap_or_default()
}

fn supervisor_pipeline_source_commit_ref(metadata: &Map<String, Value>) -> Option<String> {
    metadata_string(metadata.get("source_publish_source_commit_ref"))
        .or_else(|| metadata_string(metadata.get("verified_commit_ref")))
        .or_else(|| {
            supervisor_disposition_event_payload(metadata)
                .get("source_commit_ref")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
        })
}

fn supervisor_create_repair_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION)
}

fn supervisor_create_repair_projection_complete(
    node: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
    nodes_by_id: &HashMap<String, WorkspacePlanNodeRecord>,
) -> bool {
    let Some(repair_node_id) = metadata_string(metadata.get("supervisor_repair_node_id"))
        .or_else(|| metadata_string(metadata.get("blocked_by_repair_node_id")))
    else {
        return false;
    };
    node.current_attempt_id.is_none()
        && node.intent == "todo"
        && node.execution == "idle"
        && node.depends_on_json.iter().any(|id| id == &repair_node_id)
        && nodes_by_id.contains_key(&repair_node_id)
        && metadata_string(metadata.get("workspace_task_projection_status")).as_deref()
            == Some(SUPERVISOR_REPLAN_REQUESTED_VERDICT)
}

fn existing_repair_node_id_for_original(
    nodes_by_id: &HashMap<String, WorkspacePlanNodeRecord>,
    original_node_id: &str,
) -> Option<String> {
    let mut ids = nodes_by_id
        .values()
        .filter_map(|node| {
            let metadata = object_or_empty(node.metadata_json.clone());
            (metadata_string(metadata.get("repair_for_node_id")).as_deref()
                == Some(original_node_id))
            .then_some(node.id.clone())
        })
        .collect::<Vec<_>>();
    ids.sort();
    ids.into_iter().next()
}

fn supervisor_create_repair_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_judge_required_next_action")))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested repair node".to_string())
}

fn clear_supervisor_create_repair_node_metadata(metadata: &mut Map<String, Value>) {
    for key in [
        "retry_count",
        "retry_last_reason",
        "retry_not_before",
        "terminal_attempt_reconciled_at",
        "terminal_attempt_retry_count",
        "terminal_attempt_retry_reason",
        "terminal_attempt_status",
        "terminal_attempt_superseded_attempt_id",
        "terminal_attempt_superseded_reason",
        "terminal_attempt_superseded_status",
    ] {
        metadata.remove(key);
    }
    clear_attempt_retry_worker_stream_state(metadata);
}

fn generated_repair_node_id() -> String {
    let token = generate_uuid_v4()
        .chars()
        .filter(|ch| *ch != '-')
        .take(12)
        .collect::<String>();
    format!("node-{token}")
}

fn supervisor_repair_plan_node(
    original: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
    repair_node_id: &str,
    summary: &str,
    evidence_refs: &[String],
    previous_attempt_id: Option<&str>,
    now: DateTime<Utc>,
) -> WorkspacePlanNodeRecord {
    let title = supervisor_repair_title(original);
    let mut repair_metadata = Map::new();
    repair_metadata.insert(
        "generated_from_verification_failure".to_string(),
        json!(true),
    );
    repair_metadata.insert("repair_for_node_id".to_string(), json!(original.id.clone()));
    repair_metadata.insert(
        "repair_source".to_string(),
        json!("verification_judge_create_repair_node"),
    );
    repair_metadata.insert("repair_trigger".to_string(), json!("verification_failed"));
    repair_metadata.insert(
        "repair_source_iteration_phase".to_string(),
        metadata
            .get("iteration_phase")
            .cloned()
            .unwrap_or_else(|| json!("repair")),
    );
    repair_metadata.insert(
        "source_verification_judge_verdict".to_string(),
        metadata
            .get("last_verification_judge_verdict")
            .cloned()
            .unwrap_or_else(|| json!("needs_rework")),
    );
    repair_metadata.insert(
        "source_verification_judge_next_action_kind".to_string(),
        json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
    );
    repair_metadata.insert(
        "source_verification_attempt_id".to_string(),
        previous_attempt_id
            .map(|attempt_id| json!(attempt_id))
            .or_else(|| metadata.get("last_verification_attempt_id").cloned())
            .unwrap_or(Value::Null),
    );
    repair_metadata.insert(
        "repair_failure_signature".to_string(),
        json!(repair_failure_signature(metadata, original)),
    );
    repair_metadata.insert(
        "last_supervisor_decision_action".to_string(),
        json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
    );
    repair_metadata.insert(
        "last_supervisor_decision_rationale".to_string(),
        json!(summary),
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_supervisor_decision_confidence",
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_supervisor_decision_repair_brief",
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_verification_judge_repair_brief",
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_verification_feedback_items",
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_supervisor_decision_feedback_items",
    );
    if let Some(value) = metadata
        .get("last_supervisor_decision_feedback_items")
        .or_else(|| metadata.get("last_verification_feedback_items"))
        .filter(|value| !value.is_null())
    {
        repair_metadata.insert(
            "source_verification_feedback_items".to_string(),
            value.clone(),
        );
    }
    for key in ["iteration_index", "iteration_phase", "scrum_artifact"] {
        copy_optional_metadata_value(metadata, &mut repair_metadata, key);
    }
    if !evidence_refs.is_empty() {
        repair_metadata.insert(
            "verification_evidence_refs".to_string(),
            json!(evidence_refs),
        );
    }

    WorkspacePlanNodeRecord {
        id: repair_node_id.to_string(),
        plan_id: original.plan_id.clone(),
        parent_id: original.parent_id.clone(),
        kind: "task".to_string(),
        title: title.clone(),
        description: supervisor_repair_description(original, summary),
        depends_on_json: original.depends_on_json.clone(),
        inputs_schema_json: json!({}),
        outputs_schema_json: json!({}),
        acceptance_criteria_json: vec![
            json!(
                "Fresh repair evidence includes a current commit_ref, git diff summary, and verification output."
            ),
        ],
        feature_checkpoint_json: Some(json!({
            "feature_id": format!("feature-{repair_node_id}"),
            "title": title,
            "base_ref": "HEAD"
        })),
        handoff_package_json: None,
        recommended_capabilities_json: original.recommended_capabilities_json.clone(),
        preferred_agent_id: original.preferred_agent_id.clone(),
        estimated_effort_json: original.estimated_effort_json.clone(),
        priority: original.priority.max(1),
        intent: "todo".to_string(),
        execution: "idle".to_string(),
        progress_json: json!({"percent": 0, "confidence": 0.0}),
        assignee_agent_id: None,
        current_attempt_id: None,
        workspace_task_id: None,
        metadata_json: Value::Object(repair_metadata),
        created_at: now,
        updated_at: Some(now),
        completed_at: None,
    }
}

fn supervisor_repair_title(original: &WorkspacePlanNodeRecord) -> String {
    format!("Repair {}", original.title)
        .chars()
        .take(120)
        .collect()
}

fn supervisor_repair_description(original: &WorkspacePlanNodeRecord, summary: &str) -> String {
    format!(
        "Repair the blockers that prevented verification of `{}`.\n\nRepair execution constraints:\n- Perform the repair in the active attempt worktree only; do not require or attempt edits, merges, or artifact copying in the main checkout or sandbox_code_root.\n- Report only fresh evidence produced during this repair turn.\n\n{}\n\nAfter the repair is complete, the original verification node will re-run.",
        original.title, summary
    )
}

fn repair_failure_signature(
    metadata: &Map<String, Value>,
    original: &WorkspacePlanNodeRecord,
) -> String {
    for key in [
        "last_supervisor_decision_feedback_items",
        "last_verification_feedback_items",
    ] {
        let Some(Value::Array(items)) = metadata.get(key) else {
            continue;
        };
        for item in items {
            let Some(item) = item.as_object() else {
                continue;
            };
            if let Some(signature) = metadata_string(item.get("failure_signature")) {
                return signature;
            }
        }
    }
    format!("supervisor-create-repair-node:{}", original.id)
}

fn copy_optional_metadata_value(
    source: &Map<String, Value>,
    target: &mut Map<String, Value>,
    key: &str,
) {
    if let Some(value) = source.get(key).filter(|value| !value.is_null()) {
        target.insert(key.to_string(), value.clone());
    }
}

fn push_unique_string(values: &mut Vec<String>, value: String) {
    if !values.iter().any(|existing| existing == &value) {
        values.push(value);
    }
}

fn supervisor_replan_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_REPLAN_NODE_ACTION)
}

fn supervisor_replan_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested replan".to_string())
}

fn clear_supervisor_replan_node_metadata(metadata: &mut Map<String, Value>) {
    for key in [
        "candidate_artifacts",
        "candidate_verifications",
        "deploy_mode",
        "deployment_status",
        "evidence_refs",
        "execution_verifications",
        "external_id",
        "external_provider",
        "external_url",
        "current_repair_turn",
        "last_verification_attempt_id",
        "last_verification_feedback_items",
        "last_verification_hard_fail",
        "last_verification_judge_confidence",
        "last_verification_judge_failed_criteria",
        "last_verification_judge_next_action_kind",
        "last_verification_judge_rationale",
        "last_verification_judge_repair_brief",
        "last_verification_judge_required_next_action",
        "last_verification_judge_verdict",
        "last_verification_passed",
        "last_verification_ran_at",
        "last_verification_summary",
        "last_worker_report_attempt_id",
        "last_worker_report_artifacts",
        "last_worker_report_summary",
        "last_worker_report_type",
        "last_worker_report_verifications",
        "obsolete_by_verifier_feedback",
        "obsolete_feedback_items",
        "pipeline_evidence_refs",
        "pipeline_finished_at",
        "pipeline_gate_status",
        "pipeline_last_summary",
        "pipeline_request_count",
        "pipeline_requested_at",
        "pipeline_run_id",
        "pipeline_status",
        "reported_attempt_reconciled_at",
        "reported_attempt_status",
        "retry_count",
        "retry_last_reason",
        "retry_not_before",
        "source_publish_branch",
        "source_publish_commit_ref",
        "source_publish_provider",
        "source_publish_reason",
        "source_publish_source_commit_ref",
        "source_publish_status",
        "source_publish_token_env",
        "terminal_attempt_reconciled_at",
        "terminal_attempt_retry_count",
        "terminal_attempt_retry_reason",
        "terminal_attempt_status",
        "terminal_attempt_superseded_attempt_id",
        "terminal_attempt_superseded_reason",
        "terminal_attempt_superseded_status",
        "verification_evidence_refs",
        "verification_feedback_disposition",
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
    ] {
        metadata.remove(key);
    }
    clear_attempt_retry_worker_stream_state(metadata);
}

fn supervisor_blocked_human_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "human intervention required by workspace supervisor".to_string())
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

mod task_lifecycle;
use task_lifecycle::*;

#[cfg(test)]
mod tests;
