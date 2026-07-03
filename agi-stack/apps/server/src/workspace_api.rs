//! P6 workspace foundation over Python-owned workspace tables.
//!
//! This deliberately covers only precise, database-backed resources:
//! workspaces, workspace chat messages, workspace tasks, topology nodes/edges, and blackboard
//! posts/replies/files plus transactional plan action/outbox rows. Runtime-heavy
//! siblings (execution diagnostics, full leader adjudication, autonomy)
//! remain Python-owned until their full semantics are migrated; accept-review
//! already projects linked attempts to accepted so pending adjudication does not
//! linger after explicit human acceptance.

use std::collections::{HashMap, HashSet};
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
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Extension, Json, Router,
};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use uuid::Uuid;

#[cfg(test)]
use agistack_adapters_mem::InMemoryObjectStore;
use agistack_adapters_postgres::{
    BlackboardFileRecord, BlackboardOutboxRecord, BlackboardPostRecord, BlackboardReplyRecord,
    PgWorkspaceRepository, TopologyEdgeRecord, TopologyNodeRecord, WorkspaceAccess,
    WorkspaceAgentRecord, WorkspaceMessageRecord, WorkspacePlanBlackboardEntryRecord,
    WorkspacePlanEventRecord, WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord,
    WorkspacePlanRecord, WorkspaceProjectAccess, WorkspaceRecord, WorkspaceTaskRecord,
    WorkspaceTaskSessionAttemptRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::ports::ObjectStore;

use crate::auth::Identity;
use crate::AppState;

mod plan_actions;
mod plan_snapshot;

pub(crate) type SharedWorkspaces = Arc<dyn WorkspaceService>;

const PIPELINE_RUN_REQUESTED_EVENT: &str = "pipeline_run_requested";
const SUPERVISOR_TICK_EVENT: &str = "supervisor_tick";
const WORKER_LAUNCH_EVENT: &str = "worker_launch";
const HANDOFF_RESUME_EVENT: &str = "handoff_resume";
const WORKSPACE_AGENT_MENTION_EVENT: &str = "workspace_agent_mention";
const WORKSPACE_AGENT_MENTION_STATUS: &str = "pending_runtime";
const WORKSPACE_AGENT_MENTION_SOURCE: &str = "workspace_chat_mention";
const WORKSPACE_AGENT_MENTION_STAGE: &str = "chat_mention";
const STALE_RECOVERY_DISPATCH_STALE_SECONDS: i64 = 180;
const STALE_RECOVERY_RUNNING_STALE_SECONDS: i64 = 300;
const STALE_RECOVERY_RECENT_JOB_SUPPRESSION_SECONDS: i64 = 300;
const OPERATOR_CLEARED_RETRY_KEYS: &[&str] = &[
    "retry_count",
    "retry_last_reason",
    "retry_not_before",
    "terminal_attempt_retry_count",
    "terminal_attempt_retry_reason",
    "terminal_attempt_reconciled_at",
    "terminal_attempt_status",
    "terminal_attempt_superseded_attempt_id",
    "terminal_attempt_superseded_reason",
    "terminal_attempt_superseded_status",
];
const OPERATOR_CLEARED_ATTEMPT_KEYS: &[&str] = &[
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
    "source_publish_branch",
    "source_publish_commit_ref",
    "source_publish_provider",
    "source_publish_reason",
    "source_publish_source_commit_ref",
    "source_publish_status",
    "source_publish_token_env",
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
];

pub(crate) struct WorkspaceReplyUpdateInput<'a> {
    pub(crate) user_id: &'a str,
    pub(crate) tenant_id: &'a str,
    pub(crate) project_id: &'a str,
    pub(crate) workspace_id: &'a str,
    pub(crate) post_id: &'a str,
    pub(crate) reply_id: &'a str,
    pub(crate) body: BlackboardReplyUpdatePayload,
}

#[async_trait]
pub(crate) trait WorkspaceService: Send + Sync {
    async fn create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError>;

    async fn list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError>;

    async fn get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError>;

    async fn send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError>;

    async fn list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError>;

    async fn list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError>;

    async fn get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError>;

    async fn retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError>;

    async fn update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError>;

    async fn delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError>;

    async fn create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError>;

    async fn list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError>;

    async fn get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError>;

    async fn update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError>;

    async fn delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError>;

    async fn transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError>;

    async fn create_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyNodeCreatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError>;

    async fn list_nodes(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyNodeView>, WorkspaceApiError>;

    async fn get_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<TopologyNodeView, WorkspaceApiError>;

    async fn update_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: TopologyNodeUpdatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError>;

    async fn delete_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<(), WorkspaceApiError>;

    async fn create_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyEdgeCreatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError>;

    async fn list_edges(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyEdgeView>, WorkspaceApiError>;

    async fn get_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<TopologyEdgeView, WorkspaceApiError>;

    async fn update_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
        body: TopologyEdgeUpdatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError>;

    async fn delete_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<(), WorkspaceApiError>;

    async fn create_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: BlackboardPostCreatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError>;

    async fn list_posts(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardPostListView, WorkspaceApiError>;

    async fn get_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<BlackboardPostView, WorkspaceApiError>;

    async fn update_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardPostUpdatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError>;

    async fn delete_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError>;

    async fn create_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardReplyCreatePayload,
    ) -> Result<BlackboardReplyView, WorkspaceApiError>;

    async fn list_replies(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardReplyListView, WorkspaceApiError>;

    async fn update_reply(
        &self,
        input: WorkspaceReplyUpdateInput<'_>,
    ) -> Result<BlackboardReplyView, WorkspaceApiError>;

    async fn delete_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError>;

    async fn list_files(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: BlackboardFileListQuery,
    ) -> Result<BlackboardFileListView, WorkspaceApiError>;

    async fn create_directory(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: MkdirPayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError>;

    async fn upload_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        upload: BlackboardUpload,
    ) -> Result<BlackboardFileView, WorkspaceApiError>;

    async fn download_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
    ) -> Result<BlackboardFileDownload, WorkspaceApiError>;

    async fn patch_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: RenameOrMoveFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError>;

    async fn copy_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: CopyFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError>;

    async fn delete_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        query: DeleteFileQuery,
    ) -> Result<DeletedView, WorkspaceApiError>;
}

#[derive(Debug)]
pub(crate) struct WorkspaceApiError {
    status: StatusCode,
    detail: String,
}

impl WorkspaceApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn forbidden() -> Self {
        Self::new(StatusCode::FORBIDDEN, "Access denied")
    }

