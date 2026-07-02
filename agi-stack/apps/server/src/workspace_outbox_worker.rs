//! Server-only Workspace Plan outbox worker foundation.
//!
//! The portable core stays out of this module: it owns no Tokio, SQLx, or
//! Postgres contracts. This file is the strangler-side host shell that can claim
//! Python-shaped `workspace_plan_outbox` rows and dispatch them to event
//! handlers once each P6 runtime slice is migrated.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use agistack_adapters_postgres::{
    PgWorkspaceRepository, WorkspacePipelineRunRecord, WorkspacePipelineStageRunRecord,
    WorkspacePlanEventRecord, WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord,
    WorkspacePlanRecord, WorkspaceRecord, WorkspaceTaskRecord, WorkspaceTaskSessionAttemptRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use serde_json::{json, Map, Value};
use tokio::task::JoinHandle;
use tokio::time::{sleep, Duration};

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
const TASK_ROLE: &str = "task_role";
const GOAL_ROOT_TASK_ROLE: &str = "goal_root";
const REMEDIATION_STATUS: &str = "remediation_status";
const REMEDIATION_SUMMARY: &str = "remediation_summary";
const WORKER_LAUNCH_MAX_ACTIVE_ENV: &str = "WORKSPACE_WORKER_LAUNCH_MAX_ACTIVE";
const WORKER_LAUNCH_DEFER_SECONDS_ENV: &str = "WORKSPACE_WORKER_LAUNCH_DEFER_SECONDS";
const WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS_ENV: &str =
    "WORKSPACE_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS";
const WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY_ENV: &str =
    "AGISTACK_WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY";
const PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV: &str = "WORKSPACE_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES";
const AWAITING_LEADER_ADJUDICATION_STATUS: &str = "awaiting_leader_adjudication";
const DEFAULT_WORKER_LAUNCH_MAX_ACTIVE: i64 = 4;
const DEFAULT_WORKER_LAUNCH_DEFER_SECONDS: i64 = 20;
const DEFAULT_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS: i64 = 300;
const DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES: i64 = 3;
const WORKER_LAUNCHABLE_ATTEMPT_STATUSES: [&str; 2] = ["pending", "running"];
const ACCEPTED_ATTEMPT_STATUS: &str = "accepted";
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

#[cfg(test)]
pub(crate) fn workspace_plan_outbox_handlers(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
) -> WorkspacePlanOutboxHandlers {
    workspace_plan_outbox_handlers_with_stage_runner(dispatch_store, None)
}

pub(crate) fn workspace_plan_outbox_handlers_with_stage_runner(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
) -> WorkspacePlanOutboxHandlers {
    let handoff = Arc::new(DurableHandoffResumeHandler::new(Arc::clone(
        &dispatch_store,
    )));
    let worker_launch = Arc::new(WorkerLaunchAdmissionHandler::new(Arc::clone(
        &dispatch_store,
    )));
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
        node.handoff_package_json = Some(handoff.clone());
        node.current_attempt_id = Some(attempt.id.clone());
        node.assignee_agent_id = Some(worker_agent_id.to_string());
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
        }
    }
}

pub(crate) struct WorkerLaunchAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
    config: WorkerLaunchAdmissionConfig,
}

