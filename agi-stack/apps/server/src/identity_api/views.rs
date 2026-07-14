use serde::Deserialize;
use serde_json::Value;

/// OAuth2 password-grant form. Mirrors FastAPI's `OAuth2PasswordRequestForm`:
/// `username` + `password` are required; other grant fields (grant_type, scope,
/// client_id/secret) are accepted and ignored.
#[derive(Deserialize)]
pub(super) struct LoginForm {
    pub(super) username: String,
    pub(super) password: String,
}

#[derive(Deserialize)]
pub(super) struct DeviceCodeRequest {
    #[serde(default, rename = "client_id")]
    pub(super) _client_id: Option<String>,
    #[serde(default, rename = "scope")]
    pub(super) _scope: Option<String>,
}

#[derive(Deserialize)]
pub(super) struct DeviceApproveRequest {
    #[serde(default)]
    pub(super) user_code: String,
}

#[derive(Deserialize)]
pub(super) struct DeviceTokenRequest {
    #[serde(default)]
    pub(super) device_code: String,
}

#[derive(Deserialize)]
pub(super) struct WorkspaceContextSwitchRequest {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) expected_revision: i64,
    pub(super) idempotency_key: String,
}

/// Pagination + search query for the tenant list. Defaults mirror Python
/// (`page=1`, `page_size=20`).
#[derive(Deserialize)]
pub(super) struct TenantListQuery {
    #[serde(default = "default_page")]
    pub(super) page: i64,
    #[serde(default = "default_page_size")]
    pub(super) page_size: i64,
    #[serde(default)]
    pub(super) search: Option<String>,
}

fn default_page() -> i64 {
    1
}

fn default_page_size() -> i64 {
    20
}

#[derive(Deserialize)]
pub(super) struct CreateTenantRequest {
    pub(super) name: String,
    #[serde(default)]
    pub(super) description: Option<String>,
}

#[derive(Deserialize)]
pub(super) struct AddTenantMemberRequest {
    pub(super) user_id: String,
    #[serde(default)]
    pub(super) role: Option<String>,
}

#[derive(Deserialize)]
pub(super) struct AddTenantMemberQuery {
    #[serde(default = "default_member_role")]
    pub(super) role: String,
}

#[derive(Deserialize)]
pub(super) struct UpdateTenantMemberRequest {
    pub(super) role: String,
}

fn default_member_role() -> String {
    "member".to_string()
}

#[derive(Deserialize)]
pub(super) struct ProjectListQuery {
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
    #[serde(default = "default_page")]
    pub(super) page: i64,
    #[serde(default = "default_page_size")]
    pub(super) page_size: i64,
    #[serde(default)]
    pub(super) search: Option<String>,
    #[serde(default = "default_visibility")]
    pub(super) visibility: String,
    #[serde(default)]
    pub(super) owner_id: Option<String>,
}

fn default_visibility() -> String {
    "all".to_string()
}

#[derive(Deserialize)]
pub(super) struct ProjectGetQuery {
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
}

#[derive(Deserialize)]
pub(super) struct CreateProjectRequest {
    pub(super) name: String,
    pub(super) tenant_id: String,
    #[serde(default)]
    pub(super) description: Option<String>,
    #[serde(default)]
    pub(super) memory_rules: Option<Value>,
    #[serde(default)]
    pub(super) graph_config: Option<Value>,
    #[serde(default)]
    pub(super) graph_store_id: Option<String>,
    #[serde(default)]
    pub(super) retrieval_store_id: Option<String>,
    #[serde(default, rename = "sandbox_config")]
    pub(super) _sandbox_config: Option<Value>,
    #[serde(default)]
    pub(super) is_public: bool,
    #[serde(default = "default_agent_conversation_mode")]
    pub(super) agent_conversation_mode: String,
}

fn default_agent_conversation_mode() -> String {
    "single_agent".to_string()
}

#[derive(Deserialize)]
pub(super) struct AddProjectMemberRequest {
    pub(super) user_id: String,
    #[serde(default)]
    pub(super) role: Option<String>,
}

#[derive(Deserialize)]
pub(super) struct UpdateProjectMemberRequest {
    pub(super) role: String,
}

#[derive(Deserialize)]
pub(super) struct CreateInvitationRequest {
    pub(super) email: String,
    #[serde(default = "default_invitation_role")]
    pub(super) role: String,
    #[serde(default)]
    pub(super) message: Option<String>,
}

fn default_invitation_role() -> String {
    "member".to_string()
}

#[derive(Deserialize)]
pub(super) struct InvitationListQuery {
    #[serde(default = "default_invitation_limit")]
    pub(super) limit: i64,
    #[serde(default)]
    pub(super) offset: i64,
}

fn default_invitation_limit() -> i64 {
    50
}

#[derive(Deserialize)]
pub(super) struct AcceptInvitationRequest {
    #[serde(default)]
    pub(super) _display_name: Option<String>,
}
