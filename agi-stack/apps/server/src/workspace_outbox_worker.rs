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
#[cfg(test)]
use agent_mention::{
    workspace_agent_mention_event_stream_topic, MAX_WORKSPACE_AGENT_MENTION_CHAIN_DEPTH,
    MAX_WORKSPACE_AGENT_MENTION_STREAM_CHARS, MAX_WORKSPACE_AGENT_MENTION_STREAM_CHUNKS,
    WORKSPACE_AGENT_CHAIN_MENTION_SOURCE, WORKSPACE_AGENT_CHAIN_MENTION_STAGE,
    WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS, WORKSPACE_AGENT_MENTION_PENDING_RUNTIME_STATUS,
    WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS, WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS,
    WORKSPACE_AGENT_MENTION_TOKEN_CHUNK_EVENT, WORKSPACE_MESSAGE_CREATED_EVENT,
};
pub(crate) use agent_mention::{
    workspace_agent_mention_runtime_from_env, WorkspaceAgentMentionBindingHandler,
    WorkspaceAgentMentionRuntime,
};

pub(crate) type SharedWorkspacePlanOutboxWorker = Arc<WorkspacePlanOutboxWorker>;
pub(crate) type WorkspacePlanOutboxHandlers = HashMap<String, Arc<dyn WorkspacePlanOutboxHandler>>;

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
const WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY_ENV: &str =
    "AGISTACK_WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY";
const ACCEPTED_ATTEMPT_STATUS: &str = "accepted";
const DISPOSED_ATTEMPT_STATUS: &str = "disposed";
const REJECTED_ATTEMPT_STATUS: &str = "rejected";

mod outbox_core;
use outbox_core::{
    bool_env, i64_env, merge_metadata_patch, object_or_empty, positive_i64_env, string_from_map,
    string_from_value_object, ATTEMPT_RETRY_EVENT, HANDOFF_RESUME_EVENT,
    PIPELINE_RUN_REQUESTED_EVENT, SUPERVISOR_TICK_EVENT, WORKER_LAUNCH_EVENT,
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
use supervisor::{
    SupervisorTickAdmissionHandler, AWAITING_LEADER_ADJUDICATION_STATUS,
    DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES, PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV,
    SUPERVISOR_BLOCKED_HUMAN_VERDICT, SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION,
    SUPERVISOR_DECISION_DISPOSE_NODE_ACTION, SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION,
    SUPERVISOR_DECISION_NOOP_ACTION, SUPERVISOR_DECISION_REPLAN_NODE_ACTION,
    SUPERVISOR_DECISION_REPLAN_NODE_REASON, SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION,
    SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON, SUPERVISOR_DECISION_WAIT_PIPELINE_ACTION,
    SUPERVISOR_DISPOSED_NODE_DISPOSITION, SUPERVISOR_REPLAN_REQUESTED_VERDICT,
};
#[cfg(test)]
use supervisor::{
    SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON, SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_REASON,
    SUPERVISOR_DECISION_NOOP_REASON, SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON,
    SUPERVISOR_DECISION_WAIT_PIPELINE_REASON,
};

mod pipeline_shared;
use pipeline_shared::{
    bool_from_map_default, merge_object_values, source_publish_dotenv_value, GitCommandOutput,
    DEFAULT_DRONE_DEPLOY_MODE, DEFAULT_DRONE_DEPLOY_STAGE, DEFAULT_PIPELINE_TIMEOUT_SECONDS,
    DEFAULT_PREVIEW_PORT, DRONE_CLI_JSON_TEMPLATE, DRONE_DOCKER_DEPLOY_VALIDATION, DRONE_PROVIDER,
    DRONE_SERVER_ENV, DRONE_SERVER_URL_ENV, DRONE_TOKEN_ENV, DRONE_YAML_PREFLIGHT_VALIDATION,
    PIPELINE_EXIT_MARKER, PLANNING_CONTRACT_SOURCE, SANDBOX_NATIVE_PROVIDER,
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

#[cfg(test)]
pub(crate) fn workspace_plan_outbox_handlers_with_runtime_state_and_event_stream(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
    worker_launch_state: Option<Arc<dyn WorkerLaunchRuntimeStateStore>>,
    worker_stream_events: Option<Arc<dyn WorkerLaunchEventStream>>,
    workspace_mention_runtime: Option<Arc<dyn WorkspaceAgentMentionRuntime>>,
) -> WorkspacePlanOutboxHandlers {
    workspace_plan_outbox_handlers_with_runtime_state_and_streams(
        dispatch_store,
        stage_runner,
        worker_launch_state,
        worker_stream_events,
        workspace_mention_runtime,
        None,
    )
}

pub(crate) fn workspace_plan_outbox_handlers_with_runtime_state_and_streams(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
    worker_launch_state: Option<Arc<dyn WorkerLaunchRuntimeStateStore>>,
    worker_stream_events: Option<Arc<dyn WorkerLaunchEventStream>>,
    workspace_mention_runtime: Option<Arc<dyn WorkspaceAgentMentionRuntime>>,
    workspace_event_stream: Option<Arc<dyn EventStream>>,
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
    let workspace_agent_mention =
        Arc::new(match (workspace_mention_runtime, workspace_event_stream) {
            (runtime, Some(event_stream)) => {
                WorkspaceAgentMentionBindingHandler::with_runtime_and_event_stream(
                    Arc::clone(&dispatch_store),
                    runtime,
                    event_stream,
                )
            }
            (Some(runtime), None) => WorkspaceAgentMentionBindingHandler::with_runtime(
                Arc::clone(&dispatch_store),
                runtime,
            ),
            (None, None) => WorkspaceAgentMentionBindingHandler::new(Arc::clone(&dispatch_store)),
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
