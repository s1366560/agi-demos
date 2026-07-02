//! P6 workspace foundation over Python-owned workspace tables.
//!
//! This deliberately covers only precise, database-backed resources:
//! workspaces, workspace tasks, topology nodes/edges, and blackboard
//! posts/replies plus transactional outbox rows. Runtime-heavy siblings
//! (plan actions, execution diagnostics, files, leader adjudication) remain
//! Python-owned until their full semantics are migrated.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    BlackboardOutboxRecord, BlackboardPostRecord, BlackboardReplyRecord, PgWorkspaceRepository,
    TopologyEdgeRecord, TopologyNodeRecord, WorkspaceAccess, WorkspaceProjectAccess,
    WorkspaceRecord, WorkspaceTaskRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedWorkspaces = Arc<dyn WorkspaceService>;

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
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
        body: BlackboardReplyUpdatePayload,
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
pub(crate) struct DeletedView {
    deleted: bool,
}

pub(crate) struct PgWorkspaceService {
    repo: PgWorkspaceRepository,
}

impl PgWorkspaceService {
    pub(crate) fn new(repo: PgWorkspaceRepository) -> Self {
        Self { repo }
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
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
        body: BlackboardReplyUpdatePayload,
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
}

#[derive(Default)]
struct DevWorkspaceState {
    workspaces: HashMap<String, WorkspaceRecord>,
    tasks: HashMap<String, WorkspaceTaskRecord>,
    nodes: HashMap<String, TopologyNodeRecord>,
    edges: HashMap<String, TopologyEdgeRecord>,
    posts: HashMap<String, BlackboardPostRecord>,
    replies: HashMap<String, BlackboardReplyRecord>,
    outbox: Vec<BlackboardOutboxRecord>,
}

pub(crate) struct DevWorkspaceService {
    dev_user_id: String,
    state: Mutex<DevWorkspaceState>,
}

impl DevWorkspaceService {
    pub(crate) fn new(dev_user_id: impl Into<String>) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            state: Mutex::new(DevWorkspaceState::default()),
        }
    }

    fn require_dev_user(&self, user_id: &str) -> Result<(), WorkspaceApiError> {
        if user_id == self.dev_user_id {
            Ok(())
        } else {
            Err(WorkspaceApiError::forbidden())
        }
    }

    fn workspace_matches(
        &self,
        workspace: &WorkspaceRecord,
        tenant_id: &str,
        project_id: &str,
    ) -> bool {
        workspace.tenant_id == tenant_id && workspace.project_id == project_id
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
        self.state
            .lock()
            .expect("workspace dev state")
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
            .state
            .lock()
            .expect("workspace dev state")
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
        let state = self.state.lock().expect("workspace dev state");
        let workspace = state
            .workspaces
            .get(workspace_id)
            .filter(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .cloned()
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        Ok(workspace.into())
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
            .state
            .lock()
            .expect("workspace dev state")
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
        let state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
            .state
            .lock()
            .expect("workspace dev state")
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
        let state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
            .state
            .lock()
            .expect("workspace dev state")
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
        let state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let state = self.state.lock().expect("workspace dev state");
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
        self.state
            .lock()
            .expect("workspace dev state")
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
            .state
            .lock()
            .expect("workspace dev state")
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
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
        body: BlackboardReplyUpdatePayload,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.content, "content")?;
        let mut state = self.state.lock().expect("workspace dev state");
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
        let mut state = self.state.lock().expect("workspace dev state");
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
        .update_reply(
            &identity.user_id,
            &tenant_id,
            &project_id,
            &workspace_id,
            &post_id,
            &reply_id,
            body,
        )
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_parity::compare;

    fn canonical_workspace() -> WorkspaceRecord {
        WorkspaceRecord {
            id: "ws-00000000-0000-4000-8000-000000000001".to_string(),
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            name: "Core Workspace".to_string(),
            description: Some("Shared P6 surface".to_string()),
            created_by: "user-1".to_string(),
            is_archived: false,
            metadata_json: json!({
                "workspace_use_case": "programming",
                "workspace_type": "software_development",
                "collaboration_mode": "multi_agent_shared",
                "agent_conversation_mode": "multi_agent_shared",
                "autonomy_profile": {"workspace_type": "software_development"}
            }),
            office_status: "inactive".to_string(),
            hex_layout_config_json: json!({}),
            default_blocking_categories_json: Vec::new(),
            created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
            updated_at: None,
        }
    }

    fn assert_golden<T: Serialize>(actual: &T, golden: Value) {
        let actual = serde_json::to_value(actual).unwrap();
        let report = compare(&golden, &actual);
        assert!(report.is_match(), "{report:#?}\nactual={actual:#}");
    }

    #[test]
    fn workspace_response_matches_golden() {
        assert_golden(
            &WorkspaceView::from(canonical_workspace()),
            serde_json::from_str(include_str!("../tests/golden/workspace_response.json")).unwrap(),
        );
    }

    #[test]
    fn workspace_task_response_matches_golden() {
        let task = WorkspaceTaskRecord {
            id: "task-1".to_string(),
            workspace_id: "ws-1".to_string(),
            title: "Port P6".to_string(),
            description: Some("Move core workspace ledger".to_string()),
            created_by: "user-1".to_string(),
            assignee_user_id: Some("user-2".to_string()),
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: 2,
            estimated_effort: Some("M".to_string()),
            blocker_reason: None,
            metadata_json: json!({
                "workspace_agent_binding_id": "wa-1",
                "pending_leader_adjudication": true,
                "last_worker_report_artifacts": ["artifact-1"]
            }),
            created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
            updated_at: None,
            completed_at: None,
            archived_at: None,
        };
        assert_golden(
            &WorkspaceTaskView::from(task),
            serde_json::from_str(include_str!("../tests/golden/workspace_task_response.json"))
                .unwrap(),
        );
    }

    #[test]
    fn topology_responses_match_goldens() {
        let node = TopologyNodeRecord {
            id: "node-1".to_string(),
            workspace_id: "ws-1".to_string(),
            node_type: "task".to_string(),
            ref_id: Some("task-1".to_string()),
            title: "Port P6".to_string(),
            position_x: 1.5,
            position_y: -2.0,
            hex_q: Some(1),
            hex_r: Some(-1),
            status: "active".to_string(),
            tags_json: vec!["p6".to_string()],
            data_json: json!({"lane": "foundation"}),
            created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
            updated_at: None,
        };
        let edge = TopologyEdgeRecord {
            id: "edge-1".to_string(),
            workspace_id: "ws-1".to_string(),
            source_node_id: "node-1".to_string(),
            target_node_id: "node-2".to_string(),
            label: Some("depends_on".to_string()),
            source_hex_q: Some(1),
            source_hex_r: Some(-1),
            target_hex_q: Some(2),
            target_hex_r: Some(-1),
            direction: Some("forward".to_string()),
            auto_created: false,
            data_json: json!({}),
            created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
            updated_at: None,
        };
        assert_golden(
            &TopologyNodeView::from(node),
            serde_json::from_str(include_str!("../tests/golden/topology_node_response.json"))
                .unwrap(),
        );
        assert_golden(
            &TopologyEdgeView::from(edge),
            serde_json::from_str(include_str!("../tests/golden/topology_edge_response.json"))
                .unwrap(),
        );
    }

    #[test]
    fn blackboard_responses_match_goldens() {
        let post = BlackboardPostRecord {
            id: "post-1".to_string(),
            workspace_id: "ws-1".to_string(),
            author_id: "user-1".to_string(),
            title: "Status".to_string(),
            content: "P6 started".to_string(),
            status: "open".to_string(),
            is_pinned: true,
            metadata_json: json!({"lane": "p6"}),
            created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
            updated_at: None,
        };
        let reply = BlackboardReplyRecord {
            id: "reply-1".to_string(),
            post_id: "post-1".to_string(),
            workspace_id: "ws-1".to_string(),
            author_id: "user-2".to_string(),
            content: "ack".to_string(),
            metadata_json: json!({}),
            created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
            updated_at: None,
        };
        assert_golden(
            &BlackboardPostListView {
                items: vec![BlackboardPostView::from(post)],
            },
            serde_json::from_str(include_str!("../tests/golden/blackboard_post_list.json"))
                .unwrap(),
        );
        assert_golden(
            &BlackboardReplyListView {
                items: vec![BlackboardReplyView::from(reply)],
            },
            serde_json::from_str(include_str!("../tests/golden/blackboard_reply_list.json"))
                .unwrap(),
        );
    }

    #[tokio::test]
    async fn dev_service_roundtrips_workspace_task_topology_blackboard() {
        let service = DevWorkspaceService::new("user-1");
        let workspace = service
            .create_workspace(
                "user-1",
                "tenant-1",
                "project-1",
                WorkspaceCreatePayload {
                    name: "Core Workspace".to_string(),
                    description: None,
                    metadata: json!({}),
                    use_case: Some("programming".to_string()),
                    collaboration_mode: Some("multi_agent_shared".to_string()),
                    autonomy_profile: None,
                    sandbox_code_root: None,
                },
            )
            .await
            .unwrap();
        let task = service
            .create_task(
                "user-1",
                &workspace.id,
                WorkspaceTaskCreatePayload {
                    title: "Implement P6".to_string(),
                    description: None,
                    assignee_user_id: None,
                    metadata: json!({}),
                    priority: Some("P1".to_string()),
                    estimated_effort: None,
                    blocker_reason: None,
                    preferred_language: None,
                },
            )
            .await
            .unwrap();
        let node = service
            .create_node(
                "user-1",
                &workspace.id,
                TopologyNodeCreatePayload {
                    node_type: "task".to_string(),
                    ref_id: Some(task.id.clone()),
                    title: Some(task.title.clone()),
                    position_x: None,
                    position_y: None,
                    hex_q: Some(0),
                    hex_r: Some(0),
                    status: None,
                    tags: vec![],
                    data: json!({}),
                },
            )
            .await
            .unwrap();
        let node2 = service
            .create_node(
                "user-1",
                &workspace.id,
                TopologyNodeCreatePayload {
                    node_type: "note".to_string(),
                    ref_id: None,
                    title: Some("Context".to_string()),
                    position_x: None,
                    position_y: None,
                    hex_q: Some(1),
                    hex_r: Some(0),
                    status: None,
                    tags: vec![],
                    data: json!({}),
                },
            )
            .await
            .unwrap();
        let edge = service
            .create_edge(
                "user-1",
                &workspace.id,
                TopologyEdgeCreatePayload {
                    source_node_id: node.id,
                    target_node_id: node2.id,
                    label: Some("relates".to_string()),
                    direction: None,
                    auto_created: false,
                    data: json!({}),
                },
            )
            .await
            .unwrap();
        assert_eq!(edge.source_hex_q, Some(0));
        let post = service
            .create_post(
                "user-1",
                "tenant-1",
                "project-1",
                &workspace.id,
                BlackboardPostCreatePayload {
                    title: "Status".to_string(),
                    content: "P6 started".to_string(),
                    status: "open".to_string(),
                    is_pinned: true,
                    metadata: json!({}),
                },
            )
            .await
            .unwrap();
        let reply = service
            .create_reply(
                "user-1",
                "tenant-1",
                "project-1",
                &workspace.id,
                &post.id,
                BlackboardReplyCreatePayload {
                    content: "ack".to_string(),
                    metadata: json!({}),
                },
            )
            .await
            .unwrap();
        assert_eq!(reply.post_id, post.id);
        let done = service
            .transition_task(
                "user-1",
                &workspace.id,
                &task.id,
                TaskTransitionAction::Complete,
            )
            .await
            .unwrap();
        assert_eq!(done.status, "done");
        assert!(done.completed_at.is_some());
    }

    #[test]
    fn workspace_router_builds() {
        let _router: Router<AppState> = router();
    }
}
