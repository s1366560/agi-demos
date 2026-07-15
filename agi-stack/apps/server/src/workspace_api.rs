//! P6 workspace foundation over Python-owned workspace tables.
//!
//! This deliberately covers only precise, database-backed resources:
//! workspaces, workspace chat messages, workspace tasks, topology nodes/edges, and blackboard
//! posts/replies/files plus transactional plan action/outbox rows. Runtime-heavy
//! siblings (execution diagnostics and full leader adjudication) remain
//! Python-owned until their full semantics are migrated; accept-review already
//! projects linked attempts to accepted so pending adjudication does not linger
//! after explicit human acceptance. The autonomy tick endpoint owns the durable
//! plan supervisor/outbox slice plus Python-compatible Redis cooldown; Python
//! still owns planner decomposition and root auto-completion.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};

use async_trait::async_trait;
use axum::{
    body::Body,
    extract::{Multipart, Path, Query, State},
    http::{
        header::{
            ACCEPT_RANGES, CACHE_CONTROL, CONTENT_DISPOSITION, CONTENT_LENGTH, CONTENT_TYPE, ETAG,
            IF_NONE_MATCH,
        },
        HeaderMap, HeaderValue, StatusCode,
    },
    response::Response,
    Extension, Json,
};
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Map, Value};