    fn workspace_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Workspace not found")
    }

    fn task_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Workspace task not found")
    }

    fn node_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Topology node not found")
    }

    fn edge_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Topology edge not found")
    }

    fn blackboard_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Blackboard item not found")
    }

    fn plan_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Workspace plan not found")
    }

    fn conflict(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::CONFLICT, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for WorkspaceApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspaceListQuery {
    #[serde(default)]
    limit: Option<i64>,
    #[serde(default)]
    offset: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct WorkspaceCreatePayload {
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    metadata: Value,
    #[serde(default)]
    use_case: Option<String>,
    #[serde(default)]
    collaboration_mode: Option<String>,
    #[serde(default)]
    autonomy_profile: Option<Value>,
    #[serde(default)]
    sandbox_code_root: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspaceUpdatePayload {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    is_archived: Option<bool>,
    #[serde(default)]
    metadata: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SendMessagePayload {
    content: String,
    #[serde(default = "default_sender_type")]
    sender_type: String,
    #[serde(default)]
    parent_message_id: Option<String>,
    #[serde(default)]
    mentions: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct MessageListQuery {
    #[serde(default)]
    limit: Option<i64>,
    #[serde(default)]
    before: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct MessageMentionQuery {
    #[serde(default)]
    limit: Option<i64>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct TaskListQuery {
    #[serde(default, rename = "status")]
    status_filter: Option<String>,
    #[serde(default)]
    limit: Option<i64>,
    #[serde(default)]
    offset: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct WorkspaceTaskCreatePayload {
    title: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    assignee_user_id: Option<String>,
    #[serde(default)]
    metadata: Value,
    #[serde(default)]
    priority: Option<String>,
    #[serde(default)]
    estimated_effort: Option<String>,
    #[serde(default)]
    blocker_reason: Option<String>,
    #[serde(default)]
    preferred_language: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspaceTaskUpdatePayload {
    #[serde(default)]
    title: Option<String>,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    assignee_user_id: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    metadata: Option<Value>,
    #[serde(default)]
    priority: Option<String>,
    #[serde(default)]
    estimated_effort: Option<String>,
    #[serde(default)]
    blocker_reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TopologyNodeCreatePayload {
    node_type: String,
    #[serde(default)]
    ref_id: Option<String>,
    #[serde(default)]
    title: Option<String>,
    #[serde(default)]
    position_x: Option<f64>,
    #[serde(default)]
    position_y: Option<f64>,
    #[serde(default)]
    hex_q: Option<i32>,
    #[serde(default)]
    hex_r: Option<i32>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    data: Value,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct TopologyNodeUpdatePayload {
    #[serde(default)]
    node_type: Option<String>,
    #[serde(default)]
    ref_id: Option<String>,
    #[serde(default)]
    title: Option<String>,
    #[serde(default)]
    position_x: Option<f64>,
    #[serde(default)]
    position_y: Option<f64>,
    #[serde(default)]
    hex_q: Option<i32>,
    #[serde(default)]
    hex_r: Option<i32>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    tags: Option<Vec<String>>,
    #[serde(default)]
    data: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TopologyEdgeCreatePayload {
    source_node_id: String,
    target_node_id: String,
    #[serde(default)]
    label: Option<String>,
    #[serde(default)]
    direction: Option<String>,
    #[serde(default)]
    auto_created: bool,
    #[serde(default)]
    data: Value,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct TopologyEdgeUpdatePayload {
    #[serde(default)]
    source_node_id: Option<String>,
    #[serde(default)]
    target_node_id: Option<String>,
    #[serde(default)]
    label: Option<String>,
    #[serde(default)]
    direction: Option<String>,
    #[serde(default)]
    auto_created: Option<bool>,
    #[serde(default)]
    data: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct BlackboardPostCreatePayload {
    title: String,
    content: String,
    #[serde(default = "default_post_status")]
    status: String,
    #[serde(default)]
    is_pinned: bool,
    #[serde(default)]
    metadata: Value,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct BlackboardPostUpdatePayload {
    #[serde(default)]
    title: Option<String>,
    #[serde(default)]
    content: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    is_pinned: Option<bool>,
    #[serde(default)]
    metadata: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct BlackboardReplyCreatePayload {
    content: String,
    #[serde(default)]
    metadata: Value,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct BlackboardReplyUpdatePayload {
    content: String,
    #[serde(default)]
    metadata: Option<Value>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct BlackboardFileListQuery {
    #[serde(default)]
    parent_path: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct MkdirPayload {
    #[serde(default = "root_path")]
    parent_path: String,
    name: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct RenameOrMoveFilePayload {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    parent_path: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct CopyFilePayload {
    target_parent_path: String,
    #[serde(default)]
    name: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct DeleteFileQuery {
    #[serde(default)]
    recursive: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspacePlanSnapshotQuery {
    #[serde(default)]
    outbox_limit: Option<i64>,
    #[serde(default)]
    event_limit: Option<i64>,
    #[serde(default)]
    include_details: Option<bool>,
    #[serde(default)]
    recover_stale_attempts: Option<bool>,
    #[serde(default)]
    plan_id: Option<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct BlackboardUpload {
    parent_path: String,
    filename: String,
    content_type: Option<String>,
    bytes: Vec<u8>,
}

#[derive(Debug, Clone)]
pub(crate) struct BlackboardFileDownload {
    filename: String,
    content_type: String,
    file_size: i32,
    etag: String,
    bytes: Vec<u8>,
}

#[derive(Debug, Clone, Copy)]
pub(crate) enum TaskTransitionAction {
    Claim,
    Start,
    Block,
    Complete,
    UnassignAgent,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct LimitOffset {
    #[serde(default)]
    limit: Option<i64>,
    #[serde(default)]
    offset: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspaceView {
    id: String,
    tenant_id: String,
    project_id: String,
    name: String,
    created_by: String,
    description: Option<String>,
    is_archived: bool,
    metadata: Value,
    office_status: String,
    hex_layout_config: Value,
    created_at: String,
    updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspaceTaskView {
    id: String,
    workspace_id: String,
    title: String,
    description: Option<String>,
    created_by: String,
    assignee_user_id: Option<String>,
    assignee_agent_id: Option<String>,
    workspace_agent_id: Option<String>,
    current_attempt_id: Option<String>,
    current_attempt_number: Option<i64>,
    current_attempt_conversation_id: Option<String>,
    current_attempt_worker_binding_id: Option<String>,
    current_attempt_worker_agent_id: Option<String>,
    last_attempt_status: Option<String>,
    pending_leader_adjudication: bool,
    last_worker_report_type: Option<String>,
    last_worker_report_summary: Option<String>,
    last_worker_report_artifacts: Vec<String>,
    last_worker_report_verifications: Vec<String>,
    status: String,
    metadata: Value,
    created_at: String,
    updated_at: Option<String>,
    priority: String,
    estimated_effort: Option<String>,
    blocker_reason: Option<String>,
    completed_at: Option<String>,
    archived_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct MessageView {
    id: String,
    workspace_id: String,
    sender_id: String,
    sender_type: String,
    content: String,
    mentions: Vec<String>,
    parent_message_id: Option<String>,
    metadata: Value,
    created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct MessageListView {
    items: Vec<MessageView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct TopologyNodeView {
    id: String,
    workspace_id: String,
    node_type: String,
    ref_id: Option<String>,
    title: String,
    position_x: f64,
    position_y: f64,
    hex_q: Option<i32>,
    hex_r: Option<i32>,
    status: String,
    tags: Vec<String>,
    data: Value,
    created_at: String,
    updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct TopologyEdgeView {
    id: String,
    workspace_id: String,
    source_node_id: String,
    target_node_id: String,
    label: Option<String>,
    source_hex_q: Option<i32>,
    source_hex_r: Option<i32>,
    target_hex_q: Option<i32>,
    target_hex_r: Option<i32>,
    direction: Option<String>,
    auto_created: bool,
    data: Value,
    created_at: String,
    updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardPostView {
    id: String,
    workspace_id: String,
    author_id: String,
    title: String,
    content: String,
    status: String,
    is_pinned: bool,
    metadata: Value,
    created_at: String,
    updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardReplyView {
    id: String,
    post_id: String,
    workspace_id: String,
    author_id: String,
    content: String,
    metadata: Value,
    created_at: String,
    updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardPostListView {
    items: Vec<BlackboardPostView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardReplyListView {
    items: Vec<BlackboardReplyView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardFileView {
    id: String,
    workspace_id: String,
    parent_path: String,
    name: String,
    is_directory: bool,
    file_size: i32,
    content_type: String,
    uploader_type: String,
    uploader_id: String,
    uploader_name: String,
    created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardFileListView {
    items: Vec<BlackboardFileView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct DeletedView {
    deleted: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanActionCapabilityView {
    enabled: bool,
    label: String,
    reason: Option<String>,
    requires_confirmation: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanPhaseContractView {
    phase: String,
    title: String,
    entry_gate: String,
    exit_gate: String,
    required_evidence: Vec<String>,
    allowed_routing: Vec<String>,
    blocked_semantics: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanGateStatusView {
    status: String,
    summary: String,
    missing: Vec<String>,
    evidence_refs: Vec<String>,
    routing: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanEvidenceBundleView {
    artifacts: Vec<String>,
    evidence_refs: Vec<String>,
    changed_files: Vec<String>,
    pipeline_refs: Vec<String>,
    verification_summary: String,
    review_summary: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanBlockerAnalysisView {
    blocker_type: String,
    root_cause: String,
    resolution: String,
    routing_decision: String,
    human_intervention_required: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanNodeView {
    id: String,
    parent_id: Option<String>,
    kind: String,
    title: String,
    description: String,
    depends_on: Vec<String>,
    acceptance_criteria: Vec<Value>,
    feature_checkpoint: Option<Value>,
    handoff_package: Option<Value>,
    recommended_capabilities: Vec<Value>,
    intent: String,
    execution: String,
    progress: Value,
    assignee_agent_id: Option<String>,
    current_attempt_id: Option<String>,
    workspace_task_id: Option<String>,
    priority: i32,
    metadata: Value,
    created_at: String,
    updated_at: Option<String>,
    completed_at: Option<String>,
    phase_contract: Option<WorkspacePlanPhaseContractView>,
    evidence_bundle: WorkspacePlanEvidenceBundleView,
    gate_status: WorkspacePlanGateStatusView,
    blocker_analysis: Option<WorkspacePlanBlockerAnalysisView>,
    actions: HashMap<String, WorkspacePlanActionCapabilityView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanView {
    id: String,
    workspace_id: String,
    goal_id: String,
    status: String,
    created_at: String,
    updated_at: Option<String>,
    nodes: Vec<WorkspacePlanNodeView>,
    counts: HashMap<String, i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanIterationPhaseView {
    id: String,
    label: String,
    total: i32,
    done: i32,
    running: i32,
    blocked: i32,
    progress: i32,
    gate_status: WorkspacePlanGateStatusView,
    required_artifacts: Vec<String>,
    missing_artifacts: Vec<String>,
    summary: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanIterationSummaryView {
    current_iteration: i32,
    loop_label: String,
    cadence: String,
    loop_status: String,
    max_iterations: i32,
    completed_iterations: Vec<i32>,
    current_sprint_goal: String,
    review_summary: String,
    stop_reason: String,
    active_phase: String,
    active_phase_label: String,
    next_action: String,
    task_count: i32,
    task_budget: i32,
    phases: Vec<WorkspacePlanIterationPhaseView>,
    deliverables: Vec<String>,
    feedback_items: Vec<String>,
    history: Vec<Value>,
    actions: HashMap<String, WorkspacePlanActionCapabilityView>,
    findings: Vec<Value>,
    rejected_finding_count: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanRunAssessmentView {
    status: String,
    summary: String,
    evidence_refs: Vec<String>,
    warnings: Vec<String>,
    required_services_total: i32,
    required_services_healthy: i32,
    failed_required_services: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspaceDeliverySummaryView {
    provider: String,
    status: String,
    contract_source: String,
    contract_confidence: f64,
    agent_managed: bool,
    code_root: Option<String>,
    latest_run: Option<Value>,
    recent_runs: Vec<Value>,
    services: Vec<Value>,
    deployment: Option<Value>,
    deployments: Vec<Value>,
    run_assessment: WorkspacePlanRunAssessmentView,
    warnings: Vec<String>,
    actions: HashMap<String, WorkspacePlanActionCapabilityView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanBlackboardEntryView {
    plan_id: String,
    key: String,
    value: Value,
    published_by: String,
    version: i32,
    schema_ref: Option<String>,
    metadata: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanOutboxItemView {
    id: String,
    plan_id: Option<String>,
    workspace_id: String,
    event_type: String,
    payload: Value,
    status: String,
    attempt_count: i32,
    max_attempts: i32,
    lease_owner: Option<String>,
    lease_expires_at: Option<String>,
    last_error: Option<String>,
    next_attempt_at: Option<String>,
    processed_at: Option<String>,
    metadata: Value,
    created_at: String,
    updated_at: Option<String>,
    actions: HashMap<String, WorkspacePlanActionCapabilityView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanEventView {
    id: String,
    plan_id: String,
    workspace_id: String,
    node_id: Option<String>,
    attempt_id: Option<String>,
    event_type: String,
    source: String,
    actor_id: Option<String>,
    payload: Value,
    created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanHistoryItemView {
    plan_id: String,
    title: String,
    status: String,
    loop_status: String,
    root_goal_id: Option<String>,
    root_goal_status: Option<String>,
    current_iteration: i32,
    max_iterations: i32,
    completed_iterations: Vec<i32>,
    task_count: i32,
    created_at: String,
    updated_at: Option<String>,
    is_latest: bool,
    is_selected: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanSnapshotView {
    workspace_id: String,
    plan: Option<WorkspacePlanView>,
    root_goal: Option<Value>,
    iteration: Option<WorkspacePlanIterationSummaryView>,
    delivery: Option<WorkspaceDeliverySummaryView>,
    blackboard: Vec<WorkspacePlanBlackboardEntryView>,
    outbox: Vec<WorkspacePlanOutboxItemView>,
    events: Vec<WorkspacePlanEventView>,
    plan_history: Vec<WorkspacePlanHistoryItemView>,
    iteration_runs: Vec<Value>,
    run_health: Option<Value>,
    artifact_index: Option<Value>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspacePlanActionRequest {
    #[serde(default)]
    reason: Option<String>,
    #[serde(default)]
    evidence_refs: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspacePlanPipelineRunRequest {
    #[serde(default)]
    reason: Option<String>,
    #[serde(default)]
    evidence_refs: Vec<String>,
    #[serde(default)]
    node_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanActionResultView {
    ok: bool,
    message: String,
    plan_id: String,
    node_id: Option<String>,
    outbox_id: Option<String>,
}

pub(crate) struct PgWorkspaceService {
    repo: PgWorkspaceRepository,
    object_store: Arc<dyn ObjectStore>,
}

impl PgWorkspaceService {
    pub(crate) fn new(repo: PgWorkspaceRepository, object_store: Arc<dyn ObjectStore>) -> Self {
        Self { repo, object_store }
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
        object_key(workspace_id, storage_key)
    }
}

#[async_trait]
impl WorkspaceService for PgWorkspaceService {
    async fn create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.ensure_project_access(
            user_id,
            tenant_id,
            project_id,
            WorkspaceProjectAccess::Write,
        )
        .await?;
        validate_non_empty(&body.name, "name")?;
        let metadata_json = compose_workspace_metadata(body.clone());
        let now = Utc::now();
        let workspace = WorkspaceRecord {
            id: new_id(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            name: body.name,
            description: body.description,
            created_by: user_id.to_string(),
            is_archived: false,
            metadata_json,
            office_status: "inactive".to_string(),
            hex_layout_config_json: json!({}),
            default_blocking_categories_json: Vec::new(),
            created_at: now,
            updated_at: None,
        };
        self.repo
            .create_workspace(workspace, new_id())
            .await
            .map(WorkspaceView::from)
            .map_err(|err| {
                if err.to_string().contains("uq_workspaces_project_name") {
                    WorkspaceApiError::conflict("Workspace already exists")
                } else {
                    WorkspaceApiError::internal(err)
                }
            })
    }

    async fn list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError> {
        self.ensure_project_access(user_id, tenant_id, project_id, WorkspaceProjectAccess::Read)
            .await?;
        let items = self
            .repo
            .list_workspaces_for_user(
                tenant_id,
                project_id,
                user_id,
                clamp_limit(query.limit, 50, 500),
                query.offset.unwrap_or(0).max(0),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(items.into_iter().map(WorkspaceView::from).collect())
    }

    async fn get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        self.repo
            .get_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .map(WorkspaceView::from)
            .ok_or_else(WorkspaceApiError::workspace_not_found)
    }

    async fn send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        validate_non_empty(&body.content, "content")?;
        if body.sender_type != "human" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace chat request",
            ));
        }
        let member_ids = self
            .repo
            .list_workspace_member_user_ids(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let agents = self
            .repo
            .list_active_workspace_agents(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let agent_ids: Vec<_> = agents.iter().map(|agent| agent.agent_id.clone()).collect();
        let mentions = resolve_structured_mentions(&body.mentions, &member_ids, &agent_ids)?;
        let sender_name = self
            .repo
            .get_user_email(user_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .unwrap_or_else(|| sender_name.to_string());
        let now = Utc::now();
        let message = self
            .repo
            .create_message(WorkspaceMessageRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                sender_id: user_id.to_string(),
                sender_type: "human".to_string(),
                content: body.content,
                mentions_json: mentions,
                parent_message_id: body.parent_message_id,
                metadata_json: json!({ "sender_name": sender_name }),
                created_at: now,
            })
            .await
            .map_err(WorkspaceApiError::internal)?;
        let view = MessageView::from(message);
        self.enqueue_chat_event(
            tenant_id,
            project_id,
            workspace_id,
            "workspace_message_created",
            json!({ "message": &view }),
        )
        .await?;
        let mention_outbox =
            workspace_agent_mention_outbox_records(WorkspaceAgentMentionOutboxInput {
                tenant_id,
                project_id,
                workspace_id,
                sender_user_id: user_id,
                sender_name: &sender_name,
                message: &view,
                agents: &agents,
                now,
            });
        for outbox in mention_outbox {
            self.repo
                .enqueue_plan_outbox(outbox)
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        Ok(view)
    }

    async fn list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let messages = self
            .repo
            .list_messages(
                workspace_id,
                clamp_limit(query.limit, 50, 200),
                query.before.as_deref(),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(MessageListView {
            items: messages.into_iter().map(MessageView::from).collect(),
        })
    }

    async fn list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let messages = self
            .repo
            .list_messages_mentioning(workspace_id, target_id, clamp_limit(query.limit, 50, 200))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(MessageListView {
            items: messages.into_iter().map(MessageView::from).collect(),
        })
    }

    async fn get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        let recover_stale_attempts = query.recover_stale_attempts.unwrap_or(false);
        let mut plans = self
            .repo
            .list_plans(workspace_id, 50)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plans.is_empty() {
            return Ok(plan_snapshot::empty_plan_snapshot(workspace_id));
        }
        let selected_plan_id = if let Some(plan_id) = query.plan_id.as_deref() {
            if !plans.iter().any(|plan| plan.id == plan_id) {
                let plan = self
                    .repo
                    .get_plan(plan_id)
                    .await
                    .map_err(WorkspaceApiError::internal)?
                    .filter(|plan| plan.workspace_id == workspace_id)
                    .ok_or_else(WorkspaceApiError::plan_not_found)?;
                plans.push(plan);
            }
            plan_id.to_string()
        } else {
            plans[0].id.clone()
        };
        let mut plans_with_nodes = Vec::with_capacity(plans.len());
        for plan in plans {
            let nodes = self
                .repo
                .list_plan_nodes(&plan.id)
                .await
                .map_err(WorkspaceApiError::internal)?;
            plans_with_nodes.push((plan, nodes));
        }
        let include_details = query.include_details.unwrap_or(true);
        if recover_stale_attempts
            && include_details
            && plans_with_nodes
                .first()
                .map(|(plan, _)| plan.id.as_str() == selected_plan_id.as_str())
                .unwrap_or(false)
            && self
                .repo
                .user_can_access_workspace(user_id, workspace_id, WorkspaceAccess::Write)
                .await
                .map_err(WorkspaceApiError::internal)?
        {
            if let Some((plan, nodes)) = plans_with_nodes
                .iter()
                .find(|(plan, _)| plan.id == selected_plan_id)
            {
                plan_actions::recover_stale_plan_records_pg(
                    &self.repo,
                    workspace_id,
                    plan,
                    nodes,
                    user_id,
                )
                .await?;
            }
        }
        let (blackboard, outbox, events) = if include_details {
            (
                self.repo
                    .list_plan_blackboard_latest(&selected_plan_id)
                    .await
                    .map_err(WorkspaceApiError::internal)?,
                self.repo
                    .list_plan_outbox(
                        &selected_plan_id,
                        query.outbox_limit.unwrap_or(20).clamp(0, 100),
                    )
                    .await
                    .map_err(WorkspaceApiError::internal)?,
                self.repo
                    .list_plan_events(
                        &selected_plan_id,
                        query.event_limit.unwrap_or(50).clamp(0, 200),
                    )
                    .await
                    .map_err(WorkspaceApiError::internal)?,
            )
        } else {
            (Vec::new(), Vec::new(), Vec::new())
        };
        Ok(plan_snapshot::build_plan_snapshot(
            workspace_id,
            plans_with_nodes,
            &selected_plan_id,
            include_details,
            blackboard,
            outbox,
            events,
        ))
    }

    async fn retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let now = Utc::now();
        let item = self
            .repo
            .retry_plan_outbox_now(
                outbox_id,
                workspace_id,
                Some(user_id),
                body.reason.as_deref(),
                now,
            )
            .await
            .map_err(plan_actions::map_plan_outbox_retry_error)?
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let plan_id = item
            .plan_id
            .clone()
            .ok_or_else(|| WorkspaceApiError::bad_request("Invalid workspace plan request"))?;
        self.repo
            .create_plan_event(plan_actions::plan_retry_event(
                &plan_id,
                workspace_id,
                user_id,
                outbox_id,
                &item.event_type,
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Outbox job queued for retry.".to_string(),
            plan_id,
            node_id: None,
            outbox_id: Some(outbox_id.to_string()),
        })
    }

    async fn recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let recovered = plan_actions::recover_stale_plan_records_pg(
            &self.repo,
            workspace_id,
            &plan,
            &nodes,
            user_id,
        )
        .await?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: if recovered {
                "Workspace plan stale attempt recovery queued."
            } else {
                "No stale workspace plan attempts needed recovery."
            }
            .to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: None,
        })
    }

    async fn request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_pipeline_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let node = plan_actions::pipeline_target_node(&nodes, body.node_id.as_deref())
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested harness-native pipeline".to_string());
        let outbox = self
            .repo
            .enqueue_plan_outbox(plan_actions::plan_action_outbox(
                &plan.id,
                workspace_id,
                PIPELINE_RUN_REQUESTED_EVENT,
                json!({
                    "workspace_id": workspace_id,
                    "plan_id": plan.id,
                    "node_id": node.id,
                    "attempt_id": node.current_attempt_id,
                    "reason": reason
                }),
                json!({"source": "workspace_plan.operator_delivery_run_pipeline"}),
                Utc::now(),
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Harness-native pipeline run requested.".to_string(),
            plan_id: plan.id,
            node_id: Some(node.id),
            outbox_id: Some(outbox.id),
        })
    }

    async fn request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let now = Utc::now();
        let mut workspace = self
            .repo
            .get_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        plan_actions::apply_delivery_contract_regeneration(
            &mut workspace.metadata_json,
            user_id,
            body.reason.as_deref(),
            now,
        );
        workspace.updated_at = Some(now);
        self.repo
            .save_workspace(workspace)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested delivery contract regeneration".to_string());
        let outbox = self
            .repo
            .enqueue_plan_outbox(plan_actions::plan_action_outbox(
                &plan.id,
                workspace_id,
                SUPERVISOR_TICK_EVENT,
                json!({
                    "workspace_id": workspace_id,
                    "plan_id": plan.id,
                    "reason": reason
                }),
                json!({"source": "workspace_plan.operator_delivery_regenerate_contract"}),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .create_plan_event(WorkspacePlanEventRecord {
                id: new_id(),
                plan_id: plan.id.clone(),
                workspace_id: workspace_id.to_string(),
                node_id: None,
                attempt_id: None,
                event_type: "delivery_contract_regeneration_requested".to_string(),
                source: "operator".to_string(),
                actor_id: None,
                payload_json: json!({
                    "reason": body.reason,
                    "requested_by": user_id,
                    "requested_at": iso(now)
                }),
                created_at: now,
            })
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Delivery contract regeneration requested.".to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: Some(outbox.id),
        })
    }

    async fn request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_replan_requested",
            reason.as_deref(),
            now,
            plan_actions::done_node_has_recoverable_failure,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        self.repo
            .save_plan_node(updated)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plan_changed {
            self.repo
                .save_plan(plan.clone())
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
                plan_actions::OperatorPlanEventInput {
                    plan_id: &plan.id,
                    workspace_id,
                    node_id,
                    attempt_id,
                    event_type: "operator_replan_requested",
                    actor_id: user_id,
                    payload_json: json!({"reason": reason}),
                    created_at: now,
                },
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .enqueue_plan_outbox(plan_actions::operator_tick_outbox(
                &plan.id,
                workspace_id,
                node_id,
                user_id,
                "operator_replan_requested",
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node sent back for supervisor recovery.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        if node.intent != "blocked" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace plan request",
            ));
        }
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_node_reopened",
            reason.as_deref(),
            now,
            |_| false,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        self.repo
            .save_plan_node(updated)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plan_changed {
            self.repo
                .save_plan(plan.clone())
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
                plan_actions::OperatorPlanEventInput {
                    plan_id: &plan.id,
                    workspace_id,
                    node_id,
                    attempt_id,
                    event_type: "operator_node_reopened",
                    actor_id: user_id,
                    payload_json: json!({"reason": reason}),
                    created_at: now,
                },
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .enqueue_plan_outbox(plan_actions::operator_tick_outbox(
                &plan.id,
                workspace_id,
                node_id,
                user_id,
                "operator_node_reopened",
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Blocked plan node reopened.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let task_id = node.workspace_task_id.clone();
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "Accepted after operator review.".to_string());
        let evidence_refs = plan_actions::trimmed_evidence_refs(&body.evidence_refs);
        let now = Utc::now();
        let mut updated = plan_actions::accept_node_for_operator_review(
            node,
            user_id,
            &reason,
            evidence_refs.clone(),
            now,
        )?;
        let accepted_attempt = if let Some(attempt_id) = attempt_id.as_deref() {
            self.repo
                .finish_task_session_attempt(
                    attempt_id,
                    "accepted",
                    Some(&reason),
                    Some("operator_review_accepted"),
                    now,
                )
                .await
                .map_err(WorkspaceApiError::internal)?
        } else {
            None
        };
        if let Some(attempt) = accepted_attempt.as_ref() {
            plan_actions::apply_human_review_acceptance_to_node_attempt(&mut updated, attempt);
        }
        self.repo
            .save_plan_node(updated.clone())
            .await
            .map_err(WorkspaceApiError::internal)?;
        if let Some(task_id) = task_id {
            let mut task = self
                .repo
                .get_task(workspace_id, &task_id)
                .await
                .map_err(WorkspaceApiError::internal)?
                .ok_or_else(WorkspaceApiError::task_not_found)?;
            plan_actions::apply_human_review_acceptance_to_task(
                &mut task,
                &reason,
                &updated.metadata_json,
                accepted_attempt.as_ref(),
                now,
            );
            self.repo
                .save_task(task)
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
                plan_actions::OperatorPlanEventInput {
                    plan_id: &plan.id,
                    workspace_id,
                    node_id,
                    attempt_id,
                    event_type: "operator_review_accepted",
                    actor_id: user_id,
                    payload_json: json!({"reason": reason, "evidence_refs": evidence_refs}),
                    created_at: now,
                },
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node accepted after human review.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let mut record = self
            .repo
            .get_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        if let Some(name) = body.name {
            validate_non_empty(&name, "name")?;
            record.name = name;
        }
        if body.description.is_some() {
            record.description = body.description;
        }
        if let Some(is_archived) = body.is_archived {
            record.is_archived = is_archived;
        }
        if let Some(metadata) = body.metadata {
            record.metadata_json = metadata;
        }
        record.updated_at = Some(Utc::now());
        self.repo
            .save_workspace(record)
            .await
            .map(WorkspaceView::from)
            .map_err(WorkspaceApiError::internal)
    }

    async fn delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        if self
            .repo
            .delete_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::workspace_not_found())
        }
    }

    async fn create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        validate_non_empty(&body.title, "title")?;
        let now = Utc::now();
        let mut metadata = object_or_empty(body.metadata);
        if let Some(language) = body.preferred_language {
            metadata["preferred_language"] = json!(language);
        }
        let task = WorkspaceTaskRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            title: body.title,
            description: body.description,
            created_by: user_id.to_string(),
            assignee_user_id: body.assignee_user_id,
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: priority_rank(body.priority.as_deref())?,
            estimated_effort: body.estimated_effort,
            blocker_reason: body.blocker_reason,
            metadata_json: metadata,
            created_at: now,
            updated_at: None,
            completed_at: None,
            archived_at: None,
        };
        self.repo
            .create_task(task)
            .await
            .map(WorkspaceTaskView::from)
            .map_err(WorkspaceApiError::internal)
    }

    async fn list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        if let Some(status) = query.status_filter.as_deref() {
            validate_task_status(status)?;
        }
        let tasks = self
            .repo
            .list_tasks(
                workspace_id,
                query.status_filter.as_deref(),
                clamp_limit(query.limit, 100, 500),
                query.offset.unwrap_or(0).max(0),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(tasks.into_iter().map(WorkspaceTaskView::from).collect())
    }

    async fn get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        self.repo
            .get_task(workspace_id, task_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .map(WorkspaceTaskView::from)
            .ok_or_else(WorkspaceApiError::task_not_found)
    }

    async fn update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut task = self
            .repo
            .get_task(workspace_id, task_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::task_not_found)?;
        apply_task_update(&mut task, body)?;
        self.repo
            .save_task(task)
            .await
            .map(WorkspaceTaskView::from)
            .map_err(WorkspaceApiError::internal)
    }

    async fn delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        if self
            .repo
            .delete_task(workspace_id, task_id)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::task_not_found())
        }
    }

    async fn transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut task = self
            .repo
            .get_task(workspace_id, task_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::task_not_found)?;
        apply_task_transition(&mut task, action, user_id);
        self.repo
            .save_task(task)
            .await
            .map(WorkspaceTaskView::from)
            .map_err(WorkspaceApiError::internal)
    }

    async fn create_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyNodeCreatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        validate_node_type(&body.node_type)?;
        let now = Utc::now();
        let node = TopologyNodeRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            node_type: body.node_type,
            ref_id: body.ref_id,
            title: body.title.unwrap_or_default(),
            position_x: body.position_x.unwrap_or(0.0),
            position_y: body.position_y.unwrap_or(0.0),
            hex_q: body.hex_q,
            hex_r: body.hex_r,
            status: body.status.unwrap_or_else(|| "active".to_string()),
            tags_json: body.tags,
            data_json: object_or_empty(body.data),
            created_at: now,
            updated_at: None,
        };
        self.repo
            .create_node(node)
            .await
            .map(TopologyNodeView::from)
            .map_err(WorkspaceApiError::internal)
    }

    async fn list_nodes(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyNodeView>, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        let nodes = self
            .repo
            .list_nodes(
                workspace_id,
                clamp_limit(query.limit, 1000, 2000),
                query.offset.unwrap_or(0).max(0),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(nodes.into_iter().map(TopologyNodeView::from).collect())
    }

    async fn get_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        self.repo
            .get_node(workspace_id, node_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .map(TopologyNodeView::from)
            .ok_or_else(WorkspaceApiError::node_not_found)
    }

    async fn update_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: TopologyNodeUpdatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut node = self
            .repo
            .get_node(workspace_id, node_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::node_not_found)?;
        if let Some(node_type) = body.node_type {
            validate_node_type(&node_type)?;
            node.node_type = node_type;
        }
        if body.ref_id.is_some() {
            node.ref_id = body.ref_id;
        }
        if let Some(title) = body.title {
            node.title = title;
        }
        if let Some(value) = body.position_x {
            node.position_x = value;
        }
        if let Some(value) = body.position_y {
            node.position_y = value;
        }
        if body.hex_q.is_some() {
            node.hex_q = body.hex_q;
        }
        if body.hex_r.is_some() {
            node.hex_r = body.hex_r;
        }
        if let Some(value) = body.status {
            node.status = value;
        }
        if let Some(value) = body.tags {
            node.tags_json = value;
        }
        if let Some(value) = body.data {
            node.data_json = object_or_empty(value);
        }
        node.updated_at = Some(Utc::now());
        self.repo
            .save_node(node)
            .await
            .map(TopologyNodeView::from)
            .map_err(WorkspaceApiError::internal)
    }

    async fn delete_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        if self
            .repo
            .delete_node(workspace_id, node_id)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::node_not_found())
        }
    }

    async fn create_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyEdgeCreatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let Some((source_hex_q, source_hex_r, target_hex_q, target_hex_r)) = self
            .repo
            .edge_endpoints_in_workspace(workspace_id, &body.source_node_id, &body.target_node_id)
            .await
            .map_err(WorkspaceApiError::internal)?
        else {
            return Err(WorkspaceApiError::bad_request(
                "Edge endpoints must exist in same workspace",
            ));
        };
        let now = Utc::now();
        let edge = TopologyEdgeRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            source_node_id: body.source_node_id,
            target_node_id: body.target_node_id,
            label: body.label,
            source_hex_q,
            source_hex_r,
            target_hex_q,
            target_hex_r,
            direction: body.direction,
            auto_created: body.auto_created,
            data_json: object_or_empty(body.data),
            created_at: now,
            updated_at: None,
        };
        self.repo
            .create_edge(edge)
            .await
            .map(TopologyEdgeView::from)
            .map_err(WorkspaceApiError::internal)
    }

    async fn list_edges(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyEdgeView>, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        let edges = self
            .repo
            .list_edges(
                workspace_id,
                clamp_limit(query.limit, 2000, 4000),
                query.offset.unwrap_or(0).max(0),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(edges.into_iter().map(TopologyEdgeView::from).collect())
    }

    async fn get_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        self.repo
            .get_edge(workspace_id, edge_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .map(TopologyEdgeView::from)
            .ok_or_else(WorkspaceApiError::edge_not_found)
    }

    async fn update_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
        body: TopologyEdgeUpdatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut edge = self
            .repo
            .get_edge(workspace_id, edge_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::edge_not_found)?;
        if body.source_node_id.is_some() || body.target_node_id.is_some() {
            let source = body
                .source_node_id
                .unwrap_or_else(|| edge.source_node_id.clone());
            let target = body
                .target_node_id
                .unwrap_or_else(|| edge.target_node_id.clone());
            let Some((source_hex_q, source_hex_r, target_hex_q, target_hex_r)) = self
                .repo
                .edge_endpoints_in_workspace(workspace_id, &source, &target)
                .await
                .map_err(WorkspaceApiError::internal)?
            else {
                return Err(WorkspaceApiError::bad_request(
                    "Edge endpoints must exist in same workspace",
                ));
            };
            edge.source_node_id = source;
            edge.target_node_id = target;
            edge.source_hex_q = source_hex_q;
            edge.source_hex_r = source_hex_r;
            edge.target_hex_q = target_hex_q;
            edge.target_hex_r = target_hex_r;
        }
        if body.label.is_some() {
            edge.label = body.label;
        }
        if body.direction.is_some() {
            edge.direction = body.direction;
        }
        if let Some(value) = body.auto_created {
            edge.auto_created = value;
        }
        if let Some(value) = body.data {
            edge.data_json = object_or_empty(value);
        }
        edge.updated_at = Some(Utc::now());
        self.repo
            .save_edge(edge)
            .await
            .map(TopologyEdgeView::from)
            .map_err(WorkspaceApiError::internal)
    }

    async fn delete_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        if self
            .repo
            .delete_edge(workspace_id, edge_id)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::edge_not_found())
        }
    }

    async fn create_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: BlackboardPostCreatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        validate_non_empty(&body.title, "title")?;
        validate_non_empty(&body.content, "content")?;
        validate_post_status(&body.status)?;
        let now = Utc::now();
        let post = self
            .repo
            .create_post(BlackboardPostRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                author_id: user_id.to_string(),
                title: body.title,
                content: body.content,
                status: body.status,
                is_pinned: body.is_pinned,
                metadata_json: object_or_empty(body.metadata),
                created_at: now,
                updated_at: None,
            })
            .await
            .map_err(WorkspaceApiError::internal)?;
        let view = BlackboardPostView::from(post);
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_post_created",
            json!({ "post": view, "workspace_id": workspace_id, "post_id": view.id }),
        )
        .await?;
        Ok(view)
    }

    async fn list_posts(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardPostListView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let items = self
            .repo
            .list_posts(
                workspace_id,
                clamp_limit(query.limit, 50, 200),
                query.offset.unwrap_or(0).max(0),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(BlackboardPostListView {
            items: items.into_iter().map(BlackboardPostView::from).collect(),
        })
    }

    async fn get_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        self.repo
            .get_post(workspace_id, post_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .map(BlackboardPostView::from)
            .ok_or_else(WorkspaceApiError::blackboard_not_found)
    }

    async fn update_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardPostUpdatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let mut post = self
            .repo
            .get_post(workspace_id, post_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if let Some(title) = body.title {
            validate_non_empty(&title, "title")?;
            post.title = title;
        }
        if let Some(content) = body.content {
            validate_non_empty(&content, "content")?;
            post.content = content;
        }
        if let Some(status) = body.status {
            validate_post_status(&status)?;
            post.status = status;
        }
        if let Some(value) = body.is_pinned {
            post.is_pinned = value;
        }
        if let Some(value) = body.metadata {
            post.metadata_json = object_or_empty(value);
        }
        post.updated_at = Some(Utc::now());
        let view = self
            .repo
            .save_post(post)
            .await
            .map(BlackboardPostView::from)
            .map_err(WorkspaceApiError::internal)?;
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_post_updated",
            json!({ "post": view }),
        )
        .await?;
        Ok(view)
    }

    async fn delete_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let deleted = self
            .repo
            .delete_post(workspace_id, post_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if !deleted {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_post_deleted",
            json!({ "post_id": post_id, "workspace_id": workspace_id }),
        )
        .await?;
        Ok(DeletedView { deleted })
    }

    async fn create_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardReplyCreatePayload,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        validate_non_empty(&body.content, "content")?;
        if self
            .repo
            .get_post(workspace_id, post_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .is_none()
        {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        let reply = self
            .repo
            .create_reply(BlackboardReplyRecord {
                id: new_id(),
                post_id: post_id.to_string(),
                workspace_id: workspace_id.to_string(),
                author_id: user_id.to_string(),
                content: body.content,
                metadata_json: object_or_empty(body.metadata),
                created_at: Utc::now(),
                updated_at: None,
            })
            .await
            .map_err(WorkspaceApiError::internal)?;
        let view = BlackboardReplyView::from(reply);
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_reply_created",
            json!({ "reply": view, "post_id": post_id }),
        )
        .await?;
        Ok(view)
    }

    async fn list_replies(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardReplyListView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        if self
            .repo
            .get_post(workspace_id, post_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .is_none()
        {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        let items = self
            .repo
            .list_replies(
                workspace_id,
                post_id,
                clamp_limit(query.limit, 200, 500),
                query.offset.unwrap_or(0).max(0),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(BlackboardReplyListView {
            items: items.into_iter().map(BlackboardReplyView::from).collect(),
        })
    }

    async fn update_reply(
        &self,
        input: WorkspaceReplyUpdateInput<'_>,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        let WorkspaceReplyUpdateInput {
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            post_id,
            reply_id,
            body,
        } = input;
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        validate_non_empty(&body.content, "content")?;
        let mut reply = self
            .repo
            .get_reply(workspace_id, post_id, reply_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        reply.content = body.content;
        if let Some(metadata) = body.metadata {
            reply.metadata_json = object_or_empty(metadata);
        }
        reply.updated_at = Some(Utc::now());
        let view = self
            .repo
            .save_reply(reply)
            .await
            .map(BlackboardReplyView::from)
            .map_err(WorkspaceApiError::internal)?;
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_reply_updated",
            json!({ "reply": view, "post_id": post_id }),
        )
        .await?;
        Ok(view)
    }

    async fn delete_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let deleted = self
            .repo
            .delete_reply(workspace_id, post_id, reply_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if !deleted {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_reply_deleted",
            json!({ "reply_id": reply_id, "post_id": post_id, "workspace_id": workspace_id }),
        )
        .await?;
        Ok(DeletedView { deleted })
    }

    async fn list_files(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: BlackboardFileListQuery,
    ) -> Result<BlackboardFileListView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let parent_path = validate_file_path(query.parent_path.as_deref().unwrap_or("/"))?;
        let files = self
            .repo
            .list_files(workspace_id, &parent_path)
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(BlackboardFileListView {
            items: files.into_iter().map(BlackboardFileView::from).collect(),
        })
    }

    async fn create_directory(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: MkdirPayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let parent_path = validate_file_path(&body.parent_path)?;
        let name = validate_filename(&body.name)?;
        if parent_path != "/" {
            require_directory_exists_pg(&self.repo, workspace_id, &parent_path).await?;
        }
        ensure_file_name_available_pg(&self.repo, workspace_id, &parent_path, &name).await?;
        let file = self
            .repo
            .create_file(BlackboardFileRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                parent_path,
                name,
                is_directory: true,
                file_size: 0,
                content_type: String::new(),
                storage_key: String::new(),
                uploader_type: "user".to_string(),
                uploader_id: user_id.to_string(),
                uploader_name: user_id.to_string(),
                checksum_sha256: None,
                mime_type_detected: None,
                created_at: Utc::now(),
            })
            .await
            .map_err(map_file_storage_error)?;
        let view = BlackboardFileView::from(file);
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_file_created",
            file_event_payload(workspace_id, &view),
        )
        .await?;
        Ok(view)
    }

    async fn upload_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        upload: BlackboardUpload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        if upload.bytes.len() > MAX_FILE_SIZE {
            return Err(WorkspaceApiError::bad_request(format!(
                "File exceeds maximum size of {MAX_FILE_SIZE} bytes"
            )));
        }
        let parent_path = validate_file_path(&upload.parent_path)?;
        if parent_path != "/" {
            require_directory_exists_pg(&self.repo, workspace_id, &parent_path).await?;
        }
        let filename = validate_filename(&upload.filename)?;
        ensure_file_name_available_pg(&self.repo, workspace_id, &parent_path, &filename).await?;
        let file_id = new_id();
        let content_type = upload
            .content_type
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| guess_content_type(&filename));
        let file_size = upload.bytes.len().min(i32::MAX as usize) as i32;
        let storage_key = format!("{file_id}/{filename}");
        self.object_store
            .put(
                &self.object_key(workspace_id, &storage_key),
                upload.bytes,
                Some(&content_type),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        let file = self
            .repo
            .create_file(BlackboardFileRecord {
                id: file_id,
                workspace_id: workspace_id.to_string(),
                parent_path,
                name: filename,
                is_directory: false,
                file_size,
                content_type,
                storage_key,
                uploader_type: "user".to_string(),
                uploader_id: user_id.to_string(),
                uploader_name: user_id.to_string(),
                checksum_sha256: None,
                mime_type_detected: None,
                created_at: Utc::now(),
            })
            .await
            .map_err(map_file_storage_error)?;
        let mut file = file;
        if let Some(meta) = self
            .object_store
            .stat(&self.object_key(workspace_id, &file.storage_key))
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            file.file_size = meta.size.min(i32::MAX as u64) as i32;
            if let Some(content_type) = meta.content_type {
                file.content_type = content_type;
            }
            file = self
                .repo
                .save_file(file)
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        let view = BlackboardFileView::from(file);
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_file_created",
            file_event_payload(workspace_id, &view),
        )
        .await?;
        Ok(view)
    }

    async fn download_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
    ) -> Result<BlackboardFileDownload, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let file = self
            .repo
            .get_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if file.is_directory {
            return Err(WorkspaceApiError::bad_request(
                "Cannot read directory content",
            ));
        }
        let bytes = self
            .object_store
            .get(&self.object_key(workspace_id, &file.storage_key))
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(|| {
                WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found")
            })?;
        Ok(BlackboardFileDownload {
            filename: file.name,
            content_type: if file.content_type.is_empty() {
                "application/octet-stream".to_string()
            } else {
                file.content_type
            },
            file_size: file.file_size,
            etag: file
                .checksum_sha256
                .map(|checksum| format!("\"{checksum}\""))
                .unwrap_or_else(|| format!("W/\"sz-{}-id-{}\"", file.file_size, file.id)),
            bytes,
        })
    }

    async fn patch_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: RenameOrMoveFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        if body.name.is_none() && body.parent_path.is_none() {
            return Err(WorkspaceApiError::bad_request(
                "Provide at least one of 'name' or 'parent_path'",
            ));
        }
        let mut file = self
            .repo
            .get_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if let Some(parent_path) = body.parent_path {
            let target_parent = validate_file_path(&parent_path)?;
            if target_parent != file.parent_path {
                if target_parent != "/" {
                    require_directory_exists_pg(&self.repo, workspace_id, &target_parent).await?;
                }
                if file.is_directory {
                    let own_prefix = join_child_path(&file.parent_path, &file.name)?;
                    if target_parent == own_prefix || target_parent.starts_with(&own_prefix) {
                        return Err(WorkspaceApiError::bad_request(
                            "Cannot move a directory into itself",
                        ));
                    }
                    let new_prefix = join_child_path(&target_parent, &file.name)?;
                    self.repo
                        .bulk_update_file_parent_path(workspace_id, &own_prefix, &new_prefix)
                        .await
                        .map_err(WorkspaceApiError::internal)?;
                }
                ensure_file_name_available_pg(&self.repo, workspace_id, &target_parent, &file.name)
                    .await?;
                file.parent_path = target_parent;
            }
        }
        if let Some(name) = body.name {
            let safe_name = validate_filename(&name)?;
            if safe_name != file.name {
                ensure_file_name_available_pg(
                    &self.repo,
                    workspace_id,
                    &file.parent_path,
                    &safe_name,
                )
                .await?;
                if file.is_directory {
                    let old_prefix = join_child_path(&file.parent_path, &file.name)?;
                    let new_prefix = join_child_path(&file.parent_path, &safe_name)?;
                    self.repo
                        .bulk_update_file_parent_path(workspace_id, &old_prefix, &new_prefix)
                        .await
                        .map_err(WorkspaceApiError::internal)?;
                }
                file.name = safe_name;
            }
        }
        let view = self
            .repo
            .save_file(file)
            .await
            .map(BlackboardFileView::from)
            .map_err(WorkspaceApiError::internal)?;
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_file_updated",
            json!({ "file": view, "file_id": view.id }),
        )
        .await?;
        Ok(view)
    }

    async fn copy_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: CopyFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let source = self
            .repo
            .get_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        let target_parent = validate_file_path(&body.target_parent_path)?;
        if target_parent != "/" {
            require_directory_exists_pg(&self.repo, workspace_id, &target_parent).await?;
        }
        let copy_name = validate_filename(body.name.as_deref().unwrap_or(&source.name))?;
        ensure_file_name_available_pg(&self.repo, workspace_id, &target_parent, &copy_name).await?;
        let copied = if source.is_directory {
            copy_directory_pg(
                &self.repo,
                Arc::clone(&self.object_store),
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        } else {
            copy_single_file_pg(
                &self.repo,
                Arc::clone(&self.object_store),
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        };
        let view = BlackboardFileView::from(copied);
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_file_created",
            file_event_payload(workspace_id, &view),
        )
        .await?;
        Ok(view)
    }

    async fn delete_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        query: DeleteFileQuery,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let file = self
            .repo
            .get_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        let was_directory = file.is_directory;
        if file.is_directory {
            let child_path = join_child_path(&file.parent_path, &file.name)?;
            let children = self
                .repo
                .list_files(workspace_id, &child_path)
                .await
                .map_err(WorkspaceApiError::internal)?;
            if !children.is_empty() && !query.recursive {
                return Err(WorkspaceApiError::bad_request("Directory is not empty"));
            }
            if query.recursive {
                let descendants = self
                    .repo
                    .find_file_descendants(workspace_id, &child_path)
                    .await
                    .map_err(WorkspaceApiError::internal)?;
                for descendant in descendants.iter().rev() {
                    if !descendant.is_directory && !descendant.storage_key.is_empty() {
                        self.object_store
                            .delete(&self.object_key(workspace_id, &descendant.storage_key))
                            .await
                            .map_err(WorkspaceApiError::internal)?;
                    }
                    self.repo
                        .delete_file(workspace_id, &descendant.id)
                        .await
                        .map_err(WorkspaceApiError::internal)?;
                }
            }
        } else if !file.storage_key.is_empty() {
            self.object_store
                .delete(&self.object_key(workspace_id, &file.storage_key))
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        let deleted = self
            .repo
            .delete_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if !deleted {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            if was_directory {
                "blackboard_directory_deleted"
            } else {
                "blackboard_file_deleted"
            },
            json!({
                "workspace_id": workspace_id,
                "file_id": file_id,
                "deleted": deleted,
                "recursive": query.recursive,
                "is_directory": was_directory
            }),
        )
        .await?;
        Ok(DeletedView { deleted })
    }
}

#[derive(Default)]
struct DevWorkspaceState {
    workspaces: HashMap<String, WorkspaceRecord>,
    workspace_agents: Vec<WorkspaceAgentRecord>,
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
        Self {
            dev_user_id: dev_user_id.into(),
            state: Mutex::new(DevWorkspaceState::default()),
            object_store,
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
        object_key(workspace_id, storage_key)
    }
}

#[async_trait]
impl WorkspaceService for DevWorkspaceService {
    async fn create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.name, "name")?;
        let metadata_json = compose_workspace_metadata(body.clone());
        let now = Utc::now();
        let workspace = WorkspaceRecord {
            id: new_id(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            name: body.name,
            description: body.description,
            created_by: user_id.to_string(),
            is_archived: false,
            metadata_json,
            office_status: "inactive".to_string(),
            hex_layout_config_json: json!({}),
            default_blocking_categories_json: Vec::new(),
            created_at: now,
            updated_at: None,
        };
        self.lock_state()?
            .workspaces
            .insert(workspace.id.clone(), workspace.clone());
        Ok(workspace.into())
    }

    async fn list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let limit = clamp_limit(query.limit, 50, 500) as usize;
        let offset = query.offset.unwrap_or(0).max(0) as usize;
        let mut items: Vec<_> = self
            .lock_state()?
            .workspaces
            .values()
            .filter(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .cloned()
            .collect();
        items.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(a.id.cmp(&b.id)));
        Ok(items
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(WorkspaceView::from)
            .collect())
    }

    async fn get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let workspace = state
            .workspaces
            .get(workspace_id)
            .filter(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .cloned()
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        Ok(workspace.into())
    }

    async fn send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.content, "content")?;
        if body.sender_type != "human" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace chat request",
            ));
        }
        let mut state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let member_ids = vec![self.dev_user_id.clone()];
        let agents: Vec<_> = state
            .workspace_agents
            .iter()
            .filter(|agent| agent.workspace_id == workspace_id)
            .cloned()
            .collect();
        let agent_ids: Vec<_> = agents.iter().map(|agent| agent.agent_id.clone()).collect();
        let mentions = resolve_structured_mentions(&body.mentions, &member_ids, &agent_ids)?;
        let now = Utc::now();
        let message = WorkspaceMessageRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            sender_id: user_id.to_string(),
            sender_type: "human".to_string(),
            content: body.content,
            mentions_json: mentions,
            parent_message_id: body.parent_message_id,
            metadata_json: json!({ "sender_name": sender_name }),
            created_at: now,
        };
        state.messages.insert(message.id.clone(), message.clone());
        let view = MessageView::from(message);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "workspace_message_created".to_string(),
            payload_json: json!({ "message": &view }),
            metadata_json: json!({
                "tenant_id": tenant_id,
                "project_id": project_id,
                "surface_owner": "workspace-chat",
                "surface_boundary": "hosted",
                "authority_class": "non-authoritative",
                "signal_role": "sensing-capable"
            }),
            correlation_id: None,
        });
        state
            .plan_outbox
            .extend(workspace_agent_mention_outbox_records(
                WorkspaceAgentMentionOutboxInput {
                    tenant_id,
                    project_id,
                    workspace_id,
                    sender_user_id: user_id,
                    sender_name,
                    message: &view,
                    agents: &agents,
                    now,
                },
            ));
        Ok(view)
    }

    async fn list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let before = query
            .before
            .as_deref()
            .and_then(|id| state.messages.get(id))
            .map(|message| (message.created_at, message.id.clone()));
        let limit = clamp_limit(query.limit, 50, 200) as usize;
        let mut messages: Vec<_> = state
            .messages
            .values()
            .filter(|message| {
                message.workspace_id == workspace_id
                    && before
                        .as_ref()
                        .map(|(created_at, id)| {
                            message.created_at < *created_at
                                || (message.created_at == *created_at && message.id < *id)
                        })
                        .unwrap_or(true)
            })
            .cloned()
            .collect();
        messages.sort_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)));
        Ok(MessageListView {
            items: messages
                .into_iter()
                .take(limit)
                .map(MessageView::from)
                .collect(),
        })
    }

    async fn list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let limit = clamp_limit(query.limit, 50, 200) as usize;
        let mut messages: Vec<_> = state
            .messages
            .values()
            .filter(|message| {
                message.workspace_id == workspace_id
                    && message
                        .mentions_json
                        .iter()
                        .any(|mention| mention == target_id)
            })
            .cloned()
            .collect();
        messages.sort_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)));
        Ok(MessageListView {
            items: messages
                .into_iter()
                .take(limit)
                .map(MessageView::from)
                .collect(),
        })
    }

    async fn get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let recover_stale_attempts = query.recover_stale_attempts.unwrap_or(false);
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut plans: Vec<_> = state
            .plans
            .values()
            .filter(|plan| plan.workspace_id == workspace_id)
            .cloned()
            .collect();
        plans.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(a.id.cmp(&b.id)));
        if plans.is_empty() {
            return Ok(plan_snapshot::empty_plan_snapshot(workspace_id));
        }
        let selected_plan_id = if let Some(plan_id) = query.plan_id.as_deref() {
            if !plans.iter().any(|plan| plan.id == plan_id) {
                return Err(WorkspaceApiError::plan_not_found());
            }
            plan_id.to_string()
        } else {
            plans[0].id.clone()
        };
        let include_details = query.include_details.unwrap_or(true);
        if recover_stale_attempts
            && include_details
            && plans
                .first()
                .map(|plan| plan.id.as_str() == selected_plan_id.as_str())
                .unwrap_or(false)
        {
            if let Some(plan) = plans
                .iter()
                .find(|plan| plan.id == selected_plan_id)
                .cloned()
            {
                let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
                plan_actions::recover_stale_plan_records_dev(
                    &mut state,
                    workspace_id,
                    &plan,
                    &nodes,
                    user_id,
                    Utc::now(),
                );
            }
        }
        let plans_with_nodes: Vec<_> = plans
            .into_iter()
            .map(|plan| {
                let mut nodes: Vec<_> = state
                    .plan_nodes
                    .values()
                    .filter(|node| node.plan_id == plan.id)
                    .cloned()
                    .collect();
                nodes.sort_by(|a, b| {
                    a.kind
                        .cmp(&b.kind)
                        .then(a.priority.cmp(&b.priority))
                        .then(a.id.cmp(&b.id))
                });
                (plan, nodes)
            })
            .collect();
        let (blackboard, outbox, events) = if include_details {
            let mut latest = HashMap::<String, WorkspacePlanBlackboardEntryRecord>::new();
            for entry in state
                .plan_blackboard
                .iter()
                .filter(|entry| entry.plan_id == selected_plan_id.as_str())
            {
                let replace = latest
                    .get(&entry.key)
                    .map(|current| {
                        entry.version > current.version
                            || (entry.version == current.version
                                && entry.created_at > current.created_at)
                    })
                    .unwrap_or(true);
                if replace {
                    latest.insert(entry.key.clone(), entry.clone());
                }
            }
            let mut blackboard: Vec<_> = latest.into_values().collect();
            blackboard.sort_by(|a, b| a.key.cmp(&b.key));
            let outbox_limit = query.outbox_limit.unwrap_or(20).clamp(0, 100) as usize;
            let mut outbox: Vec<_> = state
                .plan_outbox
                .iter()
                .filter(|item| item.plan_id.as_deref() == Some(selected_plan_id.as_str()))
                .cloned()
                .collect();
            outbox.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(b.id.cmp(&a.id)));
            outbox.truncate(outbox_limit);
            let event_limit = query.event_limit.unwrap_or(50).clamp(0, 200) as usize;
            let mut events: Vec<_> = state
                .plan_events
                .iter()
                .filter(|event| event.plan_id == selected_plan_id.as_str())
                .cloned()
                .collect();
            events.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(b.id.cmp(&a.id)));
            events.truncate(event_limit);
            (blackboard, outbox, events)
        } else {
            (Vec::new(), Vec::new(), Vec::new())
        };
        Ok(plan_snapshot::build_plan_snapshot(
            workspace_id,
            plans_with_nodes,
            &selected_plan_id,
            include_details,
            blackboard,
            outbox,
            events,
        ))
    }

    async fn retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let now = Utc::now();
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let item = state
            .plan_outbox
            .iter_mut()
            .find(|item| item.id == outbox_id && item.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let delayed_pending = item.status == "pending"
            && item
                .next_attempt_at
                .map(|next_attempt_at| next_attempt_at > now)
                .unwrap_or(false);
        if !matches!(item.status.as_str(), "failed" | "dead_letter") && !delayed_pending {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace plan request",
            ));
        }
        let plan_id = item
            .plan_id
            .clone()
            .ok_or_else(|| WorkspaceApiError::bad_request("Invalid workspace plan request"))?;
        let previous_status = item.status.clone();
        let previous_error = item.last_error.clone();
        let previous_next_attempt_at = item.next_attempt_at.map(iso);
        let previous_event_type = item.event_type.clone();
        item.status = "pending".to_string();
        if previous_status == "dead_letter" {
            item.attempt_count = 0;
        }
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        item.processed_at = None;
        item.updated_at = Some(now);
        let mut metadata = match item.metadata_json.clone() {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        metadata.insert(
            "operator_retry".to_string(),
            json!({
                "actor_id": user_id,
                "reason": body.reason.clone(),
                "retried_at": iso(now),
                "previous_status": previous_status,
                "previous_error": previous_error,
                "previous_next_attempt_at": previous_next_attempt_at
            }),
        );
        item.metadata_json = Value::Object(metadata);
        state.plan_events.push(plan_actions::plan_retry_event(
            &plan_id,
            workspace_id,
            user_id,
            outbox_id,
            &previous_event_type,
            body.reason.as_deref(),
            now,
        ));
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Outbox job queued for retry.".to_string(),
            plan_id,
            node_id: None,
            outbox_id: Some(outbox_id.to_string()),
        })
    }

    async fn recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
        let recovered = plan_actions::recover_stale_plan_records_dev(
            &mut state,
            workspace_id,
            &plan,
            &nodes,
            user_id,
            Utc::now(),
        );
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: if recovered {
                "Workspace plan stale attempt recovery queued."
            } else {
                "No stale workspace plan attempts needed recovery."
            }
            .to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: None,
        })
    }

    async fn request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_pipeline_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
        let node = plan_actions::pipeline_target_node(&nodes, body.node_id.as_deref())
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested harness-native pipeline".to_string());
        let outbox = plan_actions::plan_action_outbox(
            &plan.id,
            workspace_id,
            PIPELINE_RUN_REQUESTED_EVENT,
            json!({
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "node_id": node.id,
                "attempt_id": node.current_attempt_id,
                "reason": reason
            }),
            json!({"source": "workspace_plan.operator_delivery_run_pipeline"}),
            Utc::now(),
        );
        let outbox_id = outbox.id.clone();
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Harness-native pipeline run requested.".to_string(),
            plan_id: plan.id,
            node_id: Some(node.id),
            outbox_id: Some(outbox_id),
        })
    }

    async fn request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let now = Utc::now();
        let workspace = state
            .workspaces
            .get_mut(workspace_id)
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        plan_actions::apply_delivery_contract_regeneration(
            &mut workspace.metadata_json,
            user_id,
            body.reason.as_deref(),
            now,
        );
        workspace.updated_at = Some(now);
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested delivery contract regeneration".to_string());
        let outbox = plan_actions::plan_action_outbox(
            &plan.id,
            workspace_id,
            SUPERVISOR_TICK_EVENT,
            json!({
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "reason": reason
            }),
            json!({"source": "workspace_plan.operator_delivery_regenerate_contract"}),
            now,
        );
        let outbox_id = outbox.id.clone();
        state.plan_outbox.push(outbox);
        state.plan_events.push(WorkspacePlanEventRecord {
            id: new_id(),
            plan_id: plan.id.clone(),
            workspace_id: workspace_id.to_string(),
            node_id: None,
            attempt_id: None,
            event_type: "delivery_contract_regeneration_requested".to_string(),
            source: "operator".to_string(),
            actor_id: None,
            payload_json: json!({
                "reason": body.reason,
                "requested_by": user_id,
                "requested_at": iso(now)
            }),
            created_at: now,
        });
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Delivery contract regeneration requested.".to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: Some(outbox_id),
        })
    }

    async fn request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let mut plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_replan_requested",
            reason.as_deref(),
            now,
            plan_actions::done_node_has_recoverable_failure,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        state.plan_nodes.insert(node_id.to_string(), updated);
        if plan_changed {
            state.plans.insert(plan.id.clone(), plan.clone());
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_replan_requested",
                actor_id: user_id,
                payload_json: json!({"reason": reason}),
                created_at: now,
            },
        ));
        let outbox = plan_actions::operator_tick_outbox(
            &plan.id,
            workspace_id,
            node_id,
            user_id,
            "operator_replan_requested",
            body.reason.as_deref(),
            now,
        );
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node sent back for supervisor recovery.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let mut plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        if node.intent != "blocked" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace plan request",
            ));
        }
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_node_reopened",
            reason.as_deref(),
            now,
            |_| false,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        state.plan_nodes.insert(node_id.to_string(), updated);
        if plan_changed {
            state.plans.insert(plan.id.clone(), plan.clone());
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_node_reopened",
                actor_id: user_id,
                payload_json: json!({"reason": reason}),
                created_at: now,
            },
        ));
        let outbox = plan_actions::operator_tick_outbox(
            &plan.id,
            workspace_id,
            node_id,
            user_id,
            "operator_node_reopened",
            body.reason.as_deref(),
            now,
        );
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Blocked plan node reopened.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let task_id = node.workspace_task_id.clone();
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "Accepted after operator review.".to_string());
        let evidence_refs = plan_actions::trimmed_evidence_refs(&body.evidence_refs);
        let now = Utc::now();
        let mut updated = plan_actions::accept_node_for_operator_review(
            node,
            user_id,
            &reason,
            evidence_refs.clone(),
            now,
        )?;
        let accepted_attempt = if let Some(attempt_id) = attempt_id.as_deref() {
            state.task_attempts.get_mut(attempt_id).map(|attempt| {
                attempt.status = "accepted".to_string();
                attempt.leader_feedback = Some(reason.clone());
                attempt.adjudication_reason = Some("operator_review_accepted".to_string());
                attempt.completed_at = Some(now);
                attempt.updated_at = Some(now);
                attempt.clone()
            })
        } else {
            None
        };
        if let Some(attempt) = accepted_attempt.as_ref() {
            plan_actions::apply_human_review_acceptance_to_node_attempt(&mut updated, attempt);
        }
        state
            .plan_nodes
            .insert(node_id.to_string(), updated.clone());
        if let Some(task_id) = task_id {
            let task = state
                .tasks
                .get_mut(&task_id)
                .filter(|task| task.workspace_id == workspace_id)
                .ok_or_else(WorkspaceApiError::task_not_found)?;
            plan_actions::apply_human_review_acceptance_to_task(
                task,
                &reason,
                &updated.metadata_json,
                accepted_attempt.as_ref(),
                now,
            );
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_review_accepted",
                actor_id: user_id,
                payload_json: json!({"reason": reason, "evidence_refs": evidence_refs}),
                created_at: now,
            },
        ));
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node accepted after human review.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let workspace = state
            .workspaces
            .get_mut(workspace_id)
            .filter(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        if let Some(name) = body.name {
            validate_non_empty(&name, "name")?;
            workspace.name = name;
        }
        if body.description.is_some() {
            workspace.description = body.description;
        }
        if let Some(is_archived) = body.is_archived {
            workspace.is_archived = is_archived;
        }
        if let Some(metadata) = body.metadata {
            workspace.metadata_json = metadata;
        }
        workspace.updated_at = Some(Utc::now());
        Ok(workspace.clone().into())
    }

    async fn delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope || state.workspaces.remove(workspace_id).is_none() {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        state
            .tasks
            .retain(|_, task| task.workspace_id != workspace_id);
        state
            .messages
            .retain(|_, message| message.workspace_id != workspace_id);
        state
            .nodes
            .retain(|_, node| node.workspace_id != workspace_id);
        state
            .edges
            .retain(|_, edge| edge.workspace_id != workspace_id);
        state
            .posts
            .retain(|_, post| post.workspace_id != workspace_id);
        state
            .replies
            .retain(|_, reply| reply.workspace_id != workspace_id);
        state
            .files
            .retain(|_, file| file.workspace_id != workspace_id);
        Ok(())
    }

    async fn create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.title, "title")?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut metadata = object_or_empty(body.metadata);
        if let Some(language) = body.preferred_language {
            metadata["preferred_language"] = json!(language);
        }
        let task = WorkspaceTaskRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            title: body.title,
            description: body.description,
            created_by: user_id.to_string(),
            assignee_user_id: body.assignee_user_id,
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: priority_rank(body.priority.as_deref())?,
            estimated_effort: body.estimated_effort,
            blocker_reason: body.blocker_reason,
            metadata_json: metadata,
            created_at: Utc::now(),
            updated_at: None,
            completed_at: None,
            archived_at: None,
        };
        state.tasks.insert(task.id.clone(), task.clone());
        Ok(task.into())
    }

    async fn list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        if let Some(status) = query.status_filter.as_deref() {
            validate_task_status(status)?;
        }
        let limit = clamp_limit(query.limit, 100, 500) as usize;
        let offset = query.offset.unwrap_or(0).max(0) as usize;
        let mut tasks: Vec<_> = self
            .lock_state()?
            .tasks
            .values()
            .filter(|task| {
                task.workspace_id == workspace_id
                    && query
                        .status_filter
                        .as_ref()
                        .map(|status| task.status == *status)
                        .unwrap_or(true)
            })
            .cloned()
            .collect();
        tasks.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(a.id.cmp(&b.id)));
        Ok(tasks
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(WorkspaceTaskView::from)
            .collect())
    }

    async fn get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        state
            .tasks
            .get(task_id)
            .filter(|task| task.workspace_id == workspace_id)
            .cloned()
            .map(WorkspaceTaskView::from)
            .ok_or_else(WorkspaceApiError::task_not_found)
    }

    async fn update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let task = state
            .tasks
            .get_mut(task_id)
            .filter(|task| task.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::task_not_found)?;
        apply_task_update(task, body)?;
        Ok(task.clone().into())
    }

    async fn delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .tasks
            .get(task_id)
            .map(|task| task.workspace_id == workspace_id)
            .unwrap_or(false);
        if !in_scope || state.tasks.remove(task_id).is_none() {
            return Err(WorkspaceApiError::task_not_found());
        }
        Ok(())
    }

    async fn transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let task = state
            .tasks
            .get_mut(task_id)
            .filter(|task| task.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::task_not_found)?;
        apply_task_transition(task, action, user_id);
        Ok(task.clone().into())
    }

    async fn create_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyNodeCreatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_node_type(&body.node_type)?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let node = TopologyNodeRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            node_type: body.node_type,
            ref_id: body.ref_id,
            title: body.title.unwrap_or_default(),
            position_x: body.position_x.unwrap_or(0.0),
            position_y: body.position_y.unwrap_or(0.0),
            hex_q: body.hex_q,
            hex_r: body.hex_r,
            status: body.status.unwrap_or_else(|| "active".to_string()),
            tags_json: body.tags,
            data_json: object_or_empty(body.data),
            created_at: Utc::now(),
            updated_at: None,
        };
        state.nodes.insert(node.id.clone(), node.clone());
        Ok(node.into())
    }

    async fn list_nodes(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyNodeView>, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let limit = clamp_limit(query.limit, 1000, 2000) as usize;
        let offset = query.offset.unwrap_or(0).max(0) as usize;
        let mut nodes: Vec<_> = self
            .lock_state()?
            .nodes
            .values()
            .filter(|node| node.workspace_id == workspace_id)
            .cloned()
            .collect();
        nodes.sort_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)));
        Ok(nodes
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(TopologyNodeView::from)
            .collect())
    }

    async fn get_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        state
            .nodes
            .get(node_id)
            .filter(|node| node.workspace_id == workspace_id)
            .cloned()
            .map(TopologyNodeView::from)
            .ok_or_else(WorkspaceApiError::node_not_found)
    }

    async fn update_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: TopologyNodeUpdatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let node = state
            .nodes
            .get_mut(node_id)
            .filter(|node| node.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::node_not_found)?;
        if let Some(node_type) = body.node_type {
            validate_node_type(&node_type)?;
            node.node_type = node_type;
        }
        if body.ref_id.is_some() {
            node.ref_id = body.ref_id;
        }
        if let Some(title) = body.title {
            node.title = title;
        }
        if let Some(position_x) = body.position_x {
            node.position_x = position_x;
        }
        if let Some(position_y) = body.position_y {
            node.position_y = position_y;
        }
        if body.hex_q.is_some() {
            node.hex_q = body.hex_q;
        }
        if body.hex_r.is_some() {
            node.hex_r = body.hex_r;
        }
        if let Some(status) = body.status {
            node.status = status;
        }
        if let Some(tags) = body.tags {
            node.tags_json = tags;
        }
        if let Some(data) = body.data {
            node.data_json = object_or_empty(data);
        }
        node.updated_at = Some(Utc::now());
        Ok(node.clone().into())
    }

    async fn delete_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .nodes
            .get(node_id)
            .map(|node| node.workspace_id == workspace_id)
            .unwrap_or(false);
        if !in_scope || state.nodes.remove(node_id).is_none() {
            return Err(WorkspaceApiError::node_not_found());
        }
        state
            .edges
            .retain(|_, edge| edge.source_node_id != node_id && edge.target_node_id != node_id);
        Ok(())
    }

    async fn create_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyEdgeCreatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let Some(source) = state
            .nodes
            .get(&body.source_node_id)
            .filter(|node| node.workspace_id == workspace_id)
        else {
            return Err(WorkspaceApiError::bad_request(
                "Edge endpoints must exist in same workspace",
            ));
        };
        let Some(target) = state
            .nodes
            .get(&body.target_node_id)
            .filter(|node| node.workspace_id == workspace_id)
        else {
            return Err(WorkspaceApiError::bad_request(
                "Edge endpoints must exist in same workspace",
            ));
        };
        let edge = TopologyEdgeRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            source_node_id: body.source_node_id,
            target_node_id: body.target_node_id,
            label: body.label,
            source_hex_q: source.hex_q,
            source_hex_r: source.hex_r,
            target_hex_q: target.hex_q,
            target_hex_r: target.hex_r,
            direction: body.direction,
            auto_created: body.auto_created,
            data_json: object_or_empty(body.data),
            created_at: Utc::now(),
            updated_at: None,
        };
        state.edges.insert(edge.id.clone(), edge.clone());
        Ok(edge.into())
    }

    async fn list_edges(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyEdgeView>, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let limit = clamp_limit(query.limit, 2000, 4000) as usize;
        let offset = query.offset.unwrap_or(0).max(0) as usize;
        let mut edges: Vec<_> = self
            .lock_state()?
            .edges
            .values()
            .filter(|edge| edge.workspace_id == workspace_id)
            .cloned()
            .collect();
        edges.sort_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)));
        Ok(edges
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(TopologyEdgeView::from)
            .collect())
    }

    async fn get_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        state
            .edges
            .get(edge_id)
            .filter(|edge| edge.workspace_id == workspace_id)
            .cloned()
            .map(TopologyEdgeView::from)
            .ok_or_else(WorkspaceApiError::edge_not_found)
    }

    async fn update_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
        body: TopologyEdgeUpdatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let mut edge = state
            .edges
            .get(edge_id)
            .filter(|edge| edge.workspace_id == workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::edge_not_found)?;
        if body.source_node_id.is_some() || body.target_node_id.is_some() {
            edge.source_node_id = body.source_node_id.unwrap_or(edge.source_node_id);
            edge.target_node_id = body.target_node_id.unwrap_or(edge.target_node_id);
            let Some(source) = state
                .nodes
                .get(&edge.source_node_id)
                .filter(|node| node.workspace_id == workspace_id)
            else {
                return Err(WorkspaceApiError::bad_request(
                    "Edge endpoints must exist in same workspace",
                ));
            };
            let Some(target) = state
                .nodes
                .get(&edge.target_node_id)
                .filter(|node| node.workspace_id == workspace_id)
            else {
                return Err(WorkspaceApiError::bad_request(
                    "Edge endpoints must exist in same workspace",
                ));
            };
            edge.source_hex_q = source.hex_q;
            edge.source_hex_r = source.hex_r;
            edge.target_hex_q = target.hex_q;
            edge.target_hex_r = target.hex_r;
        }
        if body.label.is_some() {
            edge.label = body.label;
        }
        if body.direction.is_some() {
            edge.direction = body.direction;
        }
        if let Some(auto_created) = body.auto_created {
            edge.auto_created = auto_created;
        }
        if let Some(data) = body.data {
            edge.data_json = object_or_empty(data);
        }
        edge.updated_at = Some(Utc::now());
        state.edges.insert(edge.id.clone(), edge.clone());
        Ok(edge.into())
    }

    async fn delete_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .edges
            .get(edge_id)
            .map(|edge| edge.workspace_id == workspace_id)
            .unwrap_or(false);
        if !in_scope || state.edges.remove(edge_id).is_none() {
            return Err(WorkspaceApiError::edge_not_found());
        }
        Ok(())
    }

    async fn create_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: BlackboardPostCreatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.title, "title")?;
        validate_non_empty(&body.content, "content")?;
        validate_post_status(&body.status)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let post = BlackboardPostRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            author_id: user_id.to_string(),
            title: body.title,
            content: body.content,
            status: body.status,
            is_pinned: body.is_pinned,
            metadata_json: object_or_empty(body.metadata),
            created_at: Utc::now(),
            updated_at: None,
        };
        state.posts.insert(post.id.clone(), post.clone());
        let view = BlackboardPostView::from(post);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_post_created".to_string(),
            payload_json: json!({ "post": view, "workspace_id": workspace_id, "post_id": view.id }),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn list_posts(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardPostListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let limit = clamp_limit(query.limit, 50, 200) as usize;
        let offset = query.offset.unwrap_or(0).max(0) as usize;
        let mut posts: Vec<_> = state
            .posts
            .values()
            .filter(|post| post.workspace_id == workspace_id)
            .cloned()
            .collect();
        posts.sort_by(|a, b| {
            b.is_pinned
                .cmp(&a.is_pinned)
                .then(b.created_at.cmp(&a.created_at))
                .then(a.id.cmp(&b.id))
        });
        Ok(BlackboardPostListView {
            items: posts
                .into_iter()
                .skip(offset)
                .take(limit)
                .map(BlackboardPostView::from)
                .collect(),
        })
    }

    async fn get_post(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        self.lock_state()?
            .posts
            .get(post_id)
            .filter(|post| post.workspace_id == workspace_id)
            .cloned()
            .map(BlackboardPostView::from)
            .ok_or_else(WorkspaceApiError::blackboard_not_found)
    }

    async fn update_post(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardPostUpdatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let post = state
            .posts
            .get_mut(post_id)
            .filter(|post| post.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if let Some(title) = body.title {
            validate_non_empty(&title, "title")?;
            post.title = title;
        }
        if let Some(content) = body.content {
            validate_non_empty(&content, "content")?;
            post.content = content;
        }
        if let Some(status) = body.status {
            validate_post_status(&status)?;
            post.status = status;
        }
        if let Some(is_pinned) = body.is_pinned {
            post.is_pinned = is_pinned;
        }
        if let Some(metadata) = body.metadata {
            post.metadata_json = object_or_empty(metadata);
        }
        post.updated_at = Some(Utc::now());
        Ok(post.clone().into())
    }

    async fn delete_post(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .posts
            .get(post_id)
            .map(|post| post.workspace_id == workspace_id)
            .unwrap_or(false);
        if !in_scope || state.posts.remove(post_id).is_none() {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        state.replies.retain(|_, reply| reply.post_id != post_id);
        Ok(DeletedView { deleted: true })
    }

    async fn create_reply(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardReplyCreatePayload,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.content, "content")?;
        let mut state = self.lock_state()?;
        if !state
            .posts
            .get(post_id)
            .map(|post| post.workspace_id == workspace_id)
            .unwrap_or(false)
        {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        let reply = BlackboardReplyRecord {
            id: new_id(),
            post_id: post_id.to_string(),
            workspace_id: workspace_id.to_string(),
            author_id: user_id.to_string(),
            content: body.content,
            metadata_json: object_or_empty(body.metadata),
            created_at: Utc::now(),
            updated_at: None,
        };
        state.replies.insert(reply.id.clone(), reply.clone());
        Ok(reply.into())
    }

    async fn list_replies(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardReplyListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let limit = clamp_limit(query.limit, 200, 500) as usize;
        let offset = query.offset.unwrap_or(0).max(0) as usize;
        let mut replies: Vec<_> = self
            .lock_state()?
            .replies
            .values()
            .filter(|reply| reply.workspace_id == workspace_id && reply.post_id == post_id)
            .cloned()
            .collect();
        replies.sort_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)));
        Ok(BlackboardReplyListView {
            items: replies
                .into_iter()
                .skip(offset)
                .take(limit)
                .map(BlackboardReplyView::from)
                .collect(),
        })
    }

    async fn update_reply(
        &self,
        input: WorkspaceReplyUpdateInput<'_>,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        let WorkspaceReplyUpdateInput {
            user_id,
            workspace_id,
            post_id,
            reply_id,
            body,
            ..
        } = input;
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.content, "content")?;
        let mut state = self.lock_state()?;
        let reply = state
            .replies
            .get_mut(reply_id)
            .filter(|reply| reply.workspace_id == workspace_id && reply.post_id == post_id)
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        reply.content = body.content;
        if let Some(metadata) = body.metadata {
            reply.metadata_json = object_or_empty(metadata);
        }
        reply.updated_at = Some(Utc::now());
        Ok(reply.clone().into())
    }

    async fn delete_reply(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .replies
            .get(reply_id)
            .map(|reply| reply.workspace_id == workspace_id && reply.post_id == post_id)
            .unwrap_or(false);
        if !in_scope || state.replies.remove(reply_id).is_none() {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        Ok(DeletedView { deleted: true })
    }

    async fn list_files(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: BlackboardFileListQuery,
    ) -> Result<BlackboardFileListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let parent_path = validate_file_path(query.parent_path.as_deref().unwrap_or("/"))?;
        let state = self.lock_state()?;
        if !workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut files: Vec<_> = state
            .files
            .values()
            .filter(|file| file.workspace_id == workspace_id && file.parent_path == parent_path)
            .cloned()
            .collect();
        sort_files(&mut files);
        Ok(BlackboardFileListView {
            items: files.into_iter().map(BlackboardFileView::from).collect(),
        })
    }

    async fn create_directory(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: MkdirPayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let parent_path = validate_file_path(&body.parent_path)?;
        let name = validate_filename(&body.name)?;
        let mut state = self.lock_state()?;
        if !workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        if parent_path != "/" {
            require_directory_exists_dev(&state, workspace_id, &parent_path)?;
        }
        ensure_file_name_available_dev(&state, workspace_id, &parent_path, &name)?;
        let file = BlackboardFileRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            parent_path,
            name,
            is_directory: true,
            file_size: 0,
            content_type: String::new(),
            storage_key: String::new(),
            uploader_type: "user".to_string(),
            uploader_id: user_id.to_string(),
            uploader_name: user_id.to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at: Utc::now(),
        };
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn upload_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        upload: BlackboardUpload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        if upload.bytes.len() > MAX_FILE_SIZE {
            return Err(WorkspaceApiError::bad_request(format!(
                "File exceeds maximum size of {MAX_FILE_SIZE} bytes"
            )));
        }
        let parent_path = validate_file_path(&upload.parent_path)?;
        let filename = validate_filename(&upload.filename)?;
        {
            let state = self.lock_state()?;
            if !workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            if parent_path != "/" {
                require_directory_exists_dev(&state, workspace_id, &parent_path)?;
            }
            ensure_file_name_available_dev(&state, workspace_id, &parent_path, &filename)?;
        }
        let file_id = new_id();
        let content_type = upload
            .content_type
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| guess_content_type(&filename));
        let file_size = upload.bytes.len().min(i32::MAX as usize) as i32;
        let storage_key = format!("{file_id}/{filename}");
        self.object_store
            .put(
                &self.object_key(workspace_id, &storage_key),
                upload.bytes,
                Some(&content_type),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        let file = BlackboardFileRecord {
            id: file_id,
            workspace_id: workspace_id.to_string(),
            parent_path,
            name: filename,
            is_directory: false,
            file_size,
            content_type,
            storage_key,
            uploader_type: "user".to_string(),
            uploader_id: user_id.to_string(),
            uploader_name: user_id.to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at: Utc::now(),
        };
        let mut state = self.lock_state()?;
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn download_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
    ) -> Result<BlackboardFileDownload, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let file = {
            let state = self.lock_state()?;
            if !workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?
        };
        if file.is_directory {
            return Err(WorkspaceApiError::bad_request(
                "Cannot read directory content",
            ));
        }
        let bytes = self
            .object_store
            .get(&self.object_key(workspace_id, &file.storage_key))
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(|| {
                WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found")
            })?;
        Ok(BlackboardFileDownload {
            filename: file.name,
            content_type: if file.content_type.is_empty() {
                "application/octet-stream".to_string()
            } else {
                file.content_type
            },
            file_size: file.file_size,
            etag: file
                .checksum_sha256
                .map(|checksum| format!("\"{checksum}\""))
                .unwrap_or_else(|| format!("W/\"sz-{}-id-{}\"", file.file_size, file.id)),
            bytes,
        })
    }

    async fn patch_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: RenameOrMoveFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        if body.name.is_none() && body.parent_path.is_none() {
            return Err(WorkspaceApiError::bad_request(
                "Provide at least one of 'name' or 'parent_path'",
            ));
        }
        let mut state = self.lock_state()?;
        if !workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut file = state
            .files
            .get(file_id)
            .filter(|file| file.workspace_id == workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if let Some(parent_path) = body.parent_path {
            let target_parent = validate_file_path(&parent_path)?;
            if target_parent != file.parent_path {
                if target_parent != "/" {
                    require_directory_exists_dev(&state, workspace_id, &target_parent)?;
                }
                if file.is_directory {
                    let own_prefix = join_child_path(&file.parent_path, &file.name)?;
                    if target_parent == own_prefix || target_parent.starts_with(&own_prefix) {
                        return Err(WorkspaceApiError::bad_request(
                            "Cannot move a directory into itself",
                        ));
                    }
                    let new_prefix = join_child_path(&target_parent, &file.name)?;
                    bulk_update_parent_path_dev(&mut state, workspace_id, &own_prefix, &new_prefix);
                }
                ensure_file_name_available_dev(&state, workspace_id, &target_parent, &file.name)?;
                file.parent_path = target_parent;
            }
        }
        if let Some(name) = body.name {
            let safe_name = validate_filename(&name)?;
            if safe_name != file.name {
                ensure_file_name_available_dev(
                    &state,
                    workspace_id,
                    &file.parent_path,
                    &safe_name,
                )?;
                if file.is_directory {
                    let old_prefix = join_child_path(&file.parent_path, &file.name)?;
                    let new_prefix = join_child_path(&file.parent_path, &safe_name)?;
                    bulk_update_parent_path_dev(&mut state, workspace_id, &old_prefix, &new_prefix);
                }
                file.name = safe_name;
            }
        }
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_updated".to_string(),
            payload_json: json!({ "file": view, "file_id": view.id }),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn copy_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: CopyFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let source;
        let target_parent = validate_file_path(&body.target_parent_path)?;
        let copy_name;
        {
            let state = self.lock_state()?;
            if !workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            source = state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
            if target_parent != "/" {
                require_directory_exists_dev(&state, workspace_id, &target_parent)?;
            }
            copy_name = validate_filename(body.name.as_deref().unwrap_or(&source.name))?;
            ensure_file_name_available_dev(&state, workspace_id, &target_parent, &copy_name)?;
        }
        let copied = if source.is_directory {
            copy_directory_dev(
                self,
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        } else {
            copy_single_file_dev(
                self,
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        };
        let mut state = self.lock_state()?;
        let view = BlackboardFileView::from(copied);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn delete_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        query: DeleteFileQuery,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let (file, descendants) = {
            let state = self.lock_state()?;
            if !workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            let file = state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
            let descendants = if file.is_directory {
                let child_path = join_child_path(&file.parent_path, &file.name)?;
                let children = list_files_dev(&state, workspace_id, &child_path);
                if !children.is_empty() && !query.recursive {
                    return Err(WorkspaceApiError::bad_request("Directory is not empty"));
                }
                find_descendants_dev(&state, workspace_id, &child_path)
            } else {
                Vec::new()
            };
            (file, descendants)
        };
        for descendant in &descendants {
            if !descendant.is_directory && !descendant.storage_key.is_empty() {
                self.object_store
                    .delete(&self.object_key(workspace_id, &descendant.storage_key))
                    .await
                    .map_err(WorkspaceApiError::internal)?;
            }
        }
        if !file.is_directory && !file.storage_key.is_empty() {
            self.object_store
                .delete(&self.object_key(workspace_id, &file.storage_key))
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        let mut state = self.lock_state()?;
        for descendant in descendants {
            state.files.remove(&descendant.id);
        }
        if state.files.remove(file_id).is_none() {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: if file.is_directory {
                "blackboard_directory_deleted".to_string()
            } else {
                "blackboard_file_deleted".to_string()
            },
            payload_json: json!({
                "workspace_id": workspace_id,
                "file_id": file_id,
                "deleted": true,
                "recursive": query.recursive,
                "is_directory": file.is_directory
            }),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(DeletedView { deleted: true })
    }
}

impl From<WorkspaceRecord> for WorkspaceView {
    fn from(record: WorkspaceRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            project_id: record.project_id,
            name: record.name,
            created_by: record.created_by,
            description: record.description,
            is_archived: record.is_archived,
            metadata: record.metadata_json,
            office_status: record.office_status,
            hex_layout_config: record.hex_layout_config_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<WorkspaceTaskRecord> for WorkspaceTaskView {
    fn from(record: WorkspaceTaskRecord) -> Self {
        let metadata = object_or_empty(record.metadata_json);
        let workspace_agent_id = string_field(&metadata, "workspace_agent_binding_id");
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            title: record.title,
            description: record.description,
            created_by: record.created_by,
            assignee_user_id: record.assignee_user_id,
            assignee_agent_id: record.assignee_agent_id,
            workspace_agent_id,
            current_attempt_id: string_field(&metadata, "current_attempt_id"),
            current_attempt_number: metadata
                .get("current_attempt_number")
                .and_then(|value| value.as_i64()),
            current_attempt_conversation_id: string_field(
                &metadata,
                "current_attempt_conversation_id",
            ),
            current_attempt_worker_binding_id: string_field(
                &metadata,
                "current_attempt_worker_binding_id",
            ),
            current_attempt_worker_agent_id: string_field(
                &metadata,
                "current_attempt_worker_agent_id",
            ),
            last_attempt_status: string_field(&metadata, "last_attempt_status"),
            pending_leader_adjudication: metadata
                .get("pending_leader_adjudication")
                .and_then(|value| value.as_bool())
                .unwrap_or(false),
            last_worker_report_type: string_field(&metadata, "last_worker_report_type"),
            last_worker_report_summary: string_field(&metadata, "last_worker_report_summary"),
            last_worker_report_artifacts: string_array_field(
                &metadata,
                "last_worker_report_artifacts",
            ),
            last_worker_report_verifications: string_array_field(
                &metadata,
                "last_worker_report_verifications",
            ),
            status: record.status,
            metadata,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
            priority: public_priority(record.priority),
            estimated_effort: record.estimated_effort,
            blocker_reason: record.blocker_reason,
            completed_at: record.completed_at.map(iso),
            archived_at: record.archived_at.map(iso),
        }
    }
}

impl From<WorkspaceMessageRecord> for MessageView {
    fn from(record: WorkspaceMessageRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            sender_id: record.sender_id,
            sender_type: record.sender_type,
            content: record.content,
            mentions: record.mentions_json,
            parent_message_id: record.parent_message_id,
            metadata: record.metadata_json,
            created_at: iso(record.created_at),
        }
    }
}

impl From<TopologyNodeRecord> for TopologyNodeView {
    fn from(record: TopologyNodeRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            node_type: record.node_type,
            ref_id: record.ref_id,
            title: record.title,
            position_x: record.position_x,
            position_y: record.position_y,
            hex_q: record.hex_q,
            hex_r: record.hex_r,
            status: record.status,
            tags: record.tags_json,
            data: record.data_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<TopologyEdgeRecord> for TopologyEdgeView {
    fn from(record: TopologyEdgeRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            source_node_id: record.source_node_id,
            target_node_id: record.target_node_id,
            label: record.label,
            source_hex_q: record.source_hex_q,
            source_hex_r: record.source_hex_r,
            target_hex_q: record.target_hex_q,
            target_hex_r: record.target_hex_r,
            direction: record.direction,
            auto_created: record.auto_created,
            data: record.data_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<BlackboardPostRecord> for BlackboardPostView {
    fn from(record: BlackboardPostRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            author_id: record.author_id,
            title: record.title,
            content: record.content,
            status: record.status,
            is_pinned: record.is_pinned,
            metadata: record.metadata_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<BlackboardReplyRecord> for BlackboardReplyView {
    fn from(record: BlackboardReplyRecord) -> Self {
        Self {
            id: record.id,
            post_id: record.post_id,
            workspace_id: record.workspace_id,
            author_id: record.author_id,
            content: record.content,
            metadata: record.metadata_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<BlackboardFileRecord> for BlackboardFileView {
    fn from(record: BlackboardFileRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            parent_path: record.parent_path,
            name: record.name,
            is_directory: record.is_directory,
            file_size: record.file_size,
            content_type: record.content_type,
            uploader_type: record.uploader_type,
            uploader_id: record.uploader_id,
            uploader_name: record.uploader_name,
            created_at: iso(record.created_at),
        }
    }
}

fn phase_label(phase: &str) -> String {
    match phase {
        "research" => "Research",
        "plan" => "Plan",
        "implement" => "Implement",
        "test" => "Test",
        "deploy" => "Deploy",
        "review" => "Review",
        _ => phase,
    }
    .to_string()
}

fn string_from_value(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn int_from_value(value: Option<&Value>, fallback: i32) -> i32 {
    value
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_str().and_then(|text| text.parse::<i64>().ok()))
        })
        .filter(|value| *value >= 0)
        .map(|value| value as i32)
        .unwrap_or(fallback)
}

fn int_list_from_value(value: Option<&Value>) -> Vec<i32> {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_i64().map(|value| value as i32))
                .collect()
        })
        .unwrap_or_default()
}

fn metadata_string_values(value: &Value, keys: &[&str]) -> Vec<String> {
    let mut items = Vec::new();
    for key in keys {
        items.extend(string_values(value.get(*key)));
    }
    dedup_truncate(&mut items, usize::MAX);
    items
}

fn string_values(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::String(text)) if !text.is_empty() => vec![text.clone()],
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|item| item.as_str().filter(|text| !text.is_empty()))
            .map(ToOwned::to_owned)
            .collect(),
        _ => Vec::new(),
    }
}

fn first_metadata_string(value: &Value, keys: &[&str]) -> String {
    keys.iter()
        .find_map(|key| string_from_value(value.get(*key)))
        .unwrap_or_default()
}

fn dedup_truncate(items: &mut Vec<String>, limit: usize) {
    let mut seen = std::collections::HashSet::new();
    items.retain(|item| seen.insert(item.clone()));
    if items.len() > limit {
        items.truncate(limit);
    }
}

fn compose_workspace_metadata(body: WorkspaceCreatePayload) -> Value {
    let mut metadata = object_or_empty(body.metadata);
    let use_case = body.use_case.unwrap_or_else(|| {
        metadata
            .get("workspace_use_case")
            .and_then(|value| value.as_str())
            .unwrap_or("general")
            .to_string()
    });
    let workspace_type = match use_case.as_str() {
        "programming" => "software_development",
        "research" => "research",
        "operations" => "operations",
        _ => "general",
    };
    let collaboration_mode = body.collaboration_mode.unwrap_or_else(|| {
        metadata
            .get("collaboration_mode")
            .and_then(|value| value.as_str())
            .unwrap_or("single_agent")
            .to_string()
    });
    metadata["workspace_use_case"] = json!(use_case);
    metadata["workspace_type"] = json!(workspace_type);
    metadata["collaboration_mode"] = json!(collaboration_mode);
    metadata["agent_conversation_mode"] = json!(collaboration_mode);
    let mut profile = object_or_empty(body.autonomy_profile.unwrap_or_else(|| json!({})));
    profile["workspace_type"] = json!(workspace_type);
    metadata["autonomy_profile"] = profile;
    if let Some(root) = body
        .sandbox_code_root
        .filter(|value| !value.trim().is_empty())
    {
        metadata["sandbox_code_root"] = json!(root);
    }
    metadata
}

fn apply_task_update(
    task: &mut WorkspaceTaskRecord,
    body: WorkspaceTaskUpdatePayload,
) -> Result<(), WorkspaceApiError> {
    if let Some(title) = body.title {
        validate_non_empty(&title, "title")?;
        task.title = title;
    }
    if body.description.is_some() {
        task.description = body.description;
    }
    if body.assignee_user_id.is_some() {
        task.assignee_user_id = body.assignee_user_id;
    }
    if let Some(status) = body.status {
        validate_task_status(&status)?;
        task.status = status;
        task.completed_at = if task.status == "done" {
            Some(Utc::now())
        } else {
            None
        };
    }
    if let Some(metadata) = body.metadata {
        task.metadata_json = object_or_empty(metadata);
    }
    if let Some(priority) = body.priority {
        task.priority = priority_rank(Some(&priority))?;
    }
    if body.estimated_effort.is_some() {
        task.estimated_effort = body.estimated_effort;
    }
    if body.blocker_reason.is_some() {
        task.blocker_reason = body.blocker_reason;
    }
    task.updated_at = Some(Utc::now());
    Ok(())
}

fn apply_task_transition(
    task: &mut WorkspaceTaskRecord,
    action: TaskTransitionAction,
    user_id: &str,
) {
    match action {
        TaskTransitionAction::Claim => task.assignee_user_id = Some(user_id.to_string()),
        TaskTransitionAction::Start => task.status = "in_progress".to_string(),
        TaskTransitionAction::Block => task.status = "blocked".to_string(),
        TaskTransitionAction::Complete => {
            task.status = "done".to_string();
            task.completed_at = Some(Utc::now());
        }
        TaskTransitionAction::UnassignAgent => {
            task.assignee_agent_id = None;
            if let Some(obj) = task.metadata_json.as_object_mut() {
                obj.remove("workspace_agent_binding_id");
            }
        }
    }
    task.updated_at = Some(Utc::now());
}

fn validate_non_empty(value: &str, field: &str) -> Result<(), WorkspaceApiError> {
    if value.trim().is_empty() {
        return Err(WorkspaceApiError::bad_request(format!(
            "{field} cannot be empty"
        )));
    }
    Ok(())
}

fn validate_task_status(value: &str) -> Result<(), WorkspaceApiError> {
    match value {
        "todo" | "in_progress" | "blocked" | "done" | "dispatched" | "executing" | "reported"
        | "adjudicating" => Ok(()),
        _ => Err(WorkspaceApiError::bad_request("Invalid task status")),
    }
}

fn validate_node_type(value: &str) -> Result<(), WorkspaceApiError> {
    match value {
        "user" | "agent" | "task" | "note" | "corridor" | "human_seat" | "objective" => Ok(()),
        _ => Err(WorkspaceApiError::bad_request("Invalid topology request")),
    }
}

fn validate_post_status(value: &str) -> Result<(), WorkspaceApiError> {
    match value {
        "open" | "archived" => Ok(()),
        _ => Err(WorkspaceApiError::bad_request("Invalid blackboard request")),
    }
}

fn priority_rank(value: Option<&str>) -> Result<i32, WorkspaceApiError> {
    match value.unwrap_or("") {
        "" => Ok(0),
        "P1" => Ok(1),
        "P2" => Ok(2),
        "P3" => Ok(3),
        "P4" => Ok(4),
        _ => Err(WorkspaceApiError::bad_request("Invalid task priority")),
    }
}

fn public_priority(rank: i32) -> String {
    match rank {
        1 => "P1",
        2 => "P2",
        3 => "P3",
        4 => "P4",
        _ => "",
    }
    .to_string()
}

fn default_post_status() -> String {
    "open".to_string()
}

fn default_sender_type() -> String {
    "human".to_string()
}

fn resolve_structured_mentions(
    requested: &[String],
    member_ids: &[String],
    agent_ids: &[String],
) -> Result<Vec<String>, WorkspaceApiError> {
    let requested: Vec<_> = requested
        .iter()
        .map(|mention| mention.trim())
        .filter(|mention| !mention.is_empty())
        .map(ToOwned::to_owned)
        .collect();
    if requested.is_empty() {
        return Ok(Vec::new());
    }
    if requested
        .iter()
        .any(|mention| mention.eq_ignore_ascii_case("all"))
    {
        return Ok(agent_ids.to_vec());
    }
    let valid: HashSet<&str> = member_ids
        .iter()
        .chain(agent_ids.iter())
        .map(String::as_str)
        .collect();
    let mut seen = HashSet::new();
    let mut mentions = Vec::new();
    for mention in requested {
        if !valid.contains(mention.as_str()) {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace chat request",
            ));
        }
        if seen.insert(mention.clone()) {
            mentions.push(mention);
        }
    }
    Ok(mentions)
}

struct WorkspaceAgentMentionOutboxInput<'a> {
    tenant_id: &'a str,
    project_id: &'a str,
    workspace_id: &'a str,
    sender_user_id: &'a str,
    sender_name: &'a str,
    message: &'a MessageView,
    agents: &'a [WorkspaceAgentRecord],
    now: DateTime<Utc>,
}

