//! Server-only Workspace Plan outbox worker foundation.
//!
//! The portable core stays out of this module: it owns no Tokio, SQLx, or
//! Postgres contracts. This file is the strangler-side host shell that can claim
//! Python-shaped `workspace_plan_outbox` rows and dispatch them to event
//! handlers once each P6 runtime slice is migrated.

use std::collections::HashMap;
use std::sync::Arc;

use agistack_adapters_postgres::{
    PgWorkspaceRepository, WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord, WorkspacePlanRecord,
    WorkspaceTaskRecord, WorkspaceTaskSessionAttemptRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use serde_json::{json, Map, Value};
use tokio::task::JoinHandle;
use tokio::time::{sleep, Duration};

pub(crate) type SharedWorkspacePlanOutboxWorker = Arc<WorkspacePlanOutboxWorker>;
pub(crate) type WorkspacePlanOutboxHandlers = HashMap<String, Arc<dyn WorkspacePlanOutboxHandler>>;

const SUPERVISOR_TICK_EVENT: &str = "supervisor_tick";
const WORKER_LAUNCH_EVENT: &str = "worker_launch";
const HANDOFF_RESUME_EVENT: &str = "handoff_resume";
const ATTEMPT_RETRY_EVENT: &str = "attempt_retry";
const PIPELINE_RUN_REQUESTED_EVENT: &str = "pipeline_run_requested";
const WORKSPACE_PLAN_SYSTEM_ACTOR_ID: &str = "workspace-plan:system";
const ROOT_GOAL_TASK_ID: &str = "root_goal_task_id";
const WORKSPACE_PLAN_ID: &str = "workspace_plan_id";
const WORKSPACE_PLAN_NODE_ID: &str = "workspace_plan_node_id";
const CURRENT_ATTEMPT_ID: &str = "current_attempt_id";
const CURRENT_ATTEMPT_WORKER_BINDING_ID: &str = "current_attempt_worker_binding_id";
const WORKER_LAUNCH_MAX_ACTIVE_ENV: &str = "WORKSPACE_WORKER_LAUNCH_MAX_ACTIVE";
const WORKER_LAUNCH_DEFER_SECONDS_ENV: &str = "WORKSPACE_WORKER_LAUNCH_DEFER_SECONDS";
const WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS_ENV: &str =
    "WORKSPACE_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS";
const WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY_ENV: &str =
    "AGISTACK_WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY";
const PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV: &str = "WORKSPACE_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES";
const DEFAULT_WORKER_LAUNCH_MAX_ACTIVE: i64 = 4;
const DEFAULT_WORKER_LAUNCH_DEFER_SECONDS: i64 = 20;
const DEFAULT_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS: i64 = 300;
const DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES: i64 = 3;
const WORKER_LAUNCHABLE_ATTEMPT_STATUSES: [&str; 2] = ["pending", "running"];

pub(crate) fn workspace_plan_outbox_handlers(
    dispatch_store: Arc<dyn WorkspacePlanDispatchStore>,
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
    let pipeline_run = Arc::new(PipelineRunAdmissionHandler::new(dispatch_store));
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
    async fn get_task(
        &self,
        workspace_id: &str,
        task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskRecord>>;

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

    async fn get_task_session_attempt(
        &self,
        attempt_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>>;

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
    async fn get_task(
        &self,
        workspace_id: &str,
        task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskRecord>> {
        PgWorkspaceRepository::get_task(self, workspace_id, task_id).await
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

    async fn get_task_session_attempt(
        &self,
        attempt_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        PgWorkspaceRepository::get_task_session_attempt(self, attempt_id).await
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
}

impl PipelineRunAdmissionHandler {
    pub(crate) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self { store }
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
        let mut metadata = object_or_empty(node.metadata_json);
        metadata.insert("pipeline_status".to_string(), json!("requested"));
        metadata.insert("pipeline_gate_status".to_string(), json!("requested"));
        metadata.insert("pipeline_requested_at".to_string(), json!(now.to_rfc3339()));
        metadata.insert("pipeline_request_outbox_id".to_string(), json!(item.id));
        metadata.insert("pipeline_request_reason".to_string(), json!(reason));
        metadata.insert(
            "pipeline_runtime_state".to_string(),
            json!("runtime_admitted"),
        );
        if let Some(attempt_id) = attempt_id {
            metadata.insert(
                "pipeline_requested_attempt_id".to_string(),
                json!(attempt_id),
            );
        }
        node.execution = "idle".to_string();
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(now);
        self.store.save_plan_node(node).await?;

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
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
            if self
                .recover_missing_attempt_nodes(&item, &payload, &workspace_id, &plan_id)
                .await?
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
    struct FakeWorkspacePlanDispatchStore {
        tasks: Mutex<HashMap<String, WorkspaceTaskRecord>>,
        plans: Mutex<HashMap<String, WorkspacePlanRecord>>,
        nodes: Mutex<HashMap<String, WorkspacePlanNodeRecord>>,
        attempts: Mutex<HashMap<String, WorkspaceTaskSessionAttemptRecord>>,
        outbox: Mutex<Vec<WorkspacePlanOutboxRecord>>,
        active_worker_conversations: Mutex<i64>,
        supervisor_dispose_nodes: Mutex<HashSet<(String, String, String)>>,
    }

    impl FakeWorkspacePlanDispatchStore {
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

        fn set_active_worker_conversations(&self, count: i64) {
            *self.active_worker_conversations.lock().unwrap() = count;
        }

        fn task(&self, id: &str) -> WorkspaceTaskRecord {
            self.tasks.lock().unwrap().get(id).unwrap().clone()
        }

        fn node(&self, id: &str) -> WorkspacePlanNodeRecord {
            self.nodes.lock().unwrap().get(id).unwrap().clone()
        }

        fn attempts(&self) -> Vec<WorkspaceTaskSessionAttemptRecord> {
            self.attempts.lock().unwrap().values().cloned().collect()
        }

        fn outbox(&self) -> Vec<WorkspacePlanOutboxRecord> {
            self.outbox.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl WorkspacePlanDispatchStore for FakeWorkspacePlanDispatchStore {
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

        async fn get_task_session_attempt(
            &self,
            attempt_id: &str,
        ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
            Ok(self.attempts.lock().unwrap().get(attempt_id).cloned())
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
        PipelineRunAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>)
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