#[cfg(test)]
use agistack_adapters_mem::InMemoryObjectStore;
use agistack_adapters_postgres::{
    BlackboardFileRecord, BlackboardOutboxRecord, BlackboardPostRecord, BlackboardReplyRecord,
    PgWorkspaceRepository, TopologyEdgeRecord, TopologyNodeRecord, WorkspaceAccess,
    WorkspaceAgentDetailRecord, WorkspaceAgentRecord, WorkspaceMemberRecord,
    WorkspaceMessageRecord, WorkspacePlanBlackboardEntryRecord, WorkspacePlanEventRecord,
    WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord, WorkspacePlanRecord,
    WorkspaceProjectAccess, WorkspaceRecord, WorkspaceTaskRecord,
    WorkspaceTaskSessionAttemptRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::ports::ObjectStore;

use crate::auth::Identity;
use crate::AppState;

mod autonomy_cooldown;
mod autonomy_service;
mod blackboard_service;
mod chat_mentions;
mod file_dev_service;
mod file_pg_service;
mod files;
mod handlers;
mod plan_actions;
mod plan_dev_service;
mod plan_pg_service;
mod plan_snapshot;
mod routes;
mod service;
mod shared;
mod task_service;
mod topology_service;
mod types;
mod views;
mod workspace_chat;
mod workspace_lifecycle;
mod workspace_roster;
mod workspace_service_dev;
mod workspace_service_pg;

#[cfg(test)]
use chat_mentions::{
    workspace_agent_mention_outbox_records, workspace_conversation_id,
    WorkspaceAgentMentionOutboxInput, WORKSPACE_AGENT_MENTION_EVENT,
    WORKSPACE_AGENT_MENTION_STATUS,
};
use types::{
    AutonomyTickRequest, AutonomyTickView, BlackboardFileDownload, BlackboardFileListQuery,
    BlackboardFileListView, BlackboardFileView, BlackboardPostCreatePayload,
    BlackboardPostListView, BlackboardPostUpdatePayload, BlackboardPostView,
    BlackboardReplyCreatePayload, BlackboardReplyListView, BlackboardReplyUpdatePayload,
    BlackboardReplyView, BlackboardUpload, CopyFilePayload, DeleteFileQuery, DeletedView,
    LimitOffset, MessageListQuery, MessageListView, MessageMentionQuery, MessageView, MkdirPayload,
    RenameOrMoveFilePayload, SendMessagePayload, TaskListQuery, TaskTransitionAction,
    TopologyEdgeCreatePayload, TopologyEdgeUpdatePayload, TopologyEdgeView,
    TopologyNodeCreatePayload, TopologyNodeUpdatePayload, TopologyNodeView,
    WorkspaceAgentListQuery, WorkspaceAgentView, WorkspaceApiError, WorkspaceCreatePayload,
    WorkspaceDeliverySummaryView, WorkspaceListQuery, WorkspaceMemberView,
    WorkspacePlanActionCapabilityView, WorkspacePlanActionRequest, WorkspacePlanActionResultView,
    WorkspacePlanBlackboardEntryView, WorkspacePlanEventView, WorkspacePlanEvidenceBundleView,
    WorkspacePlanGateStatusView, WorkspacePlanHistoryItemView, WorkspacePlanIterationPhaseView,
    WorkspacePlanIterationSummaryView, WorkspacePlanNodeView, WorkspacePlanOutboxItemView,
    WorkspacePlanPhaseContractView, WorkspacePlanPipelineRunRequest,
    WorkspacePlanRunAssessmentView, WorkspacePlanSnapshotQuery, WorkspacePlanSnapshotView,
    WorkspacePlanView, WorkspaceReplyUpdateInput, WorkspaceTaskCreatePayload,
    WorkspaceTaskUpdatePayload, WorkspaceTaskView, WorkspaceUpdatePayload, WorkspaceView,
};
use views::{
    dedup_truncate, first_metadata_string, int_from_value, int_list_from_value, iso,
    metadata_string_values, object_or_empty, phase_label, string_from_value, string_values,
};

pub(crate) use autonomy_cooldown::SharedAutonomyCooldownStore;
use autonomy_cooldown::{AutonomyCooldownStore, InMemoryAutonomyCooldownStore};
pub(crate) use routes::router;
pub(crate) use service::{SharedWorkspaces, WorkspaceService};
use shared::{
    apply_task_transition, apply_task_update, clamp_limit, compose_workspace_metadata,
    priority_rank, validate_node_type, validate_non_empty, validate_post_status,
    validate_task_status, BLOCKED_FILE_SEGMENTS, MAX_COPY_ENTRIES, MAX_FILE_SIZE,
    OPERATOR_CLEARED_ATTEMPT_KEYS, OPERATOR_CLEARED_RETRY_KEYS,
};

const PIPELINE_RUN_REQUESTED_EVENT: &str = "pipeline_run_requested";
const SUPERVISOR_TICK_EVENT: &str = "supervisor_tick";
const WORKER_LAUNCH_EVENT: &str = "worker_launch";
const HANDOFF_RESUME_EVENT: &str = "handoff_resume";
const WORKSPACE_PLAN_SYSTEM_ACTOR_ID: &str = "workspace-plan:system";
const STALE_RECOVERY_DISPATCH_STALE_SECONDS: i64 = 180;
const STALE_RECOVERY_RUNNING_STALE_SECONDS: i64 = 300;
const STALE_RECOVERY_RECENT_JOB_SUPPRESSION_SECONDS: i64 = 300;

pub(crate) struct PgWorkspaceService {
    repo: PgWorkspaceRepository,
    object_store: Arc<dyn ObjectStore>,
    autonomy_cooldown: Option<SharedAutonomyCooldownStore>,
}

impl PgWorkspaceService {
    pub(crate) fn new(
        repo: PgWorkspaceRepository,
        object_store: Arc<dyn ObjectStore>,
        autonomy_cooldown: Option<SharedAutonomyCooldownStore>,
    ) -> Self {
        Self {
            repo,
            object_store,
            autonomy_cooldown,
        }
    }

    async fn ensure_project_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        access: WorkspaceProjectAccess,
    ) -> Result<(), WorkspaceApiError> {
        if self
            .repo
            .user_can_access_project(user_id, tenant_id, project_id, access)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::forbidden())
        }
    }

    async fn ensure_workspace_access(
        &self,
        user_id: &str,
        workspace_id: &str,
        access: WorkspaceAccess,
    ) -> Result<(), WorkspaceApiError> {
        if self
            .repo
            .user_can_access_workspace(user_id, workspace_id, access)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::forbidden())
        }
    }

    async fn ensure_workspace_scope_and_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        access: WorkspaceAccess,
    ) -> Result<(), WorkspaceApiError> {
        let scoped = self
            .repo
            .workspace_in_scope(workspace_id, tenant_id, project_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if !scoped {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        self.ensure_workspace_access(user_id, workspace_id, access)
            .await
    }

    async fn enqueue_blackboard_event(
        &self,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        event_type: &str,
        payload: Value,
    ) -> Result<(), WorkspaceApiError> {
        self.repo
            .enqueue_blackboard_outbox(BlackboardOutboxRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                tenant_id: tenant_id.to_string(),
                project_id: project_id.to_string(),
                event_type: event_type.to_string(),
                payload_json: payload,
                metadata_json: json!({
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "surface_boundary": "blackboard",
                    "authority_class": "authoritative"
                }),
                correlation_id: None,
            })
            .await
            .map_err(WorkspaceApiError::internal)
    }

    async fn enqueue_chat_event(
        &self,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        event_type: &str,
        payload: Value,
    ) -> Result<(), WorkspaceApiError> {
        self.repo
            .enqueue_blackboard_outbox(BlackboardOutboxRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                tenant_id: tenant_id.to_string(),
                project_id: project_id.to_string(),
                event_type: event_type.to_string(),
                payload_json: payload,
                metadata_json: json!({
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "surface_owner": "workspace-chat",
                    "surface_boundary": "hosted",
                    "authority_class": "non-authoritative",
                    "signal_role": "sensing-capable"
                }),
                correlation_id: None,
            })
            .await
            .map_err(WorkspaceApiError::internal)
    }

    fn object_key(&self, workspace_id: &str, storage_key: &str) -> String {
        files::object_key(workspace_id, storage_key)
    }
}