fn workspace_agent_mention_outbox_records(
    input: WorkspaceAgentMentionOutboxInput<'_>,
) -> Vec<WorkspacePlanOutboxRecord> {
    let conversation_scope = workspace_message_conversation_scope(&input.message.metadata);
    input
        .message
        .mentions
        .iter()
        .filter_map(|mention| input.agents.iter().find(|agent| agent.agent_id == *mention))
        .map(|agent| {
            let agent_name = workspace_agent_display_name(agent).to_string();
            let conversation_id = workspace_conversation_id(
                input.workspace_id,
                &agent.agent_id,
                conversation_scope.as_deref(),
            );
            let payload_json = json!({
                "workspace_id": input.workspace_id,
                "tenant_id": input.tenant_id,
                "project_id": input.project_id,
                "message_id": &input.message.id,
                "parent_message_id": &input.message.parent_message_id,
                "sender_user_id": input.sender_user_id,
                "sender_name": input.sender_name,
                "target_agent_id": &agent.agent_id,
                "target_workspace_agent_id": &agent.id,
                "agent_display_name": &agent.display_name,
                "agent_name": &agent_name,
                "conversation_id": &conversation_id,
                "conversation_scope": conversation_scope.clone(),
                "user_prompt": format!(
                    "[Workspace Chat] {} mentioned you:\n\n{}",
                    input.sender_name, input.message.content
                ),
                "source_message": {
                    "id": &input.message.id,
                    "content": &input.message.content,
                    "created_at": &input.message.created_at,
                    "mentions": &input.message.mentions,
                },
                "chain_depth": 0,
                "source": WORKSPACE_AGENT_MENTION_SOURCE,
                "workspace_llm_stage": WORKSPACE_AGENT_MENTION_STAGE,
            });
            WorkspacePlanOutboxRecord {
                id: new_id(),
                plan_id: None,
                workspace_id: input.workspace_id.to_string(),
                event_type: WORKSPACE_AGENT_MENTION_EVENT.to_string(),
                payload_json,
                status: WORKSPACE_AGENT_MENTION_STATUS.to_string(),
                attempt_count: 0,
                max_attempts: 5,
                lease_owner: None,
                lease_expires_at: None,
                last_error: None,
                next_attempt_at: None,
                processed_at: None,
                metadata_json: json!({
                    "tenant_id": input.tenant_id,
                    "project_id": input.project_id,
                    "surface_owner": "workspace-chat",
                    "surface_boundary": "hosted",
                    "authority_class": "agent-runtime-admission",
                    "signal_role": "runtime-trigger",
                    "runtime_bridge": "p3_workspace_mention",
                    "target_agent_id": &agent.agent_id,
                    "conversation_id": &conversation_id,
                    "message_id": &input.message.id,
                }),
                created_at: input.now,
                updated_at: None,
            }
        })
        .collect()
}