impl WorkerLaunchAdmissionHandler {
    pub(crate) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self {
            store,
            config: WorkerLaunchAdmissionConfig::from_env(),
        }
    }

    #[cfg(test)]
    fn with_config(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self { store, config }
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

        let now = Utc::now();
        task_metadata.insert("launch_state".to_string(), json!("runtime_admitted"));
        task_metadata.insert(
            "worker_launch_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        task_metadata.insert(
            "worker_launch_admitted_by".to_string(),
            json!(leader_agent_id),
        );
        task_metadata.insert(
            "current_attempt_worker_agent_id".to_string(),
            json!(worker_agent_id),
        );
        task_metadata.insert(CURRENT_ATTEMPT_WORKER_BINDING_ID.to_string(), Value::Null);
        if let Some(attempt_id) = attempt_id.as_deref() {
            task_metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt_id));
        }
        task_metadata.insert(
            "execution_state".to_string(),
            json!({
                "phase": "in_progress",
                "last_agent_reason": "workspace_plan.worker_launch.admitted",
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
            now,
        )
        .await?;

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

impl WorkerLaunchAdmissionHandler {
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
        metadata.insert("launch_state".to_string(), json!("runtime_admitted"));
        metadata.insert(
            "worker_launch_admitted_at".to_string(),
            json!(now.to_rfc3339()),
        );
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;
        Ok(())
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
        let contract = pipeline_contract_foundation(&workspace);
        let source_publish_failure =
            drone_source_publish_failure(&contract, &workspace, &node, attempt_id.as_deref());
        if !contract.can_create_sandbox_native_run() && source_publish_failure.is_none() {
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
                &pipeline_contract_metadata(&contract, source_publish_failure.as_ref()),
                now,
            )
            .await?;
        let run_metadata = pipeline_run_metadata(&reason, source_publish_failure.as_ref());
        let run = WorkspacePipelineRunRecord {
            id: generate_uuid_v4(),
            contract_id,
            workspace_id: workspace_id.clone(),
            plan_id: Some(plan_id.clone()),
            node_id: Some(node_id.clone()),
            attempt_id: attempt_id.clone(),
            commit_ref: node_expected_commit_ref(&node),
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

        if let Some(source_publish_failure) = source_publish_failure {
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

fn source_publish_stage_metadata(failure: &DroneSourcePublishFailure) -> Map<String, Value> {
    let mut metadata = Map::new();
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
    source_publish_failure: Option<&DroneSourcePublishFailure>,
) -> Value {
    source_publish_failure.map_or_else(
        || contract.metadata_json.clone(),
        |failure| {
            let mut metadata = object_or_empty(contract.metadata_json.clone());
            metadata.extend(failure.metadata.clone());
            Value::Object(metadata)
        },
    )
}

fn pipeline_run_metadata(
    reason: &str,
    source_publish_failure: Option<&DroneSourcePublishFailure>,
) -> Value {
    let mut metadata = Map::new();
    metadata.insert("reason".to_string(), json!(reason));
    if let Some(failure) = source_publish_failure {
        metadata.extend(failure.metadata.clone());
    }
    Value::Object(metadata)
}

fn merge_object_values(left: &Value, right: &Value) -> Value {
    let mut merged = object_or_empty(left.clone());
    merged.extend(object_or_empty(right.clone()));
    Value::Object(merged)
}

fn drone_source_publish_failure(
    contract: &PipelineContractFoundation,
    workspace: &WorkspaceRecord,
    node: &WorkspacePlanNodeRecord,
    attempt_id: Option<&str>,
) -> Option<DroneSourcePublishFailure> {
    if contract.provider != DRONE_PROVIDER || attempt_id.is_none() {
        return None;
    }
    let commit_ref = node_expected_commit_ref(node)?;
    let provider_config = object_or_empty(contract.provider_config_json.clone());
    let workspace_metadata = object_or_empty(workspace.metadata_json.clone());
    let source_control = drone_source_control_config(&workspace_metadata, &provider_config);
    let branch = drone_source_branch(&source_control, &provider_config);

    if host_code_root_from_workspace(&workspace.metadata_json).is_none() {
        let reason = "host_code_root is not available for Drone source publish".to_string();
        return Some(DroneSourcePublishFailure {
            metadata: source_publish_metadata(
                "failed",
                Some(&reason),
                Some(&commit_ref),
                None,
                Some(&commit_ref),
                None,
            ),
            reason,
        });
    }

    if branch.is_none() {
        let reason =
            "source_control.default_branch or delivery_cicd.drone.branch is required".to_string();
        return Some(DroneSourcePublishFailure {
            metadata: source_publish_metadata(
                "failed",
                Some(&reason),
                Some(&commit_ref),
                None,
                Some(&commit_ref),
                None,
            ),
            reason,
        });
    }

    None
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
            let changed_accepted = self
                .reconcile_accepted_terminal_attempt_nodes(&workspace_id, &plan_id)
                .await?;
            let changed_terminal = self
                .reconcile_terminal_attempt_nodes(&item, &payload, &workspace_id, &plan_id)
                .await?;
            let changed_reported = self
                .reconcile_reported_attempt_nodes(&workspace_id, &plan_id)
                .await?;
            if changed_worktree_failed
                + changed_missing
                + changed_accepted
                + changed_terminal
                + changed_reported
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
            let Some(attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            if attempt.status.trim().to_ascii_lowercase() != ACCEPTED_ATTEMPT_STATUS {
                continue;
            }
            if accepted_projection_already_complete(&node, &attempt) {
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
        Ok(None)
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

fn attempt_has_candidate_output(attempt: &WorkspaceTaskSessionAttemptRecord) -> bool {
    attempt
        .candidate_summary
        .as_deref()
        .is_some_and(|summary| !summary.trim().is_empty())
        || !attempt.candidate_artifacts_json.is_empty()
        || !attempt.candidate_verifications_json.is_empty()
}

fn accepted_projection_already_complete(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
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
    use std::collections::HashSet;
    use std::sync::Mutex;

    use agistack_core::ports::CoreError;
    use chrono::{Duration, TimeZone};
    use serde_json::json;

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

    #[derive(Default)]
    struct FakeWorkspacePlanDispatchStore {
        workspaces: Mutex<HashMap<String, WorkspaceRecord>>,
        tasks: Mutex<HashMap<String, WorkspaceTaskRecord>>,
        plans: Mutex<HashMap<String, WorkspacePlanRecord>>,
        nodes: Mutex<HashMap<String, WorkspacePlanNodeRecord>>,
        attempts: Mutex<HashMap<String, WorkspaceTaskSessionAttemptRecord>>,
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
    async fn worker_launch_handler_marks_dispatched_node_running_and_task_admitted() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
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
        assert_eq!(task.metadata_json["launch_state"], "runtime_admitted");
        assert_eq!(
            task.metadata_json["current_attempt_worker_agent_id"],
            "agent-worker"
        );
        assert!(task.metadata_json["worker_launch_admitted_at"].is_string());
        let node = store.node("node-test");
        assert_eq!(node.execution, "running");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-test"));
        assert_eq!(node.metadata_json["launch_state"], "runtime_admitted");
        assert!(store.outbox().is_empty());
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
    async fn supervisor_tick_handler_releases_accepted_attempt_that_requires_real_worktree_merge() {
        let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
        store.insert_workspace(workspace_with_code_root("/workspace/app"));
        store.insert_task(task_with_plan_metadata());
        store.insert_plan(plan());
        let mut node = plan_node();
        node.intent = "in_progress".to_string();
        node.execution = "running".to_string();
        node.current_attempt_id = Some("attempt-accepted".to_string());
        node.feature_checkpoint_json = Some(json!({
            "worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
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
        attempt.leader_feedback = Some("accepted in isolated worktree".to_string());
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
        let task = store.task("task-test");
        assert_eq!(node.intent, "in_progress");
        assert_eq!(node.execution, "running");
        assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
        assert_eq!(task.status, "todo");
        assert!(task.metadata_json.get("durable_plan_verdict").is_none());
        assert!(store.plan_events().is_empty());
        assert!(store.outbox().is_empty());
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