#[derive(Default)]
struct DevWorkspaceState {
    workspaces: HashMap<String, WorkspaceRecord>,
    workspace_members: Vec<WorkspaceMemberRecord>,
    workspace_agents: Vec<WorkspaceAgentRecord>,
    workspace_agent_details: Vec<WorkspaceAgentDetailRecord>,
    tasks: HashMap<String, WorkspaceTaskRecord>,
    messages: HashMap<String, WorkspaceMessageRecord>,
    task_attempts: HashMap<String, WorkspaceTaskSessionAttemptRecord>,
    nodes: HashMap<String, TopologyNodeRecord>,
    edges: HashMap<String, TopologyEdgeRecord>,
    posts: HashMap<String, BlackboardPostRecord>,
    replies: HashMap<String, BlackboardReplyRecord>,
    files: HashMap<String, BlackboardFileRecord>,
    outbox: Vec<BlackboardOutboxRecord>,
    plans: HashMap<String, WorkspacePlanRecord>,
    plan_nodes: HashMap<String, WorkspacePlanNodeRecord>,
    plan_blackboard: Vec<WorkspacePlanBlackboardEntryRecord>,
    plan_events: Vec<WorkspacePlanEventRecord>,
    plan_outbox: Vec<WorkspacePlanOutboxRecord>,
}

pub(crate) struct DevWorkspaceService {
    dev_user_id: String,
    state: Mutex<DevWorkspaceState>,
    object_store: Arc<dyn ObjectStore>,
    autonomy_cooldown: Option<SharedAutonomyCooldownStore>,
}

impl DevWorkspaceService {
    #[cfg(test)]
    pub(crate) fn new(dev_user_id: impl Into<String>) -> Self {
        Self::with_object_store(dev_user_id, Arc::new(InMemoryObjectStore::new()))
    }

    pub(crate) fn with_object_store(
        dev_user_id: impl Into<String>,
        object_store: Arc<dyn ObjectStore>,
    ) -> Self {
        Self::with_object_store_and_cooldown(
            dev_user_id,
            object_store,
            Some(Arc::new(InMemoryAutonomyCooldownStore::new())),
        )
    }

    pub(crate) fn with_object_store_and_cooldown(
        dev_user_id: impl Into<String>,
        object_store: Arc<dyn ObjectStore>,
        autonomy_cooldown: Option<SharedAutonomyCooldownStore>,
    ) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            state: Mutex::new(DevWorkspaceState::default()),
            object_store,
            autonomy_cooldown,
        }
    }

    fn require_dev_user(&self, user_id: &str) -> Result<(), WorkspaceApiError> {
        if user_id == self.dev_user_id {
            Ok(())
        } else {
            Err(WorkspaceApiError::forbidden())
        }
    }

    fn lock_state(&self) -> Result<MutexGuard<'_, DevWorkspaceState>, WorkspaceApiError> {
        self.state
            .lock()
            .map_err(|_| WorkspaceApiError::internal("workspace dev state unavailable"))
    }

    fn workspace_matches(
        &self,
        workspace: &WorkspaceRecord,
        tenant_id: &str,
        project_id: &str,
    ) -> bool {
        workspace.tenant_id == tenant_id && workspace.project_id == project_id
    }

    fn object_key(&self, workspace_id: &str, storage_key: &str) -> String {
        files::object_key(workspace_id, storage_key)
    }
}

fn new_id() -> String {
    generate_uuid_v4()
}

#[cfg(test)]
mod tests;