fn workspace_agent_display_name(agent: &WorkspaceAgentRecord) -> &str {
    agent
        .display_name
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(&agent.agent_id)
}

fn workspace_message_conversation_scope(metadata: &Value) -> Option<String> {
    metadata
        .get("conversation_scope")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn workspace_conversation_id(
    workspace_id: &str,
    agent_id: &str,
    conversation_scope: Option<&str>,
) -> String {
    let scope_suffix = conversation_scope
        .map(|scope| format!(":scope:{scope}"))
        .unwrap_or_default();
    Uuid::new_v5(
        &Uuid::NAMESPACE_DNS,
        format!("workspace:{workspace_id}:agent:{agent_id}{scope_suffix}").as_bytes(),
    )
    .to_string()
}

fn root_path() -> String {
    "/".to_string()
}

const BLOCKED_FILE_SEGMENTS: &[&str] = &[
    "credentials",
    "node_modules",
    ".env",
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
];
const MAX_FILE_SIZE: usize = 100 * 1024 * 1024;
const MAX_COPY_ENTRIES: usize = 500;

fn clamp_limit(limit: Option<i64>, default: i64, max: i64) -> i64 {
    limit.unwrap_or(default).clamp(1, max)
}

fn object_or_empty(value: Value) -> Value {
    if value.is_object() {
        value
    } else {
        json!({})
    }
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(|value| value.as_str())
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn string_array_field(value: &Value, key: &str) -> Vec<String> {
    value
        .get(key)
        .and_then(|value| value.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(ToOwned::to_owned))
                .collect()
        })
        .unwrap_or_default()
}

