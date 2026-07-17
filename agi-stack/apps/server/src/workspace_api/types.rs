use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub(crate) struct WorkspaceReplyUpdateInput<'a> {
    pub(crate) user_id: &'a str,
    pub(crate) tenant_id: &'a str,
    pub(crate) project_id: &'a str,
    pub(crate) workspace_id: &'a str,
    pub(crate) post_id: &'a str,
    pub(crate) reply_id: &'a str,
    pub(crate) body: BlackboardReplyUpdatePayload,
}

#[derive(Debug)]
pub(crate) struct WorkspaceApiError {
    pub(in crate::workspace_api) status: StatusCode,
    pub(in crate::workspace_api) detail: String,
}

impl WorkspaceApiError {
    pub(in crate::workspace_api) fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    pub(in crate::workspace_api) fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    pub(in crate::workspace_api) fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    pub(in crate::workspace_api) fn forbidden() -> Self {
        Self::new(StatusCode::FORBIDDEN, "Access denied")
    }

    pub(in crate::workspace_api) fn workspace_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Workspace not found")
    }

    pub(in crate::workspace_api) fn task_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Workspace task not found")
    }

    pub(in crate::workspace_api) fn node_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Topology node not found")
    }

    pub(in crate::workspace_api) fn edge_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Topology edge not found")
    }

    pub(in crate::workspace_api) fn blackboard_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Blackboard item not found")
    }

    pub(in crate::workspace_api) fn plan_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "Workspace plan not found")
    }

    pub(in crate::workspace_api) fn conflict(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::CONFLICT, detail)
    }

    pub(in crate::workspace_api) fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for WorkspaceApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum MyWorkAuthorityKind {
    WorkspaceAttempt,
    HitlRequest,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum MyWorkCapabilityMode {
    Work,
    Code,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum MyWorkGroup {
    NeedsInput,
    NeedsApproval,
    Running,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum MyWorkStatus {
    Running,
    Failed,
    NeedsInput,
    NeedsApproval,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum MyWorkRequiredAction {
    ProvideInput,
    ReviewApproval,
    Observe,
    InspectFailure,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(crate) struct ProjectWorkItem {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) authority_kind: MyWorkAuthorityKind,
    pub(in crate::workspace_api) authority_id: String,
    pub(in crate::workspace_api) run_id: Option<String>,
    pub(in crate::workspace_api) conversation_id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) project_id: String,
    pub(in crate::workspace_api) title: String,
    pub(in crate::workspace_api) capability_mode: Option<MyWorkCapabilityMode>,
    pub(in crate::workspace_api) group: MyWorkGroup,
    pub(in crate::workspace_api) status: MyWorkStatus,
    pub(in crate::workspace_api) required_action: MyWorkRequiredAction,
    pub(in crate::workspace_api) revision: Option<u64>,
    pub(in crate::workspace_api) permission_profile: Option<String>,
    pub(in crate::workspace_api) environment: Option<Value>,
    pub(in crate::workspace_api) error: Option<String>,
    pub(in crate::workspace_api) attempt_number: Option<i32>,
    pub(in crate::workspace_api) created_at: DateTime<Utc>,
    pub(in crate::workspace_api) updated_at: DateTime<Utc>,
    pub(in crate::workspace_api) last_heartbeat_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(crate) struct ProjectMyWorkResponse {
    pub(in crate::workspace_api) project_id: String,
    pub(in crate::workspace_api) items: Vec<ProjectWorkItem>,
    pub(in crate::workspace_api) total: usize,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspaceListQuery {
    #[serde(default)]
    pub(in crate::workspace_api) limit: Option<i64>,
    #[serde(default)]
    pub(in crate::workspace_api) offset: Option<i64>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspaceAgentListQuery {
    #[serde(default)]
    pub(in crate::workspace_api) active_only: bool,
    #[serde(default)]
    pub(in crate::workspace_api) limit: Option<i64>,
    #[serde(default)]
    pub(in crate::workspace_api) offset: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct WorkspaceCreatePayload {
    pub(in crate::workspace_api) name: String,
    #[serde(default)]
    pub(in crate::workspace_api) description: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) metadata: Value,
    #[serde(default)]
    pub(in crate::workspace_api) use_case: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) collaboration_mode: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) autonomy_profile: Option<Value>,
    #[serde(default)]
    pub(in crate::workspace_api) sandbox_code_root: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspaceUpdatePayload {
    #[serde(default)]
    pub(in crate::workspace_api) name: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) description: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) is_archived: Option<bool>,
    #[serde(default)]
    pub(in crate::workspace_api) metadata: Option<Value>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct AutonomyTickRequest {
    #[serde(default)]
    pub(in crate::workspace_api) force: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct AutonomyTickView {
    pub(in crate::workspace_api) triggered: bool,
    pub(in crate::workspace_api) root_task_id: Option<String>,
    pub(in crate::workspace_api) reason: String,
}

impl AutonomyTickView {
    pub(in crate::workspace_api) fn new(
        triggered: bool,
        root_task_id: Option<String>,
        reason: impl Into<String>,
    ) -> Self {
        Self {
            triggered,
            root_task_id,
            reason: reason.into(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SendMessagePayload {
    pub(in crate::workspace_api) content: String,
    #[serde(default = "default_sender_type")]
    pub(in crate::workspace_api) sender_type: String,
    #[serde(default)]
    pub(in crate::workspace_api) parent_message_id: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) mentions: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct MessageListQuery {
    #[serde(default)]
    pub(in crate::workspace_api) limit: Option<i64>,
    #[serde(default)]
    pub(in crate::workspace_api) before: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct MessageMentionQuery {
    #[serde(default)]
    pub(in crate::workspace_api) limit: Option<i64>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct TaskListQuery {
    #[serde(default, rename = "status")]
    pub(in crate::workspace_api) status_filter: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) limit: Option<i64>,
    #[serde(default)]
    pub(in crate::workspace_api) offset: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct WorkspaceTaskCreatePayload {
    pub(in crate::workspace_api) title: String,
    #[serde(default)]
    pub(in crate::workspace_api) description: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) assignee_user_id: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) metadata: Value,
    #[serde(default)]
    pub(in crate::workspace_api) priority: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) estimated_effort: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) blocker_reason: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) preferred_language: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspaceTaskUpdatePayload {
    #[serde(default)]
    pub(in crate::workspace_api) title: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) description: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) assignee_user_id: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) status: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) metadata: Option<Value>,
    #[serde(default)]
    pub(in crate::workspace_api) priority: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) estimated_effort: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) blocker_reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TopologyNodeCreatePayload {
    pub(in crate::workspace_api) node_type: String,
    #[serde(default)]
    pub(in crate::workspace_api) ref_id: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) title: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) position_x: Option<f64>,
    #[serde(default)]
    pub(in crate::workspace_api) position_y: Option<f64>,
    #[serde(default)]
    pub(in crate::workspace_api) hex_q: Option<i32>,
    #[serde(default)]
    pub(in crate::workspace_api) hex_r: Option<i32>,
    #[serde(default)]
    pub(in crate::workspace_api) status: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) tags: Vec<String>,
    #[serde(default)]
    pub(in crate::workspace_api) data: Value,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct TopologyNodeUpdatePayload {
    #[serde(default)]
    pub(in crate::workspace_api) node_type: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) ref_id: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) title: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) position_x: Option<f64>,
    #[serde(default)]
    pub(in crate::workspace_api) position_y: Option<f64>,
    #[serde(default)]
    pub(in crate::workspace_api) hex_q: Option<i32>,
    #[serde(default)]
    pub(in crate::workspace_api) hex_r: Option<i32>,
    #[serde(default)]
    pub(in crate::workspace_api) status: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) tags: Option<Vec<String>>,
    #[serde(default)]
    pub(in crate::workspace_api) data: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TopologyEdgeCreatePayload {
    pub(in crate::workspace_api) source_node_id: String,
    pub(in crate::workspace_api) target_node_id: String,
    #[serde(default)]
    pub(in crate::workspace_api) label: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) direction: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) auto_created: bool,
    #[serde(default)]
    pub(in crate::workspace_api) data: Value,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct TopologyEdgeUpdatePayload {
    #[serde(default)]
    pub(in crate::workspace_api) source_node_id: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) target_node_id: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) label: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) direction: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) auto_created: Option<bool>,
    #[serde(default)]
    pub(in crate::workspace_api) data: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct BlackboardPostCreatePayload {
    pub(in crate::workspace_api) title: String,
    pub(in crate::workspace_api) content: String,
    #[serde(default = "default_post_status")]
    pub(in crate::workspace_api) status: String,
    #[serde(default)]
    pub(in crate::workspace_api) is_pinned: bool,
    #[serde(default)]
    pub(in crate::workspace_api) metadata: Value,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct BlackboardPostUpdatePayload {
    #[serde(default)]
    pub(in crate::workspace_api) title: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) content: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) status: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) is_pinned: Option<bool>,
    #[serde(default)]
    pub(in crate::workspace_api) metadata: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct BlackboardReplyCreatePayload {
    pub(in crate::workspace_api) content: String,
    #[serde(default)]
    pub(in crate::workspace_api) metadata: Value,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct BlackboardReplyUpdatePayload {
    pub(in crate::workspace_api) content: String,
    #[serde(default)]
    pub(in crate::workspace_api) metadata: Option<Value>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct BlackboardFileListQuery {
    #[serde(default)]
    pub(in crate::workspace_api) parent_path: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct MkdirPayload {
    #[serde(default = "root_path")]
    pub(in crate::workspace_api) parent_path: String,
    pub(in crate::workspace_api) name: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct RenameOrMoveFilePayload {
    #[serde(default)]
    pub(in crate::workspace_api) name: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) parent_path: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct CopyFilePayload {
    pub(in crate::workspace_api) target_parent_path: String,
    #[serde(default)]
    pub(in crate::workspace_api) name: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct DeleteFileQuery {
    #[serde(default)]
    pub(in crate::workspace_api) recursive: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspacePlanSnapshotQuery {
    #[serde(default)]
    pub(in crate::workspace_api) outbox_limit: Option<i64>,
    #[serde(default)]
    pub(in crate::workspace_api) event_limit: Option<i64>,
    #[serde(default)]
    pub(in crate::workspace_api) include_details: Option<bool>,
    #[serde(default)]
    pub(in crate::workspace_api) recover_stale_attempts: Option<bool>,
    #[serde(default)]
    pub(in crate::workspace_api) plan_id: Option<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct BlackboardUpload {
    pub(in crate::workspace_api) parent_path: String,
    pub(in crate::workspace_api) filename: String,
    pub(in crate::workspace_api) content_type: Option<String>,
    pub(in crate::workspace_api) bytes: Vec<u8>,
}

#[derive(Debug, Clone)]
pub(crate) struct BlackboardFileDownload {
    pub(in crate::workspace_api) filename: String,
    pub(in crate::workspace_api) content_type: String,
    pub(in crate::workspace_api) file_size: i32,
    pub(in crate::workspace_api) etag: String,
    pub(in crate::workspace_api) bytes: Vec<u8>,
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
    pub(in crate::workspace_api) limit: Option<i64>,
    #[serde(default)]
    pub(in crate::workspace_api) offset: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspaceView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) tenant_id: String,
    pub(in crate::workspace_api) project_id: String,
    pub(in crate::workspace_api) name: String,
    pub(in crate::workspace_api) created_by: String,
    pub(in crate::workspace_api) description: Option<String>,
    pub(in crate::workspace_api) is_archived: bool,
    pub(in crate::workspace_api) metadata: Value,
    pub(in crate::workspace_api) office_status: String,
    pub(in crate::workspace_api) hex_layout_config: Value,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspaceMemberView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) user_id: String,
    pub(in crate::workspace_api) user_email: Option<String>,
    pub(in crate::workspace_api) role: String,
    pub(in crate::workspace_api) invited_by: Option<String>,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspaceAgentView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) agent_id: String,
    pub(in crate::workspace_api) display_name: Option<String>,
    pub(in crate::workspace_api) description: Option<String>,
    pub(in crate::workspace_api) config: Value,
    pub(in crate::workspace_api) is_active: bool,
    pub(in crate::workspace_api) hex_q: Option<i32>,
    pub(in crate::workspace_api) hex_r: Option<i32>,
    pub(in crate::workspace_api) theme_color: Option<String>,
    pub(in crate::workspace_api) label: Option<String>,
    pub(in crate::workspace_api) status: Option<String>,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspaceTaskView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) title: String,
    pub(in crate::workspace_api) description: Option<String>,
    pub(in crate::workspace_api) created_by: String,
    pub(in crate::workspace_api) assignee_user_id: Option<String>,
    pub(in crate::workspace_api) assignee_agent_id: Option<String>,
    pub(in crate::workspace_api) workspace_agent_id: Option<String>,
    pub(in crate::workspace_api) current_attempt_id: Option<String>,
    pub(in crate::workspace_api) current_attempt_number: Option<i64>,
    pub(in crate::workspace_api) current_attempt_conversation_id: Option<String>,
    pub(in crate::workspace_api) current_attempt_worker_binding_id: Option<String>,
    pub(in crate::workspace_api) current_attempt_worker_agent_id: Option<String>,
    pub(in crate::workspace_api) last_attempt_status: Option<String>,
    pub(in crate::workspace_api) pending_leader_adjudication: bool,
    pub(in crate::workspace_api) last_worker_report_type: Option<String>,
    pub(in crate::workspace_api) last_worker_report_summary: Option<String>,
    pub(in crate::workspace_api) last_worker_report_artifacts: Vec<String>,
    pub(in crate::workspace_api) last_worker_report_verifications: Vec<String>,
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) metadata: Value,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
    pub(in crate::workspace_api) priority: String,
    pub(in crate::workspace_api) estimated_effort: Option<String>,
    pub(in crate::workspace_api) blocker_reason: Option<String>,
    pub(in crate::workspace_api) completed_at: Option<String>,
    pub(in crate::workspace_api) archived_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct MessageView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) sender_id: String,
    pub(in crate::workspace_api) sender_type: String,
    pub(in crate::workspace_api) content: String,
    pub(in crate::workspace_api) mentions: Vec<String>,
    pub(in crate::workspace_api) parent_message_id: Option<String>,
    pub(in crate::workspace_api) metadata: Value,
    pub(in crate::workspace_api) created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct MessageListView {
    pub(in crate::workspace_api) items: Vec<MessageView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct TopologyNodeView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) node_type: String,
    pub(in crate::workspace_api) ref_id: Option<String>,
    pub(in crate::workspace_api) title: String,
    pub(in crate::workspace_api) position_x: f64,
    pub(in crate::workspace_api) position_y: f64,
    pub(in crate::workspace_api) hex_q: Option<i32>,
    pub(in crate::workspace_api) hex_r: Option<i32>,
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) tags: Vec<String>,
    pub(in crate::workspace_api) data: Value,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct TopologyEdgeView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) source_node_id: String,
    pub(in crate::workspace_api) target_node_id: String,
    pub(in crate::workspace_api) label: Option<String>,
    pub(in crate::workspace_api) source_hex_q: Option<i32>,
    pub(in crate::workspace_api) source_hex_r: Option<i32>,
    pub(in crate::workspace_api) target_hex_q: Option<i32>,
    pub(in crate::workspace_api) target_hex_r: Option<i32>,
    pub(in crate::workspace_api) direction: Option<String>,
    pub(in crate::workspace_api) auto_created: bool,
    pub(in crate::workspace_api) data: Value,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardPostView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) author_id: String,
    pub(in crate::workspace_api) title: String,
    pub(in crate::workspace_api) content: String,
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) is_pinned: bool,
    pub(in crate::workspace_api) metadata: Value,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardReplyView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) post_id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) author_id: String,
    pub(in crate::workspace_api) content: String,
    pub(in crate::workspace_api) metadata: Value,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardPostListView {
    pub(in crate::workspace_api) items: Vec<BlackboardPostView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardReplyListView {
    pub(in crate::workspace_api) items: Vec<BlackboardReplyView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardFileView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) parent_path: String,
    pub(in crate::workspace_api) name: String,
    pub(in crate::workspace_api) is_directory: bool,
    pub(in crate::workspace_api) file_size: i32,
    pub(in crate::workspace_api) content_type: String,
    pub(in crate::workspace_api) uploader_type: String,
    pub(in crate::workspace_api) uploader_id: String,
    pub(in crate::workspace_api) uploader_name: String,
    pub(in crate::workspace_api) created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct BlackboardFileListView {
    pub(in crate::workspace_api) items: Vec<BlackboardFileView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct DeletedView {
    pub(in crate::workspace_api) deleted: bool,
}

mod plan;
pub(in crate::workspace_api) use plan::*;
fn default_post_status() -> String {
    "open".to_string()
}

fn default_sender_type() -> String {
    "human".to_string()
}

fn root_path() -> String {
    "/".to_string()
}
