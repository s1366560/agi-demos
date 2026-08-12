use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MutationRequest {
    pub contract_version: String,
    pub surface: String,
    pub action: String,
    pub expected_revision: u64,
    pub idempotency_key: String,
    #[serde(default = "empty_object")]
    pub payload: Value,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum MutationAction {
    CreateObjective,
    UpdateObjective,
    DeleteObjective,
    ProjectObjectiveToTask,
    CreateTask,
    UpdateTask,
    DeleteTask,
    AssignTaskAgent,
    UnassignTaskAgent,
    ApplyTaskRecoveryAction,
    CreatePost,
    UpdatePost,
    DeletePost,
    PinPost,
    UnpinPost,
    CreateReply,
    UpdateReply,
    DeleteReply,
    BindAgent,
    UpdateAgentBinding,
    UnbindAgent,
    AddMember,
    UpdateMemberRole,
    RemoveMember,
    CreateGene,
    UpdateGene,
    DeleteGene,
    CreateDirectory,
    UploadFile,
    UpdateFile,
    DeleteFile,
    CopyFile,
    CreateNode,
    UpdateNode,
    DeleteNode,
    CreateEdge,
    UpdateEdge,
    DeleteEdge,
    UpdateWorkspace,
}

impl MutationAction {
    pub(super) fn parse(surface: &str, action: &str) -> Option<Self> {
        match (surface, action) {
            ("goals", "create_objective") => Some(Self::CreateObjective),
            ("goals", "update_objective") => Some(Self::UpdateObjective),
            ("goals", "delete_objective") => Some(Self::DeleteObjective),
            ("goals", "project_objective_to_task") => Some(Self::ProjectObjectiveToTask),
            ("goals" | "collaboration", "create_task") => Some(Self::CreateTask),
            ("goals" | "status" | "collaboration", "update_task") => Some(Self::UpdateTask),
            ("goals" | "collaboration", "delete_task") => Some(Self::DeleteTask),
            ("goals" | "collaboration", "assign_task_agent") => Some(Self::AssignTaskAgent),
            ("goals" | "collaboration", "unassign_task_agent") => Some(Self::UnassignTaskAgent),
            ("status", "apply_task_recovery_action") => Some(Self::ApplyTaskRecoveryAction),
            ("discussion", "create_post") => Some(Self::CreatePost),
            ("discussion", "update_post") => Some(Self::UpdatePost),
            ("discussion", "delete_post") => Some(Self::DeletePost),
            ("discussion", "pin_post") => Some(Self::PinPost),
            ("discussion", "unpin_post") => Some(Self::UnpinPost),
            ("discussion", "create_reply") => Some(Self::CreateReply),
            ("discussion", "update_reply") => Some(Self::UpdateReply),
            ("discussion", "delete_reply") => Some(Self::DeleteReply),
            ("collaboration", "bind_agent") => Some(Self::BindAgent),
            ("collaboration", "update_agent_binding") => Some(Self::UpdateAgentBinding),
            ("collaboration", "unbind_agent") => Some(Self::UnbindAgent),
            ("collaboration" | "members", "add_member") => Some(Self::AddMember),
            ("collaboration" | "members", "update_member_role") => Some(Self::UpdateMemberRole),
            ("collaboration" | "members", "remove_member") => Some(Self::RemoveMember),
            ("genes", "create_gene") => Some(Self::CreateGene),
            ("genes", "update_gene") => Some(Self::UpdateGene),
            ("genes", "delete_gene") => Some(Self::DeleteGene),
            ("files", "create_directory") => Some(Self::CreateDirectory),
            ("files", "upload_file") => Some(Self::UploadFile),
            ("files", "update_file") => Some(Self::UpdateFile),
            ("files", "delete_file") => Some(Self::DeleteFile),
            ("files", "copy_file") => Some(Self::CopyFile),
            ("topology", "create_node") => Some(Self::CreateNode),
            ("topology", "update_node") => Some(Self::UpdateNode),
            ("topology", "delete_node") => Some(Self::DeleteNode),
            ("topology", "create_edge") => Some(Self::CreateEdge),
            ("topology", "update_edge") => Some(Self::UpdateEdge),
            ("topology", "delete_edge") => Some(Self::DeleteEdge),
            ("settings", "update_workspace") => Some(Self::UpdateWorkspace),
            _ => None,
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ObjectiveCreatePayload {
    pub title: String,
    pub description: Option<String>,
    #[serde(default = "objective_type")]
    pub obj_type: String,
    pub parent_id: Option<String>,
    #[serde(default)]
    pub progress: f64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ObjectiveUpdatePayload {
    pub objective_id: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub obj_type: Option<String>,
    pub parent_id: Option<String>,
    pub progress: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ObjectiveIdPayload {
    pub objective_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ObjectiveProjectionPayload {
    pub objective_id: String,
    pub preferred_language: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TaskCreatePayload {
    pub title: String,
    pub description: Option<String>,
    pub assignee_user_id: Option<String>,
    pub metadata: Option<Value>,
    pub preferred_language: Option<String>,
    pub priority: Option<String>,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TaskUpdatePayload {
    pub task_id: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub assignee_user_id: Option<String>,
    pub status: Option<String>,
    pub metadata: Option<Value>,
    pub priority: Option<String>,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TaskIdPayload {
    pub task_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TaskAssignPayload {
    pub task_id: String,
    pub workspace_agent_id: String,
    pub preferred_language: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TaskRecoveryPayload {
    pub task_id: String,
    pub action: String,
    pub reason: Option<String>,
    pub workspace_agent_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PostCreatePayload {
    pub title: String,
    pub content: String,
    #[serde(default = "open_status")]
    pub status: String,
    #[serde(default)]
    pub is_pinned: bool,
    #[serde(default = "empty_object")]
    pub metadata: Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PostUpdatePayload {
    pub post_id: String,
    pub title: Option<String>,
    pub content: Option<String>,
    pub status: Option<String>,
    pub is_pinned: Option<bool>,
    pub metadata: Option<Value>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PostIdPayload {
    pub post_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ReplyCreatePayload {
    pub post_id: String,
    pub content: String,
    #[serde(default = "empty_object")]
    pub metadata: Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ReplyUpdatePayload {
    pub post_id: String,
    pub reply_id: String,
    pub content: String,
    pub metadata: Option<Value>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ReplyDeletePayload {
    pub post_id: String,
    pub reply_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AgentBindPayload {
    pub agent_id: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    #[serde(default = "empty_object")]
    pub config: Value,
    #[serde(default = "default_true")]
    pub is_active: bool,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub theme_color: Option<String>,
    pub label: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AgentUpdatePayload {
    pub workspace_agent_id: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub config: Option<Value>,
    pub is_active: Option<bool>,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub theme_color: Option<String>,
    pub label: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WorkspaceAgentIdPayload {
    pub workspace_agent_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MemberAddPayload {
    pub user_id: String,
    #[serde(default = "viewer_role")]
    pub role: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MemberUpdatePayload {
    pub user_id: String,
    pub role: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct UserIdPayload {
    pub user_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct GeneCreatePayload {
    pub name: String,
    #[serde(default = "skill_category")]
    pub category: String,
    pub description: Option<String>,
    pub config_json: Option<String>,
    #[serde(default = "gene_version")]
    pub version: String,
    #[serde(default = "default_true")]
    pub is_active: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct GeneUpdatePayload {
    pub gene_id: String,
    pub name: Option<String>,
    pub category: Option<String>,
    pub description: Option<String>,
    pub config_json: Option<String>,
    pub version: Option<String>,
    pub is_active: Option<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct GeneIdPayload {
    pub gene_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DirectoryCreatePayload {
    #[serde(default = "root_path")]
    pub parent_path: String,
    pub name: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FileUpdatePayload {
    pub file_id: String,
    pub name: Option<String>,
    pub parent_path: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FileDeletePayload {
    pub file_id: String,
    #[serde(default)]
    pub recursive: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FileCopyPayload {
    pub file_id: String,
    pub target_parent_path: String,
    pub name: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NodeCreatePayload {
    pub node_type: String,
    pub ref_id: Option<String>,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub position_x: f64,
    #[serde(default)]
    pub position_y: f64,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    #[serde(default = "active_status")]
    pub status: String,
    #[serde(default = "empty_array")]
    pub tags: Value,
    #[serde(default = "empty_object")]
    pub data: Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NodeUpdatePayload {
    pub node_id: String,
    pub node_type: Option<String>,
    pub ref_id: Option<String>,
    pub title: Option<String>,
    pub position_x: Option<f64>,
    pub position_y: Option<f64>,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub status: Option<String>,
    pub tags: Option<Value>,
    pub data: Option<Value>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NodeIdPayload {
    pub node_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct EdgeCreatePayload {
    pub source_node_id: String,
    pub target_node_id: String,
    pub label: Option<String>,
    pub direction: Option<String>,
    #[serde(default)]
    pub auto_created: bool,
    #[serde(default = "empty_object")]
    pub data: Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct EdgeUpdatePayload {
    pub edge_id: String,
    pub source_node_id: Option<String>,
    pub target_node_id: Option<String>,
    pub label: Option<String>,
    pub direction: Option<String>,
    pub auto_created: Option<bool>,
    pub data: Option<Value>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct EdgeIdPayload {
    pub edge_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WorkspaceUpdatePayload {
    pub name: Option<String>,
    pub description: Option<String>,
    pub is_archived: Option<bool>,
    pub metadata: Option<Value>,
}

fn empty_object() -> Value {
    json!({})
}

fn empty_array() -> Value {
    json!([])
}

fn default_true() -> bool {
    true
}

fn objective_type() -> String {
    "objective".to_string()
}

fn open_status() -> String {
    "open".to_string()
}

fn active_status() -> String {
    "active".to_string()
}

fn viewer_role() -> String {
    "viewer".to_string()
}

fn skill_category() -> String {
    "skill".to_string()
}

fn gene_version() -> String {
    "1.0.0".to_string()
}

fn root_path() -> String {
    "/".to_string()
}

#[cfg(test)]
mod tests {
    use super::MutationAction;

    #[test]
    fn every_advertised_surface_action_is_in_the_closed_dispatch_set() {
        let advertised = [
            ("goals", "create_objective"),
            ("goals", "update_objective"),
            ("goals", "delete_objective"),
            ("goals", "project_objective_to_task"),
            ("goals", "create_task"),
            ("goals", "update_task"),
            ("goals", "delete_task"),
            ("goals", "assign_task_agent"),
            ("goals", "unassign_task_agent"),
            ("discussion", "create_post"),
            ("discussion", "update_post"),
            ("discussion", "delete_post"),
            ("discussion", "pin_post"),
            ("discussion", "unpin_post"),
            ("discussion", "create_reply"),
            ("discussion", "update_reply"),
            ("discussion", "delete_reply"),
            ("status", "update_task"),
            ("status", "apply_task_recovery_action"),
            ("collaboration", "bind_agent"),
            ("collaboration", "update_agent_binding"),
            ("collaboration", "unbind_agent"),
            ("collaboration", "add_member"),
            ("collaboration", "update_member_role"),
            ("collaboration", "remove_member"),
            ("collaboration", "create_task"),
            ("collaboration", "update_task"),
            ("collaboration", "delete_task"),
            ("collaboration", "assign_task_agent"),
            ("collaboration", "unassign_task_agent"),
            ("members", "add_member"),
            ("members", "update_member_role"),
            ("members", "remove_member"),
            ("genes", "create_gene"),
            ("genes", "update_gene"),
            ("genes", "delete_gene"),
            ("files", "create_directory"),
            ("files", "upload_file"),
            ("files", "update_file"),
            ("files", "delete_file"),
            ("files", "copy_file"),
            ("topology", "create_node"),
            ("topology", "update_node"),
            ("topology", "delete_node"),
            ("topology", "create_edge"),
            ("topology", "update_edge"),
            ("topology", "delete_edge"),
            ("settings", "update_workspace"),
        ];
        assert_eq!(advertised.len(), 48);
        for (surface, action) in advertised {
            assert!(
                MutationAction::parse(surface, action).is_some(),
                "missing {surface}:{action}"
            );
        }
        assert!(MutationAction::parse("notes", "create_note").is_none());
        assert!(MutationAction::parse("goals", "bind_agent").is_none());
    }
}