fn iso(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn new_id() -> String {
    generate_uuid_v4()
}

fn validate_file_path(path: &str) -> Result<String, WorkspaceApiError> {
    let raw = if path.trim().is_empty() {
        "/".to_string()
    } else {
        path.replace('\\', "/").trim().to_string()
    };
    let mut parts = Vec::new();
    for part in raw.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." {
            return Err(WorkspaceApiError::bad_request("Path traversal detected"));
        }
        if BLOCKED_FILE_SEGMENTS
            .iter()
            .any(|blocked| part.eq_ignore_ascii_case(blocked))
        {
            return Err(WorkspaceApiError::bad_request(format!(
                "Blocked path segment: {part}"
            )));
        }
        parts.push(part);
    }
    if parts.is_empty() {
        Ok("/".to_string())
    } else {
        Ok(format!("/{}/", parts.join("/")))
    }
}

fn validate_filename(filename: &str) -> Result<String, WorkspaceApiError> {
    let normalized = filename.replace('\\', "/");
    if normalized.is_empty()
        || normalized.contains('/')
        || normalized == "."
        || normalized == ".."
        || normalized.contains('\0')
    {
        return Err(WorkspaceApiError::bad_request("Invalid filename"));
    }
    if BLOCKED_FILE_SEGMENTS
        .iter()
        .any(|blocked| normalized.eq_ignore_ascii_case(blocked))
    {
        return Err(WorkspaceApiError::bad_request(format!(
            "Blocked path segment: {normalized}"
        )));
    }
    Ok(normalized)
}

