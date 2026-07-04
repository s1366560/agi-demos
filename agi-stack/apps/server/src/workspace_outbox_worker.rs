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
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use serde_json::{json, Map, Value};
use serde_yaml_ng::Value as YamlValue;
use sha2::{Digest, Sha256};
use tokio::io::AsyncWriteExt;
use tokio::task::JoinHandle;
use tokio::time::{sleep, Duration};
use uuid::Uuid;

use crate::sandbox_api::{ExecuteToolResponse, ProjectSandboxService};

mod agent_mention;
use agent_mention::WORKSPACE_AGENT_MENTION_EVENT;

#[cfg(test)]
pub(crate) use agent_mention::{
    workspace_agent_conversation_id, WorkspaceAgentMentionRuntimeInput,
};
pub(crate) use agent_mention::{
    workspace_agent_mention_runtime_from_env, WorkspaceAgentMentionBindingHandler,
    WorkspaceAgentMentionRuntime,
};
#[cfg(test)]
use agent_mention::{
    MAX_WORKSPACE_AGENT_MENTION_CHAIN_DEPTH, WORKSPACE_AGENT_CHAIN_MENTION_SOURCE,
    WORKSPACE_AGENT_CHAIN_MENTION_STAGE, WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS,
    WORKSPACE_AGENT_MENTION_PENDING_RUNTIME_STATUS, WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS,
    WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS, WORKSPACE_MESSAGE_CREATED_EVENT,
};

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
#[cfg(test)]
const WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS: usize = 700;
const WORKER_STREAM_COMPLETION_SUMMARY_CHARS: usize = 2000;
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
    WorkspacePlanOutboxRunReport,
};
pub(crate) use outbox_core::{
    WorkspacePipelineStageRunner, WorkspacePlanOutboxHandler, WorkspacePlanOutboxHandlerOutcome,
    WorkspacePlanOutboxWorker, WorkspacePlanOutboxWorkerConfig,
};

mod shared;
use shared::{
    bool_from_map, is_goal_root_task, persisted_attempt_leader_agent_id,
    recoverable_node_attempt_id, required_string, root_goal_task_id_for_progress,
    select_root_progress_child_tasks, workspace_event_iso, workspace_message_event_payload,
};

mod outbox_store;
pub(crate) use outbox_store::{
    PgWorkspacePlanOutboxStore, WorkspacePlanDispatchStore, WorkspacePlanOutboxStore,
};

mod handoff;
use handoff::DurableHandoffResumeHandler;

mod worker_stream_watchdog;

mod supervisor;
use supervisor::SupervisorTickAdmissionHandler;

mod pipeline_shared;
use pipeline_shared::{
    bool_from_map_default, merge_object_values, source_publish_dotenv_value, GitCommandOutput,
};

mod pipeline_contract;
use pipeline_contract::{
    pipeline_contract_foundation, positive_i32_from_map, PipelineContractFoundation,
};

mod pipeline_drone;
use pipeline_drone::{finish_drone_pipeline_result, run_drone_pipeline_if_configured};

mod pipeline_git;
use pipeline_git::{
    compact_git_error, current_worktree_dirty_signature, finish_drone_provider_unavailable,
    finish_drone_source_publish_failure, host_code_root_from_workspace,
    integrate_accepted_attempt_worktree_with_git, pipeline_contract_metadata,
    pipeline_run_metadata, prepare_drone_source_publish, run_git_command, short_git_head,
    source_publish_source_commit_ref, DroneSourcePublishOutcome,
};

mod pipeline_projection;
use pipeline_projection::{
    build_worker_report_payload, can_reflect_existing_pipeline_run, finish_pipeline_on_node,
    is_stale_terminal_worker_report, mark_existing_pipeline_run_running, mark_pipeline_requested,
    pipeline_completed_supervisor_tick, pipeline_completed_supervisor_tick_with_source,
    pipeline_run_matches_node_expected_commit, reflect_existing_pipeline_run_to_node,
    stale_pipeline_run_failure_metadata, worker_execution_state,
};

mod pipeline_run;
use pipeline_run::{compact_text, PipelineRunAdmissionHandler};
pub(crate) use pipeline_run::{
    PipelineStageResult, PipelineStageSpec, ProjectSandboxPipelineStageRunner,
};

mod worker_launch;
pub(crate) use worker_launch::WorkerLaunchAdmissionHandler;
#[cfg(test)]
use worker_launch::WorkerStreamTerminalPersistence;
#[cfg(test)]
pub(crate) use worker_launch::{worker_conversation_id, WorkerLaunchAdmissionConfig};
use worker_launch::{worker_launch_outbox, WorkerReportPayload};

mod worker_launch_runtime;
use worker_launch_runtime::NoopWorkerLaunchEventStream;
pub(crate) use worker_launch_runtime::{
    worker_launch_event_stream_source, WorkerLaunchEventStream, WorkerLaunchRuntimeStateStore,
};

mod worker_launch_worktree;

#[cfg(test)]
pub(crate) fn workspace_plan_outbox_handlers(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
) -> WorkspacePlanOutboxHandlers {
    workspace_plan_outbox_handlers_with_stage_runner(dispatch_store, None)
}

#[cfg(test)]
pub(crate) fn workspace_plan_outbox_handlers_with_stage_runner(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
) -> WorkspacePlanOutboxHandlers {
    workspace_plan_outbox_handlers_with_runtime_state(dispatch_store, stage_runner, None)
}

#[cfg(test)]
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

mod supervisor_reconcile;
use supervisor_reconcile::*;

mod task_lifecycle;
use task_lifecycle::*;

mod task_metadata;
use task_metadata::*;

mod task_retry;
use task_retry::*;

#[cfg(test)]
mod tests;
