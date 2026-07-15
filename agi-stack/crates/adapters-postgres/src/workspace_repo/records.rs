use serde_json::Value;
use sqlx::types::chrono::{DateTime, Utc};

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceRecord {
    pub id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub name: String,
    pub description: Option<String>,
    pub created_by: String,
    pub is_archived: bool,
    pub metadata_json: Value,
    pub office_status: String,
    pub hex_layout_config_json: Value,
    pub default_blocking_categories_json: Vec<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceMemberRecord {
    pub id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub user_email: Option<String>,
    pub role: String,
    pub invited_by: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAgentRecord {
    pub id: String,
    pub workspace_id: String,
    pub agent_id: String,
    pub display_name: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceAgentDetailRecord {
    pub id: String,
    pub workspace_id: String,
    pub agent_id: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub config_json: Value,
    pub is_active: bool,
    pub hex_q: Option<i32>,
    pub hex_r: Option<i32>,
    pub theme_color: Option<String>,
    pub label: Option<String>,
    pub status: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceTaskRecord {
    pub id: String,
    pub workspace_id: String,
    pub title: String,
    pub description: Option<String>,
    pub created_by: String,
    pub assignee_user_id: Option<String>,
    pub assignee_agent_id: Option<String>,
    pub status: String,
    pub priority: i32,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub archived_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceTaskSessionAttemptRecord {
    pub id: String,
    pub workspace_task_id: String,
    pub root_goal_task_id: String,
    pub workspace_id: String,
    pub attempt_number: i32,
    pub status: String,
    pub conversation_id: Option<String>,
    pub worker_agent_id: Option<String>,
    pub leader_agent_id: Option<String>,
    pub candidate_summary: Option<String>,
    pub candidate_artifacts_json: Vec<String>,
    pub candidate_verifications_json: Vec<String>,
    pub leader_feedback: Option<String>,
    pub adjudication_reason: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceMessageRecord {
    pub id: String,
    pub workspace_id: String,
    pub sender_id: String,
    pub sender_type: String,
    pub content: String,
    pub mentions_json: Vec<String>,
    pub parent_message_id: Option<String>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TopologyNodeRecord {
    pub id: String,
    pub workspace_id: String,
    pub node_type: String,
    pub ref_id: Option<String>,
    pub title: String,
    pub position_x: f64,
    pub position_y: f64,
    pub hex_q: Option<i32>,
    pub hex_r: Option<i32>,
    pub status: String,
    pub tags_json: Vec<String>,
    pub data_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TopologyEdgeRecord {
    pub id: String,
    pub workspace_id: String,
    pub source_node_id: String,
    pub target_node_id: String,
    pub label: Option<String>,
    pub source_hex_q: Option<i32>,
    pub source_hex_r: Option<i32>,
    pub target_hex_q: Option<i32>,
    pub target_hex_r: Option<i32>,
    pub direction: Option<String>,
    pub auto_created: bool,
    pub data_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BlackboardPostRecord {
    pub id: String,
    pub workspace_id: String,
    pub author_id: String,
    pub title: String,
    pub content: String,
    pub status: String,
    pub is_pinned: bool,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BlackboardReplyRecord {
    pub id: String,
    pub post_id: String,
    pub workspace_id: String,
    pub author_id: String,
    pub content: String,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BlackboardFileRecord {
    pub id: String,
    pub workspace_id: String,
    pub parent_path: String,
    pub name: String,
    pub is_directory: bool,
    pub file_size: i32,
    pub content_type: String,
    pub storage_key: String,
    pub uploader_type: String,
    pub uploader_id: String,
    pub uploader_name: String,
    pub checksum_sha256: Option<String>,
    pub mime_type_detected: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BlackboardOutboxRecord {
    pub id: String,
    pub workspace_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub event_type: String,
    pub payload_json: Value,
    pub metadata_json: Value,
    pub correlation_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanRecord {
    pub id: String,
    pub workspace_id: String,
    pub goal_id: String,
    pub status: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanNodeRecord {
    pub id: String,
    pub plan_id: String,
    pub parent_id: Option<String>,
    pub kind: String,
    pub title: String,
    pub description: String,
    pub depends_on_json: Vec<String>,
    pub inputs_schema_json: Value,
    pub outputs_schema_json: Value,
    pub acceptance_criteria_json: Vec<Value>,
    pub feature_checkpoint_json: Option<Value>,
    pub handoff_package_json: Option<Value>,
    pub recommended_capabilities_json: Vec<Value>,
    pub preferred_agent_id: Option<String>,
    pub estimated_effort_json: Value,
    pub priority: i32,
    pub intent: String,
    pub execution: String,
    pub progress_json: Value,
    pub assignee_agent_id: Option<String>,
    pub current_attempt_id: Option<String>,
    pub workspace_task_id: Option<String>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanBlackboardEntryRecord {
    pub id: String,
    pub plan_id: String,
    pub key: String,
    pub value_json: Option<Value>,
    pub published_by: String,
    pub version: i32,
    pub schema_ref: Option<String>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanEventRecord {
    pub id: String,
    pub plan_id: String,
    pub workspace_id: String,
    pub node_id: Option<String>,
    pub attempt_id: Option<String>,
    pub event_type: String,
    pub source: String,
    pub actor_id: Option<String>,
    pub payload_json: Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanOutboxRecord {
    pub id: String,
    pub plan_id: Option<String>,
    pub workspace_id: String,
    pub event_type: String,
    pub payload_json: Value,
    pub status: String,
    pub attempt_count: i32,
    pub max_attempts: i32,
    pub lease_owner: Option<String>,
    pub lease_expires_at: Option<DateTime<Utc>>,
    pub last_error: Option<String>,
    pub next_attempt_at: Option<DateTime<Utc>>,
    pub processed_at: Option<DateTime<Utc>>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePipelineRunRecord {
    pub id: String,
    pub contract_id: String,
    pub workspace_id: String,
    pub plan_id: Option<String>,
    pub node_id: Option<String>,
    pub attempt_id: Option<String>,
    pub commit_ref: Option<String>,
    pub provider: String,
    pub status: String,
    pub reason: Option<String>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePipelineStageRunRecord {
    pub id: String,
    pub run_id: String,
    pub workspace_id: String,
    pub stage: String,
    pub status: String,
    pub command: Option<String>,
    pub exit_code: Option<i32>,
    pub stdout_preview: Option<String>,
    pub stderr_preview: Option<String>,
    pub log_ref: Option<String>,
    pub artifact_refs_json: Vec<String>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub duration_ms: Option<i32>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceProjectAccess {
    Read,
    Write,
    Admin,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceAccess {
    Read,
    Write,
}