fn join_child_path(parent_path: &str, name: &str) -> Result<String, WorkspaceApiError> {
    validate_file_path(&format!("{}/{}", parent_path.trim_end_matches('/'), name))
}

fn split_directory_path(path: &str) -> Result<(String, String), WorkspaceApiError> {
    let normalized = validate_file_path(path)?;
    if normalized == "/" {
        return Err(WorkspaceApiError::bad_request(
            "Root directory has no file record",
        ));
    }
    let mut parts: Vec<&str> = normalized.trim_matches('/').split('/').collect();
    let name = parts
        .pop()
        .ok_or_else(|| WorkspaceApiError::bad_request("Invalid directory path"))?;
    let parent = if parts.is_empty() {
        "/".to_string()
    } else {
        format!("/{}/", parts.join("/"))
    };
    Ok((parent, name.to_string()))
}

async fn require_directory_exists_pg(
    repo: &PgWorkspaceRepository,
    workspace_id: &str,
    path: &str,
) -> Result<(), WorkspaceApiError> {
    let (parent_path, name) = split_directory_path(path)?;
    let found = repo
        .find_file_by_path(workspace_id, &parent_path, &name)
        .await
        .map_err(WorkspaceApiError::internal)?;
    match found {
        Some(file) if file.is_directory => Ok(()),
        _ => Err(WorkspaceApiError::bad_request(
            "Destination directory not found",
        )),
    }
}

async fn ensure_file_name_available_pg(
    repo: &PgWorkspaceRepository,
    workspace_id: &str,
    parent_path: &str,
    name: &str,
) -> Result<(), WorkspaceApiError> {
    if repo
        .find_file_by_path(workspace_id, parent_path, name)
        .await
        .map_err(WorkspaceApiError::internal)?
        .is_some()
    {
        Err(WorkspaceApiError::conflict("File already exists"))
    } else {
        Ok(())
    }
}

fn map_file_storage_error(err: agistack_core::ports::CoreError) -> WorkspaceApiError {
    if err.to_string().contains("uq_blackboard_files_ws_path_name") {
        WorkspaceApiError::conflict("File already exists")
    } else {
        WorkspaceApiError::internal(err)
    }
}

fn workspace_in_scope_dev(
    state: &DevWorkspaceState,
    service: &DevWorkspaceService,
    workspace_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> bool {
    state
        .workspaces
        .get(workspace_id)
        .map(|workspace| service.workspace_matches(workspace, tenant_id, project_id))
        .unwrap_or(false)
}

fn find_file_by_path_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    parent_path: &str,
    name: &str,
) -> Option<BlackboardFileRecord> {
    state
        .files
        .values()
        .find(|file| {
            file.workspace_id == workspace_id
                && file.parent_path == parent_path
                && file.name == name
        })
        .cloned()
}

fn require_directory_exists_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    path: &str,
) -> Result<(), WorkspaceApiError> {
    let (parent_path, name) = split_directory_path(path)?;
    match find_file_by_path_dev(state, workspace_id, &parent_path, &name) {
        Some(file) if file.is_directory => Ok(()),
        _ => Err(WorkspaceApiError::bad_request(
            "Destination directory not found",
        )),
    }
}

fn ensure_file_name_available_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    parent_path: &str,
    name: &str,
) -> Result<(), WorkspaceApiError> {
    if find_file_by_path_dev(state, workspace_id, parent_path, name).is_some() {
        Err(WorkspaceApiError::conflict("File already exists"))
    } else {
        Ok(())
    }
}

fn list_files_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    parent_path: &str,
) -> Vec<BlackboardFileRecord> {
    let mut files: Vec<_> = state
        .files
        .values()
        .filter(|file| file.workspace_id == workspace_id && file.parent_path == parent_path)
        .cloned()
        .collect();
    sort_files(&mut files);
    files
}

fn find_descendants_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    path_prefix: &str,
) -> Vec<BlackboardFileRecord> {
    let mut files: Vec<_> = state
        .files
        .values()
        .filter(|file| {
            file.workspace_id == workspace_id && file.parent_path.starts_with(path_prefix)
        })
        .cloned()
        .collect();
    files.sort_by(|a, b| {
        a.parent_path
            .cmp(&b.parent_path)
            .then(b.is_directory.cmp(&a.is_directory))
            .then(a.name.cmp(&b.name))
    });
    files
}

fn sort_files(files: &mut [BlackboardFileRecord]) {
    files.sort_by(|a, b| {
        b.is_directory
            .cmp(&a.is_directory)
            .then(a.name.cmp(&b.name))
    });
}

fn bulk_update_parent_path_dev(
    state: &mut DevWorkspaceState,
    workspace_id: &str,
    old_prefix: &str,
    new_prefix: &str,
) {
    for file in state.files.values_mut() {
        if file.workspace_id == workspace_id {
            if file.parent_path == old_prefix {
                file.parent_path = new_prefix.to_string();
            } else if let Some(suffix) = file.parent_path.strip_prefix(old_prefix) {
                file.parent_path = format!("{new_prefix}{suffix}");
            }
        }
    }
}

fn object_key(workspace_id: &str, storage_key: &str) -> String {
    format!(
        "workspace-files/{}/{}",
        workspace_id.trim_matches('/'),
        storage_key.trim_start_matches('/')
    )
}

fn file_event_payload(workspace_id: &str, view: &BlackboardFileView) -> Value {
    json!({
        "file": view,
        "workspace_id": workspace_id,
        "file_id": view.id,
        "parent_path": view.parent_path,
        "name": view.name,
        "is_directory": view.is_directory,
    })
}

fn guess_content_type(filename: &str) -> String {
    match filename
        .rsplit('.')
        .next()
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "txt" | "md" | "log" => "text/plain",
        "json" => "application/json",
        "csv" => "text/csv",
        "html" | "htm" => "text/html",
        "css" => "text/css",
        "js" | "mjs" => "text/javascript",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "pdf" => "application/pdf",
        _ => "application/octet-stream",
    }
    .to_string()
}

fn content_disposition(filename: &str) -> String {
    let escaped = filename.replace('\\', "\\\\").replace('"', "\\\"");
    format!("attachment; filename=\"{escaped}\"")
}

async fn copy_single_file_pg(
    repo: &PgWorkspaceRepository,
    object_store: Arc<dyn ObjectStore>,
    workspace_id: &str,
    user_id: &str,
    source: &BlackboardFileRecord,
    target_parent: &str,
    copy_name: &str,
) -> Result<BlackboardFileRecord, WorkspaceApiError> {
    let bytes = object_store
        .get(&object_key(workspace_id, &source.storage_key))
        .await
        .map_err(WorkspaceApiError::internal)?
        .ok_or_else(|| WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found"))?;
    let new_id = new_id();
    let storage_key = format!("{new_id}/{copy_name}");
    object_store
        .put(
            &object_key(workspace_id, &storage_key),
            bytes,
            Some(&source.content_type),
        )
        .await
        .map_err(WorkspaceApiError::internal)?;
    repo.create_file(BlackboardFileRecord {
        id: new_id,
        workspace_id: workspace_id.to_string(),
        parent_path: target_parent.to_string(),
        name: copy_name.to_string(),
        is_directory: false,
        file_size: source.file_size,
        content_type: source.content_type.clone(),
        storage_key,
        uploader_type: "user".to_string(),
        uploader_id: user_id.to_string(),
        uploader_name: user_id.to_string(),
        checksum_sha256: source.checksum_sha256.clone(),
        mime_type_detected: source.mime_type_detected.clone(),
        created_at: Utc::now(),
    })
    .await
    .map_err(map_file_storage_error)
}

async fn copy_directory_pg(
    repo: &PgWorkspaceRepository,
    object_store: Arc<dyn ObjectStore>,
    workspace_id: &str,
    user_id: &str,
    source: &BlackboardFileRecord,
    target_parent: &str,
    copy_name: &str,
) -> Result<BlackboardFileRecord, WorkspaceApiError> {
    let old_prefix = join_child_path(&source.parent_path, &source.name)?;
    let descendants = repo
        .find_file_descendants(workspace_id, &old_prefix)
        .await
        .map_err(WorkspaceApiError::internal)?;
    if descendants.len() + 1 > MAX_COPY_ENTRIES {
        return Err(WorkspaceApiError::bad_request(
            "Directory copy is too large",
        ));
    }
    let root = repo
        .create_file(BlackboardFileRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            parent_path: target_parent.to_string(),
            name: copy_name.to_string(),
            is_directory: true,
            file_size: 0,
            content_type: String::new(),
            storage_key: String::new(),
            uploader_type: "user".to_string(),
            uploader_id: user_id.to_string(),
            uploader_name: user_id.to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at: Utc::now(),
        })
        .await
        .map_err(map_file_storage_error)?;
    let new_prefix = join_child_path(target_parent, copy_name)?;
    for descendant in descendants {
        let target_desc_parent =
            replace_parent_prefix(&descendant.parent_path, &old_prefix, &new_prefix);
        if descendant.is_directory {
            repo.create_file(BlackboardFileRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                parent_path: target_desc_parent,
                name: descendant.name,
                is_directory: true,
                file_size: 0,
                content_type: String::new(),
                storage_key: String::new(),
                uploader_type: "user".to_string(),
                uploader_id: user_id.to_string(),
                uploader_name: user_id.to_string(),
                checksum_sha256: None,
                mime_type_detected: None,
                created_at: Utc::now(),
            })
            .await
            .map_err(map_file_storage_error)?;
        } else {
            copy_single_file_pg(
                repo,
                Arc::clone(&object_store),
                workspace_id,
                user_id,
                &descendant,
                &target_desc_parent,
                &descendant.name,
            )
            .await?;
        }
    }
    Ok(root)
}

async fn copy_single_file_dev(
    service: &DevWorkspaceService,
    workspace_id: &str,
    user_id: &str,
    source: &BlackboardFileRecord,
    target_parent: &str,
    copy_name: &str,
) -> Result<BlackboardFileRecord, WorkspaceApiError> {
    let bytes = service
        .object_store
        .get(&service.object_key(workspace_id, &source.storage_key))
        .await
        .map_err(WorkspaceApiError::internal)?
        .ok_or_else(|| WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found"))?;
    let new_id = new_id();
    let storage_key = format!("{new_id}/{copy_name}");
    service
        .object_store
        .put(
            &service.object_key(workspace_id, &storage_key),
            bytes,
            Some(&source.content_type),
        )
        .await
        .map_err(WorkspaceApiError::internal)?;
    let clone = BlackboardFileRecord {
        id: new_id,
        workspace_id: workspace_id.to_string(),
        parent_path: target_parent.to_string(),
        name: copy_name.to_string(),
        is_directory: false,
        file_size: source.file_size,
        content_type: source.content_type.clone(),
        storage_key,
        uploader_type: "user".to_string(),
        uploader_id: user_id.to_string(),
        uploader_name: user_id.to_string(),
        checksum_sha256: source.checksum_sha256.clone(),
        mime_type_detected: source.mime_type_detected.clone(),
        created_at: Utc::now(),
    };
    service
        .lock_state()?
        .files
        .insert(clone.id.clone(), clone.clone());
    Ok(clone)
}

async fn copy_directory_dev(
    service: &DevWorkspaceService,
    workspace_id: &str,
    user_id: &str,
    source: &BlackboardFileRecord,
    target_parent: &str,
    copy_name: &str,
) -> Result<BlackboardFileRecord, WorkspaceApiError> {
    let old_prefix = join_child_path(&source.parent_path, &source.name)?;
    let descendants = {
        let state = service.lock_state()?;
        find_descendants_dev(&state, workspace_id, &old_prefix)
    };
    if descendants.len() + 1 > MAX_COPY_ENTRIES {
        return Err(WorkspaceApiError::bad_request(
            "Directory copy is too large",
        ));
    }
    let root = BlackboardFileRecord {
        id: new_id(),
        workspace_id: workspace_id.to_string(),
        parent_path: target_parent.to_string(),
        name: copy_name.to_string(),
        is_directory: true,
        file_size: 0,
        content_type: String::new(),
        storage_key: String::new(),
        uploader_type: "user".to_string(),
        uploader_id: user_id.to_string(),
        uploader_name: user_id.to_string(),
        checksum_sha256: None,
        mime_type_detected: None,
        created_at: Utc::now(),
    };
    service
        .lock_state()?
        .files
        .insert(root.id.clone(), root.clone());
    let new_prefix = join_child_path(target_parent, copy_name)?;
    for descendant in descendants {
        let target_desc_parent =
            replace_parent_prefix(&descendant.parent_path, &old_prefix, &new_prefix);
        if descendant.is_directory {
            let clone = BlackboardFileRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                parent_path: target_desc_parent,
                name: descendant.name,
                is_directory: true,
                file_size: 0,
                content_type: String::new(),
                storage_key: String::new(),
                uploader_type: "user".to_string(),
                uploader_id: user_id.to_string(),
                uploader_name: user_id.to_string(),
                checksum_sha256: None,
                mime_type_detected: None,
                created_at: Utc::now(),
            };
            service.lock_state()?.files.insert(clone.id.clone(), clone);
        } else {
            copy_single_file_dev(
                service,
                workspace_id,
                user_id,
                &descendant,
                &target_desc_parent,
                &descendant.name,
            )
            .await?;
        }
    }
    Ok(root)
}

fn replace_parent_prefix(parent_path: &str, old_prefix: &str, new_prefix: &str) -> String {
    if parent_path == old_prefix {
        new_prefix.to_string()
    } else if let Some(suffix) = parent_path.strip_prefix(old_prefix) {
        format!("{new_prefix}{suffix}")
    } else {
        parent_path.to_string()
    }
}

async fn create_workspace(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Json(body): Json<WorkspaceCreatePayload>,
) -> Result<(StatusCode, Json<WorkspaceView>), WorkspaceApiError> {
    app.workspaces
        .create_workspace(&identity.user_id, &tenant_id, &project_id, body)
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn list_workspaces(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Query(query): Query<WorkspaceListQuery>,
) -> Result<Json<Vec<WorkspaceView>>, WorkspaceApiError> {
    app.workspaces
        .list_workspaces(&identity.user_id, &tenant_id, &project_id, query)
        .await
        .map(Json)
}

async fn get_workspace(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
) -> Result<Json<WorkspaceView>, WorkspaceApiError> {
    app.workspaces
        .get_workspace(&identity.user_id, &tenant_id, &project_id, &workspace_id)
        .await
        .map(Json)
}

async fn send_message(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<SendMessagePayload>,
) -> Result<(StatusCode, Json<MessageView>), WorkspaceApiError> {
    app.workspaces
        .send_message(
            &identity.user_id,
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn list_messages(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<MessageListQuery>,
) -> Result<Json<MessageListView>, WorkspaceApiError> {
    app.workspaces
        .list_messages(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            query,
        )
        .await
        .map(Json)
}

async fn list_mentions(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, target_id)): Path<(String, String, String, String)>,
    Query(query): Query<MessageMentionQuery>,
) -> Result<Json<MessageListView>, WorkspaceApiError> {
    app.workspaces
        .list_mentions(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &target_id,
            query,
        )
        .await
        .map(Json)
}

async fn get_plan_snapshot(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Query(query): Query<WorkspacePlanSnapshotQuery>,
) -> Result<Json<WorkspacePlanSnapshotView>, WorkspaceApiError> {
    app.workspaces
        .get_plan_snapshot(&identity.user_id, &workspace_id, query)
        .await
        .map(Json)
}

async fn retry_plan_outbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, outbox_id)): Path<(String, String)>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .retry_plan_outbox(&identity.user_id, &workspace_id, &outbox_id, body)
        .await
        .map(Json)
}

async fn recover_stale_attempts(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .recover_stale_attempts(&identity.user_id, &workspace_id, body)
        .await
        .map(Json)
}

async fn request_delivery_pipeline_run(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<WorkspacePlanPipelineRunRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .request_delivery_pipeline_run(&identity.user_id, &workspace_id, body)
        .await
        .map(Json)
}

async fn request_delivery_contract_regeneration(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .request_delivery_contract_regeneration(&identity.user_id, &workspace_id, body)
        .await
        .map(Json)
}

async fn request_plan_node_replan(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .request_plan_node_replan(&identity.user_id, &workspace_id, &node_id, body)
        .await
        .map(Json)
}

async fn reopen_plan_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .reopen_plan_node(&identity.user_id, &workspace_id, &node_id, body)
        .await
        .map(Json)
}

async fn accept_plan_node_review(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    Json(body): Json<WorkspacePlanActionRequest>,
) -> Result<Json<WorkspacePlanActionResultView>, WorkspaceApiError> {
    app.workspaces
        .accept_plan_node_review(&identity.user_id, &workspace_id, &node_id, body)
        .await
        .map(Json)
}

async fn update_workspace(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<WorkspaceUpdatePayload>,
) -> Result<Json<WorkspaceView>, WorkspaceApiError> {
    app.workspaces
        .update_workspace(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            body,
        )
        .await
        .map(Json)
}

async fn delete_workspace(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
) -> Result<StatusCode, WorkspaceApiError> {
    app.workspaces
        .delete_workspace(&identity.user_id, &tenant_id, &project_id, &workspace_id)
        .await
        .map(|()| StatusCode::NO_CONTENT)
}

async fn create_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<WorkspaceTaskCreatePayload>,
) -> Result<(StatusCode, Json<WorkspaceTaskView>), WorkspaceApiError> {
    app.workspaces
        .create_task(&identity.user_id, &workspace_id, body)
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn list_tasks(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Query(query): Query<TaskListQuery>,
) -> Result<Json<Vec<WorkspaceTaskView>>, WorkspaceApiError> {
    app.workspaces
        .list_tasks(&identity.user_id, &workspace_id, query)
        .await
        .map(Json)
}

async fn get_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    app.workspaces
        .get_task(&identity.user_id, &workspace_id, &task_id)
        .await
        .map(Json)
}

async fn update_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    Json(body): Json<WorkspaceTaskUpdatePayload>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    app.workspaces
        .update_task(&identity.user_id, &workspace_id, &task_id, body)
        .await
        .map(Json)
}

async fn delete_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<StatusCode, WorkspaceApiError> {
    app.workspaces
        .delete_task(&identity.user_id, &workspace_id, &task_id)
        .await
        .map(|()| StatusCode::NO_CONTENT)
}

async fn transition_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    action: TaskTransitionAction,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    app.workspaces
        .transition_task(&identity.user_id, &workspace_id, &task_id, action)
        .await
        .map(Json)
}

async fn create_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<TopologyNodeCreatePayload>,
) -> Result<(StatusCode, Json<TopologyNodeView>), WorkspaceApiError> {
    app.workspaces
        .create_node(&identity.user_id, &workspace_id, body)
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn list_nodes(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Query(query): Query<LimitOffset>,
) -> Result<Json<Vec<TopologyNodeView>>, WorkspaceApiError> {
    app.workspaces
        .list_nodes(&identity.user_id, &workspace_id, query)
        .await
        .map(Json)
}

async fn get_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
) -> Result<Json<TopologyNodeView>, WorkspaceApiError> {
    app.workspaces
        .get_node(&identity.user_id, &workspace_id, &node_id)
        .await
        .map(Json)
}

async fn update_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    Json(body): Json<TopologyNodeUpdatePayload>,
) -> Result<Json<TopologyNodeView>, WorkspaceApiError> {
    app.workspaces
        .update_node(&identity.user_id, &workspace_id, &node_id, body)
        .await
        .map(Json)
}

async fn delete_node(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, node_id)): Path<(String, String)>,
) -> Result<StatusCode, WorkspaceApiError> {
    app.workspaces
        .delete_node(&identity.user_id, &workspace_id, &node_id)
        .await
        .map(|()| StatusCode::NO_CONTENT)
}

async fn create_edge(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Json(body): Json<TopologyEdgeCreatePayload>,
) -> Result<(StatusCode, Json<TopologyEdgeView>), WorkspaceApiError> {
    app.workspaces
        .create_edge(&identity.user_id, &workspace_id, body)
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn list_edges(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(workspace_id): Path<String>,
    Query(query): Query<LimitOffset>,
) -> Result<Json<Vec<TopologyEdgeView>>, WorkspaceApiError> {
    app.workspaces
        .list_edges(&identity.user_id, &workspace_id, query)
        .await
        .map(Json)
}

async fn get_edge(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
) -> Result<Json<TopologyEdgeView>, WorkspaceApiError> {
    app.workspaces
        .get_edge(&identity.user_id, &workspace_id, &edge_id)
        .await
        .map(Json)
}

async fn update_edge(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
    Json(body): Json<TopologyEdgeUpdatePayload>,
) -> Result<Json<TopologyEdgeView>, WorkspaceApiError> {
    app.workspaces
        .update_edge(&identity.user_id, &workspace_id, &edge_id, body)
        .await
        .map(Json)
}

async fn delete_edge(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, edge_id)): Path<(String, String)>,
) -> Result<StatusCode, WorkspaceApiError> {
    app.workspaces
        .delete_edge(&identity.user_id, &workspace_id, &edge_id)
        .await
        .map(|()| StatusCode::NO_CONTENT)
}

async fn create_post(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<BlackboardPostCreatePayload>,
) -> Result<(StatusCode, Json<BlackboardPostView>), WorkspaceApiError> {
    app.workspaces
        .create_post(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn list_posts(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<LimitOffset>,
) -> Result<Json<BlackboardPostListView>, WorkspaceApiError> {
    app.workspaces
        .list_posts(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            query,
        )
        .await
        .map(Json)
}

async fn get_post(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
) -> Result<Json<BlackboardPostView>, WorkspaceApiError> {
    app.workspaces
        .get_post(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
        )
        .await
        .map(Json)
}

async fn update_post(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    Json(body): Json<BlackboardPostUpdatePayload>,
) -> Result<Json<BlackboardPostView>, WorkspaceApiError> {
    app.workspaces
        .update_post(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            body,
        )
        .await
        .map(Json)
}

async fn delete_post(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
) -> Result<Json<DeletedView>, WorkspaceApiError> {
    app.workspaces
        .delete_post(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
        )
        .await
        .map(Json)
}

async fn create_reply(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    Json(body): Json<BlackboardReplyCreatePayload>,
) -> Result<(StatusCode, Json<BlackboardReplyView>), WorkspaceApiError> {
    app.workspaces
        .create_reply(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn list_replies(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    Query(query): Query<LimitOffset>,
) -> Result<Json<BlackboardReplyListView>, WorkspaceApiError> {
    app.workspaces
        .list_replies(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            query,
        )
        .await
        .map(Json)
}

async fn update_reply(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id, reply_id)): Path<(
        String,
        String,
        String,
        String,
        String,
    )>,
    Json(body): Json<BlackboardReplyUpdatePayload>,
) -> Result<Json<BlackboardReplyView>, WorkspaceApiError> {
    app.workspaces
        .update_reply(WorkspaceReplyUpdateInput {
            user_id: &identity.user_id,
            tenant_id: &tenant_id,
            project_id: &project_id,
            workspace_id: &workspace_id,
            post_id: &post_id,
            reply_id: &reply_id,
            body,
        })
        .await
        .map(Json)
}

async fn delete_reply(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, post_id, reply_id)): Path<(
        String,
        String,
        String,
        String,
        String,
    )>,
) -> Result<Json<DeletedView>, WorkspaceApiError> {
    app.workspaces
        .delete_reply(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            &reply_id,
        )
        .await
        .map(Json)
}

async fn list_files(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<BlackboardFileListQuery>,
) -> Result<Json<BlackboardFileListView>, WorkspaceApiError> {
    app.workspaces
        .list_files(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            query,
        )
        .await
        .map(Json)
}

async fn create_directory(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(body): Json<MkdirPayload>,
) -> Result<(StatusCode, Json<BlackboardFileView>), WorkspaceApiError> {
    app.workspaces
        .create_directory(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn upload_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    multipart: Multipart,
) -> Result<(StatusCode, Json<BlackboardFileView>), WorkspaceApiError> {
    let upload = parse_upload(multipart).await?;
    app.workspaces
        .upload_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            upload,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn download_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    headers: HeaderMap,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
) -> Result<Response, WorkspaceApiError> {
    let download = app
        .workspaces
        .download_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &file_id,
        )
        .await?;
    if let Some(if_none_match) = headers
        .get(IF_NONE_MATCH)
        .and_then(|value| value.to_str().ok())
    {
        let candidates = if_none_match.split(',').map(str::trim);
        if candidates
            .into_iter()
            .any(|candidate| candidate == download.etag)
        {
            return response_with_headers(StatusCode::NOT_MODIFIED, &download, Vec::new());
        }
    }
    let bytes = download.bytes.clone();
    response_with_headers(StatusCode::OK, &download, bytes)
}

async fn patch_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    Json(body): Json<RenameOrMoveFilePayload>,
) -> Result<Json<BlackboardFileView>, WorkspaceApiError> {
    app.workspaces
        .patch_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &file_id,
            body,
        )
        .await
        .map(Json)
}

async fn copy_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    Json(body): Json<CopyFilePayload>,
) -> Result<(StatusCode, Json<BlackboardFileView>), WorkspaceApiError> {
    app.workspaces
        .copy_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &file_id,
            body,
        )
        .await
        .map(|view| (StatusCode::CREATED, Json(view)))
}

async fn delete_file(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    Query(query): Query<DeleteFileQuery>,
) -> Result<Json<DeletedView>, WorkspaceApiError> {
    app.workspaces
        .delete_file(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &file_id,
            query,
        )
        .await
        .map(Json)
}

async fn parse_upload(mut multipart: Multipart) -> Result<BlackboardUpload, WorkspaceApiError> {
    let mut parent_path = "/".to_string();
    let mut filename = None;
    let mut content_type = None;
    let mut bytes = None;
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|err| WorkspaceApiError::bad_request(format!("Invalid multipart upload: {err}")))?
    {
        let name = field.name().map(str::to_string);
        match name.as_deref() {
            Some("parent_path") => {
                parent_path = field.text().await.map_err(|err| {
                    WorkspaceApiError::bad_request(format!("Invalid multipart upload: {err}"))
                })?;
            }
            Some("file") => {
                filename = Some(field.file_name().unwrap_or("unnamed").to_string());
                content_type = field.content_type().map(str::to_string);
                bytes = Some(
                    field
                        .bytes()
                        .await
                        .map_err(|err| {
                            WorkspaceApiError::bad_request(format!(
                                "Invalid multipart upload: {err}"
                            ))
                        })?
                        .to_vec(),
                );
            }
            _ => {}
        }
    }
    Ok(BlackboardUpload {
        parent_path,
        filename: filename.unwrap_or_else(|| "unnamed".to_string()),
        content_type,
        bytes: bytes.ok_or_else(|| WorkspaceApiError::bad_request("Missing upload file"))?,
    })
}

fn response_with_headers(
    status: StatusCode,
    download: &BlackboardFileDownload,
    bytes: Vec<u8>,
) -> Result<Response, WorkspaceApiError> {
    let mut response = Response::builder().status(status);
    let headers = response
        .headers_mut()
        .ok_or_else(|| WorkspaceApiError::internal("response headers unavailable"))?;
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_str(&download.content_type)
            .map_err(|err| WorkspaceApiError::internal(format!("content-type: {err}")))?,
    );
    headers.insert(
        CONTENT_DISPOSITION,
        HeaderValue::from_str(&content_disposition(&download.filename))
            .map_err(|err| WorkspaceApiError::internal(format!("content-disposition: {err}")))?,
    );
    headers.insert(
        CONTENT_LENGTH,
        HeaderValue::from_str(&download.file_size.max(0).to_string())
            .map_err(|err| WorkspaceApiError::internal(format!("content-length: {err}")))?,
    );
    headers.insert(CACHE_CONTROL, HeaderValue::from_static("private, no-cache"));
    headers.insert(ACCEPT_RANGES, HeaderValue::from_static("bytes"));
    headers.insert(
        ETAG,
        HeaderValue::from_str(&download.etag)
            .map_err(|err| WorkspaceApiError::internal(format!("etag: {err}")))?,
    );
    response
        .body(Body::from(bytes))
        .map_err(|err| WorkspaceApiError::internal(format!("response body: {err}")))
}

async fn claim_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::Claim,
    )
    .await
}

async fn start_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::Start,
    )
    .await
}

async fn block_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::Block,
    )
    .await
}

async fn complete_task(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::Complete,
    )
    .await
}

async fn unassign_agent(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((workspace_id, task_id)): Path<(String, String)>,
) -> Result<Json<WorkspaceTaskView>, WorkspaceApiError> {
    transition_task(
        State(app),
        Extension(identity),
        Path((workspace_id, task_id)),
        TaskTransitionAction::UnassignAgent,
    )
    .await
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces",
            post(create_workspace).get(list_workspaces),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id",
            get(get_workspace).patch(update_workspace).delete(delete_workspace),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/messages",
            post(send_message).get(list_messages),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/messages/mentions/:target_id",
            get(list_mentions),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/plan",
            get(get_plan_snapshot),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/plan/outbox/:outbox_id/retry",
            post(retry_plan_outbox),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/plan/recover-stale-attempts",
            post(recover_stale_attempts),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/plan/delivery/run-pipeline",
            post(request_delivery_pipeline_run),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/plan/delivery/regenerate-contract",
            post(request_delivery_contract_regeneration),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/plan/nodes/:node_id/request-replan",
            post(request_plan_node_replan),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/plan/nodes/:node_id/reopen",
            post(reopen_plan_node),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/plan/nodes/:node_id/accept-review",
            post(accept_plan_node_review),
        )
        .route("/api/v1/workspaces/:workspace_id/tasks", post(create_task).get(list_tasks))
        .route(
            "/api/v1/workspaces/:workspace_id/tasks/:task_id",
            get(get_task).patch(update_task).delete(delete_task),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/tasks/:task_id/claim",
            post(claim_task),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/tasks/:task_id/start",
            post(start_task),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/tasks/:task_id/block",
            post(block_task),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/tasks/:task_id/complete",
            post(complete_task),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/tasks/:task_id/unassign-agent",
            post(unassign_agent),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/topology/nodes",
            post(create_node).get(list_nodes),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/topology/nodes/:node_id",
            get(get_node).patch(update_node).delete(delete_node),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/topology/edges",
            post(create_edge).get(list_edges),
        )
        .route(
            "/api/v1/workspaces/:workspace_id/topology/edges/:edge_id",
            get(get_edge).patch(update_edge).delete(delete_edge),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/posts",
            post(create_post).get(list_posts),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/posts/:post_id",
            get(get_post).patch(update_post).delete(delete_post),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/posts/:post_id/replies",
            post(create_reply).get(list_replies),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/posts/:post_id/replies/:reply_id",
            patch(update_reply).delete(delete_reply),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/files",
            get(list_files),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/files/mkdir",
            post(create_directory),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/files/upload",
            post(upload_file),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/files/:file_id/download",
            get(download_file),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/files/:file_id",
            patch(patch_file).delete(delete_file),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/blackboard/files/:file_id/copy",
            post(copy_file),
        )
}

#[cfg(test)]
mod tests;
